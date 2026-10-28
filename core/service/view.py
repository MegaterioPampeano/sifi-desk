"""Adaptador manifest `sifi.results/1` -> forma que consume la ventana.

El manifest es el contrato científico: no se toca ni se recalcula nada. Acá
sólo se **presentan** los datos que ya trae (candidatos puntuados, hits por
panel, largo del gen) con los nombres que espera `ui/assets/js`.

Si un manifest viejo no trae `candidates`, se puntúa con `sifi.scoring` (la
misma función que usa el pipeline), nunca con una fórmula propia de la UI.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

def _gc(seq: Optional[str]) -> Optional[float]:
    if not seq:
        return None
    s = seq.upper()
    return round(100.0 * sum(1 for c in s if c in "GC") / len(s), 2)


def _hits_por_sirna(rows: List[dict]) -> Dict[tuple, List[dict]]:
    out: Dict[tuple, List[dict]] = {}
    for row in rows:
        if not row.get("is_off_target"):
            continue
        key = (row.get("sirna_name"), row.get("sirna_position"))
        out.setdefault(key, []).append(row)
    return out


def ui_results(manifest: dict, run: Optional[dict] = None) -> dict:
    """Devuelve `{records, panels, params, scoring, ...}` listo para la UI."""
    run = run or {}
    public = run.get("request") or {}
    params = manifest.get("params") or {}
    public_panels = {p.get("id"): p for p in (public.get("panels") or [])}
    roles = {p.get("id"): p.get("role") for p in (public.get("panels") or [])
             if p.get("role")}

    # sólo si el manifest es viejo y no trae scoring: usar el del pipeline
    need_score = any("candidates" not in rec for rec in manifest.get("records", []))
    scored_manifest = None
    if need_score:
        try:
            from sifi import scoring as _scoring
            scored_manifest = _scoring.score_candidates(manifest, _scoring.load_params(), roles)
        except Exception:  # pragma: no cover - manifest raro: se muestra vacío
            scored_manifest = None
    by_query = {}
    if scored_manifest:
        for cand in scored_manifest:
            by_query.setdefault(cand.get("query_name"), []).append(cand)

    records = []
    for rec in manifest.get("records", []):
        query_name = rec.get("query_name") or ""
        rows = rec.get("sirnas") or []
        hits_map = _hits_por_sirna(rows)
        row_by_key = {(r.get("sirna_name"), r.get("sirna_position")): r for r in rows}
        cands = rec.get("candidates")
        if cands is None:
            cands = by_query.get(query_name, [])

        out_cands = []
        for cand in cands:
            key = (cand.get("id"), cand.get("pos"))
            row = row_by_key.get(key) or {}
            hits = []
            for h in hits_map.get(key, []):
                pid = h.get("panel")
                ppub = public_panels.get(pid) or {}
                hits.append({
                    "panel": pid or pmeta.get("name") or "panel",
                    "panel_nombre": ppub.get("nombre") or pid or "panel",
                    "rol": roles.get(pid) or "desconocido",
                    "seq_id": h.get("hit_name"),
                    "mismatch": _int(h.get("mismatches")),
                    "pos": h.get("reference_strand_pos"),
                    "strand": h.get("strand"),
                })
            item = dict(cand)
            item.update({
                "acc": row.get("accessibility_value", item.get("acc")),
                "strand": row.get("strand", item.get("strand", "+")),
                "gc": item.get("gc", _gc(cand.get("seq"))),
                "efficient": row.get("is_efficient", item.get("efficient")),
                "strand_selection": row.get("strand_selection", item.get("strand_selection")),
                "end_stability": row.get("end_stability", item.get("end_stability")),
                "sifi_score": item.get("sifi_score"),
                "dg": item.get("dg"),
                "n_hits": len(hits) if hits else int(item.get("n_hits") or 0),
                "hits": hits,
            })
            item.setdefault("notas", [])
            out_cands.append(item)

        longitud = rec.get("query_length")
        if not longitud and rows:
            longitud = max((r.get("sirna_position") or 0) + len(r.get("sirna_sequence") or "")
                           for r in rows)
        records.append({
            "query_name": query_name,
            "gene": {"id": query_name, "nombre": query_name, "longitud": longitud,
                     "secuencia": None, "regiones": []},
            "candidates": out_cands,
            "scoring": rec.get("scoring") or {},
            "error": rec.get("error"),
        })

    scoring = manifest.get("scoring") or {}
    if not scoring and records:
        scoring = records[0].get("scoring") or {}
    panel_ids = [p.get("id") for p in public.get("panels") or [] if p.get("id")]
    if not panel_ids:
        panel_ids = [manifest.get("database", {}).get("panel_id")] if \
            manifest.get("database", {}).get("panel_id") else []

    return {
        "schema": "sifi.ui.results/1",
        "run_id": run.get("run_id") or manifest.get("run_id"),
        "generated_at": manifest.get("generated_at"),
        "params": {
            "mode": public.get("mode") or params.get("mode") or "design",
            "mismatches": _int(params.get("mismatches")),
            "sirna_size": _int(params.get("sirna_size")),
        },
        "panel_ids": panel_ids,
        "panels": [
            {"id": p.get("id"), "nombre": p.get("nombre") or p.get("id"),
             "rol": p.get("role") or p.get("rol"), "version": p.get("version")}
            for p in (public.get("panels") or [])
        ],
        "records": records,
        "scoring": scoring,
        "manifest_path": None,
        "source": "service",
    }


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
