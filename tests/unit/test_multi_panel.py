"""Tests del modo multi-panel (una corrida, N bases) y del progreso por registro.

Lo que se protege acá:
  1. **Fidelidad**: con `panels=None` la salida sigue teniendo exactamente las 14 claves
     del original, en el mismo orden. (El test diferencial contra siFi es el juez final,
     pero este test falla rápido si alguien agrega una columna de más.)
  2. **Atribución**: con N paneles, cada hit sale etiquetado con el panel de donde vino y
     la columna de mismatches NO se pisa (bowtie escribe 7 columnas, el pipeline la 8ª).
  3. **Blanco principal**: en multi-panel el gen consultado no cuenta como off-target en
     otro panel distinto, aunque tenga el mismo nombre.
  4. **Progreso**: el callback recibe un aviso por registro, y un callback que explota no
     tumba la corrida.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from sifi.params import SifiParams, ToolPaths  # noqa: E402
from sifi.pipeline import SifiPipeline  # noqa: E402
from sifi.run import run_once  # noqa: E402
from sifi.tools import find_tool  # noqa: E402

QUERY = os.path.join(ROOT, "tests", "data", "query.fa")
TOY = os.path.join(ROOT, "tests", "data", "toy.fa")
BOWTIE = find_tool("bowtie")
RNAPLFOLD = find_tool("rnaplfold")
BOWTIE_BUILD = find_tool("bowtie-build")

pytestmark = pytest.mark.skipif(
    not (BOWTIE and RNAPLFOLD and BOWTIE_BUILD),
    reason="faltan bowtie / RNAplfold / bowtie-build",
)

CLAVES_ORIGINAL = [
    "query_name", "sirna_name", "sirna_position", "sirna_sequence", "is_efficient",
    "strand_selection", "end_stability", "target_site_accessibility",
    "accessibility_value", "is_off_target", "hit_name", "reference_strand_pos",
    "strand", "mismatches",
]


def _params(**kw):
    return SifiParams(mismatches=kw.pop("mismatches", 1), **kw)


def _tools():
    return ToolPaths(bowtie=BOWTIE, rnaplfold=RNAPLFOLD)


def _build(fasta_text, tmp_path, name):
    """Arma un índice bowtie chico a partir de un FASTA escrito a mano."""
    import subprocess
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    fa = d / "seqs.fa"
    fa.write_text(fasta_text, encoding="utf-8")
    rc = subprocess.run([BOWTIE_BUILD, "-q", str(fa), str(d / "idx")],
                        capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr
    return {"panel": name, "db_dir": str(d), "db_name": "idx"}


@pytest.fixture(scope="module")
def panels():
    """Dos paneles: uno con el gen consultado (maíz) y otro con dianas de 1 mismatch."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix="sifi_mp_")
    from pathlib import Path
    base = Path(tmp)
    # panel "maiz": el índice de juguete de siempre (contiene el gen consultado)
    import subprocess
    d = base / "maiz"
    d.mkdir()
    rc = subprocess.run([BOWTIE_BUILD, "-q", TOY, str(d / "idx")], capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr
    maiz = {"panel": "maiz", "db_dir": str(d), "db_name": "idx"}

    seq = "".join(l.strip() for l in open(QUERY, encoding="utf-8")
                  if not l.startswith(">"))
    perfecta = seq[30:51]
    mutada = perfecta[:10] + ("A" if perfecta[10] != "A" else "T") + perfecta[11:]
    otro = seq[100:200]
    simb = _build(f">DianaPerfecta\n{perfecta}\n>DianaMutada\n{mutada}\n>DianaLarga\n{otro}\n",
                  base, "simbionte")
    return [maiz, simb]


def test_sin_panels_salida_original_intacta(tmp_path, panels):
    """panels=None -> 14 claves, sin 'panel', y mismatches con su valor real."""
    m = run_once(QUERY, panels[0]["db_dir"], panels[0]["db_name"], _params(), _tools(),
                 str(tmp_path / "out"))
    filas = m["records"][0]["sirnas"]
    assert filas, "la corrida de juguete tiene que producir filas"
    for fila in filas:
        assert list(fila.keys()) == CLAVES_ORIGINAL
    assert any(f["mismatches"] for f in filas), "con mismatches=1 hay que ver descriptores"


def test_multi_panel_etiqueta_y_respeta_mismatches(tmp_path, panels):
    m = run_once(QUERY, panels[0]["db_dir"], panels[0]["db_name"], _params(), _tools(),
                 str(tmp_path / "out"), panels=panels)
    filas = m["records"][0]["sirnas"]
    etiquetas = {f["panel"] for f in filas}
    assert etiquetas == {"maiz", "simbionte"}, etiquetas
    assert all(f["panel"] for f in filas), "toda fila multi-panel lleva su panel"
    # la novena columna es el panel: la de mismatches quedó intacta.
    # bowtie deja la columna vacía cuando no hay mismatches (así lo hace también el
    # original), y con 1 mismatch escribe el descriptor "pos:A>G".
    for f in filas:
        mm = str(f["mismatches"] or "")
        assert mm in ("", "0") or ">" in mm, f"mismatches pisado: {mm!r}"
        assert mm not in ("maiz", "simbionte"), "el panel se coló en la columna de mismatches"
    # el manifiesto declara los paneles con su huella
    assert [p["panel"] for p in m["panels"]] == ["maiz", "simbionte"]
    assert all(len(p["fingerprint"]) == 16 for p in m["panels"])


def test_multi_panel_blanco_principal_solo_en_su_panel(tmp_path, panels):
    """El gen consultado vive en 'maiz': ahí no es off-target; en 'simbionte' sí."""
    m = run_once(QUERY, panels[0]["db_dir"], panels[0]["db_name"], _params(), _tools(),
                 str(tmp_path / "out"), panels=panels)
    filas = m["records"][0]["sirnas"]
    en_maiz = [f for f in filas if f["panel"] == "maiz"]
    en_simb = [f for f in filas if f["panel"] == "simbionte"]
    assert any(f["is_off_target"] is False for f in en_maiz)
    assert all(f["is_off_target"] is True for f in en_simb)


def test_multi_panel_resumen_separa_por_panel(tmp_path, panels):
    m = run_once(QUERY, panels[0]["db_dir"], panels[0]["db_name"], _params(), _tools(),
                 str(tmp_path / "out"), panels=panels)
    tabla = m["records"][0]["summary"]["table"]
    assert all("panel" in fila for fila in tabla)
    assert {f["panel"] for f in tabla} == {"maiz", "simbionte"}


def test_progreso_un_aviso_por_registro(tmp_path, panels):
    avisos = []
    run_once(QUERY, panels[0]["db_dir"], panels[0]["db_name"], _params(), _tools(),
             str(tmp_path / "out"), panels=panels,
             progress_cb=lambda done, total, name: avisos.append((done, total, name)))
    assert avisos[0][:2] == (0, 1) and avisos[-1][:2] == (1, 1)
    assert avisos[0][2] == avisos[-1][2], "el mismo registro abre y cierra su aviso"


def test_progreso_que_explota_no_tumba_la_corrida(tmp_path, panels):
    def roto(done, total, name):
        raise RuntimeError("el callback está roto")

    m = run_once(QUERY, panels[0]["db_dir"], panels[0]["db_name"], _params(), _tools(),
                 str(tmp_path / "out"), progress_cb=roto)
    assert m["records"] and m["records"][0]["sirnas"]


def test_run_bowtie_panels_normaliza_columnas(tmp_path, panels):
    """bowtie -v escribe 7 columnas: el panel debe quedar 9º, no pisar la 8ª."""
    pl = SifiPipeline(panels[0]["db_name"], panels[0]["db_dir"], QUERY, _params(), _tools(),
                      str(tmp_path / "w"), panels=panels)
    try:
        sirna_file, _ = pl.create_sirnas("GCTAAAGACAATTACATAACATACACGTCAGCACGAAACTTGTTGGCCCAG"
                                         "TGTGAATCGCTTAAGGG", 21)
        filas = pl.run_bowtie_panels(sirna_file, panels, 1)
        assert filas
        for linea in filas:
            campos = linea.split("\t")
            assert len(campos) == 9, campos
            assert campos[8] in {"maiz", "simbionte"}
            assert campos[7] in ("", "0") or ">" in campos[7], campos[7]
            assert campos[7] not in ("maiz", "simbionte")
    finally:
        pl.cleanup()
