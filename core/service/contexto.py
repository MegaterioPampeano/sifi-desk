"""Armado de la ventana de contexto del agente.

Tres cosas que antes no existían:

1. **Presupuesto real por tokens** (no "últimos 8 turnos"): se toman los turnos del más
   nuevo al más viejo hasta llenar el presupuesto, y si el turno es enorme se recorta por
   los bordes, no se tira entero.
2. **Resultados de herramientas en el contexto**: cada tarjeta (comando + salida) vuelve
   como parte del turno del asistente, recortada. Antes sólo se veían en la UI, y por eso
   el agente "se olvidaba" de lo que había corrido.
3. **Compactación con resumen**: cuando la sesión supera el umbral, los turnos viejos se
   resumen con el propio modelo y el resumen queda persistido en el JSON de la sesión.
   Los últimos turnos se conservan textuales.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

#: caracteres por token (español técnico ronda 3.4-3.8; redondeamos conservador)
CHARS_POR_TOKEN = 3.4

#: techo de trabajo del historial. El modelo declara 1M de contexto; gastar eso por turno
#: es tirar plata, así que la ventana útil es esta y el resto lo cubre el resumen.
PRESUPUESTO_TOKENS = int(os.environ.get("SIFI_AGENT_HIST_TOKENS") or 90000)
#: a partir de acá se compacta
UMBRAL_COMPACTAR = float(os.environ.get("SIFI_AGENT_COMPACT_AT") or 0.75)
#: cuántos turnos quedan textuales después de compactar
TURNOS_VIVOS = int(os.environ.get("SIFI_AGENT_TURNOS_VIVOS") or 10)
#: tope por salida de herramienta que vuelve al contexto
TOPE_TOOL_CTX = 4000
#: tope por turno de texto
TOPE_TURNO = 12000


def estimar_tokens(texto: str) -> int:
    return int(len(texto or "") / CHARS_POR_TOKEN) + 1


def tokens_de(mensajes: List[dict]) -> int:
    total = 0
    for m in mensajes:
        total += estimar_tokens(str(m.get("content") or ""))
        for k in ("tool_calls", "herramientas"):
            if m.get(k):
                total += estimar_tokens(str(m[k]))
    return total


def recortar(texto: str, tope: int = TOPE_TURNO) -> str:
    """Recorta por los bordes: el principio orienta, el final tiene la conclusión."""
    texto = texto or ""
    if len(texto) <= tope:
        return texto
    mitad = tope // 2
    return (texto[:mitad].rstrip()
            + f"\n… [{len(texto) - tope} caracteres recortados] …\n"
            + texto[-mitad:].lstrip())


def tarjeta_a_texto(tarjeta: dict) -> str:
    """Convierte una tarjeta de herramienta en el bloque que lee el modelo."""
    nombre = tarjeta.get("nombre") or "?"
    args = tarjeta.get("args") or {}
    res = str(tarjeta.get("resultado") or "").strip()
    if len(res) > TOPE_TOOL_CTX:
        res = res[:TOPE_TOOL_CTX] + f" … (+{len(res) - TOPE_TOOL_CTX} caracteres)"
    pedido = ", ".join(f"{k}={str(v)[:120]}" for k, v in args.items()
                       if not isinstance(v, (dict, list)))
    if len(pedido) > 300:
        pedido = pedido[:300] + "…"
    estado = "ok" if tarjeta.get("ok") else "error"
    return f"[{nombre}({pedido}) → {estado}]\n{res or '(sin salida)'}"


def turnos_para_llm(sesion: Dict[str, Any], presupuesto: int = PRESUPUESTO_TOKENS,
                    incluir_resumen: bool = True) -> List[dict]:
    """Historial en formato chat, con tarjetas de herramientas adentro."""
    mensajes = sesion.get("mensajes") or []
    salida: List[dict] = []
    usados = 0
    for m in reversed(mensajes):
        rol = m.get("role")
        if rol not in ("user", "assistant"):
            continue
        texto = (m.get("texto") or "").strip()
        tarjetas = m.get("herramientas") or []
        if not texto and not tarjetas:
            continue
        if tarjetas:
            bloques = "\n\n".join(tarjeta_a_texto(t) for t in tarjetas)
            texto = (texto + "\n\n" + bloques).strip() if texto else bloques
        texto = recortar(texto)
        costo = estimar_tokens(texto)
        if usados + costo > presupuesto and salida:
            break
        usados += costo
        salida.append({"role": rol, "content": texto})
    salida.reverse()

    if incluir_resumen and sesion.get("resumen"):
        salida.insert(0, {
            "role": "user",
            "content": "[RESUMEN DE LA CONVERSACIÓN ANTERIOR — lo que ya se habló, "
                       "resolvió y quedó pendiente]\n" + str(sesion["resumen"]).strip(),
        })
    return salida


def necesita_compactar(sesion: Dict[str, Any],
                       presupuesto: int = PRESUPUESTO_TOKENS) -> bool:
    return tokens_de(turnos_para_llm(sesion, presupuesto * 10)) > presupuesto * UMBRAL_COMPACTAR


def mensajes_a_resumir(sesion: Dict[str, Any],
                       vivos: int = TURNOS_VIVOS) -> List[dict]:
    """Los turnos que quedan afuera y hay que resumir (todos menos los últimos `vivos`)."""
    mensajes = [m for m in (sesion.get("mensajes") or [])
                if m.get("role") in ("user", "assistant")]
    if len(mensajes) <= vivos:
        return []
    return mensajes[:-vivos]


def texto_para_resumen(mensajes: List[dict], maximo: int = 120000) -> str:
    partes = []
    for m in mensajes:
        quién = "Mariano" if m.get("role") == "user" else "Agente"
        cuerpo = (m.get("texto") or "").strip()
        if m.get("herramientas"):
            cuerpo += "\n" + "\n".join(
                f"  · {t.get('nombre')}: {str(t.get('resultado'))[:400]}"
                for t in m["herramientas"])
        partes.append(f"{quién}: {cuerpo}")
    texto = "\n\n".join(partes)
    return texto[-maximo:]
