"""Traducción de la consulta del usuario a FTS5, con ranking bm25 y snippet.

Lo que escribe el usuario no es sintaxis FTS5: es lenguaje natural. Reglas:

* `dsrna delivery` → `dsrna* AND delivery*` (las palabras sueltas se combinan con AND);
* `"dsrna delivery"` → frase exacta;
* `dsrna OR sirna` → alternativa (el operador se respeta en mayúsculas);
* `tag:entrega` → filtro por etiqueta, no término de búsqueda;
* `dsrna*` → prefijo explícito;
* palabras de 4+ letras se buscan como prefijo (tolerante a plurales/sufijos);
* `year:2026` y `status:ok` también se aceptan como filtros.

El ranking usa `bm25(papers_fts, 8, 3, 1)`: título pesa más que abstract, y abstract más
que cuerpo. El snippet se arma alrededor del match en el cuerpo; si el match fue sólo en
el título/abstract, se muestra ese texto.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from typing import Any, Dict, List, Optional, Sequence

from .store import BM25_BODY, BM25_ABSTRACT, BM25_TITLE, Library

AUTO_PREFIX_MIN = 4
SNIPPET_TOKENS = 32


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _clean_word(word: str) -> str:
    """Deja sólo letras/números; separa guiones y barras en palabras."""
    word = _fold(word).strip()
    word = re.sub(r"^[^\w]+|[^\w]+$", "", word)
    word = re.sub(r"[^\w]+", " ", word)
    return re.sub(r"\s+", " ", word).strip()


def _term(word: str, auto_prefix: bool = True) -> str:
    explicit = word.endswith("*")
    if explicit:
        word = word[:-1]
    cleaned = _clean_word(word)
    if not cleaned:
        return ""
    if " " in cleaned:  # `dsRNA-mediated` → frase
        return '"' + cleaned + '"'
    if explicit or (auto_prefix and len(cleaned) >= AUTO_PREFIX_MIN):
        return f"{cleaned}*"
    return cleaned


def parse(query: str) -> Dict[str, Any]:
    """Devuelve `{match, tags, year, status, terms}` sin tocar la base."""
    text = _fold(query)
    tags: List[str] = []
    year: Optional[int] = None
    status: Optional[str] = None

    # filtros `clave:valor` fuera de comillas
    def take_filter(pattern: str, value: str) -> str:
        nonlocal year, status
        key, _, val = value.partition(":")
        val = val.strip().strip('"')
        if not val:
            return ""
        if key == "tag":
            tags.append(val.lower())
        elif key == "year" and re.fullmatch(r"\d{4}", val):
            year = int(val)
        elif key == "status":
            status = val.lower()
        return " "

    text = re.sub(r'(?<![\w-])(tag|year|status):("[^"]*"|\S+)',
                  lambda m: take_filter(m.group(1), m.group(0)), text)

    parts: List[str] = []
    pending: Optional[str] = None
    tokens = re.findall(r'"[^"]*"|\S+', text)
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        if token.startswith('"') and token.endswith('"') and len(token) >= 2:
            phrase = _clean_word(token[1:-1])
            if not phrase:
                continue
            term = f'"{phrase}"'
        elif token.upper() in ("OR", "AND", "NOT"):
            if not parts:
                continue
            pending = token.upper()
            continue
        else:
            term = _term(token)
            if not term:
                continue
        if parts:
            parts.append(pending or "AND")
        parts.append(term)
        pending = None
    while parts and parts[-1] in ("AND", "OR", "NOT"):
        parts.pop()
    return {"match": " ".join(parts), "tags": tags, "year": year,
            "status": status, "terms": tokens}


def build_match(query: str) -> str:
    return parse(query)["match"]


def _snippet(row: Dict[str, Any], query: str) -> str:
    for key in ("body_snip", "abs_snip", "title_snip"):
        value = (row.get(key) or "").strip()
        if "[[" in value:
            return re.sub(r"\s+", " ", value)
    return ""


def search(lib: Library, query: str = "", tags: Optional[Sequence[str]] = None,
           year: Optional[int] = None, status: Optional[str] = None,
           limit: int = 20, offset: int = 0, auto_prefix: bool = True) -> Dict[str, Any]:
    """Busca y devuelve `{query, match, count, results[]}`."""
    parsed = parse(query or "")
    all_tags = list(dict.fromkeys([*(tags or []), *parsed["tags"]]))
    year = year if year is not None else parsed["year"]
    status = status or parsed["status"]
    match = parsed["match"]

    where: List[str] = []
    params: List[Any] = []
    for tag in all_tags:
        where.append("p.id IN (SELECT paper_id FROM tags WHERE tag = ?)")
        params.append(tag)
    if year is not None:
        where.append("p.year = ?")
        params.append(int(year))
    if status:
        where.append("p.status = ?")
        params.append(status)

    base_cols = """p.id, p.doi, p.pmid, p.pmcid, p.title, p.authors, p.journal, p.year,
                   p.status, p.oa_status, p.license, p.pdf_path, p.pdf_sha256,
                   p.pdf_bytes, p.pages, p.text_chars, p.motivo, p.source, p.added_at"""

    if match:
        sql = f"""
            SELECT {base_cols},
                   snippet(papers_fts, 0, '[[', ']]', '…', {SNIPPET_TOKENS}) AS title_snip,
                   snippet(papers_fts, 1, '[[', ']]', '…', {SNIPPET_TOKENS}) AS abs_snip,
                   snippet(papers_fts, 2, '[[', ']]', '…', {SNIPPET_TOKENS}) AS body_snip,
                   bm25(papers_fts, {BM25_TITLE}, {BM25_ABSTRACT}, {BM25_BODY}) AS score
            FROM papers_fts JOIN papers p ON p.id = papers_fts.rowid
            WHERE papers_fts MATCH ?
        """
        params = [match, *params]
    else:
        sql = f"""
            SELECT {base_cols}, '' AS title_snip, '' AS abs_snip, '' AS body_snip,
                   0.0 AS score
            FROM papers p WHERE 1=1
        """
    if where:
        sql += " AND " + " AND ".join(where)
    sql += " ORDER BY score ASC, p.year DESC, p.id DESC" if match else \
           " ORDER BY p.added_at DESC, p.id DESC"
    sql += " LIMIT ? OFFSET ?"
    params += [int(limit), int(offset)]

    rows = []
    for row in lib.db.execute(sql, params):
        data = dict(row)
        data["tags"] = lib.tags(int(data["id"]))
        data["snippet"] = _snippet(data, query)
        rows.append(data)

    count_sql = "SELECT COUNT(*) FROM papers_fts JOIN papers p ON p.id = papers_fts.rowid"
    count_sql += (" WHERE papers_fts MATCH ?" if match else " WHERE 1=1")
    count_params = [match, *[p for p in params[1:len(params) - 2]]] if match else \
        params[:len(params) - 2]
    if where:
        count_sql += " AND " + " AND ".join(where)
    total = lib.db.execute(count_sql, count_params).fetchone()[0]

    return {"query": query, "match": match, "filters": {"tags": all_tags, "year": year,
                                                        "status": status},
            "count": int(total), "results": rows}


def highlight(text: str) -> str:
    """Convierte `[[...]]` en ANSI inverso para el CLI; sin TTY o con `NO_COLOR`, lo limpia."""
    text = text or ""
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text.replace("[[", "").replace("]]", "")
    return text.replace("[[", "\033[7m").replace("]]", "\033[0m")
