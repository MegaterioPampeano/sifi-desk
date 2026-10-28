"""Registro de paneles (bases de secuencias) con versionado e indexado bowtie.

Un panel es un directorio inmutable:

    <panels_root>/<panel_id>/<version>/
        seqs.fa         FASTA normalizado (una línea por secuencia)
        idx.*.ebwt      índice bowtie1
        meta.yaml       metadatos + hashes

Nada se reescribe: construir el mismo panel con otro FASTA genera otra versión.
La corrida guarda el fingerprint del índice, así que un resultado siempre se puede
atar a la base exacta con la que se calculó.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from Bio import SeqIO

INDEX_SUFFIXES = (".1.ebwt", ".2.ebwt", ".3.ebwt", ".4.ebwt", ".rev.1.ebwt", ".rev.2.ebwt")
ROLES = ("no_blanco", "blanco", "patogeno", "simbionte", "control", "universal")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,40}$")


class PanelError(RuntimeError):
    pass


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _index_digest(index_prefix: str) -> Optional[str]:
    """sha256 de todos los archivos del índice bowtie (nombre + contenido), en orden fijo."""
    h = hashlib.sha256()
    found = False
    for suf in INDEX_SUFFIXES:
        p = index_prefix + suf
        if os.path.exists(p):
            found = True
            h.update(suf.encode())
            h.update(open(p, "rb").read())
    return h.hexdigest() if found else None


def _fingerprint(index_prefix: str) -> Optional[str]:
    """Versión corta (16 hex) del hash del índice, para mostrar y comparar a ojo."""
    digest = _index_digest(index_prefix)
    return digest[:16] if digest else None


def _normalize_fasta(src: str, dst: str) -> int:
    """Reescribe el FASTA con un ID limpio (sin descripción) y secuencia en una línea.

    Los IDs importan: siFi usa el nombre del hit como 'main target', así que un FASTA con
    descripciones largas o caracteres raros produce resultados difíciles de interpretar.
    """
    n = 0
    seen = set()
    with open(dst, "w", encoding="utf-8") as out:
        for rec in SeqIO.parse(src, "fasta"):
            rid = rec.id.strip().replace(" ", "_")
            if rid in seen:
                raise PanelError(f"ID duplicado en el FASTA: {rid}")
            seen.add(rid)
            seq = str(rec.seq).upper().replace("U", "T")
            if not seq:
                continue
            out.write(f">{rid}\n{seq}\n")
            n += 1
    if not n:
        raise PanelError("El FASTA no contiene secuencias.")
    return n


def build_panel(
    panel_id: str,
    fasta_path: str,
    panels_root: str,
    bowtie_build: str,
    nombre: str = "",
    rol: str = "no_blanco",
    fuente: str = "",
    notas: str = "",
    version: Optional[str] = None,
) -> dict:
    """Construye (o reconstruye) un panel y devuelve su meta."""
    if not ID_RE.match(panel_id):
        raise PanelError("panel_id inválido: usar minúsculas, números, '-' o '_' (2-41 chars)")
    if rol not in ROLES:
        raise PanelError(f"rol inválido: {rol!r} (usar uno de {', '.join(ROLES)})")
    if not os.path.exists(fasta_path):
        raise PanelError(f"no existe el FASTA: {fasta_path}")

    version = version or datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = os.path.join(panels_root, panel_id, version)

    # Normalizamos primero en un temporal: así la comparación de idempotencia es sobre el
    # contenido real (el FASTA normalizado), no sobre el archivo de entrada.
    with tempfile.TemporaryDirectory(prefix="sifi_panel_") as td:
        tmp_fa = os.path.join(td, "seqs.fa")
        n_seqs = _normalize_fasta(fasta_path, tmp_fa)
        norm_sha = _sha256(tmp_fa)

        if os.path.exists(dest):
            # mismo contenido -> reutilizar; distinto -> error (nunca se pisa un panel)
            meta = read_meta(dest)
            if meta and meta.get("sha256_fasta") == norm_sha:
                meta["path"] = dest
                return meta
            raise PanelError(f"ya existe {dest} con otro contenido; usá otra version")

        os.makedirs(dest, exist_ok=False)
        seqs = os.path.join(dest, "seqs.fa")
        shutil.copyfile(tmp_fa, seqs)
        os.chmod(seqs, 0o444)  # el panel es inmutable

    prefix = os.path.join(dest, "idx")
    proc = subprocess.run([bowtie_build, "-q", "--ntoa", seqs, prefix],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise PanelError(f"bowtie-build falló: {proc.stderr.strip()[:400]}")

    fp = _fingerprint(prefix)
    digest = _index_digest(prefix)
    if not fp:
        shutil.rmtree(dest, ignore_errors=True)
        raise PanelError("bowtie-build no generó el índice")

    meta = {
        "id": panel_id,
        "version": version,
        "nombre": nombre or panel_id,
        "rol": rol,
        "fuente": fuente,
        "notas": notas,
        "n_seqs": n_seqs,
        "sha256_fasta": norm_sha,
        "sha256_source": _sha256(fasta_path),
        "sha256_index": digest,
        "fingerprint": fp,
        "index_prefix": "idx",
        "bowtie_build": os.path.basename(bowtie_build),
        "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes_fasta": os.path.getsize(seqs),
    }
    with open(os.path.join(dest, "meta.yaml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump(meta, fh, allow_unicode=True, sort_keys=True)
    return meta


def read_meta(panel_dir: str) -> Optional[dict]:
    p = os.path.join(panel_dir, "meta.yaml")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def list_panels(panels_root: str) -> List[dict]:
    """Todos los paneles, con todas sus versiones, ordenados por id y versión."""
    out = []
    if not os.path.isdir(panels_root):
        return out
    for pid in sorted(os.listdir(panels_root)):
        pdir = os.path.join(panels_root, pid)
        if not os.path.isdir(pdir):
            continue
        for ver in sorted(os.listdir(pdir)):
            meta = read_meta(os.path.join(pdir, ver))
            if meta:
                meta["path"] = os.path.join(pdir, ver)
                out.append(meta)
    return out


def resolve_panel(panels_root: str, panel_id: str, version: Optional[str] = None) -> dict:
    """Devuelve el meta del panel pedido (última versión si no se especifica)."""
    pdir = os.path.join(panels_root, panel_id)
    if not os.path.isdir(pdir):
        raise PanelError(f"no existe el panel {panel_id!r} en {panels_root}")
    versions = sorted(v for v in os.listdir(pdir) if read_meta(os.path.join(pdir, v)))
    if not versions:
        raise PanelError(f"el panel {panel_id!r} no tiene versiones válidas")
    ver = version or versions[-1]
    if ver not in versions:
        raise PanelError(f"el panel {panel_id!r} no tiene la versión {ver!r} (hay: {', '.join(versions)})")
    meta = read_meta(os.path.join(pdir, ver))
    meta["path"] = os.path.join(pdir, ver)
    return meta


def remove_panel(panels_root: str, panel_id: str, version: str) -> None:
    """Borra una versión de panel (operación explícita, no se usa automáticamente)."""
    dest = os.path.join(panels_root, panel_id, version)
    if not os.path.isdir(dest):
        raise PanelError(f"no existe {dest}")
    shutil.rmtree(dest)
    parent = os.path.dirname(dest)
    if not os.listdir(parent):
        os.rmdir(parent)


# --------------------------------------------------------------------------- #
# API orientada a objetos (la que usa el pipeline / sifid)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PanelSpec:
    """Descripción inmutable de un panel ya ingestado.

    Los campos de hash/n_seqs quedan vacíos cuando la instancia se usa como *pedido*
    de ingestión (id + nombre + rol + fuente + version) y se completan al ingestar.
    """

    id: str
    nombre: str = ""
    rol: str = "no_blanco"
    fuente: str = ""
    version: str = ""
    sha256_fasta: str = ""
    sha256_index: str = ""
    n_seqs: int = 0
    path: str = ""
    index_prefix: str = "idx"

    @property
    def fingerprint(self) -> str:
        return self.sha256_index[:16]

    @property
    def index_path(self) -> str:
        """Prefijo de índice listo para pasarle a bowtie (`-x`)."""
        return os.path.join(self.path, self.index_prefix) if self.path else ""

    @classmethod
    def from_meta(cls, meta: dict, path: Optional[str] = None) -> "PanelSpec":
        return cls(
            id=meta["id"],
            nombre=meta.get("nombre", meta["id"]),
            rol=meta.get("rol", "no_blanco"),
            fuente=meta.get("fuente", ""),
            version=str(meta.get("version", "")),
            sha256_fasta=meta.get("sha256_fasta", ""),
            sha256_index=meta.get("sha256_index") or meta.get("fingerprint", ""),
            n_seqs=int(meta.get("n_seqs", 0)),
            path=path or meta.get("path", ""),
            index_prefix=meta.get("index_prefix", "idx"),
        )


class PanelsRegistry:
    """Vista de un `panels_root` con las operaciones de ingestión y resolución."""

    def __init__(self, root: Optional[str] = None, bowtie_build: Optional[str] = None):
        self.root = root or os.environ.get(
            "SIFI_PANELS_ROOT", os.path.expanduser("~/.sifidesk/panels"))
        self.bowtie_build = bowtie_build

    # -- ingestión ---------------------------------------------------------- #
    def ingest(self, spec: PanelSpec, fasta_path: str, version: Optional[str] = None) -> PanelSpec:
        """Copia/normaliza el FASTA, construye el índice y devuelve el PanelSpec final.

        Idempotente: ingestar dos veces el mismo contenido con la misma versión devuelve
        el mismo panel sin reescribir nada.
        """
        bb = self.bowtie_build
        if not bb:
            from .tools import find_tool

            bb = find_tool("bowtie-build") or "bowtie-build"
        meta = build_panel(
            panel_id=spec.id,
            fasta_path=fasta_path,
            panels_root=self.root,
            bowtie_build=bb,
            nombre=spec.nombre,
            rol=spec.rol,
            fuente=spec.fuente,
            version=version or spec.version or None,
        )
        meta["path"] = os.path.join(self.root, meta["id"], meta["version"])
        return PanelSpec.from_meta(meta)

    # -- consulta ----------------------------------------------------------- #
    def get(self, panel_id: str, version: Optional[str] = None) -> PanelSpec:
        meta = resolve_panel(self.root, panel_id, version)
        return PanelSpec.from_meta(meta, meta.get("path"))

    def list(self) -> List[PanelSpec]:
        return [PanelSpec.from_meta(m, m.get("path")) for m in list_panels(self.root)]

    def available(self) -> Dict[str, List[str]]:
        """{panel_id: [versiones]} — útil para mensajes de error."""
        out: Dict[str, List[str]] = {}
        for spec in self.list():
            out.setdefault(spec.id, []).append(spec.version)
        return out

    def resolve(self, panel_ids: List[str], version: Optional[str] = None) -> List[str]:
        """Prefijos de índice bowtie para los paneles pedidos, en el orden pedido.

        Falla con un mensaje que dice exactamente qué falta y qué hay disponible: un
        panel ausente cambia el resultado del off-target en silencio, así que nunca se
        ignora.
        """
        if not panel_ids:
            raise PanelError("no se pidió ningún panel")
        prefixes: List[str] = []
        missing: List[str] = []
        for pid in panel_ids:
            try:
                spec = self.get(pid, version)
            except PanelError:
                missing.append(pid)
                continue
            prefix = spec.index_path
            if not os.path.exists(prefix + ".1.ebwt"):
                missing.append(f"{pid} (índice incompleto en {spec.path})")
                continue
            prefixes.append(prefix)
        if missing:
            disp = ", ".join(f"{k} ({'/'.join(v)})" for k, v in self.available().items()) or "ninguno"
            raise PanelError(
                "faltan paneles o están incompletos: " + ", ".join(missing) +
                f". Disponibles en {self.root}: {disp}")
        return prefixes
