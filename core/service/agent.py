"""Agente del panel lateral: respuestas a partir del manifest de la corrida.

No inventa datos: arma un contexto acotado con lo que el servicio ya calculó
(candidatos puntuados, hits por panel, parámetros) y le pide al LLM que responda
sólo con eso. Si no hay clave configurada devuelve 200 con una explicación y
`configurar: true`, para que la UI ofrezca abrir Ajustes en vez de un error 405.

El modelo y el endpoint salen de `service.settings`; el dialecto es OpenAI-compatible
(DeepSeek, OpenRouter, together, vLLM local).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from . import settings

MAX_CANDIDATOS = 15

SYSTEM = """Sos el agente de siFi Desk, una aplicación de escritorio para diseñar dsRNA
contra plagas (Dalbulus maidis, la chicharrita del maíz, y otras). Hablás en español
rioplatense, breve y concreto, sin vueltas y sin adulación.

Reglas:
- Respondés SÓLO con la información del CONTEXTO que te paso. Si algo no está ahí,
  decís que no está en los datos de esta corrida y qué habría que correr para saberlo.
- Cuando cites números (score, GC, posiciones, hits) usá los del contexto, tal cual.
- El score va de 0 a 100: más alto es mejor candidato. E, R, S, T y D son los
  componentes (eficiencia, riesgo, especificidad, termodinámica, diseño).
- Un off-target contra el panel "blanco" es esperable (el siRNA sale del propio gen
  blanco). Lo que importa es lo que pega en paneles "no_blanco", "control" o
  "relacionado": eso es riesgo real.
- No prometas resultados en el insecto: todo esto es predicción in silico y necesita
  validación en bioensayo. Decilo cuando des una recomendación fuerte.
- Máximo 8 líneas, salvo que te pidan detalle."""


def _contexto(store, run_id: Optional[str]) -> Dict[str, Any]:
    if not run_id:
        return {"corrida": None,
                "nota": "No hay una corrida seleccionada en la interfaz."}
    run = store.get(run_id)
    if not run:
        return {"corrida": None, "nota": f"No existe la corrida {run_id}."}

    ctx: Dict[str, Any] = {
        "corrida": run_id,
        "estado": run.get("status"),
        "pedido": run.get("request") or {},
    }
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
    ctx["top"] = [
        {k: c.get(k) for k in ("name", "sirna", "position", "gene", "score",
                               "efficiency", "risk", "specificity", "thermo", "design")}
        for c in cands[:MAX_CANDIDATOS]
    ]

    # off-target agregado por panel
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


def _llamar(prompt_sistema: str, mensajes: List[dict], *,
            max_tokens: int = 700, timeout: int = 60) -> str:
    clave = settings.clave_actual()
    if not clave:
        raise RuntimeError("sin clave")
    est = settings.estado()
    url = est["base_url"].rstrip("/") + "/chat/completions"
    cuerpo = {
        "model": est["modelo"],
        "messages": [{"role": "system", "content": prompt_sistema}] + mensajes,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }
    req = urllib.request.Request(
        url, data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {clave}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read().decode("utf-8"))
    return (data["choices"][0]["message"].get("content") or "").strip()


def chat(store, mensaje: str, run_id: Optional[str] = None,
         historial: Optional[List[dict]] = None) -> Dict[str, Any]:
    mensaje = (mensaje or "").strip()
    if not mensaje:
        return {"respuesta": "Escribí una pregunta.", "configurar": False}

    if not settings.clave_actual():
        return {
            "respuesta": ("Todavía no tengo clave del modelo, así que no puedo responder. "
                          "Pegala en Ajustes → Clave del modelo y volvé a preguntar."),
            "configurar": True,
        }

    ctx = _contexto(store, run_id)
    mensajes: List[dict] = []
    for m in (historial or [])[-6:]:
        rol = m.get("role")
        txt = (m.get("content") or "").strip()
        if rol in ("user", "assistant") and txt:
            mensajes.append({"role": rol, "content": txt[:2000]})
    mensajes.append({
        "role": "user",
        "content": "CONTEXTO (datos de la corrida, no inventar nada fuera de esto):\n"
                   + json.dumps(ctx, ensure_ascii=False, indent=1)
                   + "\n\nPREGUNTA: " + mensaje,
    })

    t0 = time.time()
    try:
        texto = _llamar(SYSTEM, mensajes)
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
        return {"respuesta": f"El proveedor devolvió {exc.code}. {detalle}".strip()}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"respuesta": f"No pude llegar al proveedor del modelo: {exc}."}
    except (KeyError, ValueError) as exc:
        return {"respuesta": f"Respuesta inesperada del proveedor: {exc}."}

    return {"respuesta": texto or "(el modelo no devolvió texto)",
            "modelo": settings.estado()["modelo"],
            "ms": int((time.time() - t0) * 1000)}


def probar() -> Dict[str, Any]:
    """Un pedido mínimo para saber si la clave sirve."""
    if not settings.clave_actual():
        return {"ok": False, "detalle": "no hay clave configurada"}
    t0 = time.time()
    try:
        texto = _llamar("Respondé sólo 'ok'.", [{"role": "user", "content": "ping"}],
                        max_tokens=4, timeout=25)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "detalle": f"HTTP {exc.code}", "status": exc.code}
    except Exception as exc:  # noqa: BLE001 - queremos el motivo, sea cual sea
        return {"ok": False, "detalle": str(exc)[:200]}
    return {"ok": True, "detalle": (texto or "ok")[:40],
            "ms": int((time.time() - t0) * 1000),
            "modelo": settings.estado()["modelo"]}
