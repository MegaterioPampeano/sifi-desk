"""Digest en texto plano: un resumen corto por ítem, sin prosa inventada.

El resumen no lo escribe un LLM: se arma con los campos que devolvió la fuente y con la
query que encontró el paper. `por_que_importa` sale de la config (`why` de cada query),
así que lo que se afirma sobre relevancia es exactamente el criterio que el usuario definió.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SOURCE_LABEL = {
    "crossref": "Crossref",
    "pubmed": "PubMed",
    "biorxiv": "bioRxiv",
    "github": "GitHub",
}


def source_label(item: Dict[str, Any]) -> str:
    src = item.get("source") or "?"
    return SOURCE_LABEL.get(src, src)


def summarize_item(item: Dict[str, Any], index: Optional[int] = None) -> str:
    """2–4 líneas: qué, de dónde, cuándo, dónde leerlo y por qué apareció."""
    head = f"{index}. " if index is not None else ""
    date = item.get("date") or "sin fecha"
    line = f"{head}[{source_label(item)}] {date} — {item.get('title') or '(sin título)'}"

    why_bits: List[str] = []
    matched = item.get("matched_by") or []
    if matched:
        first = matched[0]
        if first.get("why"):
            why_bits.append(first["why"])
        if len(matched) > 1:
            ids = ", ".join(str(q.get("query_id") or q.get("query") or "?") for q in matched[1:])
            why_bits.append(f"también lo levantó: {ids}")
    elif item.get("why"):
        why_bits.append(item["why"])
    if item.get("matched_terms"):
        why_bits.append("términos: " + ", ".join(item["matched_terms"][:6]))

    lines = [line]
    if why_bits:
        lines.append("   por qué: " + " · ".join(why_bits))
    refs = []
    if item.get("doi"):
        refs.append("doi:" + item["doi"])
    if item.get("pmid"):
        refs.append("pmid:" + str(item["pmid"]))
    if item.get("query"):
        refs.append(f'query: "{item["query"]}"')
    if refs:
        lines.append("   " + " · ".join(refs))
    if item.get("url"):
        lines.append("   " + item["url"])
    return "\n".join(lines)


def render_digest(digest: Dict[str, Any], max_items: Optional[int] = None,
                  show_warnings: bool = True) -> str:
    """Digest completo, listo para mandar por Telegram/consola."""
    items: List[Dict[str, Any]] = list(digest.get("items") or [])
    out: List[str] = []
    since = digest.get("since") or "?"
    out.append(f"Novedades siFi-Desk · desde {since} · {len(items)} nuevas")
    if digest.get("summarized"):
        out.append(f"({digest['summarized']} ítems revisados; el resto ya estaba en el inventario)")
    for i, item in enumerate(items[:max_items] if max_items else items, start=1):
        out.append("")
        out.append(summarize_item(item, index=i))
    if max_items and len(items) > max_items:
        out.append(f"\n… y {len(items) - max_items} más en el JSON.")
    if show_warnings and digest.get("warnings"):
        out.append("")
        out.append("Avisos:")
        out.extend(f"- {w}" for w in digest["warnings"])
    return "\n".join(out)
