"""Conversaciones del agente, guardadas en disco.

Cada charla es un archivo JSON en `<data>/agent_sesiones/<id>.json`. El agente no
tenía memoria entre sesiones: se cerraba la ventana y volvía a cero, aunque hubiera
bajado un transcriptoma y armado un panel en la charla anterior. Esto lo arregla.

El formato guarda el texto de cada turno y las herramientas usadas (nombre, comando,
salida corta) para que al reabrir la sesión la conversación se vea igual que cuando
pasó, sin volver a ejecutar nada.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional

MAX_MENSAJES = 200
MAX_TEXTO = 20000


def _dir(data_dir: str) -> str:
    ruta = os.path.join(data_dir, "agent_sesiones")
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _ruta(data_dir: str, sid: str) -> str:
    if not sid or not all(c.isalnum() or c in "-_" for c in sid):
        raise ValueError("id de sesión inválido")
    return os.path.join(_dir(data_dir), sid + ".json")


def _leer(data_dir: str, sid: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_ruta(data_dir, sid), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _escribir(data_dir: str, sesion: Dict[str, Any]) -> None:
    sesion["actualizado"] = time.time()
    destino = _ruta(data_dir, sesion["id"])
    tmp = destino + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(sesion, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, destino)


def _titulo(texto: str) -> str:
    limpio = " ".join((texto or "").split())
    if len(limpio) > 60:
        limpio = limpio[:57].rstrip() + "…"
    return limpio or "Charla nueva"


def crear(data_dir: str, titulo: Optional[str] = None) -> Dict[str, Any]:
    ahora = time.time()
    sesion = {
        "id": "c-" + secrets.token_hex(5),
        "titulo": titulo or "Charla nueva",
        "creado": ahora,
        "actualizado": ahora,
        "mensajes": [],
    }
    _escribir(data_dir, sesion)
    return sesion


def listar(data_dir: str) -> List[Dict[str, Any]]:
    filas = []
    for nombre in os.listdir(_dir(data_dir)):
        if not nombre.endswith(".json"):
            continue
        s = _leer(data_dir, nombre[:-5])
        if not s:
            continue
        filas.append({"id": s.get("id"), "titulo": s.get("titulo"),
                      "actualizado": s.get("actualizado"), "creado": s.get("creado"),
                      "n": len(s.get("mensajes") or []),
                      "corridas": sorted({m.get("run_id") for m in s.get("mensajes") or []
                                          if m.get("run_id")})})
    filas.sort(key=lambda f: f.get("actualizado") or 0, reverse=True)
    return filas


def obtener(data_dir: str, sid: str) -> Dict[str, Any]:
    s = _leer(data_dir, sid)
    if not s:
        raise ValueError("no existe esa sesión")
    return s


def asegurar(data_dir: str, sid: Optional[str]) -> Dict[str, Any]:
    """Devuelve la sesión pedida; si no hay id, abre una nueva."""
    if not sid:
        return crear(data_dir)
    s = _leer(data_dir, sid)
    return s if s else crear(data_dir)


def agregar(data_dir: str, sid: str, rol: str, texto: str, *,
            herramientas: Optional[List[dict]] = None,
            run_id: Optional[str] = None) -> Dict[str, Any]:
    s = obtener(data_dir, sid)
    msgs = s.setdefault("mensajes", [])
    entrada: Dict[str, Any] = {"role": rol, "texto": (texto or "")[:MAX_TEXTO],
                               "ts": time.time()}
    if herramientas:
        entrada["herramientas"] = herramientas[:20]
    if run_id:
        entrada["run_id"] = run_id
    msgs.append(entrada)
    if len(msgs) > MAX_MENSAJES:
        s["mensajes"] = msgs[-MAX_MENSAJES:]
    if rol == "user" and (s.get("titulo") in (None, "", "Charla nueva")):
        s["titulo"] = _titulo(texto)
    _escribir(data_dir, s)
    return s


def guardar_plan(data_dir: str, sid: str, pasos, nota: str = "") -> bool:
    """Guarda el plan de trabajo de la charla (lista de pasos con estado)."""
    sesion = _leer(data_dir, sid)
    if not sesion:
        return False
    sesion["plan"] = {"pasos": list(pasos or [])[:20], "nota": (nota or "")[:300],
                      "actualizado": time.time()}
    _escribir(data_dir, sesion)
    return True


def renombrar(data_dir: str, sid: str, titulo: str) -> Dict[str, Any]:
    s = obtener(data_dir, sid)
    s["titulo"] = _titulo(titulo)
    _escribir(data_dir, s)
    return s


def borrar(data_dir: str, sid: str) -> Dict[str, Any]:
    try:
        os.unlink(_ruta(data_dir, sid))
    except OSError:
        raise ValueError("no existe esa sesión")
    return {"borrada": sid}


def historial_para_llm(sesion: Dict[str, Any], turnos: Optional[int] = None) -> List[dict]:
    """Ventana de contexto: turnos con sus herramientas y el resumen, si hay.

    Antes se mandaban sólo los últimos 8 turnos y **sólo texto**: los resultados de las
    herramientas no volvían al modelo y por eso "se olvidaba" de lo que había corrido.
    Ahora la selección es por presupuesto de tokens (`contexto.turnos_para_llm`), cada
    turno trae sus tarjetas recortadas y, si la sesión se compactó, primero va el resumen.
    """
    from . import contexto as _ctx
    if turnos:
        return _ctx.turnos_para_llm(sesion, presupuesto=turnos * 2000)
    return _ctx.turnos_para_llm(sesion)


def compactar(data_dir: str, sid: str, resumidor, vivos: int = 0) -> Optional[Dict[str, Any]]:
    """Resume los turnos viejos y deja los últimos `vivos` textuales.

    `resumidor(texto) -> str` la provee el agente (usa el mismo modelo). Si falla, se
    devuelve None y la sesión queda como estaba: compactar es una optimización, no puede
    romper la charla.
    """
    from . import contexto as _ctx
    sesion = _leer(data_dir, sid)
    if not sesion:
        return None
    vivos = vivos or _ctx.TURNOS_VIVOS
    viejos = _ctx.mensajes_a_resumir(sesion, vivos)
    if len(viejos) < 4:
        return None
    previo = (sesion.get("resumen") or "").strip()
    material = _ctx.texto_para_resumen(viejos)
    if previo:
        material = f"RESUMEN PREVIO:\n{previo}\n\nTURNOS NUEVOS A INCORPORAR:\n{material}"
    try:
        resumen = resumidor(material)
    except Exception:  # noqa: BLE001
        return None
    if not resumen:
        return None
    todos = [m for m in (sesion.get("mensajes") or [])
             if m.get("role") in ("user", "assistant")]
    restantes = todos[-vivos:] if vivos else []
    sesion["resumen"] = resumen.strip()
    sesion["mensajes"] = restantes
    sesion["compactado"] = time.time()
    _escribir(data_dir, sesion)
    return {"resumen_chars": len(sesion["resumen"]), "turnos_resumidos": len(viejos),
            "turnos_vivos": len(restantes)}
