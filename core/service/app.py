"""sifid — API local de siFi-Desk.

    python3 -m service.app --port 8765 --data-dir /tmp/sifid

Endpoints (v1):
    GET  /health                     estado del servicio, cola y worker
    GET  /panels                     paneles ingerados (registro bowtie)
    POST /runs                       encola una corrida -> 201 {run}
    GET  /runs                       lista corridas (?status=&limit=&offset=)
    GET  /runs/{id}                  detalle (estado, progreso, timestamps, error)
    POST /runs/{id}/cancel           cancela (encolada: inmediato; corriendo: mata el grupo)
    GET  /runs/{id}/results          manifest `sifi.results/1` de la corrida terminada

La cola es SQLite (WAL) y hay **un** worker: el pipeline corre en un subproceso
(`python3 -m service.runner`), nunca dentro del proceso web.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import SERVICE_NAME, __version__
from . import sandbox  # noqa: E402  (carpeta del agente para /agent/estado)
from .models import CancelResponse, RunRequest
from .queue import STATUSES, Store, new_run_id, utcnow
from .worker import CORE_DIR, Worker, recover_interrupted

if CORE_DIR not in sys.path:  # el paquete `sifi` vive al lado de `service`
    sys.path.insert(0, CORE_DIR)

_REPORT_LOCKS: dict = {}
_REPORT_LOCKS_GUARD = threading.Lock()


def _report_lock(path: str):
    """Lock por archivo de informe (varios pedidos simultáneos, una sola generación)."""
    with _REPORT_LOCKS_GUARD:
        return _REPORT_LOCKS.setdefault(path, threading.Lock())


DEFAULT_DATA_DIR = os.environ.get("SIFID_DATA_DIR", os.path.expanduser("~/.sifidesk/sifid"))
DEFAULT_PANELS_ROOT = os.environ.get("SIFI_PANELS_ROOT",
                                     os.path.expanduser("~/.sifidesk/panels"))


# --------------------------------------------------------------------------- #
# validación / armado del spec
# --------------------------------------------------------------------------- #
def _count_records(path: str) -> int:
    n = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith(">"):
                n += 1
    return n


def _first_record_id(path: str) -> Optional[str]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith(">"):
                return line[1:].strip().split()[0] if line[1:].strip() else None
    return None


def _build_params(req: RunRequest):
    from sifi.params import SifiParams

    kw = {
        "mode": req.mode,
        "sirna_size": req.sirna_size,
        "mismatches": req.mismatches,
        "no_efficience": req.no_efficience,
    }
    if req.accessibility_window is not None:
        kw["accessibility_window"] = req.accessibility_window
    for name in ("strand_check", "end_check", "accessibility_check", "terminal_check"):
        value = getattr(req, name)
        if value is not None:
            kw[name] = value
    if req.mode == "offtarget":
        # mismos defaults que la CLI (`sifi offtarget`): sólo hebra + terminales
        kw.setdefault("end_check", False)
        kw.setdefault("accessibility_check", False)
    try:
        return SifiParams(**kw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"parámetros inválidos: {exc}") from exc


def _resolve_panel(spec, panels_root: str) -> dict:
    """Un panel del registro -> {panel, db_dir, db_name} listo para bowtie."""
    from sifi.panels import PanelError, PanelsRegistry

    if not os.path.exists(spec.index_path + ".1.ebwt"):
        raise HTTPException(status_code=400,
                            detail=f"el panel {spec.id} {spec.version} no tiene índice bowtie"
                                   f" completo ({spec.path})")
    return {"panel": spec.id, "db_dir": spec.path, "db_name": spec.index_prefix,
            "version": spec.version, "role": spec.rol, "n_seqs": spec.n_seqs,
            "fingerprint": spec.fingerprint}


def _resolve_db(req: RunRequest, panels_root: str) -> tuple[dict, List[dict], str, str,
                                                           Optional[List[dict]]]:
    """Devuelve (public_db, paneles, db_dir, db_name, panels_para_bowtie)."""
    from sifi.panels import PanelError, PanelsRegistry

    if req.panel_ids:
        if req.panel_id or req.db_dir or req.db_name:
            raise HTTPException(status_code=400,
                                detail="usá panel_ids O panel_id O db_dir+db_name, no varios")
        if len(set(req.panel_ids)) != len(req.panel_ids):
            raise HTTPException(status_code=400, detail="panel_ids tiene repetidos")
        reg = PanelsRegistry(root=panels_root)
        targets: List[dict] = []
        public_panels: List[dict] = []
        for pid in req.panel_ids:
            try:
                spec = reg.get(pid, req.panel_version)
            except PanelError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            targets.append(_resolve_panel(spec, panels_root))
            public_panels.append({"id": spec.id, "version": spec.version, "n_seqs": spec.n_seqs,
                                  "fingerprint": spec.fingerprint, "role": spec.rol})
        first = targets[0]
        public = {"dir": first["db_dir"], "name": first["db_name"], "panel_id": first["panel"],
                  "panel_version": first.get("version"), "fingerprint": first.get("fingerprint"),
                  "multi": True}
        return public, public_panels, first["db_dir"], first["db_name"], targets

    if req.panel_id:
        if req.db_dir or req.db_name:
            raise HTTPException(status_code=400,
                                detail="usá panel_id O db_dir+db_name, no los dos")
        try:
            spec = PanelsRegistry(root=panels_root).get(req.panel_id, req.panel_version)
        except PanelError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not os.path.exists(spec.index_path + ".1.ebwt"):
            raise HTTPException(status_code=400,
                                detail=f"el panel {spec.id} {spec.version} no tiene índice bowtie"
                                       f" completo ({spec.path})")
        public = {"dir": spec.path, "name": spec.index_prefix,
                  "panel_id": spec.id, "panel_version": spec.version,
                  "fingerprint": spec.fingerprint}
        panels = [{"id": spec.id, "version": spec.version, "n_seqs": spec.n_seqs,
                   "fingerprint": spec.fingerprint, "role": spec.rol}]
        return public, panels, spec.path, spec.index_prefix, None

    if not req.db_dir or not req.db_name:
        raise HTTPException(status_code=400,
                            detail="falta la base: pasá panel_id o db_dir + db_name")
    db_dir = os.path.abspath(req.db_dir)
    if not os.path.isdir(db_dir):
        raise HTTPException(status_code=400, detail=f"no existe db_dir: {db_dir}")
    prefix = os.path.join(db_dir, req.db_name)
    if not os.path.exists(prefix + ".1.ebwt"):
        raise HTTPException(status_code=400,
                            detail=f"no hay índice bowtie en {prefix}.1.ebwt "
                                   f"(¿--db-name correcto?)")
    public = {"dir": db_dir, "name": req.db_name, "panel_id": None,
              "panel_version": None, "fingerprint": None}
    return public, [], db_dir, req.db_name, None


def _resolve_tools(req: RunRequest):
    from sifi.tools import discover

    try:
        return discover(req.bowtie, req.rnaplfold)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# app
# --------------------------------------------------------------------------- #
DEFAULT_UI_DIR = os.path.join(os.path.dirname(CORE_DIR), "ui")


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def create_app(data_dir: Optional[str] = None,
               panels_root: Optional[str] = None,
               runner_argv: Optional[List[str]] = None,
               start_worker: bool = True,
               token: Optional[str] = None,
               require_auth: bool = False,
               ui_dir: Optional[str] = None,
               news_config: Optional[str] = None,
               news_cache_dir: Optional[str] = None,
               news_inventory: Optional[str] = None) -> FastAPI:
    data_dir = os.path.abspath(data_dir or DEFAULT_DATA_DIR)
    panels_root = os.path.abspath(panels_root or DEFAULT_PANELS_ROOT)
    runs_dir = os.path.join(data_dir, "runs")
    os.makedirs(runs_dir, exist_ok=True)

    store = Store(os.path.join(data_dir, "sifid.sqlite3"))
    worker = Worker(store, data_dir, runner_argv=runner_argv)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        recover_interrupted(store)   # runners huérfanos de una vida anterior
        if start_worker:
            worker.start()
        try:
            yield
        finally:
            if start_worker:
                worker.stop()
            store.close()

    app = FastAPI(title="sifid", version=__version__,
                  description="Servicio local de siFi-Desk (cola de corridas)",
                  lifespan=lifespan)
    app.state.token = token
    app.state.require_auth = bool(require_auth and token)

    # La UI puede servirse desde otro origen en desarrollo (`?api=`), así que
    # el servicio acepta CORS local. El token sigue siendo obligatorio.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    # Biblioteca de papers (edición developer): el router ya se autoprotege y
    # responde 403 legible en la edición stable, así que se monta siempre.
    try:
        from library import api as library_api
    except ImportError:  # bundle sin el módulo: la app sigue andando
        library_api = None
    if library_api is not None:
        app.include_router(library_api.router)

    def _ui_public(path: str) -> bool:
        if not (ui_dir and os.path.isdir(ui_dir)):
            return False
        return path in ("/", "/index.html", "/favicon.ico") or path.startswith("/assets/")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if app.state.require_auth:
            path = request.url.path
            if request.method != "OPTIONS" and path != "/health" and not _ui_public(path):
                got = request.headers.get("x-sifi-token") or ""
                if not secrets.compare_digest(got, app.state.token or ""):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "falta o no coincide el header x-sifi-token"},
                    )
        return await call_next(request)

    app.state.store = store
    app.state.worker = worker
    app.state.data_dir = data_dir
    app.state.panels_root = panels_root
    app.state.runs_dir = runs_dir
    app.state.start_worker = start_worker
    app.state.news_config = news_config
    app.state.news_cache_dir = news_cache_dir
    app.state.news_inventory = news_inventory
    app.state.ui_dir = ui_dir

    # ---------------------------------------------------------------- salud
    @app.get("/health")
    def health() -> dict:
        counts = store.counts()
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": __version__,
            "data_dir": data_dir,
            "panels_root": panels_root,
            "worker": {"enabled": start_worker, "alive": worker.alive,
                       "current_run": worker.current},
            "queue": counts,
        }

    # --------------------------------------------------------------- paneles
    @app.get("/panels")
    def panels() -> dict:
        from sifi.panels import PanelsRegistry

        out = []
        for spec in PanelsRegistry(root=panels_root).list():
            out.append({
                "id": spec.id, "version": spec.version, "nombre": spec.nombre,
                "rol": spec.rol, "n_seqs": spec.n_seqs, "fingerprint": spec.fingerprint,
                "path": spec.path,
                "index_ok": os.path.exists(spec.index_path + ".1.ebwt"),
            })
        return {"panels_root": panels_root, "count": len(out), "panels": out}

    @app.patch("/panels/{pid}")
    def panel_rol(pid: str, body: dict) -> dict:
        """Cambia el rol de un panel (blanco / no_blanco / patogeno / simbionte...).

        El rol es lo que decide cómo pesa un hit: contra el blanco es el objetivo,
        contra un no_blanco es riesgo. Se escribe en el meta.yaml de la versión vigente.
        """
        from sifi.panels import PanelsRegistry, ROLES
        import yaml as _yaml

        rol = (body or {}).get("rol")
        if rol not in ROLES:
            raise HTTPException(status_code=400,
                                detail=f"rol inválido: {rol!r} (usar {', '.join(ROLES)})")
        for spec in PanelsRegistry(root=panels_root).list():
            if spec.id != pid:
                continue
            meta_path = os.path.join(spec.path, "meta.yaml")
            if not os.path.isfile(meta_path):
                raise HTTPException(status_code=409,
                                    detail=f"el panel {pid} no tiene meta.yaml editable")
            with open(meta_path, encoding="utf-8") as fh:
                meta = _yaml.safe_load(fh) or {}
            anterior = meta.get("rol")
            meta["rol"] = rol
            tmp = meta_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                _yaml.safe_dump(meta, fh, allow_unicode=True, sort_keys=True)
            os.replace(tmp, meta_path)
            return {"id": pid, "rol": rol, "anterior": anterior, "version": spec.version}
        raise HTTPException(status_code=404, detail=f"no existe el panel {pid}")

    # ----------------------------------------------------------------- runs
    @app.post("/runs", status_code=201)
    def create_run(req: RunRequest) -> dict:
        if bool(req.query_path) == bool(req.query_fasta):
            raise HTTPException(status_code=400,
                                detail="pasá exactamente uno: query_path o query_fasta")

        params = _build_params(req)
        tools = _resolve_tools(req)
        db_public, panel_list, db_dir, db_name, panel_targets = _resolve_db(req, panels_root)

        if req.main_target_mode == "explicit" and not req.main_targets:
            raise HTTPException(status_code=400,
                                detail="main_target_mode='explicit' requiere main_targets")

        run_id = new_run_id()
        run_dir = os.path.join(runs_dir, run_id)
        os.makedirs(run_dir, exist_ok=False)
        query_file = os.path.join(run_dir, "input.fa")
        try:
            if req.query_fasta is not None:
                with open(query_file, "w", encoding="utf-8") as fh:
                    fh.write(req.query_fasta if req.query_fasta.endswith("\n")
                             else req.query_fasta + "\n")
                origin = {"kind": "inline"}
            else:
                src = os.path.abspath(req.query_path or "")
                if not os.path.isfile(src):
                    raise HTTPException(status_code=400, detail=f"no existe query_path: {src}")
                with open(src, "rb") as fi, open(query_file, "wb") as fo:
                    fo.write(fi.read())
                origin = {"kind": "path", "path": src}

            records_total = _count_records(query_file)
            if records_total == 0:
                raise HTTPException(status_code=400,
                                    detail="el FASTA de entrada no tiene registros")
            query_name = _first_record_id(query_file)

            out_dir = os.path.join(run_dir, "out")
            spec = {
                "run_id": run_id,
                "core_path": CORE_DIR,
                "query_path": query_file,
                "db_dir": db_dir,
                "db_name": db_name,
                "out_dir": out_dir,
                "params": params.as_dict(),
                "tools": tools.as_dict(),
                "main_targets": req.main_targets,
                "main_target_mode": req.main_target_mode,
                "panels": panel_targets,
                "panel_roles": {p["id"]: p["role"] for p in panel_list if p.get("role")},
                "records_total": records_total,
                "extra_meta": {
                    "service": {"name": SERVICE_NAME, "version": __version__,
                                "run_id": run_id, "requested_at": utcnow()},
                    **(req.extra_meta or {}),
                },
                "public": {
                    "mode": req.mode,
                    "query": {"name": query_name, "records": records_total,
                              "origin": origin},
                    "database": db_public,
                    "panels": panel_list,
                    "params": params.as_dict(),
                    "main_target_mode": req.main_target_mode,
                    "main_targets": req.main_targets,
                },
            }
            return store.create(spec, records_total, run_id=run_id)
        except Exception:
            # una corrida que no llegó a encolarse no deja basura en disco
            if store.get(run_id) is None:
                import shutil
                shutil.rmtree(run_dir, ignore_errors=True)
            raise

    @app.get("/runs")
    def list_runs(status: Optional[str] = Query(None),
                  limit: int = Query(50, ge=1, le=500),
                  offset: int = Query(0, ge=0)) -> dict:
        if status is not None and status not in STATUSES:
            raise HTTPException(status_code=400,
                                detail=f"status inválido: {status!r} (usar {', '.join(STATUSES)})")
        runs = store.list(status=status, limit=limit, offset=offset)
        return {"count": len(runs), "runs": runs}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run = store.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"no existe la corrida {run_id!r}")
        return run

    @app.post("/runs/{run_id}/cancel", response_model=CancelResponse)
    def cancel_run(run_id: str) -> CancelResponse:
        result, run = store.request_cancel(run_id)
        if result == "missing":
            raise HTTPException(status_code=404, detail=f"no existe la corrida {run_id!r}")
        if result == "conflict":
            raise HTTPException(
                status_code=409,
                detail=f"la corrida {run_id!r} ya terminó ({run['status'] if run else '?'})")
        detail = ("cancelada antes de arrancar" if result == "cancelled"
                  else "cancelación pedida: el worker está matando el subproceso")
        assert run is not None
        return CancelResponse(run_id=run_id, status=run["status"],
                              cancel_requested=run["cancel_requested"], detail=detail)

    @app.get("/runs/{run_id}/results")
    def get_results(run_id: str) -> JSONResponse:
        raw = store.raw(run_id)
        if raw is None:
            raise HTTPException(status_code=404, detail=f"no existe la corrida {run_id!r}")
        if raw["status"] != "done":
            raise HTTPException(
                status_code=409,
                detail=f"la corrida {run_id!r} está en estado {raw['status']!r};"
                       " los resultados sólo están disponibles en 'done'")
        path = raw["result_path"]
        if not path or not os.path.isfile(path):
            raise HTTPException(status_code=500,
                                detail=f"el manifest de {run_id!r} se perdió ({path!r})")
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        return JSONResponse(content=manifest)

    # -------------------------------------------------------------- informe
    @app.get("/runs/{run_id}/report")
    def get_report(run_id: str, fmt: str = Query("pdf")):
        fmt = (fmt or "pdf").lower().lstrip(".")
        if fmt not in ("pdf", "html"):
            raise HTTPException(status_code=400,
                                detail=f"fmt inválido: {fmt!r} (usar pdf o html)")
        raw = store.raw(run_id)
        if raw is None:
            raise HTTPException(status_code=404, detail=f"no existe la corrida {run_id!r}")
        if raw["status"] != "done":
            raise HTTPException(
                status_code=409,
                detail=f"la corrida {run_id!r} está en estado {raw['status']!r};"
                       " el informe sólo se genera sobre corridas terminadas")
        manifest_path = raw["result_path"]
        if not manifest_path or not os.path.isfile(manifest_path):
            raise HTTPException(status_code=500,
                                detail=f"el manifest de {run_id!r} se perdió")
        report_dir = os.path.join(os.path.dirname(manifest_path), "report")
        out_path = os.path.join(report_dir, f"informe-{run_id}.{fmt}")
        try:
            # Un solo pedido genera; los demás esperan y sirven el archivo completo.
            with _report_lock(out_path):
                fresh = (os.path.isfile(out_path)
                         and os.path.getmtime(out_path) >= os.path.getmtime(manifest_path))
                if not fresh:
                    from report.render import render
                    out_path = render([manifest_path], out_dir=report_dir, fmt=fmt,
                                      filename=f"informe-{run_id}")
        except Exception as exc:
            raise HTTPException(status_code=500,
                                detail=f"no se pudo generar el informe {fmt}: {exc}") from exc
        if not os.path.isfile(out_path):
            raise HTTPException(status_code=500, detail="el informe no quedó en disco")
        media = "application/pdf" if fmt == "pdf" else "text/html; charset=utf-8"
        return FileResponse(out_path, media_type=media,
                            filename=os.path.basename(out_path))

    # --------------------------------------------------- resultados para UI
    @app.get("/runs/{run_id}/view")
    def get_view(run_id: str) -> JSONResponse:
        raw = store.raw(run_id)
        if raw is None:
            raise HTTPException(status_code=404, detail=f"no existe la corrida {run_id!r}")
        if raw["status"] != "done":
            raise HTTPException(
                status_code=409,
                detail=f"la corrida {run_id!r} está en estado {raw['status']!r};"
                       " los resultados sólo están disponibles en 'done'")
        path = raw["result_path"]
        if not path or not os.path.isfile(path):
            raise HTTPException(status_code=500,
                                detail=f"el manifest de {run_id!r} se perdió ({path!r})")
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        spec = store.spec(run_id) or {}
        run = {"run_id": run_id, "request": spec.get("public") or {}}
        from .view import ui_results
        payload = ui_results(manifest, run)
        payload["manifest_path"] = None  # no filtrar rutas del disco a la UI
        return JSONResponse(content=payload)

    # -------------------------------------------------------------- novedades
    @app.get("/news")
    def get_news(since: str = Query("7d"), offline: bool = Query(False),
                 refresh: bool = Query(False)) -> dict:
        from .news import get_news as _news
        try:
            return _news(data_dir, since=since, offline=offline, refresh=refresh,
                         config=news_config, cache_dir=news_cache_dir,
                         inventory=news_inventory)
        except Exception as exc:  # la UI nunca tiene que ver un 500 acá
            from .news import empty_digest
            return empty_digest(since, offline, f"sin novedades ahora: {exc}")

    # La UI se sirve desde disco y cambia con cada actualización: sin caché, para
    # que un F5 (o el reinicio de la ventana) traiga el JS nuevo de verdad.
    @app.middleware("http")
    async def _sin_cache_assets(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/assets/") or path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response

    # --------------------------------------------------------------- ajustes
    @app.get("/settings/llm")
    def get_llm_settings() -> dict:
        from . import settings as _settings
        return _settings.estado()

    @app.put("/settings/llm")
    def put_llm_settings(body: dict) -> dict:
        from . import settings as _settings
        try:
            return _settings.guardar(body.get("api_key") or "",
                                     body.get("modelo"), body.get("base_url"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.delete("/settings/llm")
    def delete_llm_settings() -> dict:
        from . import settings as _settings
        return _settings.borrar()

    @app.post("/settings/llm/test")
    def test_llm_settings() -> dict:
        from . import agent as _agent
        return _agent.probar()

    # ----------------------------------------------------------------- agente
    @app.get("/agent/sesiones")
    def agent_sesiones() -> dict:
        from . import charlas
        return {"sesiones": charlas.listar(data_dir)}

    @app.post("/agent/sesiones")
    def agent_sesion_nueva(body: dict | None = None) -> dict:
        from . import charlas
        return charlas.crear(data_dir, (body or {}).get("titulo"))

    @app.get("/agent/sesiones/{sid}")
    def agent_sesion(sid: str) -> dict:
        from . import charlas
        try:
            return charlas.obtener(data_dir, sid)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.patch("/agent/sesiones/{sid}")
    def agent_sesion_renombrar(sid: str, body: dict) -> dict:
        from . import charlas
        try:
            return charlas.renombrar(data_dir, sid, body.get("titulo") or "")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.delete("/agent/sesiones/{sid}")
    def agent_sesion_borrar(sid: str) -> dict:
        from . import charlas
        try:
            return charlas.borrar(data_dir, sid)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/agent/chat")
    def agent_chat(request: Request, body: dict) -> dict:
        from . import agent as _agent, charlas
        mensaje = body.get("mensaje") or body.get("message") or ""
        run_id = body.get("run_id")
        sesion = charlas.asegurar(data_dir, body.get("sesion_id"))
        sid = sesion["id"]
        historial = charlas.historial_para_llm(sesion) or body.get("historial")
        charlas.agregar(data_dir, sid, "user", mensaje, run_id=run_id)
        salida = _agent.chat(store, mensaje, run_id, historial,
                             base_url=str(request.base_url).rstrip("/"), token=token,
                             data_dir=data_dir, sesion_id=sid)
        charlas.agregar(data_dir, sid, "assistant", salida.get("respuesta") or "",
                        herramientas=salida.get("tools") or None, run_id=run_id)
        salida["sesion_id"] = sid
        # Compactación: si la charla creció por encima del umbral, se resumen los turnos
        # viejos con el mismo modelo y el resumen queda guardado en la sesión. Si falla,
        # no pasa nada: la charla sigue como estaba.
        from . import contexto as _ctx
        sesion_actual = charlas.obtener(data_dir, sid)
        if _ctx.necesita_compactar(sesion_actual):
            info = charlas.compactar(data_dir, sid, _agent.resumir)
            if info:
                salida["compactado"] = info
        salida["sesion"] = [s for s in charlas.listar(data_dir) if s["id"] == sid][:1]
        return salida

    @app.get("/agent/estado")
    def agent_estado(sesion_id: str = "") -> dict:
        from . import contexto, memoria, charlas
        from . import settings as _settings
        ses = charlas.obtener(data_dir, sesion_id) if sesion_id else None
        turnos = contexto.turnos_para_llm(ses) if ses else []
        return {
            "modelo": _settings.estado()["modelo"],
            "presupuesto_tokens": contexto.PRESUPUESTO_TOKENS,
            "tokens_sesion": contexto.tokens_de(turnos),
            "turnos": len([m for m in (ses or {}).get("mensajes", [])
                           if m.get("role") in ("user", "assistant")]),
            "resumen_chars": len((ses or {}).get("resumen") or ""),
            "compactado": (ses or {}).get("compactado"),
            "memoria": memoria.resumen_para_ui(),
            "carpeta": sandbox.RAIZ,
        }

    @app.post("/agent/sesiones/{sid}/compactar")
    def agent_compactar(sid: str, body: dict | None = None) -> dict:
        from . import charlas
        from . import agent as _agent
        vivos = int((body or {}).get("vivos") or 0)
        info = charlas.compactar(data_dir, sid, _agent.resumir, vivos=vivos)
        if not info:
            return {"ok": False, "detalle": "no había suficientes turnos para compactar"}
        return {"ok": True, **info}

    # ------------------------------------------------------- aprobaciones
    @app.get("/aprobaciones")
    def get_aprobaciones(estado: str = "pendiente") -> dict:
        from . import aprobaciones
        return {"items": aprobaciones.listar(data_dir, estado)}

    @app.post("/aprobaciones/{aid}")
    def post_aprobacion(aid: str, body: dict) -> dict:
        from . import aprobaciones
        aprobado = bool(body.get("aprobar"))
        try:
            item = aprobaciones.resolver(data_dir, aid, aprobado, body.get("nota") or "")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return item

    # ------------------------------------------------------------------- UI
    def _ui_index() -> Optional[HTMLResponse]:
        index = os.path.join(ui_dir, "index.html") if ui_dir else ""
        if not index or not os.path.isfile(index):
            return None
        with open(index, encoding="utf-8") as fh:
            return HTMLResponse(fh.read())

    @app.get("/")
    def root():
        page = _ui_index()
        if page is not None:
            return page
        return {"service": SERVICE_NAME, "version": __version__,
                "docs": "/docs", "health": "/health"}

    @app.get("/index.html")
    def index_html():
        page = _ui_index()
        if page is None:
            raise HTTPException(status_code=404, detail="la UI no está instalada")
        return page

    if ui_dir and os.path.isdir(ui_dir):
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")

    return app


# --------------------------------------------------------------------------- #
# arranque
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sifid",
                                 description="Servicio local de siFi-Desk (FastAPI)")
    ap.add_argument("--port", type=int, default=8765,
                    help="puerto local (0 = elegir uno libre; default: %(default)s)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                    help="cola SQLite + corridas (default: %(default)s)")
    ap.add_argument("--panels-root", default=DEFAULT_PANELS_ROOT,
                    help="registro de paneles (default: %(default)s)")
    ap.add_argument("--ui-dir", default=None,
                    help="carpeta de la ventana (default: ./ui si existe)")
    ap.add_argument("--token", default=None,
                    help="token fijo (default: efímero por proceso, o SIFID_TOKEN)")
    ap.add_argument("--no-auth", action="store_true",
                    help="DESACTIVA la autenticación: sólo para tests locales; "
                         "cualquier proceso de la máquina puede usar la API")
    ap.add_argument("--news-config", default=None, help="watch.yaml alternativo")
    ap.add_argument("--news-cache-dir", default=None, help="caché HTTP de watch")
    ap.add_argument("--news-inventory", default=None, help="inventario de novedades")
    ap.add_argument("--log-level", default="info")
    ap.add_argument("--no-worker", action="store_true",
                    help="no ejecutar corridas (sólo API; para depurar la cola)")
    args = ap.parse_args(argv)

    token = None if args.no_auth else (args.token or os.environ.get("SIFID_TOKEN")
                                       or secrets.token_urlsafe(24))
    port = args.port if args.port else _free_port(args.host)
    ui_dir = args.ui_dir
    if ui_dir is None and os.path.isdir(DEFAULT_UI_DIR):
        ui_dir = DEFAULT_UI_DIR

    import uvicorn

    app = create_app(data_dir=args.data_dir, panels_root=args.panels_root,
                     start_worker=not args.no_worker, token=token,
                     require_auth=not args.no_auth, ui_dir=ui_dir,
                     news_config=args.news_config,
                     news_cache_dir=args.news_cache_dir,
                     news_inventory=args.news_inventory)

    # Contrato D4: la ventana descubre URL y token por stdout, no por args fijos.
    print(f"SIFID_URL=http://{args.host}:{port}", flush=True)
    if token:
        print(f"SIFID_TOKEN={token}", flush=True)
    else:
        print("SIFID_AUTH=disabled (--no-auth: API sin token, sólo para tests)",
              flush=True)
    print(f"{SERVICE_NAME} {__version__}  (data-dir={os.path.abspath(args.data_dir)})",
          file=sys.stderr, flush=True)
    uvicorn.run(app, host=args.host, port=port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
