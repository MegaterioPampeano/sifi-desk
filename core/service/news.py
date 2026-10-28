"""Novedades para la ventana: `core/watch` envuelto con caché y sin 500.

La UI pregunta `GET /news?since=7d`; si no hay red tiene que poder mostrar
"sin novedades ahora" con un aviso, nunca una pantalla de error. Por eso este
módulo siempre devuelve un digest (aunque sea vacío) y acumula `warnings`.

El digest se cachea en `<data-dir>/news/` por `since` y modo (online/offline).
El inventario de `watch` **no se actualiza**: la ventana sólo mira, no consume.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from .queue import utcnow

CACHE_TTL_S = float(os.environ.get("SIFID_NEWS_TTL", "900"))
WATCH_TIMEOUT_S = float(os.environ.get("SIFID_NEWS_TIMEOUT", "10"))
CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIGEST_SCHEMA = "sifi.watch.digest/1"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name))[:60] or "default"


def empty_digest(since: str, offline: bool, warning: Optional[str] = None) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "schema": DIGEST_SCHEMA,
        "generated_at": utcnow(),
        "since": None,
        "since_arg": since,
        "until": None,
        "offline": bool(offline),
        "queries": [],
        "counts": {"fetched": 0, "in_window": 0, "dropped_old": 0, "new": 0,
                   "inventory_entries": 0},
        "items": [],
        "warnings": [],
        "service": {"ok": True, "cached": False},
    }
    if warning:
        d["warnings"].append(warning)
    return d


def _watch(since: str, offline: bool, config: Optional[str],
           cache_dir: Optional[str], inventory: Optional[str]) -> Dict[str, Any]:
    """Corre `watch` en un subproceso con techo de tiempo.

    En proceso (import) una fuente colgada bloquearía un thread del servicio;
    con subprocess + timeout la UI siempre recibe respuesta y se cae a la caché.
    """
    cmd = [sys.executable, "-m", "watch.cli", "run", "--since", str(since),
           "--json-only", "--no-update-inventory"]
    if offline:
        cmd.append("--offline")
    if config:
        cmd += ["--config", config]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    if inventory:
        cmd += ["--inventory", inventory]
    env = dict(os.environ)
    env["PYTHONPATH"] = CORE_DIR + (os.pathsep + env["PYTHONPATH"]
                                    if env.get("PYTHONPATH") else "")
    proc = subprocess.run(cmd, cwd=CORE_DIR, env=env, capture_output=True,
                          text=True, timeout=WATCH_TIMEOUT_S)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(msg[-1] if msg else f"watch salió {proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError(f"watch no devolvió JSON: {exc}") from exc


def _cache_path(root: str, since: str, offline: bool) -> str:
    mode = "offline" if offline else "online"
    return os.path.join(root, f"digest-{_safe(since)}-{mode}.json")


def _read_cache(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def get_news(data_dir: str,
             since: str = "7d",
             offline: bool = False,
             refresh: bool = False,
             config: Optional[str] = None,
             cache_dir: Optional[str] = None,
             inventory: Optional[str] = None,
             ttl_s: float = CACHE_TTL_S) -> Dict[str, Any]:
    """Devuelve un digest de novedades. Nunca levanta excepción por red."""
    root = os.path.join(data_dir, "news")
    os.makedirs(root, exist_ok=True)
    path = _cache_path(root, since, offline)
    cached = _read_cache(path)

    def with_meta(digest: Dict[str, Any], is_cached: bool) -> Dict[str, Any]:
        out = dict(digest)
        out["service"] = {"ok": True, "cached": bool(is_cached), "cache_path": path}
        return out

    if cached and not refresh:
        age = time.time() - float(cached.get("_cached_at") or 0)
        if age < ttl_s:
            return with_meta(cached, True)

    try:
        digest = _watch(since, offline, config, cache_dir, inventory)
    except Exception as exc:  # red, timeout, YAML, permisos: aviso, no 500
        if cached:
            stale = dict(cached)
            stale["service"] = {"ok": True, "cached": True, "stale": True,
                                "cache_path": path, "error": str(exc)}
            stale.setdefault("warnings", []).append(
                f"sin red o watch falló ({exc}); muestro el digest en caché")
            return stale
        if not offline:
            # segundo intento: sólo caché local de las fuentes (cero red)
            try:
                digest = _watch(since, True, config, cache_dir, inventory)
                digest.setdefault("warnings", []).append(
                    f"sin red ({exc}); se usó la caché local de las fuentes")
            except Exception as exc2:
                return empty_digest(since, offline,
                                    f"sin novedades ahora: falló la consulta ({exc2})")
        else:
            return empty_digest(since, offline,
                                f"sin novedades ahora: falló la consulta ({exc})")

    digest["_cached_at"] = time.time()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(digest, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass  # el digest igual se devuelve; no poder cachear no es fatal
    return with_meta(digest, False)
