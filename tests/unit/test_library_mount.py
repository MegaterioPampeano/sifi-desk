"""La biblioteca montada dentro de `sifid`.

Lo que se protege: que el router quede montado (una línea fácil de perder en un merge),
que en edición `stable` conteste 403 con un mensaje legible —nunca un traceback ni 404—
y que en `dev` funcione con la base vacía sin pedir red.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from service.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFI_LIBRARY_DIR", str(tmp_path / "library"))
    app = create_app(data_dir=str(tmp_path / "data"),
                     panels_root=str(tmp_path / "panels"), require_auth=False)
    return TestClient(app)


def test_stable_responde_403_legible(client, monkeypatch):
    monkeypatch.setenv("SIFI_EDITION", "stable")
    r = client.get("/library/stats")
    assert r.status_code == 403
    assert "developer" in r.json()["detail"].lower()


def test_dev_responde_stats_y_busqueda(client, monkeypatch):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    r = client.get("/library/stats")
    assert r.status_code == 200, r.text
    assert r.json()["papers"] == 0

    r = client.get("/library/search", params={"q": "dsrna"})
    assert r.status_code == 200, r.text
    assert r.json()["results"] == []

    # búsqueda vacía: 422 de FastAPI, no 500
    assert client.get("/library/search", params={"q": ""}).status_code in (400, 422)
