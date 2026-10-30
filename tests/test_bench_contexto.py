"""Benchmark de contexto (F5): cuánto pesa una charla larga y cuánto tarda en armarse.

No llama al modelo: mide el armado de la ventana. Sirve para detectar regresiones (por
ejemplo, si alguien vuelve a mandar el historial entero o deja de recortar las tarjetas).
Corre con: python3 -m pytest tests/test_bench_contexto.py -q -s
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "core"))

from service import contexto  # noqa: E402

TOOL = {"nombre": "ejecutar", "args": {"cmd": "ls -la /mnt/datos/biotech"},
        "resultado": "x" * 9000, "ok": True}


def sesion_larga(turnos=120):
    msgs = []
    for i in range(turnos):
        msgs.append({"role": "user", "texto": f"pedido {i} " + "contexto " * 40})
        msgs.append({"role": "assistant", "texto": f"respuesta {i} " + "detalle " * 120,
                     "herramientas": [TOOL, TOOL]})
    return {"id": "bench", "mensajes": msgs, "resumen": "resumen previo " * 200}


def test_bench_ventana():
    s = sesion_larga()
    t0 = time.perf_counter()
    ventana = contexto.turnos_para_llm(s)
    ms = (time.perf_counter() - t0) * 1000
    tokens = contexto.tokens_de(ventana)
    chars = sum(len(str(m.get("content") or "")) for m in ventana)
    print(f"\n120 turnos → {len(ventana)} mensajes, {chars} chars, "
          f"{tokens} tokens estimados, armado en {ms:.1f} ms")
    assert tokens <= contexto.PRESUPUESTO_TOKENS * 1.25, "la ventana no respeta el presupuesto"
    assert ms < 400, f"el armado tardó {ms:.0f} ms"
    # las tarjetas se recortan: 9000 chars de salida no pueden entrar enteros 240 veces
    assert chars < contexto.PRESUPUESTO_TOKENS * contexto.CHARS_POR_TOKEN * 1.3


def test_bench_compactacion_detecta():
    assert contexto.necesita_compactar(sesion_larga())
    assert not contexto.necesita_compactar({"mensajes": [], "resumen": ""})


def test_bench_turno_gigante_se_recorta():
    enorme = {"mensajes": [{"role": "user", "texto": "a" * 500000}], "resumen": ""}
    ventana = contexto.turnos_para_llm(enorme)
    assert "caracteres recortados" in ventana[0]["content"]
    assert len(ventana[0]["content"]) <= contexto.TOPE_TURNO + 120
