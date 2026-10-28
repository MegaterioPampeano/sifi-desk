"""Scoring v2: convierte la salida del core en candidatos ordenados y explicables.

El núcleo (``pipeline.py``) dice *qué* encontró: accesibilidad, selección de hebra,
estabilidad de extremo, veredicto ``is_efficient`` y los hits de off-target. Este módulo
dice *cuánto sirve* cada siRNA, con cinco ejes independientes y un desglose que se puede
mostrar, discutir y auditar:

    E  eficiencia termodinámica     (40)
    R  riesgo de off-target         (15)  ← alto = seguro
    S  especificidad                (15)  ← pocos off-targets distintos
    T  consenso con el motor siFi   (15)
    D  calidad de diseño            (15)

El total (0..100) es exactamente ``Σ peso[eje] * valor[eje]``; no hay constantes ocultas
ni normalizaciones posteriores. Los pesos viven en ``score.yaml``, versionado, y la
versión viaja en cada resultado: dos corridas con versiones distintas no se comparan
sin decirlo.

Lo que este módulo **no** hace: no recalcula termodinámica ni toca los binarios. Trabaja
sobre el JSON. Si un dato falta (``NaN`` en los bordes de la secuencia), se marca en
``notas`` y se usa el valor declarado en ``E.desconocido``: nunca se inventa un cero.
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml

DEFAULT_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "score.yaml")

EJE_ORDEN = ("E", "R", "S", "T", "D")

EJE_NOMBRE = {
    "E": "eficiencia",
    "R": "riesgo",
    "S": "especificidad",
    "T": "consenso_sifi",
    "D": "diseno",
}


class ScoringError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# parámetros
# --------------------------------------------------------------------------- #

def load_params(path: Optional[str] = None) -> dict:
    """Carga ``score.yaml`` y valida lo que rompe el ranking si está mal."""
    with open(path or DEFAULT_YAML, encoding="utf-8") as fh:
        params = yaml.safe_load(fh) or {}
    pesos = params.get("pesos") or {}
    faltan = [e for e in EJE_ORDEN if e not in pesos]
    if faltan:
        raise ScoringError(f"faltan pesos para los ejes: {', '.join(faltan)}")
    suma = float(sum(float(pesos[e]) for e in EJE_ORDEN))
    if abs(suma - 100.0) > 1e-6:
        raise ScoringError(f"los pesos deben sumar 100 (suman {suma:g})")
    if "version" not in params:
        raise ScoringError("score.yaml sin 'version': un score sin versión no es reproducible")
    return params


def _merge(base: dict, override: Optional[dict]) -> dict:
    """Merge superficial por eje (basta para estos params y deja el YAML legible)."""
    if not override:
        return base
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            sub = dict(out[k])
            sub.update(v)
            out[k] = sub
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# helpers numéricos
# --------------------------------------------------------------------------- #

def _num(x: Any) -> Optional[float]:
    """float o None. Acepta 'NA' (bordes de RNAplfold) y NaN."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _clip01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _bool_or_none(x: Any) -> Optional[bool]:
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    return bool(x)


def _runs(seq: str) -> int:
    """Largo del homopolímero más largo de la secuencia."""
    best = run = 1
    for i in range(1, len(seq)):
        run = run + 1 if seq[i] == seq[i - 1] else 1
        best = max(best, run)
    return best if seq else 0


def _gc(seq: str) -> Optional[float]:
    if not seq:
        return None
    gc = sum(1 for c in seq.upper() if c in "GC")
    return 100.0 * gc / len(seq)


# --------------------------------------------------------------------------- #
# normalización de la entrada
# --------------------------------------------------------------------------- #

def _iter_rows(results: Any) -> Iterable[dict]:
    """Acepta el manifest de ``run.py``, el esquema canónico o una lista de filas."""
    if isinstance(results, dict):
        if "records" in results:
            for rec in results.get("records") or []:
                for row in rec.get("sirnas") or []:
                    yield row
            return
        if "sirnas" in results:
            for row in results.get("sirnas") or []:
                yield row
            return
        raise ScoringError("results.json sin 'records' ni 'sirnas'")
    if isinstance(results, (list, tuple)):
        for row in results:
            yield row
        return
    raise ScoringError(f"tipo de results no soportado: {type(results).__name__}")


def _hits_of(row: dict) -> List[dict]:
    """Hits de off-target de una fila, en forma homogénea."""
    out: List[dict] = []
    for h in row.get("hits") or []:
        out.append({
            "name": h.get("seq_id") or h.get("name") or "?",
            "panel": h.get("panel") or h.get("db") or "",
            "mismatch": _num(h.get("mismatch")),
            "pos": h.get("pos"),
        })
    # manifest: una fila por par siRNA-hit; el hit está en hit_name
    if row.get("hit_name") and row.get("is_off_target") is not False:
        out.append({
            "name": row.get("hit_name"),
            "panel": row.get("panel") or row.get("db") or "",
            "mismatch": _num(row.get("mismatches")),
            "pos": row.get("reference_strand_pos"),
        })
    return out


def _candidates(results: Any) -> List[dict]:
    """Agrupa las filas por siRNA (el manifest repite una fila por hit)."""
    groups: Dict[tuple, dict] = {}
    for row in _iter_rows(results):
        name = row.get("sirna_name") or row.get("id") or ""
        seq = row.get("sirna_sequence") or row.get("seq") or ""
        pos = row.get("sirna_position", row.get("pos"))
        key = (name, seq.upper())
        cand = groups.get(key)
        if cand is None:
            cand = {
                "id": name,
                "seq": seq.upper(),
                "pos": pos,
                "acc": _num(row.get("accessibility_value", row.get("accessibility"))),
                "strand_sel": _bool_or_none(row.get("strand_selection")),
                "end_stab": _bool_or_none(row.get("end_stability")),
                "efficient": _bool_or_none(row.get("is_efficient", row.get("efficient"))),
                "sifi_score": _num(row.get("score")),
                "hits": [],
            }
            groups[key] = cand
        cand["hits"].extend(_hits_of(row))

    out = []
    for cand in groups.values():
        # dedup: el mismo hit puede venir de dos queries distintas
        seen, uniq = set(), []
        for h in cand["hits"]:
            k = (h.get("name"), h.get("mismatch"), h.get("pos"))
            if k not in seen:
                seen.add(k)
                uniq.append(h)
        cand["hits"] = uniq
        out.append(cand)
    return out


# --------------------------------------------------------------------------- #
# ejes
# --------------------------------------------------------------------------- #

def _eje_e(cand: dict, p: dict) -> tuple:
    cfg = p["E"]
    acc = cand["acc"]
    desconocido = float(cfg.get("desconocido", 0.5))
    acc_v = _clip01(acc) if acc is not None else desconocido
    hebra_v = {True: 1.0, False: 0.0, None: desconocido}[cand["strand_sel"]]
    extremo_v = {True: 1.0, False: 0.0, None: desconocido}[cand["end_stab"]]
    valor = (float(cfg["acceso"]) * acc_v
             + float(cfg["hebra"]) * hebra_v
             + float(cfg["extremo"]) * extremo_v)
    detalle = {"acceso": round(acc_v, 4), "hebra": hebra_v, "extremo": extremo_v}
    if acc is None:
        detalle["acceso_fuente"] = "sin dato (borde de la secuencia)"
    return _clip01(valor), detalle


def _eje_t(cand: dict, p: dict) -> tuple:
    cfg = p["T"]
    base = float(cfg["eficiente"]) if cand["efficient"] else float(cfg["no_eficiente"])
    detalle = {"is_efficient": cand["efficient"], "base": base}
    valor = base
    if cfg.get("usar_score", True) and cand["sifi_score"] is not None:
        s = _clip01(cand["sifi_score"])
        valor = 0.5 * base + 0.5 * s
        detalle["score_sifi"] = round(s, 4)
    return _clip01(valor), detalle


def _eje_s(cand: dict, p: dict) -> tuple:
    cfg = p["S"]
    unidades = 0.0
    for h in cand["hits"]:
        mm = h["mismatch"] if h["mismatch"] is not None else 0.0
        unidades += 1.0 / (1.0 + max(0.0, mm))
    valor = 1.0 / (1.0 + float(cfg["decaimiento"]) * unidades)
    return _clip01(valor), {"hits": len(cand["hits"]), "unidades": round(unidades, 4)}


def _rol_de(hit: dict, roles: Dict[str, str]) -> str:
    pid = hit.get("panel") or ""
    if pid in roles:
        return roles[pid]
    # tolera nombres versionados ("maiz_v5" -> "maiz") sin inventar roles nuevos
    base = pid.split("_v")[0] if "_v" in pid else pid
    return roles.get(base, "desconocido")


def _eje_r(cand: dict, p: dict, roles: Dict[str, str]) -> tuple:
    cfg = p["R"]
    escalones = sorted(int(k) for k in cfg["severidad"])
    pesos_rol = cfg["peso_rol"]

    riesgo = 0.0
    peor = None
    paneles = set()
    for h in cand["hits"]:
        mm = h["mismatch"] if h["mismatch"] is not None else 0.0
        nivel = max([e for e in escalones if e <= mm], default=escalones[0])
        sev = float(cfg["severidad"][nivel])
        rol = _rol_de(h, roles)
        w = float(pesos_rol.get(rol, pesos_rol.get("desconocido", 0.8)))
        aporte = sev * w
        peor = mm if peor is None else min(peor, mm)
        if h.get("panel"):
            paneles.add(h["panel"])
        riesgo = max(riesgo, aporte)

    if len(paneles) > 1:
        riesgo += float(cfg.get("penalidad_multi_panel", 0.0)) * (len(paneles) - 1)

    valor = _clip01(1.0 - riesgo)
    return valor, {"riesgo": round(min(riesgo, 1.0), 4), "peor_mismatch": peor,
                   "paneles": sorted(paneles)}


def _eje_d(cand: dict, p: dict) -> tuple:
    cfg = p["D"]
    seq = cand["seq"]
    gcp = _gc(seq)
    opt_lo, opt_hi = (float(x) for x in cfg["gc"]["optimo"])
    tol_lo, tol_hi = (float(x) for x in cfg["gc"]["tolerable"])
    if gcp is None:
        gc_v, gc_nota = 1.0, None
    elif opt_lo <= gcp <= opt_hi:
        gc_v, gc_nota = 1.0, None
    elif tol_lo <= gcp <= tol_hi:
        # rampa lineal de 1.0 (borde del óptimo) a 0.4 (borde de lo tolerable)
        if gcp < opt_lo:
            gc_v = 0.4 + 0.6 * (gcp - tol_lo) / max(1e-9, opt_lo - tol_lo)
        else:
            gc_v = 0.4 + 0.6 * (tol_hi - gcp) / max(1e-9, tol_hi - opt_hi)
        gc_nota = "gc_fuera_optimo"
    else:
        gc_v, gc_nota = 0.15, "gc_fuera_rango"

    run = _runs(seq)
    hom_max = int(cfg["homopolimero_max"])
    if not seq or run < hom_max:
        hom_v = 1.0
    elif run == hom_max:
        hom_v = 0.6
    else:
        hom_v = 0.2

    pref = [c.upper() for c in (cfg.get("extremo_preferido") or ["A", "T"])]
    ext_v = 1.0 if len(seq) > 1 and seq[1] in pref else 0.5

    valor = (float(cfg["peso_gc"]) * gc_v
             + float(cfg["peso_homopolimero"]) * hom_v
             + float(cfg["peso_extremo"]) * ext_v)
    detalle = {"gc": round(gcp, 2) if gcp is not None else None,
               "gc_valor": round(gc_v, 4),
               "homopolimero": run,
               "extremo_5p": seq[1] if len(seq) > 1 else None}
    if gc_nota:
        detalle["gc_nota"] = gc_nota
    return _clip01(valor), detalle


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

def score_candidate(cand: dict, params: dict, roles: Optional[Dict[str, str]] = None) -> dict:
    """Puntúa un candidato ya normalizado y devuelve el desglose completo."""
    roles = roles or {}
    valores = {
        "E": _eje_e(cand, params),
        "R": _eje_r(cand, params, roles),
        "S": _eje_s(cand, params),
        "T": _eje_t(cand, params),
        "D": _eje_d(cand, params),
    }
    desglose, total, notas = {}, 0.0, []
    for eje in EJE_ORDEN:
        valor, detalle = valores[eje]
        peso = float(params["pesos"][eje])
        # se publica el valor redondeado y el aporte se calcula con ESE valor:
        # así cualquiera puede reproducir el total a mano desde el desglose.
        valor_r = round(valor, 4)
        aporte = peso * valor_r
        total += aporte
        desglose[eje] = {
            "nombre": EJE_NOMBRE[eje],
            "peso": peso,
            "valor": valor_r,
            "aporte": aporte,
            "detalle": detalle,
        }

    r_valor = valores["R"][0]
    umbrales = params.get("umbrales") or {}
    rec = float(umbrales.get("recomendado", 70))
    rev = float(umbrales.get("revisar", 50))
    desc = float(umbrales.get("descartar", 25))

    if total >= rec:
        banda = "recomendado"
    elif total >= rev:
        banda = "revisar"
    elif total >= desc:
        banda = "bajo"
    else:
        banda = "descartar"

    if r_valor < float(umbrales.get("riesgo_alto", 0.35)):
        notas.append("riesgo_alto")
    if cand["hits"] and any((h["mismatch"] or 0) == 0 for h in cand["hits"]):
        notas.append("hit_perfecto")
    if cand["acc"] is None:
        notas.append("sin_accesibilidad")
    if cand["efficient"] is False:
        notas.append("no_eficiente_sifi")
    if desglose["D"]["detalle"].get("gc_nota"):
        notas.append(desglose["D"]["detalle"]["gc_nota"])
    if desglose["D"]["detalle"]["homopolimero"] >= int(params["D"]["homopolimero_max"]):
        notas.append("homopolimero")

    return {
        "id": cand["id"],
        "pos": cand["pos"],
        "seq": cand["seq"],
        "total": round(total, 2),
        "banda": banda,
        "n_hits": len(cand["hits"]),
        "desglose": desglose,
        "notas": notas,
    }


def score_candidates(results: Any, params: Optional[dict] = None,
                     panel_roles: Optional[Dict[str, str]] = None) -> List[dict]:
    """Puntúa todos los siRNAs de un ``results.json`` y los devuelve ordenados.

    ``results``: el manifest que escribe ``run.run_once`` (``records[].sirnas[]``),
    el esquema canónico (``sirnas[]`` con ``hits[]``) o una lista de filas.

    ``params``: overrides sobre ``score.yaml`` (se mergea por eje).
    ``panel_roles``: ``{panel_id: rol}``; sin esto los paneles se tratan como
    ``desconocido`` y el eje R queda conservador (0.8), nunca optimista.
    """
    base = load_params()
    params = _merge(base, params)
    if abs(float(sum(float(params["pesos"][e]) for e in EJE_ORDEN)) - 100.0) > 1e-6:
        raise ScoringError("los pesos override no suman 100")

    scored = [score_candidate(c, params, panel_roles) for c in _candidates(results)]
    scored.sort(key=lambda r: (-r["total"], r["pos"] if r["pos"] is not None else 0))
    return scored


def summarize(scored: Sequence[dict], params: Optional[dict] = None) -> dict:
    """Resumen para el reporte/visor: conteos por banda y versión del scoring."""
    p = _merge(load_params(), params)
    por_banda: Dict[str, int] = {}
    for r in scored:
        por_banda[r["banda"]] = por_banda.get(r["banda"], 0) + 1
    return {
        "scoring": {"schema": p.get("schema", "sifi.score/2"), "version": p["version"],
                    "pesos": {e: float(p["pesos"][e]) for e in EJE_ORDEN}},
        "n": len(scored),
        "por_banda": por_banda,
        "mejor": scored[0]["id"] if scored else None,
        "mejor_total": scored[0]["total"] if scored else None,
    }
