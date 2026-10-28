"""Agente del panel lateral: conversación con herramientas reales.

Tres capas, en este orden:

1. **Contexto**: lo que el servicio ya calculó (candidatos, score, off-target por panel)
   entra en el prompt. El agente no recalcula ni inventa cifras.
2. **Herramientas**: puede ejecutar comandos en *su* carpeta, correr Python, bajar
   archivos, leer/escribir ahí, usar el CLI de siFi y lanzar corridas del servicio.
   Todo pasa por `service.sandbox`, que le prohíbe tocar el programa instalado o el
   sistema y le recorta tiempo y salida.
3. **Transparencia**: cada herramienta usada vuelve a la UI como tarjeta con el comando
   exacto y su salida, así se ve qué hizo y con qué.

Sin clave configurada no hay agente: se devuelve `configurar: true` y la UI ofrece
abrir Ajustes.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from . import sandbox, settings

MAX_CANDIDATOS = 15
MAX_RONDAS = 6
MAX_HISTORIAL = 8

CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYSTEM = """Sos el agente de siFi Desk, una aplicación de escritorio para diseñar dsRNA
contra plagas (Dalbulus maidis, la chicharrita del maíz, y otras). Hablás en español
rioplatense, breve y concreto, sin adulación ni vueltas.

Qué podés hacer (usá las herramientas, no digas que no podés):
- `ejecutar`: comandos de shell en tu carpeta de trabajo (~/.sifidesk/agente). Ahí podés
  instalar cosas de usuario con pip --user, descomprimir, procesar FASTA con lo que haya.
- `python`: scripts sueltos para analizar secuencias o archivos.
- `descargar`: bajar un archivo por HTTP(S) (genomas, transcriptomas, papers, bases).
- `leer` / `escribir`: archivos dentro de tu carpeta.
- `sifi`: el CLI de la app (paneles, diseño, off-target, doctor).
- `listar_paneles`, `correr_corrida`, `estado_corrida`: la biblioteca y las corridas del
  servicio, para lo mismo que hace la interfaz.
- `listar_archivos`: qué tenés en tu carpeta.

Qué NO podés: modificar el programa instalado (el bundle, el repo, el código de la app),
usar sudo, tocar el sistema, servicios o cuentas. Si un cambio de código hace falta, lo
pedís: lo revisa y lo aplica Mariano. Tampoco inventes resultados: si algo no está en el
contexto ni lo obtuviste con una herramienta, decí que no lo sabés y qué habría que correr.

Reglas de trabajo:
- Para tareas largas (descargar un genoma, indexar un panel) hacelo en pasos y contá qué
  estás haciendo; los comandos quedan visibles en la interfaz.
- El score va de 0 a 100 (más alto, mejor); E, R, S, T y D son sus componentes. Un
  off-target contra el panel "blanco" es esperable; el riesgo real está en paneles
  "no_blanco", "control" o "relacionado".
- Todo es predicción in silico: decilo cuando recomiendes algo concreto.
- Respuestas de 8 líneas o menos, salvo que pidan detalle. Nada de markdown pesado:
  texto plano, listas con guiones."""

TOOLS: List[dict] = [
    {"type": "function", "function": {
        "name": "ejecutar",
        "description": "Ejecuta un comando de shell dentro de ~/.sifidesk/agente (tu carpeta). "
                       "No podés tocar el programa instalado ni el sistema.",
        "parameters": {"type": "object", "properties": {
            "cmd": {"type": "string", "description": "comando a ejecutar"},
            "timeout": {"type": "integer", "description": "segundos (máx 600)"},
        }, "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "python",
        "description": "Corre un script de Python en tu carpeta de trabajo (para análisis, "
                       "conteos, parseo de FASTA, gráficos simples).",
        "parameters": {"type": "object", "properties": {
            "codigo": {"type": "string"}}, "required": ["codigo"]}}},
    {"type": "function", "function": {
        "name": "descargar",
        "description": "Descarga un archivo por HTTP(S) a tu carpeta (por defecto descargas/).",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
            "archivo": {"type": "string", "description": "nombre o ruta relativa dentro de tu carpeta"},
            "limite_mb": {"type": "integer"},
        }, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "leer",
        "description": "Lee un archivo de tu carpeta (texto, hasta 200 líneas).",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"}, "lineas": {"type": "integer"}},
            "required": ["ruta"]}}},
    {"type": "function", "function": {
        "name": "escribir",
        "description": "Escribe un archivo en tu carpeta (texto).",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"}, "contenido": {"type": "string"}},
            "required": ["ruta", "contenido"]}}},
    {"type": "function", "function": {
        "name": "listar_archivos",
        "description": "Lista lo que hay en tu carpeta de trabajo y en descargas, con tamaño.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "sifi",
        "description": "CLI de siFi Desk. Acciones: 'panel list', 'panel add <fasta> --id <id> "
                       "--rol blanco|no_blanco|control|relacionado', 'doctor', 'design ...', "
                       "'offtarget ...'. Escribí los argumentos tal cual después de 'sifi'.",
        "parameters": {"type": "object", "properties": {
            "args": {"type": "string", "description": "argumentos del CLI"}},
            "required": ["args"]}}},
    {"type": "function", "function": {
        "name": "listar_paneles",
        "description": "Paneles registrados en el servicio, con rol y cantidad de secuencias.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "correr_corrida",
        "description": "Lanza una corrida de diseño u off-target en el servicio.",
        "parameters": {"type": "object", "properties": {
            "query_path": {"type": "string", "description": "FASTA en el disco (tu carpeta o la biblioteca)"},
            "query_fasta": {"type": "string", "description": "alternativa: contenido FASTA"},
            "panel_ids": {"type": "array", "items": {"type": "string"}},
            "modo": {"type": "string", "enum": ["design", "offtarget"]},
            "mismatches": {"type": "integer"},
            "sirna_size": {"type": "integer"},
            "main_target": {"type": "string"},
        }}}},
    {"type": "function", "function": {
        "name": "estado_corrida",
        "description": "Estado, progreso y resultado de una corrida del servicio.",
        "parameters": {"type": "object", "properties": {
            "run_id": {"type": "string"}}, "required": ["run_id"]}}},
]


# --------------------------------------------------------------------------- #
# contexto de la corrida
# --------------------------------------------------------------------------- #
def _contexto(store, run_id: Optional[str]) -> Dict[str, Any]:
    if not run_id:
        return {"corrida": None, "nota": "No hay una corrida seleccionada en la interfaz."}
    run = store.get(run_id)
    if not run:
        return {"corrida": None, "nota": f"No existe la corrida {run_id}."}

    ctx: Dict[str, Any] = {"corrida": run_id, "estado": run.get("status"),
                           "pedido": run.get("request") or {}}
    if run.get("status") != "done":
        return ctx

    raw = store.raw(run_id)
    path = raw["result_path"] if raw is not None else None
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, TypeError, ValueError):
        return ctx

    ctx["parametros"] = manifest.get("params")
    cands: List[dict] = []
    for rec in manifest.get("records", []):
        for c in rec.get("candidates", []):
            cands.append(c)
    cands.sort(key=lambda c: c.get("score") or 0, reverse=True)
    ctx["n_candidatos"] = len(cands)
    ctx["top"] = [{k: c.get(k) for k in ("name", "sirna", "position", "gene", "score",
                                         "efficiency", "risk", "specificity", "thermo", "design")}
                  for c in cands[:MAX_CANDIDATOS]]

    por_panel: Dict[str, int] = {}
    genes: Dict[str, set] = {}
    for rec in manifest.get("records", []):
        for row in rec.get("hits", []) or []:
            if not row.get("is_off_target"):
                continue
            panel = row.get("panel") or row.get("panel_id") or "?"
            por_panel[panel] = por_panel.get(panel, 0) + 1
            genes.setdefault(panel, set()).add(row.get("target_name") or "?")
    ctx["offtarget_por_panel"] = por_panel
    ctx["genes_por_panel"] = {k: sorted(v)[:20] for k, v in genes.items()}
    return ctx


# --------------------------------------------------------------------------- #
# herramientas
# --------------------------------------------------------------------------- #
class _Entorno:
    def __init__(self, store, base_url: str, token: Optional[str]):
        self.store = store
        self.base_url = base_url.rstrip("/")
        self.token = token

    def http(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None,
             timeout: int = 60) -> Any:
        data = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.base_url + ruta, data=data, method=metodo,
                                     headers={"Content-Type": "application/json",
                                              **({"X-Sifi-Token": self.token} if self.token else {})})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode() or "{}")


def _ejecutar(nombre: str, args: dict, ent: _Entorno) -> Dict[str, Any]:
    """Devuelve {ok, salida, ...} para una llamada del modelo."""
    if nombre == "ejecutar":
        timeout = min(int(args.get("timeout") or 180), 600)
        return sandbox.correr(args.get("cmd") or "", timeout=timeout)
    if nombre == "python":
        return sandbox.python(args.get("codigo") or "")
    if nombre == "descargar":
        return sandbox.descargar(args.get("url") or "", args.get("archivo"),
                                 int(args.get("limite_mb") or 800))
    if nombre == "leer":
        return {"ok": True, "salida": sandbox.leer(args.get("ruta") or "",
                                                   int(args.get("lineas") or 200))}
    if nombre == "escribir":
        return {"ok": True, "salida": sandbox.escribir(args.get("ruta") or "",
                                                      args.get("contenido") or "")}
    if nombre == "listar_archivos":
        return {"ok": True, "salida": json.dumps(sandbox.inventario(), ensure_ascii=False)}
    if nombre == "sifi":
        cli = os.path.join(CORE_DIR, "cli.py")
        return sandbox.correr(f"{sys.executable} {sandbox.shlex_quote(cli)} "
                              f"{args.get('args') or ''}",
                              timeout=min(int(args.get("timeout") or 600), 1800))
    if nombre == "listar_paneles":
        data = ent.http("GET", "/panels")
        return {"ok": True, "salida": json.dumps(
            [{k: p.get(k) for k in ("id", "nombre", "rol", "n_seqs", "index_ok")}
             for p in data.get("panels", [])], ensure_ascii=False)}
    if nombre == "correr_corrida":
        cuerpo = {
            "mode": args.get("modo") or "design",
            "panel_ids": args.get("panel_ids") or [],
            "mismatches": int(args.get("mismatches") or 0),
            "sirna_size": int(args.get("sirna_size") or 21),
        }
        if args.get("query_path"):
            cuerpo["query_path"] = sandbox.resolver(args["query_path"])
        elif args.get("query_fasta"):
            cuerpo["query_fasta"] = args["query_fasta"]
        else:
            return {"ok": False, "salida": "falta query_path o query_fasta"}
        if args.get("main_target"):
            cuerpo["main_target_mode"] = "explicit"
            cuerpo["main_targets"] = [args["main_target"]]
        try:
            data = ent.http("POST", "/runs", cuerpo, timeout=120)
        except urllib.error.HTTPError as exc:
            return {"ok": False, "salida": f"el servicio rechazó la corrida: "
                                           f"{exc.code} {exc.read().decode('utf-8', 'replace')[:300]}"}
        run = data.get("run", data)
        return {"ok": True, "salida": f"corrida {run.get('run_id')} en estado {run.get('status')}"}
    if nombre == "estado_corrida":
        try:
            run = ent.http("GET", f"/runs/{args.get('run_id')}")
        except urllib.error.HTTPError as exc:
            return {"ok": False, "salida": f"HTTP {exc.code}"}
        resumen = {k: run.get(k) for k in ("run_id", "status", "progress", "error")}
        return {"ok": True, "salida": json.dumps(resumen, ensure_ascii=False)}
    return {"ok": False, "salida": f"herramienta desconocida: {nombre}"}


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
def _post_llm(mensajes: List[dict], *, tools: bool, max_tokens: int = 800,
              timeout: int = 120) -> dict:
    clave = settings.clave_actual()
    if not clave:
        raise RuntimeError("sin clave")
    est = settings.estado()
    cuerpo: Dict[str, Any] = {
        "model": est["modelo"],
        "messages": mensajes,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        cuerpo["tools"] = TOOLS
        cuerpo["tool_choice"] = "auto"
    req = urllib.request.Request(
        est["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {clave}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def _tarjeta(nombre: str, args: dict, res: dict) -> dict:
    salida = str(res.get("salida") or "")
    if res.get("ruta"):
        salida = f"{salida}\n→ {res['ruta']} ({res.get('bytes', '?')} bytes)"
    return {"nombre": nombre, "args": args, "resultado": salida[:MAX_CANDIDATOS * 400],
            "ok": bool(res.get("ok")), "ms": res.get("ms")}


def chat(store, mensaje: str, run_id: Optional[str] = None,
         historial: Optional[List[dict]] = None, *, base_url: str = "",
         token: Optional[str] = None) -> Dict[str, Any]:
    mensaje = (mensaje or "").strip()
    if not mensaje:
        return {"respuesta": "Escribí una pregunta.", "configurar": False}

    if not settings.clave_actual():
        return {"respuesta": ("Todavía no tengo clave del modelo, así que no puedo responder. "
                              "Pegala en Ajustes → Clave del modelo y volvé a preguntar."),
                "configurar": True}

    ent = _Entorno(store, base_url or "http://127.0.0.1:8765", token)
    ctx = _contexto(store, run_id)
    mensajes: List[dict] = [{"role": "system", "content": SYSTEM}]
    for m in (historial or [])[-MAX_HISTORIAL:]:
        rol, txt = m.get("role"), (m.get("content") or "").strip()
        if rol in ("user", "assistant") and txt:
            mensajes.append({"role": rol, "content": txt[:2000]})
    mensajes.append({
        "role": "user",
        "content": "CONTEXTO (datos de la corrida; no inventar nada fuera de esto):\n"
                   + json.dumps(ctx, ensure_ascii=False, indent=1)
                   + f"\n\nTu carpeta de trabajo: {sandbox.RAIZ}\n"
                   + "\nPREGUNTA: " + mensaje,
    })

    tarjetas: List[dict] = []
    t0 = time.time()
    try:
        for _ronda in range(MAX_RONDAS):
            data = _post_llm(mensajes, tools=True)
            msg = data["choices"][0]["message"]
            llamadas = msg.get("tool_calls") or []
            if not llamadas:
                texto = (msg.get("content") or "").strip()
                return {"respuesta": texto or "(el modelo no devolvió texto)",
                        "tools": tarjetas, "modelo": settings.estado()["modelo"],
                        "ms": int((time.time() - t0) * 1000)}

            mensajes.append({"role": "assistant", "content": msg.get("content"), 
                             "tool_calls": llamadas})
            for ll in llamadas:
                fn = ll.get("function") or {}
                nombre = fn.get("name") or "?"
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                try:
                    res = _ejecutar(nombre, args, ent)
                except sandbox.Denegado as exc:
                    res = {"ok": False, "salida": f"bloqueado: {exc}"}
                except Exception as exc:  # noqa: BLE001 - el agente tiene que ver el motivo
                    res = {"ok": False, "salida": f"error: {type(exc).__name__}: {exc}"}
                tarjetas.append(_tarjeta(nombre, args, res))
                mensajes.append({"role": "tool", "tool_call_id": ll.get("id"),
                                 "content": json.dumps(
                                     {"ok": res.get("ok"), "salida": res.get("salida")},
                                     ensure_ascii=False)})

        # se quedó sin rondas: pedir un cierre sin herramientas
        mensajes.append({"role": "user", "content": "Cerrá con lo que tengas, sin usar más "
                                                    "herramientas, en 5 líneas."})
        data = _post_llm(mensajes, tools=False, max_tokens=400)
        texto = (data["choices"][0]["message"].get("content") or "").strip()
        return {"respuesta": texto or "No llegué a una conclusión.", "tools": tarjetas,
                "modelo": settings.estado()["modelo"], "ms": int((time.time() - t0) * 1000)}
    except urllib.error.HTTPError as exc:
        detalle = ""
        try:
            detalle = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if exc.code in (401, 403):
            return {"respuesta": "La clave fue rechazada por el proveedor (401/403). "
                                 "Revisala en Ajustes.", "configurar": True}
        if exc.code == 402:
            return {"respuesta": "El proveedor dice que la cuenta no tiene saldo (402)."}
        return {"respuesta": f"El proveedor devolvió {exc.code}. {detalle}".strip(),
                "tools": tarjetas}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"respuesta": f"No pude llegar al proveedor del modelo: {exc}.",
                "tools": tarjetas}
    except (KeyError, ValueError) as exc:
        return {"respuesta": f"Respuesta inesperada del proveedor: {exc}.", "tools": tarjetas}


def probar() -> Dict[str, Any]:
    """Un pedido mínimo para saber si la clave sirve."""
    if not settings.clave_actual():
        return {"ok": False, "detalle": "no hay clave configurada"}
    t0 = time.time()
    try:
        data = _post_llm([{"role": "system", "content": "Respondé sólo 'ok'."},
                          {"role": "user", "content": "ping"}], tools=False,
                         max_tokens=4, timeout=25)
        texto = (data["choices"][0]["message"].get("content") or "").strip()
    except urllib.error.HTTPError as exc:
        return {"ok": False, "detalle": f"HTTP {exc.code}", "status": exc.code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detalle": str(exc)[:200]}
    return {"ok": True, "detalle": texto[:40] or "ok",
            "ms": int((time.time() - t0) * 1000), "modelo": settings.estado()["modelo"]}
