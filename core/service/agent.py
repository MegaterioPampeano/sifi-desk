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
MAX_RONDAS = 10
MAX_HISTORIAL = 8

CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYSTEM = """Sos el agente de siFi Desk: un asistente de laboratorio para diseñar dsRNA
contra plagas, sobre todo Dalbulus maidis (la chicharrita del maíz). Hablás en español
rioplatense, breve y concreto, sin adulación.

## Cómo trabajás (esto es lo importante)

Tratá cada pedido como un problema a resolver, no como una charla. El ciclo es:

1. **Entendé qué se pregunta.** Si es ambiguo, elegí la interpretación más útil y decila
   en una línea; no devuelvas la pregunta.
2. **Buscá antes de opinar.** Tenés herramientas para buscar en los datos del laboratorio,
   en la web y en NCBI. Usalas. Nunca contestes "no existe" porque no lo tenés en el
   contexto: "no lo tengo" y "no existe" son cosas distintas. Si buscaste y no aparece,
   decí dónde buscaste.
3. **Verificá.** Un hit de BLAST, un título de paper y un número de eficacia no valen
   igual. Citá la evidencia concreta (ID de transcrito, e-value, DOI, archivo:línea).
4. **Actuá.** Si el paso siguiente es un comando, un script o una descarga, hacelo vos.
5. **Reportá.** Qué encontraste, qué hiciste, qué quedó pendiente. Sin relleno.

## Autonomía

No pidas permiso para lo que es reversible y está en tu carpeta: leer, buscar, descargar
hasta ~100 MB, correr Python, procesar FASTA, mirar los datos del laboratorio. Hacelo y
contá el resultado. **Sólo** consultá antes de: bajar algo de más de 300 MB, lanzar una
corrida del servicio, o escribir fuera de tu carpeta de trabajo.

Nunca pegues código en el chat para que lo ejecute Mariano. Si hace falta código, usá
`python` o `ejecutar` y mostrá la salida real.

## Dónde está la información

- **Datos del laboratorio (sólo lectura, en /mnt/datos/biotech):** `buscar_gen` busca un
  gen o proteína en lo ya calculado (anotación del TSA de D. maidis contra el proteoma de
  D. melanogaster, shortlists, off-target, termodinámica). `transcrito` devuelve la
  secuencia de un ID del TSA (GITV…). Empezá por ahí: casi todo lo que sabemos de la
  chicharrita ya está calculado.
- **Web:** `buscar_web` (DuckDuckGo) y `abrir_url` para papers, PubMed, NCBI, preprints.
  Para literatura usá PubMed (`pubmed.ncbi.nlm.nih.gov/?term=…`) y citá DOI.
- **NCBI por API:** `descargar` con URLs de eutils (esearch/efetch) sirve para traer
  secuencias o genomas.
- **El servicio:** `listar_paneles`, `correr_corrida`, `estado_corrida`, `sifi`.
- **Tu carpeta:** ~/.sifidesk/agente (trabajo, descargas). `listar_archivos` para ver qué
  dejaste antes; los archivos persisten entre charlas.

## Dominio (lo mínimo para no meter la pata)

- BicC = Bicaudal C, RNA-binding, ovogénesis. En D. maidis está descrito por
  Dalaisón-Fuentes et al. 2022 (Pest Manag Sci 78:3108, doi 10.1002/ps.6937): dsRNA baja
  el transcrito hasta 170× y reduce la oviposición. Es el blanco de referencia.
- Score 0–100 (más alto mejor); componentes E/R/S/T/D = eficacia, riesgo, especificidad,
  termodinámica y diseño. Off-target en el panel "blanco" es esperable; el riesgo real
  está en no_blanco, control y relacionados.
- Todo es predicción in silico salvo que cites un experimento. Decilo cuando recomendás.

## Límites

No podés modificar el programa instalado (bundle, repo, `agent/`), usar sudo ni tocar el
sistema. Si un cambio de código hace falta, lo pedís: lo revisa Mariano.

Formato: 10 líneas o menos salvo que pidan detalle; texto plano, listas con guiones,
números exactos. Si una tarea es larga, hacé los pasos y contá el avance."""

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
        "name": "buscar_gen",
        "description": "Busca un gen, proteína o transcrito en los datos ya calculados del "
                       "laboratorio (anotación del TSA de Dalbulus maidis vs Drosophila, "
                       "shortlists, off-target, termodinámica). Devolvé el término corto: "
                       "'BicC', 'Q24009', 'GITV01002238.1', 'V-ATPasa'.",
        "parameters": {"type": "object", "properties": {
            "termino": {"type": "string"}, "maximo": {"type": "integer"}},
            "required": ["termino"]}}},
    {"type": "function", "function": {
        "name": "transcrito",
        "description": "Devuelve la secuencia completa (o los primeros N nt) de un transcrito "
                       "del TSA de D. maidis, por ID (GITV01002238.1).",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string"}, "contexto": {"type": "integer",
                                                  "description": "si >0, sólo los primeros N nt"}},
            "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "buscar_web",
        "description": "Busca en la web (DuckDuckGo) y devuelve títulos, URLs y fragmentos. "
                       "Para papers conviene buscar en PubMed o por DOI.",
        "parameters": {"type": "object", "properties": {
            "consulta": {"type": "string"}, "maximo": {"type": "integer"}},
            "required": ["consulta"]}}},
    {"type": "function", "function": {
        "name": "abrir_url",
        "description": "Trae una página y la devuelve como texto plano (para leer abstracts, "
                       "fichas de NCBI, documentación).",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}, "maximo": {"type": "integer"}},
            "required": ["url"]}}},
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
    if nombre == "buscar_gen":
        return {"ok": True, "salida": sandbox.buscar_gen(args.get("termino") or "",
                                                        int(args.get("maximo") or 40))}
    if nombre == "transcrito":
        return {"ok": True, "salida": sandbox.transcrito(args.get("id") or "",
                                                        int(args.get("contexto") or 0))}
    if nombre == "buscar_web":
        return {"ok": True, "salida": sandbox.buscar_web(args.get("consulta") or "",
                                                        int(args.get("maximo") or 6))}
    if nombre == "abrir_url":
        return {"ok": True, "salida": sandbox.abrir_url(args.get("url") or "",
                                                       int(args.get("maximo") or 6000))}
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
