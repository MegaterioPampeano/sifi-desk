"""`APIRouter` de la biblioteca probado con una app FastAPI propia.

`core/service` no se toca: acá se monta `library.api.router` en un `FastAPI()` vacío, que
es exactamente lo que hará `core/service/app.py`.
"""
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from library import api, store  # noqa: E402


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    directory = tmp_path / "data"
    monkeypatch.setenv("SIFI_LIBRARY_DIR", str(directory))
    lib = store.Library(data_dir=directory)
    paper = lib.add_paper({"doi": "10.9999/api", "title": "dsRNA delivery in aphids",
                           "year": 2026, "journal": "J API",
                           "authors": "Doe, Jane", "abstract": "RNAi in aphids."})
    lib.set_pdf(paper["id"], "pdfs/api.pdf", "b" * 64, 54321, 7,
                "dsRNA delivery by feeding reduced aphid survival.")
    lib.add_tag(paper["id"], "entrega")
    (lib.pdf_dir / "api.pdf").write_bytes(b"%PDF-1.4\n%fake\n")
    lib.close()
    return directory


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_stable_edition_is_403_with_clear_detail(client, monkeypatch):
    monkeypatch.delenv("SIFI_EDITION", raising=False)
    for method, path in [("get", "/library/search"), ("get", "/library/stats"),
                         ("get", "/library/papers/1"), ("get", "/library/tags")]:
        resp = getattr(client, method)(path)
        assert resp.status_code == 403, path
        assert "edición developer" in resp.json()["detail"]


def test_dev_search_and_paper(client, data_dir, monkeypatch):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    resp = client.get("/library/search", params={"q": "dsrna delivery"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert "[[" in data["results"][0]["snippet"]
    pid = data["results"][0]["id"]

    resp = client.get(f"/library/papers/{pid}")
    assert resp.status_code == 200 and resp.json()["doi"] == "10.9999/api"

    resp = client.get("/library/stats")
    assert resp.status_code == 200 and resp.json()["with_pdf"] == 1

    resp = client.get(f"/library/papers/{pid}/text")
    assert resp.status_code == 200 and "aphid survival" in resp.json()["text"]

    resp = client.get(f"/library/papers/{pid}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


def test_dev_annotations_crud(client, data_dir, monkeypatch):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    resp = client.post("/library/papers/1/annotations",
                       json={"kind": "idea_test", "text": "probar feeding en pulgones",
                             "author": "mariano"})
    assert resp.status_code == 201
    ann = resp.json()
    assert ann["kind"] == "idea_test" and ann["author"] == "mariano"

    resp = client.get("/library/papers/1/annotations")
    assert resp.status_code == 200 and len(resp.json()["annotations"]) == 1

    resp = client.get("/library/papers/1/annotations", params={"kind": "riesgo"})
    assert resp.json()["annotations"] == []

    bad = client.post("/library/papers/1/annotations", json={"kind": "otro", "text": "x"})
    assert bad.status_code == 422

    resp = client.delete(f"/library/annotations/{ann['id']}")
    assert resp.status_code == 200
    assert client.get("/library/papers/1/annotations").json()["annotations"] == []


def test_dev_tags_and_404(client, data_dir, monkeypatch):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    resp = client.post("/library/papers/1/tags", json={"add": ["riesgo"], "remove": []})
    assert resp.status_code == 200 and resp.json()["tags"] == ["entrega", "riesgo"]

    assert client.get("/library/tags").json()["tags"] == [
        {"tag": "entrega", "n": 1}, {"tag": "riesgo", "n": 1}]

    assert client.get("/library/papers/999").status_code == 404
    assert client.get("/library/papers/1/pdf").status_code == 200


def test_dev_post_paper_requires_identifier(client, data_dir, monkeypatch):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    resp = client.post("/library/papers", json={})
    assert resp.status_code == 422
