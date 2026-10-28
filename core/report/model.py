"""Normalización de manifests ``sifi.results/1`` para el reporte.

Todo lo que el template necesita queda calculado acá, en estructuras simples
(dicts/listas): el HTML no piensa, sólo muestra. Las tolerancias son deliberadas:
un manifest viejo o un fixture de prueba puede no traer ``tools``, ``database`` o
``core_version``; el reporte lo dice explícitamente en vez de inventar datos.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

# Permite importar ``report`` tanto desde ``core/`` como desde la raíz del repo.
_CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

import sifi  # noqa: E402
from sifi.scoring import ScoringError, score_candidates  # noqa: E402

SCHEMA_PREFIX = "sifi.results/"

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")

# etiquetas legibles para las claves de params.yaml / SifiParams.as_dict()
PARAM_LABELS = {
    "mode": "Modo",
    "sirna_size": "Largo del siRNA (nt)",
    "mismatches": "Mismatches permitidos",
    "strand_check": "Chequeo de selección de hebra",
    "end_check": "Chequeo de estabilidad de extremo",
    "accessibility_check": "Chequeo de accesibilidad",
    "terminal_check": "Chequeo de extremo 5' (A/T)",
    "no_efficience": "Omite el filtro de eficiencia",
    "accessibility_window": "Columna de accesibilidad (u)",
    "end_stability_threshold": "Umbral de estabilidad de extremo",
    "target_site_accessibility_threshold": "Umbral de accesibilidad del sitio",
    "winsize": "Ventana de plegado (W)",
    "span": "Span del plegado (L)",
    "temperature": "Temperatura (°C)",
    "overhang": "Overhang 3' (nt)",
    "end_nucleotides": "Nucleótidos de extremo (nt)",
    "sirna_start_position": "Posición inicial del corte",
    "rnaplfold.W": "RNAplfold: ventana (W)",
    "rnaplfold.span": "RNAplfold: span (L)",
    "rnaplfold.T": "RNAplfold: temperatura (°C)",
    "panels": "Paneles",
    "scoring": "Scoring",
}

# parámetros que el apéndice de metodología destaca siempre:
# (clave, etiqueta, valor canónico de siFi, unidad)
CLAVES_METODOLOGIA = (
    ("sirna_size", "Largo del siRNA", 21, "nt"),
    ("temperature", "Temperatura de plegado", 22, "°C"),
    ("winsize", "Ventana RNAplfold (W)", 80, ""),
    ("span", "Span RNAplfold (L)", 40, ""),
)

BAND_LABEL = {
    "recomendado": "recomendado",
    "revisar": "revisar",
    "bajo": "bajo",
    "descartar": "descartar",
}

NOTA_LABEL = {
    "riesgo_alto": "riesgo alto",
    "hit_perfecto": "hit perfecto",
    "sin_accesibilidad": "sin accesibilidad",
    "no_eficiente_sifi": "no eficiente (siFi)",
    "gc_fuera_optimo": "GC fuera de óptimo",
    "gc_fuera_rango": "GC fuera de rango",
    "homopolimero": "homopolímero",
    "acceso_fuente": "accesibilidad estimada",
}

PANEL_SIN_DECLARAR = "sin panel declarado"


class ReportError(RuntimeError):
    """Entrada inválida o manifest que no se puede reportar."""


# --------------------------------------------------------------------------- #
# fechas y valores
# --------------------------------------------------------------------------- #

def fecha_larga(iso: Optional[str]) -> str:
    """ISO-8601 -> '28 de octubre de 2026, 18:00 UTC' (o el texto original)."""
    if not iso:
        return "no informada"
    txt = str(iso)
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError:
        return txt
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return f"{dt.day} de {MESES[dt.month - 1]} de {dt.year}, {dt:%H:%M} UTC"


def ahora_larga() -> str:
    return fecha_larga(datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _digest(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# carga / normalización
# --------------------------------------------------------------------------- #

def _load(raw: Any, index: int) -> dict:
    if isinstance(raw, (str, os.PathLike)):
        path = os.fspath(raw)
        if not os.path.exists(path):
            raise ReportError(f"no existe el archivo de resultados: {path}")
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError) as exc:
            raise ReportError(f"no pude leer {path}: {exc}") from exc
    if isinstance(raw, dict):
        # conveniencia: {"runs": [manifest, ...]}
        if "runs" in raw and "records" not in raw:
            raise ReportError("pasá la lista de corridas directamente, no el envoltorio 'runs'")
        return raw
    raise ReportError(f"corrida #{index + 1}: tipo no soportado ({type(raw).__name__})")


def _canonical(manifest: dict) -> dict:
    """Devuelve una copia con ``records[].sirnas[]``; acepta el esquema canónico."""
    if not isinstance(manifest, dict):
        raise ReportError("el results.json no es un objeto JSON")
    if "records" in manifest:
        records = manifest.get("records") or []
        if not isinstance(records, list):
            raise ReportError("'records' debe ser una lista")
        return manifest
    if "sirnas" in manifest:
        rec = {
            "query_name": manifest.get("query_name") or "(sin nombre)",
            "query_length": manifest.get("query_length"),
            "sirnas": manifest.get("sirnas") or [],
            "summary": manifest.get("summary") or {},
            "warnings": manifest.get("warnings") or [],
            "error": manifest.get("error"),
        }
        out = {k: v for k, v in manifest.items() if k != "sirnas"}
        out["records"] = [rec]
        return out
    if isinstance(manifest.get("sirnas") or manifest.get("results"), list):
        return {"records": [{"query_name": "(sin nombre)",
                             "sirnas": manifest.get("sirnas") or manifest.get("results")}]}
    raise ReportError("results.json sin 'records' ni 'sirnas' (¿es un manifest sifi.results/1?)")


def _flatten(obj: Any, prefix: str = "") -> List[tuple]:
    out: List[tuple] = []
    if not isinstance(obj, dict):
        return out
    for key, value in obj.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.extend(_flatten(value, name + "."))
        elif isinstance(value, (list, tuple)) and value and all(
                isinstance(v, dict) for v in value):
            # listas de dicts no se muestran como parámetro: se resumen
            out.append((name, f"{len(value)} elemento(s)"))
        else:
            out.append((name, value))
    return out


def _param_rows(params: dict) -> List[dict]:
    rows = []
    known = set(PARAM_LABELS)
    for key, value in _flatten(params):
        label = PARAM_LABELS.get(key, key)
        rows.append({"clave": key, "label": label, "valor": value,
                     "conocido": key in known or key.split(".")[0] in known})
    # primero los parámetros conocidos y con etiqueta, en el orden de PARAM_LABELS
    order = {k: i for i, k in enumerate(PARAM_LABELS)}
    rows.sort(key=lambda r: (0 if r["conocido"] else 1,
                             order.get(r["clave"], 999), r["clave"]))
    return rows


def _tool_rows(tools: Any) -> List[dict]:
    if not isinstance(tools, dict):
        return []
    rows = []
    for name, info in tools.items():
        if isinstance(info, dict):
            rows.append({
                "nombre": name,
                "path": info.get("path") or "—",
                "version": info.get("version") or "—",
                "sha256": info.get("sha256") or "—",
            })
        else:
            rows.append({"nombre": name, "path": str(info), "version": "—", "sha256": "—"})
    return rows


def _record_error(rec: dict) -> str:
    err = rec.get("error")
    return str(err) if err else ""


# --------------------------------------------------------------------------- #
# figuras: datos
# --------------------------------------------------------------------------- #

def panel_hits(records: Sequence[dict]) -> List[dict]:
    """Hits de off-target por panel, partidos en perfectos (0 mm) y con mismatches.

    El manifest del core no atribuye cada hit a un panel (el nombre del hit alcanza
    para buscarlo). Si la corrida agrega ``panel``/``db`` en la fila, se usa; si no,
    todo cae en 'sin panel declarado' — el reporte no inventa una atribución.
    """
    agg: Dict[str, dict] = {}
    for rec in records:
        for row in rec.get("sirnas") or []:
            hit = row.get("hit_name")
            if not hit or row.get("is_off_target") is False:
                continue
            panel = (row.get("panel") or row.get("db") or row.get("panel_id")
                     or PANEL_SIN_DECLARAR)
            item = agg.setdefault(str(panel), {"panel": str(panel), "perfect": 0,
                                               "imperfect": 0})
            mm = row.get("mismatches")
            try:
                mm_i = int(mm)
            except (TypeError, ValueError):
                mm_i = None
            if mm_i == 0:
                item["perfect"] += 1
            else:
                item["imperfect"] += 1
    out = sorted(agg.values(), key=lambda x: (-(x["perfect"] + x["imperfect"]), x["panel"]))
    return out


def _panel_summary(panels: Sequence[dict], max_rows: int = 12) -> List[dict]:
    if len(panels) <= max_rows:
        return list(panels)
    top = list(panels[:max_rows - 1])
    rest = panels[max_rows - 1:]
    top.append({
        "panel": f"otros ({len(rest)} paneles)",
        "perfect": sum(p["perfect"] for p in rest),
        "imperfect": sum(p["imperfect"] for p in rest),
    })
    return top


def _scoring_overrides(manifest: dict) -> Optional[dict]:
    sc = manifest.get("scoring")
    if not isinstance(sc, dict):
        return None
    out: Dict[str, Any] = {}
    if isinstance(sc.get("pesos"), dict):
        out["pesos"] = sc["pesos"]
    if isinstance(sc.get("weights"), dict):
        out["pesos"] = sc["weights"]
    if isinstance(sc.get("umbrales"), dict):
        out["umbrales"] = sc["umbrales"]
    return out or None


def _panel_roles(manifest: dict) -> Dict[str, str]:
    for source in (manifest.get("panel_roles"),
                   (manifest.get("extra") or {}).get("panel_roles"),
                   (manifest.get("params") or {}).get("panel_roles")):
        if isinstance(source, dict):
            return {str(k): str(v) for k, v in source.items()}
    return {}


# --------------------------------------------------------------------------- #
# RunView
# --------------------------------------------------------------------------- #

@dataclass
class RunView:
    index: int
    run_id: str
    run_id_declarado: bool
    manifest_digest: str
    generated_at: Optional[str]
    generated_at_largo: str
    core_version: str
    core_version_declarada: bool
    params: dict
    param_rows: List[dict]
    tools: List[dict]
    tools_declarados: bool
    database: dict
    query_file: Optional[str]
    query_sha256: Optional[str]
    records: List[dict]
    candidates: List[dict]
    band_counts: Dict[str, int]
    best: Optional[dict]
    n_rows: int
    n_candidates: int
    panels: List[dict]
    e_values: List[float]
    warnings: List[str]
    errors: List[dict]
    notas_scoring: List[str] = field(default_factory=list)

    @property
    def etiqueta(self) -> str:
        return f"Corrida {self.index} — {self.run_id}"


def build_run(raw: Any, index: int = 1) -> RunView:
    manifest = _canonical(_load(raw, index - 1))
    manifest_digest = _digest(manifest)

    run_id = manifest.get("run_id")
    declarado = bool(run_id)
    if not declarado:
        run_id = manifest_digest
    run_id = str(run_id)

    core_version = manifest.get("core_version")
    core_declarada = bool(core_version)
    core_version = str(core_version or sifi.__version__)

    records = manifest.get("records") or []
    try:
        candidates = score_candidates(manifest, params=_scoring_overrides(manifest),
                                      panel_roles=_panel_roles(manifest))
    except ScoringError as exc:
        raise ReportError(f"corrida {run_id}: scoring inválido: {exc}") from exc

    band_counts: Dict[str, int] = {}
    for cand in candidates:
        band_counts[cand["banda"]] = band_counts.get(cand["banda"], 0) + 1

    # notas del scoring, en orden de aparición, sin repetir
    notas: List[str] = []
    for cand in candidates:
        for nota in cand.get("notas") or []:
            if nota not in notas:
                notas.append(nota)

    warnings: List[str] = []
    errors: List[dict] = []
    n_rows = 0
    for rec in records:
        n_rows += len(rec.get("sirnas") or [])
        for w in rec.get("warnings") or []:
            if w not in warnings:
                warnings.append(str(w))
        err = _record_error(rec)
        if err:
            errors.append({"query": rec.get("query_name") or "(sin nombre)", "error": err})

    e_values = [float(c["desglose"]["E"]["valor"]) for c in candidates]
    db = manifest.get("database") if isinstance(manifest.get("database"), dict) else {}

    return RunView(
        index=index,
        run_id=run_id,
        run_id_declarado=declarado,
        manifest_digest=manifest_digest,
        generated_at=manifest.get("generated_at"),
        generated_at_largo=fecha_larga(manifest.get("generated_at")),
        core_version=core_version,
        core_version_declarada=core_declarada,
        params=manifest.get("params") or {},
        param_rows=_param_rows(manifest.get("params") or {}),
        tools=_tool_rows(manifest.get("tools")),
        tools_declarados=bool(manifest.get("tools")),
        database=db,
        query_file=manifest.get("query_file"),
        query_sha256=manifest.get("query_file_sha256"),
        records=records,
        candidates=candidates,
        band_counts=band_counts,
        best=candidates[0] if candidates else None,
        n_rows=n_rows,
        n_candidates=len(candidates),
        panels=_panel_summary(panel_hits(records)),
        e_values=e_values,
        warnings=warnings,
        errors=errors,
        notas_scoring=notas,
    )


def build_runs(results: Any) -> List[RunView]:
    """Acepta un manifest, una ruta, o una lista mezclando ambos."""
    if isinstance(results, (str, os.PathLike, dict)):
        items: Sequence[Any] = [results]
    elif isinstance(results, (list, tuple)):
        items = list(results)
    else:
        raise ReportError(f"tipo de 'results' no soportado: {type(results).__name__}")
    if not items:
        raise ReportError("no hay ninguna corrida para reportar")
    return [build_run(raw, i + 1) for i, raw in enumerate(items)]


# --------------------------------------------------------------------------- #
# metodología
# --------------------------------------------------------------------------- #

def _txt(value: Any) -> str:
    """Valor corto para el apéndice (sin depender de los filtros del template)."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, float):
        return (str(int(value)) if value.is_integer()
                else f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ","))
    return str(value)


def _param_value(params: dict, key: str) -> Optional[Any]:
    """Busca el parámetro en el manifest: primero plano, después en rnaplfold.*."""
    if key in params:
        return params[key]
    nested = {"temperature": ("rnaplfold", "T"),
              "winsize": ("rnaplfold", "W"),
              "span": ("rnaplfold", "span")}.get(key)
    if nested and isinstance(params.get(nested[0]), dict):
        if nested[1] in params[nested[0]]:
            return params[nested[0]][nested[1]]
    return None


def _mismo_numero(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a) == str(b)


def metodologia_rows(runs: Sequence[RunView]) -> List[dict]:
    """Valores clave del método: canónicos de siFi vs. lo que declaró cada corrida.

    El apéndice describe la configuración canónica (21 nt, 22 °C, W=80, L=40). Si una
    corrida declaró otro valor, se muestra al lado y se marca: el apéndice no puede
    contradecir en silencio al manifest que se está reportando.
    """
    rows: List[dict] = []
    for key, label, canonico, unidad in CLAVES_METODOLOGIA:
        declarados = []
        for run in runs:
            valor = _param_value(run.params, key)
            if valor is not None:
                declarados.append({"run_id": run.run_id, "valor": valor})
        coincide = all(_mismo_numero(d["valor"], canonico) for d in declarados)
        rows.append({
            "label": label,
            "canonico": f"{_txt(canonico)} {unidad}".strip(),
            "declarados": declarados,
            "coincide": coincide,
            "en_corrida": "; ".join(
                f"{_txt(d['valor'])} {unidad}".strip() for d in declarados) or "no declarado",
            "difiere": not coincide,
        })
    return rows


def diferencias_metodologia(rows: Sequence[dict]) -> List[str]:
    """Frases para avisar si alguna corrida se apartó de los valores canónicos."""
    out = []
    for row in rows:
        if not row.get("difiere"):
            continue
        detalle = ", ".join(f"{d['run_id']}={_txt(d['valor'])}" for d in row["declarados"])
        out.append(f"{row['label']}: canónico {row['canonico']}, declarado {detalle}")
    return out
