"""Herramientas de F3: trabajos en segundo plano, plan y unificación de corridas."""
import os
import sys
import time

import pytest

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
sys.path.insert(0, CORE)

from service import agent, charlas, sandbox  # noqa: E402


def test_lanzar_y_leer_log():
    r = sandbox.lanzar("echo uno; sleep 0.3; echo dos", nombre="test-f3")
    assert r["ok"] and r["id"].startswith("test-f3-")
    assert os.path.exists(r["log"])
    logs = ""
    for _ in range(20):
        time.sleep(0.25)
        salida = sandbox.proceso("log", r["id"], 20)
        logs = salida["salida"]
        if "dos" in logs:
            break
    assert "uno" in logs and "dos" in logs
    estado = sandbox.proceso("estado", r["id"])
    assert '"estado"' in estado["salida"]
    listado = sandbox.proceso("listar")
    assert r["id"] in listado["salida"]


def test_proceso_inexistente():
    assert sandbox.proceso("estado", "no-existe-123")["ok"] is False


def test_lanzar_respeta_la_politica():
    with pytest.raises(sandbox.Denegado):
        sandbox.lanzar("cat ~/.ssh/id_rsa")


def test_plan_se_guarda_en_la_sesion(tmp_path):
    data_dir = str(tmp_path)
    s = charlas.crear(data_dir)
    pasos = [{"texto": "uno", "estado": "hecho"}, {"texto": "dos", "estado": "pendiente"}]
    assert charlas.guardar_plan(data_dir, s["id"], pasos, "nota")
    plan = charlas.obtener(data_dir, s["id"])["plan"]
    assert plan["pasos"][0]["texto"] == "uno" and plan["nota"] == "nota"


def test_corrida_unifica_las_seis_tools():
    nombres = [t["function"]["name"] for t in agent.TOOLS]
    assert "corrida" in nombres
    for viejo in ("listar_paneles", "correr_corrida", "resultados_corrida", "informe",
                  "ver_error_corrida", "estado_corrida"):
        assert viejo not in nombres, f"{viejo} debería estar dentro de corrida"
    assert set(agent._ACCIONES_CORRIDA) == {"paneles", "lanzar", "estado", "resultados",
                                            "error", "informe"}


def test_tools_sin_duplicados_y_con_schema():
    nombres = [t["function"]["name"] for t in agent.TOOLS]
    assert len(nombres) == len(set(nombres))
    for t in agent.TOOLS:
        f = t["function"]
        assert f.get("description"), f"falta descripción en {f['name']}"
        assert f.get("parameters", {}).get("type") == "object"


def test_ejecutar_en_fondo_true_pasa_por_lanzar():
    r = sandbox.lanzar("echo fondo-ok")
    time.sleep(0.6)
    assert "fondo-ok" in sandbox.proceso("log", r["id"], 10)["salida"]
