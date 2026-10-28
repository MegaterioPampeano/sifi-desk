"""CLI del vigilante de novedades.

    cd core
    python3 -m watch.cli run --since 7d --out novedades.json
    python3 -m watch.cli run --since 7d --offline --out novedades.json

Opciones útiles:

    --dry-run             no escribe el inventario (para probar sin "gastar" novedades)
    --no-update-inventory igual, pero explícito
    --config PATH         otro watch.yaml
    --inventory PATH      otro inventory.json
    --cache-dir DIR       otra caché HTTP
    --limit N             ítems por fuente y por query (pisa config)
    --json-only           imprime el digest JSON en stdout y no el texto
    --max-items N         cuántos ítems muestra el resumen de texto
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("falta PyYAML (pip install pyyaml)") from exc

from . import sources
from .digest import render_digest
from .store import Inventory, utcnow

DIGEST_SCHEMA = "sifi.watch.digest/1"
CONFIG_DEFAULT = Path(__file__).resolve().parent / "config" / "watch.yaml"
SCHEMA_CONFIG = "sifi.watch.config/1"


class ConfigError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #

def load_config(path: str | os.PathLike = CONFIG_DEFAULT) -> Dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"no existe la config: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"config inválida (no es un mapa): {path}")
    if raw.get("schema") not in (None, SCHEMA_CONFIG):
        raise ConfigError(f"config de otro schema: {raw.get('schema')}")

    cfg = dict(raw)
    cfg.setdefault("schema", SCHEMA_CONFIG)
    cfg.setdefault("window_days", 7)
    cfg.setdefault("contact", sources.DEFAULT_CONTACT)
    cfg.setdefault("cache", {})
    cfg.setdefault("inventory", {})
    cfg.setdefault("limits", {})
    cfg["limits"].setdefault("per_source", 25)
    cfg["limits"].setdefault("biorxiv_max_pages", 8)

    queries = cfg.get("queries") or []
    if not isinstance(queries, list) or not queries:
        raise ConfigError("la config no tiene `queries`")
    clean: List[Dict[str, Any]] = []
    seen_ids = set()
    for q in queries:
        if not isinstance(q, dict) or not q.get("text"):
            raise ConfigError(f"query inválida (falta `text`): {q!r}")
        qid = str(q.get("id") or q["text"])[:40]
        if qid in seen_ids:
            raise ConfigError(f"query id repetido: {qid}")
        seen_ids.add(qid)
        q = dict(q)
        q["id"] = qid
        q["sources"] = list(q.get("sources") or ["crossref", "pubmed"])
        unknown = [s for s in q["sources"] if s not in sources.SOURCES]
        if unknown:
            raise ConfigError(f"query {qid}: fuentes desconocidas {unknown}")
        q.setdefault("keywords", [])
        q.setdefault("why", "")
        clean.append(q)
    cfg["queries"] = clean
    return cfg


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "sifi-desk" / "watch"


# --------------------------------------------------------------------------- #
# fechas
# --------------------------------------------------------------------------- #

def parse_since(value: Optional[str], today: Optional[date] = None,
                window_days: int = 7) -> Tuple[date, str]:
    """`7d`, `2w`, `36h`, `2026-10-01` o vacío → fecha de corte."""
    today = today or sources.today_utc()
    if value in (None, "", "default"):
        value = f"{int(window_days)}d"
    text = str(value).strip().lower()
    if not text:
        text = f"{int(window_days)}d"
    if text.endswith("d") and text[:-1].isdigit():
        return today - timedelta(days=int(text[:-1])), text
    if text.endswith("w") and text[:-1].isdigit():
        return today - timedelta(weeks=int(text[:-1])), text
    if text.endswith("h") and text[:-1].isdigit():
        cut = datetime.combine(today, datetime.min.time()) - timedelta(hours=int(text[:-1]))
        return cut.date(), text
    try:
        parsed = date.fromisoformat(text)
        return parsed, text
    except ValueError:
        raise ConfigError(f"--since inválido: {value!r} (usá 7d, 2w, 36h o 2026-10-01)")


def _in_window(item: Dict[str, Any], since: date) -> bool:
    """Guarda final: aunque la API devuelva algo viejo, no entra al digest."""
    raw = (item.get("date") or "").strip()
    if not raw:
        return True  # sin fecha no podemos descartarlo; la fuente ya filtró
    cut = since.isoformat()
    if len(raw) >= 10:
        return raw[:10] >= cut
    if len(raw) == 7:
        return raw >= cut[:7]
    if len(raw) == 4:
        return raw >= cut[:4]
    return True


# --------------------------------------------------------------------------- #
# corrida
# --------------------------------------------------------------------------- #

def run(
    *,
    config: str | os.PathLike = CONFIG_DEFAULT,
    config_dict: Optional[Dict[str, Any]] = None,
    since: Optional[str] = "7d",
    until: Optional[str] = None,
    out: Optional[str | os.PathLike] = None,
    offline: bool = False,
    inventory: Optional[str | os.PathLike] = None,
    cache_dir: Optional[str | os.PathLike] = None,
    limit: Optional[int] = None,
    max_pages: Optional[int] = None,
    update_inventory: bool = True,
    client: Optional[sources.HttpClient] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Corre la vigilancia y devuelve el digest. No imprime (eso es del CLI)."""
    cfg = config_dict or load_config(config)
    today = today or sources.today_utc()
    until_date = date.fromisoformat(until) if until else today
    since_date, since_label = parse_since(since, today=today,
                                          window_days=int(cfg.get("window_days", 7)))
    if since_date > until_date:
        raise ConfigError(f"--since {since_date} es posterior a --until {until_date}")

    cache_root = Path(cache_dir) if cache_dir else (
        Path(cfg["cache"].get("dir")).expanduser() if cfg["cache"].get("dir") else default_cache_dir()
    )
    inv_path = Path(inventory) if inventory else (
        Path(cfg["inventory"].get("path")).expanduser() if cfg["inventory"].get("path")
        else cache_root / "inventory.json"
    )

    if client is None:
        cache = sources.DiskCache(cache_root, ttl_hours=float(cfg["cache"].get("ttl_hours", 24)))
        client = sources.HttpClient(
            cache=cache,
            offline=offline,
            timeout=float(cfg["cache"].get("timeout_s", 25)),
            retries=int(cfg["cache"].get("retries", 3)),
            backoff=float(cfg["cache"].get("backoff_s", 1.0)),
            contact=cfg.get("contact"),
        )

    per_source = int(limit or cfg["limits"].get("per_source", 25))
    pages = int(max_pages or cfg["limits"].get("biorxiv_max_pages", 8))

    fetched: List[Dict[str, Any]] = []
    warnings: List[str] = []
    per_query: List[Dict[str, Any]] = []
    for q in cfg["queries"]:
        if q.get("repo"):
            q = dict(q, repo=q["repo"])
        got, errors = sources.fetch_query(q, since_date, per_source, client,
                                          until=until_date, max_pages=pages)
        warnings.extend(errors)
        fetched.extend(got)
        per_query.append({"id": q["id"], "text": q["text"], "n_fetched": len(got),
                          "errors": errors})

    in_window = [it for it in fetched if _in_window(it, since_date)]
    dropped_old = len(fetched) - len(in_window)

    inv = Inventory.load(inv_path)
    new_items = inv.diff(in_window)
    new_items.sort(key=lambda it: (it.get("date") or "", it.get("title") or ""), reverse=True)
    for it in new_items:
        it["resumen"] = _short_summary(it)

    digest: Dict[str, Any] = {
        "schema": DIGEST_SCHEMA,
        "generated_at": utcnow(),
        "since": since_date.isoformat(),
        "since_arg": since_label,
        "until": until_date.isoformat(),
        "offline": bool(offline),
        "queries": per_query,
        "counts": {
            "fetched": len(fetched),
            "in_window": len(in_window),
            "dropped_old": dropped_old,
            "new": len(new_items),
            "inventory_entries": len(inv),
        },
        "items": new_items,
        "warnings": _unique(warnings + list(client.warnings)),
    }

    if out:
        out_path = Path(out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
        digest["out_path"] = str(out_path)

    if update_inventory and new_items:
        inv.mark(new_items)
        inv.save(inv_path)
        digest["inventory_path"] = str(inv_path)

    return digest


def _short_summary(item: Dict[str, Any]) -> str:
    """Una línea para el agente: título + por qué + doi."""
    bits = [item.get("title") or ""]
    if item.get("why"):
        bits.append("Relevante: " + item["why"])
    if item.get("doi"):
        bits.append("doi:" + item["doi"])
    return " — ".join(b for b in bits if b)


def _unique(items: List[str]) -> List[str]:
    out: List[str] = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m watch.cli",
                                description="Vigilante de novedades de siFi-Desk (M7)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="buscar novedades y escribir el digest")
    r.add_argument("--since", default="7d",
                   help="ventana: 7d, 2w, 36h o una fecha ISO (default: 7d)")
    r.add_argument("--until", default=None, help="fin de la ventana (default: hoy UTC)")
    r.add_argument("--out", default=None, help="path del JSON de salida")
    r.add_argument("--offline", action="store_true", help="sólo caché, cero red")
    r.add_argument("--config", default=str(CONFIG_DEFAULT))
    r.add_argument("--inventory", default=None)
    r.add_argument("--cache-dir", default=None)
    r.add_argument("--limit", type=int, default=None, help="ítems por fuente y query")
    r.add_argument("--max-pages", type=int, default=None, help="páginas de bioRxiv (100 c/u)")
    r.add_argument("--dry-run", action="store_true", help="no actualizar el inventario")
    r.add_argument("--no-update-inventory", action="store_true")
    r.add_argument("--json-only", action="store_true", help="imprimir el JSON en stdout")
    r.add_argument("--max-items", type=int, default=None, help="ítems en el resumen de texto")
    r.add_argument("--quiet", action="store_true", help="no imprimir nada (sólo --out)")

    s = sub.add_parser("sources", help="listar fuentes y queries configuradas")
    s.add_argument("--config", default=str(CONFIG_DEFAULT))
    return p


def cmd_sources(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    print("Fuentes:", ", ".join(sorted(sources.SOURCES)))
    print(f"Ventana por defecto: {cfg['window_days']} días")
    for q in cfg["queries"]:
        print(f"- {q['id']}: {q['text']}")
        print(f"    fuentes: {', '.join(q['sources'])} · por qué: {q['why'] or '(sin why)'}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "sources":
            return cmd_sources(args)
        digest = run(
            config=args.config,
            since=args.since,
            until=args.until,
            out=args.out,
            offline=args.offline,
            inventory=args.inventory,
            cache_dir=args.cache_dir,
            limit=args.limit,
            max_pages=args.max_pages,
            update_inventory=not (args.dry_run or args.no_update_inventory),
        )
    except ConfigError as exc:
        print(f"error de configuración: {exc}", file=sys.stderr)
        return 2

    if args.json_only:
        print(json.dumps(digest, ensure_ascii=False, indent=1))
    elif not args.quiet:
        print(render_digest(digest, max_items=args.max_items))
        if args.out:
            print(f"\nJSON: {digest.get('out_path')}")

    counts = digest["counts"]
    if counts["fetched"] == 0 and digest["warnings"]:
        return 1  # todas las fuentes fallaron: que el cron lo note
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
