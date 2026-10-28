"""CLI de la biblioteca (edición developer).

Desde `core/`:

    SIFI_EDITION=dev python3 -m library.cli add --doi 10.3390/plants15203237 --tag entrega
    SIFI_EDITION=dev python3 -m library.cli import-watch watch/ejemplo_novedades.json --limit 5
    SIFI_EDITION=dev python3 -m library.cli search "dsrna delivery" --tag entrega
    SIFI_EDITION=dev python3 -m library.cli show 3 --text | less
    SIFI_EDITION=dev python3 -m library.cli tag 3 +test -entrega
    SIFI_EDITION=dev python3 -m library.cli note 3 --kind idea_test "probar el panel ..."
    SIFI_EDITION=dev python3 -m library.cli stats
    SIFI_EDITION=dev python3 -m library.cli export --tag entrega --out /tmp/biblioteca

En `stable` (default) todo contesta "función de la edición developer".
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from . import __version__, edition, fetch, search as search_mod, store

DEFAULT_AUTHOR = os.environ.get("SIFI_AUTHOR") or getpass.getuser()


# --------------------------------------------------------------------------- #
# helpers de salida
# --------------------------------------------------------------------------- #
def _color(text: str, code: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(text: str) -> str:
    return _color(text, "1")


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=1, default=str))


def _open(args) -> store.Library:
    return store.Library(data_dir=args.data_dir, path=args.db)


def _http(args) -> fetch.Http:
    return fetch.Http(cache_dir=args.cache_dir, offline=bool(getattr(args, "offline", False)))


def _paper_line(p: Dict[str, Any]) -> str:
    status = _color("PDF", "32") if p.get("status") == "ok" else \
        _color("—", "33") + f" {p.get('motivo', '')[:60]}"
    tags = ", ".join(p.get("tags") or [])
    return (f"[{p['id']}] {p.get('year') or '????'} · {p.get('title') or '(sin título)'}\n"
            f"      {p.get('journal') or ''} · {p.get('doi') or ''} · {status}"
            + (f" · tags: {tags}" if tags else ""))


# --------------------------------------------------------------------------- #
# comandos
# --------------------------------------------------------------------------- #
def cmd_add(args) -> int:
    if not (args.doi or args.pmid or args.url):
        print("error: indicá --doi, --pmid o --url", file=sys.stderr)
        return 2
    with _open(args) as lib:
        result = fetch.ingest(lib, doi=args.doi, pmid=args.pmid, url=args.url,
                              tags=args.tag or (), http=_http(args),
                              source="cli", author=DEFAULT_AUTHOR, force=args.force)
        paper = lib.get(result["id"])
    if args.json:
        _print_json(result)
        return 0 if result["status"] == "ok" else 1
    print(f"{'alta' if result['created'] else 'ya estaba'}: [{result['id']}] "
          f"{paper.get('title') if paper else ''}")
    if result["status"] == "ok":
        pdf = result.get("pdf") or {}
        print(f"  PDF real: {pdf.get('bytes', 0) / 1e6:.2f} MB · "
              f"{pdf.get('pages', 0)} pág. · sha256 {str(pdf.get('sha256', ''))[:16]}… · "
              f"fuente {pdf.get('source', '')}")
        print(f"  texto: {pdf.get('text_chars', 0)} caracteres indexados")
    else:
        print(f"  SIN PDF: {result['motivo']}")
    if result.get("resolution", {}).get("notes") and not args.quiet:
        for note in result["resolution"]["notes"][:5]:
            print(f"  nota: {note}")
    return 0 if result["status"] == "ok" else 1


def cmd_import_watch(args) -> int:
    path = Path(args.novedades)
    if not path.is_file():
        print(f"error: no existe {path}", file=sys.stderr)
        return 2
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"error: JSON inválido en {path}: {exc}", file=sys.stderr)
        return 2
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        print("error: el digest no tiene `items`", file=sys.stderr)
        return 2
    with _open(args) as lib:
        result = fetch.import_items(lib, items, limit=args.limit, tags=args.tag or (),
                                    tag_from_query=args.tag_from_query,
                                    http=_http(args), force=args.force)
    if args.json:
        _print_json(result)
        return 0
    print(f"importados {result['total']} · con PDF {result['ok']} · "
          f"sin PDF {result['sin_pdf']}")
    for item in result["items"]:
        mark = _color("ok ", "32") if item["status"] == "ok" else _color("—  ", "33")
        detail = ""
        if item["status"] == "ok" and item.get("pdf"):
            detail = (f"{item['pdf']['bytes'] / 1e6:.2f} MB, "
                      f"{item['pdf']['pages']} pág, "
                      f"sha {item['pdf']['sha256'][:12]}")
        else:
            detail = item.get("motivo", "")[:240]
        print(f"  {mark} [{item['id']}] {item.get('title', '')[:80]}\n       {detail}")
    return 0


def cmd_search(args) -> int:
    with _open(args) as lib:
        out = search_mod.search(lib, args.query, tags=args.tag, year=args.year,
                                status=args.status, limit=args.limit)
    if args.json:
        _print_json(out)
        return 0
    print(f"{out['count']} resultado(s) para {out['query']!r} "
          f"(match: {out['match'] or '—'}"
          + (f"; tags: {', '.join(out['filters']['tags'])}" if out['filters']['tags'] else "")
          + ")")
    for row in out["results"]:
        tags = ", ".join(row.get("tags") or [])
        print(f"\n[{row['id']}] {row.get('year') or '????'} · {row.get('title') or ''}")
        meta = " · ".join(x for x in [row.get("authors", "")[:80], row.get("journal"),
                                      row.get("doi")] if x)
        if meta:
            print(f"    {meta}")
        if tags:
            print(f"    tags: {tags}")
        if row.get("status") != "ok":
            print(f"    {_color('SIN PDF', '33')}: {row.get('motivo', '')[:100]}")
        elif row.get("snippet"):
            print("    …" + search_mod.highlight(row["snippet"]) + "…")
    if out["count"] > len(out["results"]):
        print(f"\n(mostrando {len(out['results'])} de {out['count']})")
    return 0


def cmd_show(args) -> int:
    with _open(args) as lib:
        paper = lib.get(args.ref)
        if not paper:
            print(f"error: no existe el paper {args.ref}", file=sys.stderr)
            return 1
        annotations = lib.annotations(paper["id"])
    if args.json:
        _print_json({**paper, "annotations": annotations})
        return 0
    print(_bold(paper.get("title") or "(sin título)"))
    for key in ("authors", "journal", "year", "doi", "pmid", "pmcid"):
        if paper.get(key):
            print(f"{key:>8}: {paper[key]}")
    print(f"{'estado':>8}: {paper['status']}"
          + (f" — {paper['motivo']}" if paper.get("motivo") else ""))
    if paper.get("status") == "ok":
        print(f"{'pdf':>8}: {paper['pdf_path']} "
              f"({paper['pdf_bytes'] / 1e6:.2f} MB, {paper['pages']} pág., "
              f"sha256 {paper['pdf_sha256'][:16]}…)")
        print(f"{'texto':>8}: {paper['text_chars']} caracteres indexados")
    print(f"{'tags':>8}: {', '.join(paper.get('tags') or []) or '—'}")
    if paper.get("abstract"):
        print("\nAbstract:\n" + paper["abstract"][:1500])
    print("\nQué se puede extraer:")
    if annotations:
        for ann in annotations:
            print(f"  - [{ann['kind']}] {ann['text']}  "
                  f"({ann.get('author') or 's/a'}, {ann['created_at'][:10]})")
    else:
        print("  (sin anotaciones)")
    if args.text:
        if paper.get("body"):
            print("\n--- texto del PDF ---\n")
            text = paper["body"]
            print(text if args.full else text[:args.chars])
        else:
            print("\n(no hay texto indexado: el paper no tiene PDF)", file=sys.stderr)
    return 0


def cmd_tag(args) -> int:
    if not args.changes:
        print("error: indicá al menos una etiqueta (+nueva o -vieja)", file=sys.stderr)
        return 2
    with _open(args) as lib:
        paper = lib.get(args.ref)
        if not paper:
            print(f"error: no existe el paper {args.ref}", file=sys.stderr)
            return 1
        for change in args.changes:
            if change.startswith("+"):
                added = lib.add_tag(paper["id"], change[1:])
                print(f"{'+ ' if added else '= '}{change[1:].lower()}")
            elif change.startswith("-"):
                removed = lib.remove_tag(paper["id"], change[1:])
                suffix = "" if removed else " (no estaba)"
                print(f"{'- ' if removed else '= '}{change[1:].lower()}{suffix}")
            else:
                lib.add_tag(paper["id"], change)
                print(f"+ {change.lower()}")
        print("tags: " + (", ".join(lib.tags(paper["id"])) or "—"))
    return 0


def cmd_note(args) -> int:
    with _open(args) as lib:
        paper = lib.get(args.ref)
        if not paper:
            print(f"error: no existe el paper {args.ref}", file=sys.stderr)
            return 1
        try:
            ann = lib.add_annotation(paper["id"], args.kind, args.text,
                                     author=args.author or DEFAULT_AUTHOR)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if args.json:
        _print_json(ann)
        return 0
    print(f"anotación #{ann['id']} [{ann['kind']}] en [{paper['id']}]: {ann['text']}")
    return 0


def cmd_stats(args) -> int:
    with _open(args) as lib:
        stats = lib.stats()
    if args.json:
        _print_json(stats)
        return 0
    print(f"papers: {stats['papers']} · con PDF: {stats['with_pdf']} · "
          f"sin PDF: {stats['without_pdf']}")
    print(f"PDFs: {stats['pdf_bytes'] / 1e6:.1f} MB · {stats['pages']} páginas · "
          f"{stats['text_chars']} caracteres indexados")
    if stats["by_status"]:
        print("estados: " + ", ".join(f"{k}={v}" for k, v in stats["by_status"].items()))
    if stats["tags"]:
        print("tags: " + ", ".join(f"{t['tag']}({t['n']})" for t in stats["tags"]))
    if stats["annotations"]:
        print("anotaciones: " + ", ".join(f"{a['kind']}={a['n']}" for a in stats["annotations"]))
    if stats["years"]:
        print("años: " + ", ".join(f"{y['year']}({y['n']})" for y in stats["years"]))
    print(f"base: {stats['db_path']}")
    return 0


def cmd_export(args) -> int:
    with _open(args) as lib:
        result = lib.export(args.out, tag=args.tag)
    if args.json:
        _print_json(result)
        return 0
    print(f"exportados {result['count']} paper(s) a {result['out']}")
    print(f"  index.json · notas.md · pdfs/")
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m library.cli",
        description="Biblioteca de papers con PDF real, búsqueda full-text y anotaciones "
                    "(edición developer).")
    parser.add_argument("--version", action="version", version=f"library {__version__}")
    parser.add_argument("--db", help="ruta a library.db (default: <data-dir>/library.db)")
    parser.add_argument("--data-dir", default=store.DEFAULT_DATA_DIR,
                        help=f"directorio de datos (default: {store.DEFAULT_DATA_DIR})")
    parser.add_argument("--cache-dir", default=fetch.DEFAULT_CACHE_DIR,
                        help="caché de respuestas de resolución")
    parser.add_argument("--offline", action="store_true",
                        help="no hacer requests: usar sólo la caché")
    parser.add_argument("--json", action="store_true", help="salida JSON")
    parser.add_argument("-q", "--quiet", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="baja un paper por DOI/PMID/URL")
    p.add_argument("--doi")
    p.add_argument("--pmid")
    p.add_argument("--url")
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--force", action="store_true", help="rebajar el PDF aunque ya esté")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("import-watch", help="importa un digest del vigilante (M7)")
    p.add_argument("novedades")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--tag-from-query", action="store_true",
                   help="usar el `query_id` del digest como etiqueta")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_import_watch)

    p = sub.add_parser("search", help="búsqueda full-text")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--year", type=int)
    p.add_argument("--status", choices=list(store.STATUSES))
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("show", help="detalle de un paper (id/DOI/PMID)")
    p.add_argument("ref")
    p.add_argument("--text", action="store_true", help="incluir texto extraído")
    p.add_argument("--full", action="store_true", help="texto completo (con --text)")
    p.add_argument("--chars", type=int, default=4000)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("tag", help="agregar/quitar etiquetas")
    p.add_argument("ref")
    p.add_argument("changes", nargs="*", help="+nueva -vieja")
    p.set_defaults(func=cmd_tag)

    p = sub.add_parser("note", help="anotar qué se puede extraer del paper")
    p.add_argument("ref")
    p.add_argument("--kind", default="nota",
                   help=f"tipo de nota: {', '.join(store.ANNOTATION_KINDS)}")
    p.add_argument("--author", default="")
    p.add_argument("text")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("stats", help="resumen de la biblioteca")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("export", help="exportar PDFs + índice + notas")
    p.add_argument("--tag")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_export)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    # `tag 3 +test -entrega`: los `-etiqueta` parecen opciones, así que se recogen aparte
    args, extras = parser.parse_known_args(argv)
    if getattr(args, "command", "") == "tag":
        args.changes = list(args.changes or []) + list(extras)
        extras = []
    if extras:
        parser.error(f"argumentos desconocidos: {' '.join(extras)}")
    if not edition.is_dev():
        print(f"error: {edition.MESSAGE}", file=sys.stderr)
        return 2
    try:
        return int(args.func(args) or 0)
    except edition.EditionError as exc:  # defensivo
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except fetch.FetchError as exc:
        print(f"error de red: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrumpido", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
