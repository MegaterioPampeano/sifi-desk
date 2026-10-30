"""Memoria del agente en archivos, en la carpeta del agente.

Mismo modelo que usa Multivac (el asistente de OpenClaw), adaptado al laboratorio:

  memoria/MEMORY.md              archivo de largo plazo (curado, se reescribe)
  memoria/hot/HOT_MEMORY.md      en qué está trabajando ahora (chico, se pisa)
  memoria/warm/WARM_MEMORY.md    preferencias y configuración estable
  memoria/YYYY-MM-DD.md          bitácora cruda del día (se agrega, no se pisa)

El agente arranca cada turno con HOT + WARM + la cola de MEMORY.md en el prompt
(bloque_sistema), y tiene tres herramientas para leer, escribir y buscar. La idea es
que no dependa de que la ventana de contexto lo recuerde: si algo importa, va al archivo.
"""
from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional

ARCHIVOS = {
    "hot": os.path.join("hot", "HOT_MEMORY.md"),
    "warm": os.path.join("warm", "WARM_MEMORY.md"),
    "largo": "MEMORY.md",
}


def _raiz() -> str:
    from . import politica
    return os.path.join(politica.RAIZ, "memoria")


def _ruta(nombre: str) -> str:
    """Acepta 'hot', 'warm', 'largo' o un nombre de archivo (incluso YYYY-MM-DD.md)."""
    if nombre in ARCHIVOS:
        return os.path.join(_raiz(), ARCHIVOS[nombre])
    limpio = str(nombre or "").strip().replace("\\", "/").lstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,80}", limpio) or ".." in limpio.split("/"):
        raise ValueError("nombre de archivo de memoria inválido")
    destino = os.path.normpath(os.path.join(_raiz(), limpio))
    if not destino.startswith(_raiz() + os.sep):
        raise ValueError("nombre de archivo de memoria inválido")
    return destino


def diario(fecha: Optional[str] = None) -> str:
    fecha = fecha or time.strftime("%Y-%m-%d")
    return os.path.join(_raiz(), f"{fecha}.md")


def asegurar() -> None:
    for ruta in (*ARCHIVOS.values(),):
        destino = os.path.join(_raiz(), ruta)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        if not os.path.exists(destino):
            with open(destino, "w", encoding="utf-8") as fh:
                fh.write("# " + os.path.basename(ruta).replace(".md", "").replace("_", " ")
                         + "\n")


def leer(nombre: str = "largo", limite: int = 20000) -> str:
    ruta = _ruta(nombre)
    try:
        with open(ruta, encoding="utf-8", errors="replace") as fh:
            return fh.read()[-limite:]
    except FileNotFoundError:
        return ""


def escribir(nombre: str, contenido: str, agregar: bool = True) -> Dict[str, object]:
    asegurar()
    ruta = _ruta(nombre)
    modo = "a" if agregar else "w"
    with open(ruta, modo, encoding="utf-8") as fh:
        if agregar and fh.tell() and not leer(nombre).endswith("\n"):
            fh.write("\n")
        fh.write(contenido.rstrip() + "\n")
    return {"archivo": os.path.relpath(ruta, _raiz()), "bytes": os.path.getsize(ruta),
            "agregado": agregar}


def anotar(texto: str, fecha: Optional[str] = None) -> Dict[str, object]:
    """Agrega una línea a la bitácora del día (atajo de lo anterior)."""
    ruta = diario(fecha)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", encoding="utf-8") as fh:
        if nuevo:
            fh.write(f"# {os.path.basename(ruta)[:-3]}\n\n")
        fh.write(f"- {time.strftime('%H:%M')} {texto.strip()}\n")
    return {"archivo": os.path.relpath(ruta, _raiz()), "bytes": os.path.getsize(ruta)}


def buscar(termino: str, maximo: int = 20) -> List[Dict[str, object]]:
    """grep case-insensitive sobre todos los archivos de memoria."""
    patron = re.compile(re.escape(termino), re.IGNORECASE)
    out: List[Dict[str, object]] = []
    for base, _dirs, files in os.walk(_raiz()):
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            ruta = os.path.join(base, f)
            try:
                with open(ruta, encoding="utf-8", errors="replace") as fh:
                    for i, linea in enumerate(fh, 1):
                        if patron.search(linea):
                            out.append({"archivo": os.path.relpath(ruta, _raiz()),
                                        "linea": i, "texto": linea.strip()[:300]})
                            if len(out) >= maximo:
                                return out
            except OSError:
                continue
    return out


def bloque_sistema(limite_hot: int = 6000, limite_warm: int = 4000,
                   limite_largo: int = 8000) -> str:
    """Lo que entra en el system prompt: lo vivo y lo estable, recortado."""
    asegurar()
    partes = []
    for nombre, tope, titulo in (("hot", limite_hot, "EN QUÉ ESTOY AHORA"),
                                 ("warm", limite_warm, "PREFERENCIAS Y CONFIG"),
                                 ("largo", limite_largo, "MEMORIA DE LARGO PLAZO")):
        texto = leer(nombre, tope).strip()
        if texto:
            partes.append(f"### {titulo}\n{texto}")
    return "\n\n".join(partes)


def resumen_para_ui() -> Dict[str, object]:
    asegurar()
    salida = {}
    for nombre in (*ARCHIVOS, ):
        ruta = os.path.join(_raiz(), ARCHIVOS[nombre])
        salida[nombre] = {"bytes": os.path.getsize(ruta) if os.path.exists(ruta) else 0}
    return salida
