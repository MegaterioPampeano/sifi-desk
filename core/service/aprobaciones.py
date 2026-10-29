"""Cola de aprobaciones del agente.

Cuando el agente quiere escribir fuera de su carpeta, antes se le contestaba
"no puedo" y quedaba ahí: Mariano tenía que hacerlo a mano. Ahora ese pedido
queda encolado con un id, aparece en la app y se ejecuta (o se rechaza) con un
botón. Lo que está vetado por política dura (sudo, mkfs, apagado) no pasa por
acá: eso no se aprueba desde la UI.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from . import sandbox

_LOCK = threading.Lock()
MAXIMO = 200


def _ruta(data_dir: str) -> str:
    return os.path.join(data_dir, "aprobaciones.json")


def _leer(data_dir: str) -> List[dict]:
    try:
        with open(_ruta(data_dir), encoding="utf-8") as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, list) else []
    except (OSError, ValueError):
        return []


def _guardar(data_dir: str, items: List[dict]) -> None:
    os.makedirs(os.path.dirname(_ruta(data_dir)) or ".", exist_ok=True)
    tmp = _ruta(data_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(items[-MAXIMO:], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _ruta(data_dir))


def pedir(data_dir: str, cmd: str, motivo: str = "", origen: str = "agente") -> Dict[str, Any]:
    """Encola un pedido. Si el mismo comando ya está pendiente, devuelve ese."""
    with _LOCK:
        items = _leer(data_dir)
        for it in items:
            if it.get("estado") == "pendiente" and it.get("cmd") == cmd:
                return it
        item = {
            "id": "ap-" + uuid.uuid4().hex[:10],
            "cmd": cmd,
            "motivo": motivo,
            "origen": origen,
            "estado": "pendiente",
            "creado": time.time(),
            "resuelto": None,
            "resultado": None,
        }
        items.append(item)
        _guardar(data_dir, items)
        return item


def listar(data_dir: str, estado: Optional[str] = "pendiente") -> List[Dict[str, Any]]:
    items = _leer(data_dir)
    if estado and estado != "todos":
        items = [i for i in items if i.get("estado") == estado]
    return sorted(items, key=lambda i: i.get("creado") or 0, reverse=True)


def resolver(data_dir: str, aid: str, aprobado: bool, nota: str = "",
             timeout: int = sandbox.TIMEOUT_DEFECTO) -> Dict[str, Any]:
    """Aprueba (y ejecuta) o rechaza un pedido pendiente."""
    with _LOCK:
        items = _leer(data_dir)
        item = next((i for i in items if i.get("id") == aid), None)
        if item is None:
            raise KeyError(f"no existe el pedido {aid}")
        if item.get("estado") != "pendiente":
            return item
        item["estado"] = "aprobado" if aprobado else "rechazado"
        item["resuelto"] = time.time()
        if nota:
            item["nota"] = nota
        _guardar(data_dir, items)

    if not aprobado:
        return item

    try:
        res = sandbox.correr_aprobado(item["cmd"], timeout=timeout)
        item["resultado"] = {"ok": res.get("ok"), "rc": res.get("rc"),
                             "salida": res.get("salida")}
    except sandbox.Denegado as exc:  # vetado duro: ni con aprobación
        item["resultado"] = {"ok": False, "salida": f"bloqueado: {exc}"}
    except Exception as exc:  # noqa: BLE001
        item["resultado"] = {"ok": False, "salida": f"error: {type(exc).__name__}: {exc}"}

    with _LOCK:
        items = _leer(data_dir)
        for i, it in enumerate(items):
            if it.get("id") == aid:
                items[i] = item
        _guardar(data_dir, items)
    return item


def pendientes_para_el_agente(data_dir: str) -> List[Dict[str, Any]]:
    """Resumen corto para meter en el contexto del LLM."""
    return [{"id": i["id"], "cmd": i["cmd"], "estado": i["estado"],
             "resultado": (i.get("resultado") or {}).get("salida")}
            for i in listar(data_dir, "todos")[:5]]
