"""Port headless del pipeline de si-Fi (siFi21 commit d6296b7).

Diferencias deliberadas con el original (todas documentadas en PORT_NOTES.md):
  * no hay GUI: la selección de "main targets" (popup Qt) se recibe como argumento;
  * no hay os.chdir(): cada subproceso corre con cwd explícito;
  * los temporales van a un run_dir explícito en vez de %TEMP%;
  * se devuelve un objeto PipelineResult en lugar de rutas de imágenes Qt.

La lógica de cálculo (cortado, bowtie, lunp, eficiencia, JSON) es idéntica.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import numpy as np
from Bio import SeqIO
from Bio.Seq import Seq

from . import free_energy
from .params import SifiParams, ToolPaths

log = logging.getLogger("sifi.pipeline")


@dataclass
class PipelineResult:
    """Resultado de una corrida (equivalente al JSON que escribe el original)."""
    query_name: str
    query_sequence: str
    sirnas: List[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "query_name": self.query_name,
            "query_length": len(self.query_sequence),
            "query_sha256": hashlib.sha256(self.query_sequence.encode()).hexdigest(),
            "sirnas": self.sirnas,
            "summary": self.summary,
            "artifacts": self.artifacts,
            "warnings": self.warnings,
            "error": self.error,
        }

    def dump_json(self, path: str | os.PathLike) -> str:
        path = str(path)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=4)
        return path


class SifiPipeline:
    """Pipeline si-Fi, modo design (mode=0) u off-target (mode=1)."""

    def __init__(
        self,
        bowtie_db: str,
        db_location: str,
        query_sequences: str,
        params: SifiParams,
        tools: ToolPaths,
        work_dir: str,
        main_targets: Optional[Sequence[str]] = None,
        main_target_mode: str = "explicit",   # "explicit" | "auto"
    ) -> None:
        self.bowtie_db = bowtie_db
        self.db_location = os.path.abspath(db_location)
        self.query_sequences = query_sequences
        self.p = params
        # rutas absolutas: los subprocesos corren con cwd distinto
        self.tools = ToolPaths(
            bowtie=os.path.abspath(tools.bowtie),
            rnaplfold=os.path.abspath(tools.rnaplfold),
            bowtie_build=os.path.abspath(tools.bowtie_build) if tools.bowtie_build else None,
        )
        self.work_dir = os.path.abspath(work_dir)
        self.main_targets = list(main_targets) if main_targets else None
        self.main_target_mode = main_target_mode

        # estado por registro (equivalente a los atributos mutables del original)
        self.len_seq = 0
        self.bowtie_data_l: List[list] = []
        self.sirna_l: List[list] = []

        os.makedirs(self.work_dir, exist_ok=True)
        self.tmp_dir = tempfile.mkdtemp(prefix="tmp_", dir=self.work_dir)

    # ------------------------------------------------------------------ run
    def run(self) -> List[PipelineResult]:
        """Procesa todos los registros del FASTA de entrada."""
        results: List[PipelineResult] = []
        for seq_record in SeqIO.parse(self.query_sequences, "fasta"):
            results.append(self._run_one(str(seq_record.id), str(seq_record.seq)))
        if not results:
            results.append(PipelineResult(
                query_name="", query_sequence="", error="El FASTA de entrada no contiene registros."))
        return results

    def _run_one(self, query_name: str, query_sequence: str) -> PipelineResult:
        logger = logging.LoggerAdapter(log, {"query": query_name})
        self.len_seq = len(query_sequence)
        res = PipelineResult(query_name=query_name, query_sequence=query_sequence)

        if not query_sequence:
            res.error = "Secuencia vacía."
            return res

        # 1. FASTA de la query (una sola secuencia)
        query_seq_temp_file = self.create_single_fasta_file(query_name, query_sequence)

        # 2. siRNAs de tamaño fijo a multi-FASTA (+ versión TSV)
        sirna_file, tab_file_name = self.create_sirnas(query_sequence, self.p.sirna_size)

        # 3. bowtie contra la DB
        bowtie_data = self.run_bowtie(sirna_file, self.bowtie_db, self.p.mismatches)
        self.bowtie_data_l = self.bowtie_to_lst(bowtie_data)

        # 4. RNAplfold (accesibilidad)
        lunp_data = self.run_rnaplfold(query_name, query_seq_temp_file)

        # 5. main targets (sólo design)
        if self.p.mode_code == 0:
            main_targets = self.resolve_main_targets(query_name)
            no_target = main_targets is None
        else:
            main_targets = None
            no_target = True

        # 6. tabla de siRNAs (igual que el original: la vuelve a leer del TSV)
        self.sirna_l = []
        with open(tab_file_name, "r", encoding="utf-8") as f_in:
            for x in f_in.readlines():
                self.sirna_l.append(x.split("\t"))

        # 7. input_data según haya o no hits (misma lógica que el original)
        if self.bowtie_data_l:
            input_data = self.bowtie_data_l
            no_target = False
        else:
            if self.p.mode_code == 0:
                input_data = [x.split("\t") for x in open(tab_file_name, encoding="utf-8").readlines()]
                no_target = True
                res.warnings.append(
                    "Sin hits en la base: se omite el análisis de off-target y sólo se evalúa eficiencia.")
            else:
                input_data = None

        if main_targets == "Canceled":  # compatibilidad con el original
            res.error = "Canceled by user."
            return res

        if not input_data:
            res.error = ("No targets found. Please make sure that the query and/or "
                         "database sequences are in correct orientation")
            return res

        # 8. JSON canónico (el corte headless: data_to_json no toca la GUI)
        json_lst = self.data_to_json(query_name, input_data, no_target, lunp_data, main_targets)
        if not json_lst:
            res.error = ("No targets found. Please make sure that the query and/or database "
                         "sequences are in correct orientation.")
            return res

        res.sirnas = json_lst
        res.summary = self.summarize(json_lst)
        res.artifacts = {
            "sirna_fasta": sirna_file,
            "sirna_tsv": tab_file_name,
            "query_fasta": query_seq_temp_file,
        }
        logger.info("siRNAs=%d eficientes=%d", res.summary["n_rows"], res.summary["n_efficient_rows"])
        return res

    # ------------------------------------------------------- main targets
    def resolve_main_targets(self, query_name: str):
        """Sustituye al popup.ListSelection del original.

        "explicit": usa la lista recibida (si está vacía -> None).
        "auto": el/los hit(s) que coinciden con el id de la query (exacto, o prefijo
                '<query>_' / '<query>|'); si no hay coincidencia, None (todo es off-target).
        """
        if self.main_target_mode == "explicit":
            return self.main_targets

        all_targets = Counter(player[2] for player in self.bowtie_data_l)
        if query_name in all_targets:
            return [query_name]
        pref = [t for t in all_targets if t.startswith(query_name + "_") or t.startswith(query_name + "|")]
        if len(pref) == 1:
            return pref
        log.warning("main_target auto: no pude identificar el blanco principal para %r (%d hits)",
                    query_name, len(all_targets))
        return pref or None

    # ------------------------------------------------------------- helpers
    def bowtie_to_lst(self, bowtie_data: Iterable[str]) -> List[list]:
        """Convierte la salida de bowtie en listas. Añade 0 si no hubo mismatches."""
        bowtie_lst = []
        for line in bowtie_data:
            parts = line.strip().split("\t")
            if len(parts) == 7:
                parts.append(0)
            bowtie_lst.append(parts)
        return bowtie_lst

    def create_sirnas(self, query_sequence: str, sirna_size: int):
        """Corta la secuencia en x-mers (posición 1-based, como el original)."""
        fasta_name = os.path.join(self.tmp_dir, "sirnas.fa")
        tab_name = os.path.join(self.tmp_dir, "sirnas.tsv")
        start = self.p.sirna_start_position
        end = sirna_size
        seq_list = []
        for _ in range(len(query_sequence)):
            if len(query_sequence[start:end]) == sirna_size:
                seq_list.append(("sirna%d" % (start + 1), query_sequence[start:end]))
                start += 1
                end += 1
        return self.create_multi_fasta_file(seq_list, fasta_name, tab_name)

    def create_single_fasta_file(self, query_name: str, query_sequence: str) -> str:
        path = os.path.join(self.tmp_dir, "query.fa")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(">" + str(query_name) + "\n")
            fh.write(str(query_sequence) + "\n")
        return path

    def create_multi_fasta_file(self, sequence_list, file_name, tab_file_name):
        with open(file_name, "w", encoding="utf-8") as f_fasta, \
                open(tab_file_name, "w", encoding="utf-8") as f_tab:
            for name, sequence in sequence_list:
                f_fasta.write("> " + str(name) + "\n")
                f_fasta.write(str(sequence) + "\n")
                f_tab.write(str(name) + "\t" + str(sequence) + "\n")
        return file_name, tab_file_name

    # -------------------------------------------------------------- bowtie
    def run_bowtie(self, sequence: str, database_name: str, mismatches: int) -> List[str]:
        """bowtie -a -v N -y <db> -f <sirnas> <out>  (idéntico al original)."""
        out = os.path.join(self.tmp_dir, "bowtie.out")
        cmd = [self.tools.bowtie, "-a", "-v", str(mismatches), "-y",
               os.path.join(self.db_location, database_name), "-f", sequence, out]
        log.debug("bowtie: %s", " ".join(cmd))
        proc = subprocess.run(cmd, cwd=self.db_location, capture_output=True, text=True)
        if proc.returncode not in (0, 1):  # bowtie: 1 == sin alineamientos
            raise RuntimeError(f"bowtie falló (rc={proc.returncode}): {proc.stderr.strip()[:500]}")
        if not os.path.exists(out):
            return []
        with open(out, "r", encoding="utf-8") as fh:
            return fh.readlines()

    # ---------------------------------------------------------- rnaplfold
    def run_rnaplfold(self, query_name: str, sequence_file: str):
        """RNAplfold -W 80 -L 40 -u <size> -T 22 (igual que el original)."""
        cwd = tempfile.mkdtemp(prefix="lunp_", dir=self.tmp_dir)
        with open(sequence_file, "r", encoding="utf-8") as fh:
            seq = fh.read()

        cmd = [self.tools.rnaplfold,
               "-W", "%d" % self.p.winsize,
               "-L", "%d" % self.p.span,
               "-u", "%d" % self.p.sirna_size,
               "-T", "%.2f" % self.p.temperature]
        log.debug("rnaplfold: %s (cwd=%s)", " ".join(cmd), cwd)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, cwd=cwd)
        _out, err = proc.communicate(input=(seq + "\n").encode())
        if proc.returncode != 0:
            raise RuntimeError(f"RNAplfold falló (rc={proc.returncode}): {err.decode()[:500]}")

        lunp_file = os.path.join(cwd, query_name + "_lunp")
        if not os.path.exists(lunp_file):
            raise RuntimeError(f"RNAplfold no generó {lunp_file!r}")
        with warnings.catch_warnings():
            # el header "#i$" arranca con espacio: numpy avisa y no cuenta esa línea
            warnings.simplefilter("ignore", UserWarning)
            lunp_data = np.loadtxt(lunp_file, dtype=str)
        if lunp_data.ndim == 1:
            lunp_data = lunp_data.reshape(1, -1)
        # las primeras (size-1) filas están incompletas
        lunp_data = np.delete(lunp_data, np.r_[: self.p.sirna_size - 1], 0)
        return lunp_data

    # ----------------------------------------------------- free energy (ΔG)
    def free_energy3(self, sirna_sequence: str):
        """ΔG sin dangling ends (primeros dos siRNAs)."""
        p = self.p
        sense_five_seq = sirna_sequence[p.sirna_start_position:p.end_nucleotides]
        antisense_five_seq = sirna_sequence[p.sirna_size - p.overhang - p.end_nucleotides:
                                            p.sirna_size - p.overhang]
        return (free_energy.calculate_free_energy(sense_five_seq),
                free_energy.calculate_free_energy(antisense_five_seq))

    def free_energy_dangling_ends(self, sirna_sequence: str, sirna_sequence_n2: str):
        """ΔG con dangling ends (a partir del tercer siRNA)."""
        p = self.p
        sense_five_seq = sirna_sequence[p.sirna_start_position:p.end_nucleotides]
        sense_c_seq = Seq(sirna_sequence_n2).reverse_complement().strip()[
            p.sirna_size - 5:p.sirna_size - 1]
        antisense_five_seq = Seq(sirna_sequence_n2).reverse_complement().strip()[
            p.sirna_start_position:p.end_nucleotides]
        antisense_c_seq = sirna_sequence[p.sirna_size - 5:p.sirna_size - 1]

        sense5 = free_energy.calculate_free_energy(
            sense_five_seq, check=True, strict=True, c_seq=sense_c_seq[::-1], shift=1)
        antisense5 = free_energy.calculate_free_energy(
            antisense_five_seq, check=True, strict=True, c_seq=antisense_c_seq[::-1], shift=1)
        return sense5, antisense5

    def _dG_pair(self, sirna_sequence: str, sirna_sequence_n2: Optional[str]):
        if sirna_sequence_n2 is not None:
            return self.free_energy_dangling_ends(sirna_sequence, sirna_sequence_n2)
        return self.free_energy3(sirna_sequence)

    # ------------------------------------------------------ reglas si-Fi
    def strand_selection(self, sirna_sequence: str, sirna_sequence_n2: Optional[str]) -> bool:
        sense5, antisense5 = self._dG_pair(sirna_sequence, sirna_sequence_n2)
        return antisense5 >= sense5

    def end_stability(self, sirna_sequence: str, sirna_sequence_n2: Optional[str]) -> bool:
        sense5, antisense5 = self._dG_pair(sirna_sequence, sirna_sequence_n2)
        return (antisense5 - sense5) >= self.p.end_stability_threshold

    def pair_probability(self, lunp_data_xmer: float) -> bool:
        return lunp_data_xmer >= self.p.target_site_accessibility_threshold

    def check_efficient(self, strand_sel: bool, end_stab: bool, ts_acc: bool) -> bool:
        p = self.p
        checks = []
        if p.strand_check:
            checks.append(strand_sel)
        if p.end_check:
            checks.append(end_stab)
        if p.accessibility_check:
            checks.append(ts_acc)
        return all(checks) if checks else True

    def calculate_efficiency(self, sirna_sequence: str, sirna_sequence_n2: Optional[str],
                             lunp_data_xmer: float):
        p = self.p
        if p.no_efficience:
            return False, None, None, None, None

        strand_sel = self.strand_selection(sirna_sequence, sirna_sequence_n2)
        end_stab = self.end_stability(sirna_sequence, sirna_sequence_n2)
        ts_acc = self.pair_probability(lunp_data_xmer)
        thermo = self.check_efficient(strand_sel, end_stab, ts_acc)

        if p.terminal_check:
            # Regla de terminales (posición S19 y S1), idéntica al original
            if sirna_sequence[p.sirna_size - 3] in ("A", "T"):
                if sirna_sequence[1] in ("A", "T"):
                    is_eff = bool(thermo)
                else:
                    is_eff = bool(ts_acc) if p.accessibility_check else True
            else:
                if sirna_sequence[1] in ("G", "C"):
                    is_eff = bool(thermo)
                else:
                    is_eff = False
        else:
            is_eff = bool(thermo)
        return is_eff, strand_sel, end_stab, ts_acc, thermo

    # -------------------------------------------------------- data_to_json
    def data_to_json(self, query_name, input_data, no_target, lunp_data, main_targets):
        """Arma la lista de dicts por hit. Es la salida canónica del núcleo."""
        p = self.p
        json_lst = []
        for data_split in input_data:
            if not no_target:
                sirna_name = data_split[0]
                strand = data_split[1]
                hit_name = data_split[2]
                reference_strand_pos = int(data_split[3])
                query_position = int(sirna_name.split("sirna")[1])
                sirna_sequence = data_split[4]
                missmatches = data_split[7]

                if p.mode_code == 0:
                    off_target = hit_name not in (main_targets or [])
                else:
                    off_target = None
            else:
                sirna_name = data_split[0]
                query_position = int(sirna_name.split("sirna")[1])
                sirna_sequence = data_split[1]
                off_target = False
                strand = None
                hit_name = False
                reference_strand_pos = None
                missmatches = None

            if strand == "+":
                # antisentido = secuencia 2 posiciones atrás; los primeros 2 no se pueden calcular
                if query_position in (1, 2):
                    sirna_sequence_n2 = None
                else:
                    sirna_sequence_n2 = self.sirna_l[query_position - 3][1].strip()

                # El original hacía lunp_data[pos-1,:].astype(float)[window]; eso revienta
                # si CUALQUIER celda de la fila es "NA" (bordes de la secuencia). Acá se
                # convierte sólo la celda usada; los números son los mismos.
                _cell = str(lunp_data[int(sirna_name.split("sirna")[1]) - 1][p.accessibility_window])
                lunp_data_xmer = float(_cell) if _cell.upper() != "NA" else float("nan")

                (is_efficient, strand_selection, end_stability,
                 target_site_accessibility, thermo_effcicient) = self.calculate_efficiency(
                    sirna_sequence, sirna_sequence_n2, lunp_data_xmer)

                json_lst.append({
                    "query_name": query_name,
                    "sirna_name": sirna_name,
                    "sirna_position": query_position,
                    "sirna_sequence": sirna_sequence,
                    "is_efficient": is_efficient,
                    "strand_selection": strand_selection,
                    "end_stability": end_stability,
                    "target_site_accessibility": target_site_accessibility,
                    "accessibility_value": lunp_data_xmer,
                    "is_off_target": off_target,
                    "hit_name": hit_name,
                    "reference_strand_pos": reference_strand_pos,
                    "strand": strand,
                    "mismatches": missmatches,
                })
        return json_lst

    # ------------------------------------------------------------- resumen
    @staticmethod
    def summarize(json_lst: List[dict]) -> dict:
        hits = Counter(row["hit_name"] for row in json_lst)
        eff = Counter(row["hit_name"] for row in json_lst if row["is_efficient"])
        table = []
        for name, total in hits.most_common():
            table.append({"hit_name": name, "hits": total, "efficient": eff.get(name, 0)})
        return {
            "n_rows": len(json_lst),
            "n_efficient_rows": sum(1 for r in json_lst if r["is_efficient"]),
            "n_sirnas": len({r["sirna_name"] for r in json_lst}),
            "n_sirnas_efficient": len({r["sirna_name"] for r in json_lst if r["is_efficient"]}),
            "n_hits": len(hits),
            "n_offtarget_rows": sum(1 for r in json_lst if r["is_off_target"]),
            "table": table,
        }

    # ------------------------------------------------------------ limpieza
    def cleanup(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
