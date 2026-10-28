"""Tests de la API HTTP (sin worker): validación, estados, 404/409, paneles."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_service_helpers as H  # noqa: E402

sys.path.insert(0, H.CORE)

from service.app import create_app  # noqa: E402

pytestmark = pytest.mark.skipif(not H.HAVE_TOOLS, reason="faltan binarios (bowtie/RNAplfold)")


@pytest.fixture(scope="module")
def toy_db():
    return H.make_toy_db()


@pytest.fixture()
def panels_root(tmp_path):
    return str(tmp_path / "panels")


@pytest.fixture()
def client(tmp_path, toy_db, panels_root):
    app = create_app(data_dir=str(tmp_path / "data"), panels_root=panels_root,
                     start_worker=False)
    with TestClient(app) as c:   # el lifespan inicializa/cierra el store
        yield c


def _payload(toy_db, **kw):
    db_dir, db_name = toy_db
    base = {"mode": "design", "query_path": H.QUERY_FA, "db_dir": db_dir, "db_name": db_name}
    base.update(kw)
    return base


def test_health_sin_worker(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["service"] == "sifid"
    assert body["worker"]["enabled"] is False
    assert body["queue"]["queued"] == 0


def test_paneles_vacio(client, panels_root):
    body = client.get("/panels").json()
    assert body["count"] == 0 and body["panels"] == []
    assert body["panels_root"] == os.path.abspath(panels_root)


def test_paneles_lista_panel_ingerido(client, panels_root):
    from sifi.panels import PanelSpec, PanelsRegistry

    reg = PanelsRegistry(root=panels_root, bowtie_build=H.TOOLS["bowtie-build"])
    reg.ingest(PanelSpec("toy", nombre="Panel de juguete", rol="no_blanco",
                         version="v1"), H.TOY_FA)
    body = client.get("/panels").json()
    assert body["count"] == 1
    p = body["panels"][0]
    assert p["id"] == "toy" and p["version"] == "v1"
    assert p["index_ok"] is True and p["n_seqs"] == 2 and len(p["fingerprint"]) == 16


def test_post_run_encola(client, toy_db):
    r = client.post("/runs", json=_payload(toy_db))
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "queued"
    assert run["request"]["query"]["name"] == "GeneA"
    assert run["request"]["query"]["records"] == 1
    assert run["progress"] == {"done": 0, "total": 1, "percent": 0.0}

    detail = client.get(f"/runs/{run['run_id']}").json()
    assert detail["run_id"] == run["run_id"]
    listed = client.get("/runs").json()
    assert listed["count"] == 1 and listed["runs"][0]["run_id"] == run["run_id"]


def test_post_run_con_panel(client, panels_root):
    from sifi.panels import PanelSpec, PanelsRegistry

    reg = PanelsRegistry(root=panels_root, bowtie_build=H.TOOLS["bowtie-build"])
    spec = reg.ingest(PanelSpec("toy", version="v1"), H.TOY_FA)

    r = client.post("/runs", json={"mode": "offtarget", "query_fasta": H.query_text(),
                                   "panel_id": "toy"})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["request"]["database"]["panel_id"] == "toy"
    assert run["request"]["database"]["fingerprint"] == spec.fingerprint
    assert run["request"]["panels"][0]["id"] == "toy"
    # modo off-target: mismos defaults que la CLI (sin end/accessibility)
    assert run["request"]["params"]["end_check"] is False
    assert run["request"]["params"]["accessibility_check"] is False


def test_post_run_valida_entrada(client, toy_db):
    assert client.post("/runs", json=_payload(toy_db, query_path=None)).status_code == 400
    assert client.post("/runs", json=_payload(toy_db, query_fasta=">a\nACGT\n")).status_code == 400
    assert client.post("/runs", json=_payload(toy_db, query_path="/no/existe.fa")).status_code == 400
    assert client.post("/runs", json=_payload(toy_db, query_fasta="sin header\nACGT\n")).status_code == 400


def test_post_run_valida_base(client, toy_db, tmp_path):
    db_dir, db_name = toy_db
    assert client.post("/runs", json=_payload(toy_db, db_dir=None)).status_code == 400
    assert client.post("/runs", json=_payload(toy_db, db_name="no-existe")).status_code == 400
    assert client.post("/runs", json=_payload(toy_db, panel_id="fantasma")).status_code == 400
    # panel_id y db_dir juntos: ambiguo
    assert client.post("/runs", json=_payload(toy_db, panel_id="toy")).status_code == 400


def test_post_run_valida_parametros(client, toy_db):
    assert client.post("/runs", json=_payload(toy_db, mismatches=7)).status_code == 422
    assert client.post("/runs", json=_payload(toy_db, sirna_size=2)).status_code == 422
    assert client.post("/runs", json=_payload(toy_db, mode="raro")).status_code == 422
    assert client.post("/runs", json=_payload(
        toy_db, main_target_mode="explicit", main_targets=[])).status_code == 400
    # campo desconocido: se rechaza (extra=forbid) en vez de ignorarse en silencio
    assert client.post("/runs", json=_payload(toy_db, typo=1)).status_code == 422


def test_run_inexistente(client):
    assert client.get("/runs/nope").status_code == 404
    assert client.post("/runs/nope/cancel").status_code == 404
    assert client.get("/runs/nope/results").status_code == 404


def test_results_solo_cuando_termino(client, toy_db):
    run = client.post("/runs", json=_payload(toy_db)).json()
    r = client.get(f"/runs/{run['run_id']}/results")
    assert r.status_code == 409
    assert "queued" in r.json()["detail"]


def test_cancelar_encolada_y_conflicto(client, toy_db):
    run = client.post("/runs", json=_payload(toy_db)).json()
    r = client.post(f"/runs/{run['run_id']}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled" and r.json()["cancel_requested"] is True
    assert client.get(f"/runs/{run['run_id']}").json()["status"] == "cancelled"
    # segunda cancelación: ya terminó
    assert client.post(f"/runs/{run['run_id']}/cancel").status_code == 409


def test_list_filtra_por_estado(client, toy_db):
    a = client.post("/runs", json=_payload(toy_db)).json()
    b = client.post("/runs", json=_payload(toy_db)).json()
    client.post(f"/runs/{b['run_id']}/cancel")
    assert [x["run_id"] for x in client.get("/runs?status=queued").json()["runs"]] == [a["run_id"]]
    assert client.get("/runs?status=zzz").status_code == 400
    assert client.get("/runs?limit=0").status_code == 422


def test_auth_token_obligatorio(tmp_path):
    app = create_app(data_dir=str(tmp_path / "d"), panels_root=str(tmp_path / "p"),
                     start_worker=False, token="s3creto", require_auth=True)
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/panels").status_code == 401
        r = c.get("/panels", headers={"x-sifi-token": "otro"})
        assert r.status_code == 401
        ok = c.get("/panels", headers={"x-sifi-token": "s3creto"})
        assert ok.status_code == 200
        # preflight CORS no lleva token y no puede romper el navegador
        assert c.options("/panels", headers={"Origin": "http://127.0.0.1:8000",
                                             "Access-Control-Request-Method": "GET"}
                         ).status_code in (200, 204)
        # la UI estática es pública para poder cargar la página; la API no
        assert c.get("/openapi.json").status_code == 401


def test_news_nunca_500(tmp_path):
    app = create_app(data_dir=str(tmp_path / "d"), panels_root=str(tmp_path / "p"),
                     start_worker=False, token="t", require_auth=True,
                     news_config=str(tmp_path / "no-existe.yaml"))
    with TestClient(app) as c:
        r = c.get("/news?since=7d&offline=1", headers={"x-sifi-token": "t"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["counts"]["new"] == 0
        assert d["warnings"]
        assert d["service"]["ok"] is True
