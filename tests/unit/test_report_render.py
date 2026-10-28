"""Tests del informe M6 (``core/report``).

Lo que se exige no es "que no explote" sino que el PDF sea usable y verificable:
* se genera un archivo real, A4, de más de 20 KB;
* el texto extraído contiene los run_id y los nombres de los candidatos;
* la tabla está ordenada por score y el desglose E/R/S/T/D suma el total;
* funciona con una y con varias corridas;
* el comando exacto de la CLI produce el archivo pedido.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(ROOT, "core")
sys.path.insert(0, CORE)

from report import render  # noqa: E402
from report.model import ReportError, build_runs  # noqa: E402
from report.render import fmtv  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "data", "results_fixture.json")
MIN_BYTES = 20 * 1024


def extraer_texto(pdf):
    """pypdf si está; si no, pdftotext. Sin ambos, el test no puede validar nada."""
    try:
        from pypdf import PdfReader  # type: ignore

        return "\n".join((page.extract_text() or "") for page in PdfReader(pdf).pages)
    except Exception:
        pass
    exe = shutil.which("pdftotext")
    if exe:
        proc = subprocess.run([exe, "-layout", pdf, "-"], capture_output=True, text=True)
        if proc.returncode == 0:
            return proc.stdout
    pytest.fail("no hay pypdf ni pdftotext para verificar el texto del PDF")


@pytest.fixture(scope="module")
def run_a():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def test_pdf_fixture_una_corrida(tmp_path):
    pdf = render([FIXTURE], str(tmp_path / "informe"))

    assert os.path.isfile(pdf)
    assert pdf.lower().endswith(".pdf")
    assert os.path.getsize(pdf) > MIN_BYTES, "el PDF debe pesar más de 20 KB"

    texto = extraer_texto(pdf)
    assert "fixture0000000000" in texto
    for candidato in ("sirna10", "sirna20", "sirna30", "sirna50"):
        assert candidato in texto, f"falta {candidato} en el PDF"
    # secciones obligatorias
    assert "Limitaciones" in texto
    assert "Apéndice A" in texto
    assert "Distribución de eficiencia" in texto
    assert "Hits de off-target por panel" in texto
    assert "validación de laboratorio" in texto


def test_pdf_orden_y_desglose_coherentes(run_a, tmp_path):
    runs = build_runs([run_a])
    run = runs[0]
    totales = [c["total"] for c in run.candidates]
    assert totales == sorted(totales, reverse=True), "la tabla debe venir ordenada por score"
    for cand in run.candidates:
        suma = sum(cand["desglose"][eje]["aporte"] for eje in "ERSTD")
        assert suma == pytest.approx(cand["total"], abs=0.11), cand["id"]
    pdf = render([run_a], str(tmp_path / "informe"))
    assert os.path.getsize(pdf) > MIN_BYTES


def test_pdf_varias_corridas(tmp_path, run_a):
    segundo = json.loads(json.dumps(run_a))
    segundo["run_id"] = "fixtureB000000001"
    segundo_path = tmp_path / "run_b.json"
    segundo_path.write_text(json.dumps(segundo, ensure_ascii=False), encoding="utf-8")

    pdf = render([FIXTURE, str(segundo_path)], str(tmp_path / "multi"))
    texto = extraer_texto(pdf)
    assert "fixture0000000000" in texto
    assert "fixtureB000000001" in texto
    assert "Comparación de corridas" in texto


def test_cli_comando_exacto(tmp_path):
    salida = tmp_path / "reporte.pdf"
    env = dict(os.environ, PYTHONPATH=CORE)
    proc = subprocess.run(
        [sys.executable, "-m", "report.cli",
         "--results", FIXTURE, "--out", str(salida)],
        cwd=CORE, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert os.path.isfile(salida)
    assert os.path.getsize(salida) > MIN_BYTES
    assert str(salida) in proc.stdout


def test_html_es_generable(tmp_path):
    html = render([FIXTURE], str(tmp_path / "html"), fmt="html")
    assert os.path.isfile(html) and html.endswith(".html")
    contenido = open(html, encoding="utf-8").read()
    assert "fixture0000000000" in contenido
    assert "sirna10" in contenido


def test_fmt_helpers():
    assert fmtv(True) == "sí"
    assert fmtv(False) == "no"
    assert fmtv(22.0) == "22"
    assert fmtv(1.5) == "1,5"
    assert fmtv(None) == "—"


def test_manifest_invalido(tmp_path):
    malo = tmp_path / "malo.json"
    malo.write_text('{"foo": 1}', encoding="utf-8")
    with pytest.raises(ReportError):
        render([str(malo)], str(tmp_path / "out"))


def test_informe_incluye_perfil_por_posicion(tmp_path):
    """La Figura 3 (perfil por posición) tiene que existir, tener datos y estar en el PDF.

    Es el gráfico del siFi original que faltaba: curvas de todos vs eficientes y bandas de
    off-target perfecto. Sin él el informe ordena candidatos pero no dice dónde cortar.
    """
    import json
    from report.figures import perfil_posicion

    largo = 200
    filas = []
    for pos in range(1, largo - 20):
        for eficiente in (True, False):
            filas.append({"query_name": "q", "sirna_name": f"s{pos}{int(eficiente)}",
                          "sirna_position": pos, "is_efficient": eficiente,
                          "is_off_target": pos > 150 and not eficiente,
                          "mismatches": "" if pos > 150 and not eficiente else ""})
    rec = {"query_name": "q", "query_length": largo, "sirnas": filas}
    salida = perfil_posicion([rec], str(tmp_path / "perfil.png"))
    assert os.path.isfile(salida) and os.path.getsize(salida) > 15_000

    # el PDF de una corrida real tiene que traer la sección y la figura
    pdf = render([FIXTURE], out_dir=str(tmp_path / "out"), fmt="pdf", filename="i")
    html = render([FIXTURE], out_dir=str(tmp_path / "out2"), fmt="html", filename="i")
    with open(html, encoding="utf-8") as fh:
        cuerpo = fh.read()
    assert "Perfil por posición" in cuerpo
    assert "fig_perfil.png" in cuerpo
    assert os.path.isfile(os.path.join(str(tmp_path / "out"), "assets", "fig_perfil.png"))
