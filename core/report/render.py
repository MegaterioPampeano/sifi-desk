"""``render``: manifest(s) sifi.results/1 -> informe A4 (PDF u HTML).

Flujo: normalizar (model) -> puntuar con el scoring del core -> figuras matplotlib
-> plantilla Jinja2 -> WeasyPrint. Nada de red, nada de estado global: dos llamadas
con la misma entrada producen el mismo documento (salvo la fecha de generación).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import weasyprint
from jinja2 import Environment, FileSystemLoader, select_autoescape

# ``core`` en el path: permite importar ``report`` y ``core.report`` por igual.
_CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from sifi.scoring import load_params  # noqa: E402

from .figures import figuras
from .model import (
    BAND_LABEL,
    NOTA_LABEL,
    RunView,
    ahora_larga,
    build_runs,
    diferencias_metodologia,
    metodologia_rows,
)

REPORT_VERSION = "1.0"
SCORING_VERSION = str(load_params().get("version", "?"))
PRODUCTO = "Si-Fi Agent Integration"
EMPRESA = "Omnivac Science"

_TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


# --------------------------------------------------------------------------- #
# filtros de la plantilla
# --------------------------------------------------------------------------- #

def fmtv(value: Any) -> str:
    """Valor legible en español: bool -> sí/no, float -> coma decimal."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        return ", ".join(fmtv(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _num(value: Any, dec: int) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{dec}f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(value)


def f1(value: Any) -> str:
    return _num(value, 1)


def f2(value: Any) -> str:
    return _num(value, 2)


def pz(n: Any, singular: str, plural: str) -> str:
    """'1 corrida' / '2 corridas' — sin '(s)' en el texto."""
    return f"{fmtv(n)} {singular if n == 1 else plural}"


def notalabel(code: str) -> str:
    return NOTA_LABEL.get(str(code), str(code))


def bandlabel(code: str) -> str:
    return BAND_LABEL.get(str(code), str(code))


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES),
        autoescape=select_autoescape(["html", "xml", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(fmtv=fmtv, f1=f1, f2=f2, pz=pz,
                       notalabel=notalabel, bandlabel=bandlabel)
    return env


# --------------------------------------------------------------------------- #
# contexto
# --------------------------------------------------------------------------- #

LIMITACIONES: List[Dict[str, str]] = [
    {
        "titulo": "Predicción in silico, no evidencia experimental",
        "texto": (
            "Todos los valores de este informe son predicciones computacionales. Un candidato "
            "con score alto no garantiza silenciamiento en el insecto: la eficacia real depende "
            "de la absorción, la estabilidad en el tracto digestivo, la maquinaria celular y la "
            "dosis. Este informe <strong>no reemplaza</strong> la validación de laboratorio "
            "(bioensayos de mortalidad, qPCR del transcrito blanco, controles negativos y de "
            "especificidad)."
        ),
    },
    {
        "titulo": "Modelo termodinámico acotado",
        "texto": (
            "La accesibilidad del sitio blanco se estima con RNAplfold sobre ARN desnudo, con "
            "ventana W = 80, span L = 40 y temperatura de plegado de 22 °C. No modela proteínas "
            "de unión, estructura del ARN in vivo, modificaciones ni cambios conformacionales. "
            "En los extremos de la secuencia la ventana no se puede calcular (valor <code>NA</code>); "
            "el scoring usa un valor neutro y lo marca como «sin accesibilidad»."
        ),
    },
    {
        "titulo": "Cobertura de off-target limitada al panel indexado",
        "texto": (
            "La búsqueda de off-target usa bowtie con un máximo de mismatches declarado y sólo "
            "contra los paneles cargados en la corrida. No cubre genomas completos que no se "
            "hayan indexado, variantes alélicas, transcritos alternativos ni regiones repetidas "
            "ausentes del panel. Un hit perfecto en un organismo no blanco es una señal de alerta "
            "que debe revisarse antes de avanzar, aunque el score total sea alto."
        ),
    },
    {
        "titulo": "El score v2 es heurístico y versionado",
        "texto": (
            "El total (0–100) es una suma ponderada y explícita: eficiencia 40, riesgo de "
            "off-target 15, especificidad 15, consenso con siFi 15 y calidad de diseño 15. Los "
            "pesos no están calibrados contra datos de mortalidad de este sistema; son un orden "
            "de prioridad para el trabajo de laboratorio, no una probabilidad de éxito. Cambiar "
            "cualquier peso o umbral cambia el ranking: por eso la versión del scoring y los "
            "pesos se imprimen en el informe."
        ),
    },
    {
        "titulo": "Trazabilidad condicionada al manifest",
        "texto": (
            "La reproducibilidad exacta depende de que la corrida haya declarado los binarios "
            "(bowtie, RNAplfold), sus hashes SHA-256 y el fingerprint del índice. Si el manifest "
            "no los trae, este informe lo indica y no se puede garantizar que otra ejecución "
            "reproduzca los números al dígito."
        ),
    },
    {
        "titulo": "Uso responsable y marco regulatorio",
        "texto": (
            "Este documento es una herramienta de investigación. El uso de dsRNA en campo está "
            "sujeto a la evaluación regulatoria de cada país, incluida la evaluación de riesgos "
            "para organismos no blanco. La decisión final de avanzar con un candidato es humana "
            "y debe considerar el contexto agronómico, la dosis y el modo de aplicación."
        ),
    },
]


def _totales(runs: Sequence[RunView]) -> dict:
    bands: Dict[str, int] = {}
    for run in runs:
        for band, n in run.band_counts.items():
            bands[band] = bands.get(band, 0) + n

    best = None
    best_run = None
    for run in runs:
        if run.best and (best is None or run.best["total"] > best["total"]):
            best, best_run = run.best, run

    con_hits = sum(1 for run in runs for p in run.panels
                   if p["panel"] != "sin panel declarado")
    return {
        "n_runs": len(runs),
        "n_records": sum(len(run.records) for run in runs),
        "n_rows": sum(run.n_rows for run in runs),
        "n_candidates": sum(run.n_candidates for run in runs),
        "bandas": bands,
        "mejor": best,
        "mejor_run": best_run,
        "paneles_declarados": con_hits,
        "errores": sum(len(run.errors) for run in runs),
        "con_hashes": all(run.tools_declarados for run in runs),
    }


def _traza_pie(runs: Sequence[RunView], totales: dict) -> str:
    """run_id corto + versión + fecha, obligatorio en el pie de cada página."""
    primero = runs[0]
    rid = primero.run_id if len(primero.run_id) <= 20 else primero.run_id[:10] + "…"
    if len(runs) > 1:
        rid = f"{rid} (+{len(runs) - 1})"
    versiones = {run.core_version for run in runs}
    version = runs[0].core_version if len(versiones) == 1 else "varias"
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{rid} · core v{version} · {fecha}"


def _css_escape(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace('"', '\\"')


def build_context(runs: Sequence[RunView], figs: Dict[str, str]) -> dict:
    totales = _totales(runs)
    metodo = metodologia_rows(runs)
    run_ids = [run.run_id for run in runs]
    return {
        "producto": PRODUCTO,
        "empresa": EMPRESA,
        "tagline": "Diseño de dsRNA asistido in silico — informe de resultados",
        "generado": ahora_larga(),
        "report_version": REPORT_VERSION,
        "scoring_version": SCORING_VERSION,
        "traza_pie": _traza_pie(runs, totales),
        "runs": runs,
        "multirun": len(runs) > 1,
        "totales": totales,
        "run_ids": run_ids,
        "run_ids_resumen": ", ".join(run_ids[:4]) + (
            f" (+{len(run_ids) - 4} más)" if len(run_ids) > 4 else ""),
        "figs": figs,
        "limitaciones": LIMITACIONES,
        "metodologia": metodo,
        "diferencias_metodologia": diferencias_metodologia(metodo),
        "scoring_ejes": [
            ("E", "Eficiencia termodinámica", "40"),
            ("R", "Riesgo de off-target (alto = seguro)", "15"),
            ("S", "Especificidad", "15"),
            ("T", "Consenso con el motor siFi", "15"),
            ("D", "Calidad de diseño", "15"),
        ],
    }


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

def _ensure_suffix(path: str, fmt: str) -> str:
    suffix = "." + fmt
    return path if path.lower().endswith(suffix) else path + suffix


def render(results_json_list: Any, out_dir: str, fmt: str = "pdf",
           filename: Optional[str] = None) -> str:
    """Renderiza una o varias corridas y devuelve la ruta del archivo generado.

    ``results_json_list``: lista de dicts y/o rutas a ``results.json`` (también acepta
    un único dict/ruta). ``out_dir``: directorio de salida (se crea). ``fmt``: ``pdf``
    o ``html``. ``filename``: nombre del archivo; por defecto ``reporte.<fmt>``.
    """
    fmt = (fmt or "pdf").lower().lstrip(".")
    if fmt not in ("pdf", "html"):
        raise ValueError(f"fmt no soportado: {fmt!r} (usar 'pdf' o 'html')")

    runs = build_runs(results_json_list)
    out_dir = os.path.abspath(os.fspath(out_dir))
    os.makedirs(out_dir, exist_ok=True)

    figs = figuras(runs, os.path.join(out_dir, "assets"))
    ctx = build_context(runs, figs)

    env = _env()
    with open(os.path.join(_TEMPLATES, "report.css"), encoding="utf-8") as fh:
        ctx["css"] = fh.read().replace("__TRAZA__", _css_escape(ctx["traza_pie"]))
    html = env.get_template("report.html.j2").render(**ctx)

    name = filename or f"reporte.{fmt}"
    path = _ensure_suffix(os.path.join(out_dir, name), fmt)
    # Escritura atómica: se genera en un temporal y se renombra al final. Si no,
    # un segundo pedido puede leer el archivo a medio escribir (y servirlo con un
    # Content-Length que ya no coincide: PDF corrupto).
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        if fmt == "html":
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(html)
        else:
            doc = weasyprint.HTML(string=html, base_url=out_dir)
            doc.write_pdf(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:  # pragma: no cover
                pass
    return path
