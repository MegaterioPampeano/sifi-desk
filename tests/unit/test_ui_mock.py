"""Tests de la maqueta de la UI (`ui/mock/server.py`).

Lo que importa: que el archivo estático se sirva, que el contrato HTTP del
servicio contesté con la forma que consume el frontend y que una corrida se
pueda crear, seguir por polling y leer en resultados. Se levanta un proceso
real en un puerto efímero; sin red externa ni credenciales.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER = os.path.join(ROOT, "ui", "mock", "server.py")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mock():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, SERVER, "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    limite = time.time() + 15
    while time.time() < limite:
        try:
            with urllib.request.urlopen(base + "/health", timeout=1) as res:
                if res.status == 200:
                    break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.1)
    else:  # pragma: no cover - sólo si el servidor no arranca
        proc.kill()
        pytest.fail("la maqueta no arrancó")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as res:
        return res.status, json.loads(res.read().decode("utf-8"))


def _post(base, path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as res:
        return res.status, json.loads(res.read().decode("utf-8"))


def test_paneles_tienen_rol_y_metadatos(mock):
    status, body = _get(mock, "/panels")
    assert status == 200
    paneles = body["panels"]
    assert len(paneles) >= 3
    for p in paneles:
        assert p["id"] and p["nombre"] and p["rol"]
        assert p["n_seqs"] > 0


def test_index_se_sirve_sin_build(mock):
    with urllib.request.urlopen(mock + "/", timeout=5) as res:
        html = res.read().decode("utf-8")
    assert res.status == 200
    assert "siFi Desk" in html
    assert 'id="view-wizard"' in html
    # módulos ES, sin bundler
    assert 'type="module"' in html


def test_corrida_completa_por_polling(mock):
    fasta = ">toy\n" + "ATGCGTACGTTAGCCGATCGATCGGCTAACGTTAGCTAGCTAGCATCGATCGATTACG" * 3
    status, run = _post(mock, "/runs", {
        "query_path": "ensayo.fa",
        "query_text": fasta,
        "panel_ids": ["dalbulus_maidis", "maiz"],
        "mode": "design",
        "mismatches": 2,
    })
    assert status in (200, 201, 202)
    run_id = run["id"]
    assert run_id

    limite = time.time() + 20
    estado = None
    while time.time() < limite:
        _, estado = _get(mock, f"/runs/{run_id}")
        if estado["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.2)
    assert estado is not None and estado["status"] == "done", estado
    assert estado["progress"]["pct"] == 100

    status, resultado = _get(mock, f"/runs/{run_id}/results")
    assert status == 200
    assert resultado["run_id"] == run_id
    assert resultado["records"], "sin registros en el resultado"
    candidato = resultado["records"][0]["candidates"][0]
    for campo in ("total", "desglose"):
        assert campo in candidato


def test_run_inexistente_devuelve_404(mock):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(mock, "/runs/deadbeefdeadbeef")
    assert exc.value.code == 404
