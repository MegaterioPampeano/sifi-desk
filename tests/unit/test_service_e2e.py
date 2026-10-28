"""Tests end-to-end del servicio: worker real, subproceso real, cancelación real.

Usan el índice de juguete (tests/data/toy.fa -> toyidx) y tests/data/query.fa.
No mockean el pipeline: lo que se prueba es que el servicio encola, arranca un
subproceso, reporta progreso, guarda el manifest y mata el grupo de procesos al cancelar.
"""
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_service_helpers as H  # noqa: E402

sys.path.insert(0, H.CORE)

from service.app import create_app  # noqa: E402

pytestmark = pytest.mark.skipif(not H.HAVE_TOOLS, reason="faltan binarios (bowtie/RNAplfold)")

FAKE_RUNNER = '''\
import json, os, subprocess, sys, time

spec = json.load(open(sys.argv[sys.argv.index("--spec") + 1]))
print(json.dumps({"event": "progress", "phase": "running", "done": 0, "total": 1}), flush=True)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
run_dir = os.path.dirname(spec["out_dir"])
with open(os.path.join(run_dir, "grandchild.pid"), "w") as fh:
    fh.write(str(child.pid))
time.sleep(300)
'''


@pytest.fixture(scope="module")
def toy_db():
    return H.make_toy_db()


@pytest.fixture()
def make_client(tmp_path, toy_db):
    def _make(runner_argv=None):
        app = create_app(data_dir=str(tmp_path / "data"),
                         panels_root=str(tmp_path / "panels"),
                         runner_argv=runner_argv)
        return app
    return _make


def _payload(toy_db, **kw):
    db_dir, db_name = toy_db
    base = {"mode": "design", "query_path": H.QUERY_FA, "db_dir": db_dir, "db_name": db_name}
    base.update(kw)
    return base


def test_corrida_completa(make_client, toy_db):
    app = make_client()
    with TestClient(app) as c:
        run = c.post("/runs", json=_payload(toy_db)).json()
        rid = run["run_id"]

        done = H.wait_for(c, rid, {"done", "error"})
        assert done["status"] == "done", done
        assert done["progress"]["done"] == done["progress"]["total"] == 1
        assert done["progress"]["percent"] == 100.0
        assert done["started_at"] and done["finished_at"] and done["exit_code"] == 0
        assert done["core_run_id"] and len(done["core_run_id"]) == 16

        r = c.get(f"/runs/{rid}/results")
        assert r.status_code == 200
        manifest = r.json()
        assert manifest["schema"] == "sifi.results/1"
        assert manifest["run_id"] == done["core_run_id"]
        assert manifest["params"]["mode"] == "design"
        assert manifest["extra"]["service"]["run_id"] == rid
        rec = manifest["records"][0]
        assert rec["query_name"] == "GeneA" and rec["error"] is None
        assert rec["summary"]["n_sirnas"] > 0

        # artefactos en disco dentro del run_dir (el servicio es dueño del layout)
        result_path = os.path.join(app.state.data_dir, "runs", rid, "out", "results.json")
        assert os.path.isfile(result_path)
        assert os.path.isfile(os.path.join(app.state.data_dir, "runs", rid, "out", "sirnas.tsv"))
        assert os.path.isfile(os.path.join(app.state.data_dir, "runs", rid, "spec.json"))

        health = c.get("/health").json()
        assert health["queue"]["done"] == 1 and health["queue"]["running"] == 0
        assert health["worker"]["current_run"] is None


def test_dos_corridas_en_orden(make_client, toy_db):
    app = make_client()
    with TestClient(app) as c:
        a = c.post("/runs", json=_payload(toy_db)).json()
        b = c.post("/runs", json=_payload(toy_db, mode="offtarget")).json()
        da = H.wait_for(c, a["run_id"], {"done", "error"})
        db = H.wait_for(c, b["run_id"], {"done", "error"})
        assert da["status"] == "done" and db["status"] == "done"
        assert da["run_id"] != db["run_id"]
        # la segunda arrancó después de que terminó la primera (worker único)
        assert db["started_at"] >= da["finished_at"]

        ra = c.get(f"/runs/{a['run_id']}/results").json()
        rb = c.get(f"/runs/{b['run_id']}/results").json()
        assert ra["params"]["mode"] == "design" and rb["params"]["mode"] == "offtarget"
        assert ra["run_id"] != rb["run_id"]


def test_cancelar_corriendo_mata_el_arbol(make_client, tmp_path, toy_db):
    fake = tmp_path / "fake_runner.py"
    fake.write_text(FAKE_RUNNER, encoding="utf-8")

    app = make_client(runner_argv=[sys.executable, str(fake)])
    with TestClient(app) as c:
        run = c.post("/runs", json=_payload(toy_db)).json()
        rid = run["run_id"]

        running = H.wait_for(c, rid, "running", timeout=20)
        assert running["phase"] in ("starting", "running")
        pid_file = os.path.join(app.state.data_dir, "runs", rid, "grandchild.pid")
        grandchild = int(H.wait_file(pid_file))
        assert H.pid_alive(grandchild)

        r = c.post(f"/runs/{rid}/cancel")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "running" and r.json()["cancel_requested"] is True

        cancelled = H.wait_for(c, rid, {"cancelled", "error", "done"}, timeout=20)
        assert cancelled["status"] == "cancelled", cancelled
        assert cancelled["finished_at"] is not None
        assert cancelled["results_url"].endswith("/results")
        # el manifest no existe: cancelar no inventa resultados
        assert c.get(f"/runs/{rid}/results").status_code == 409

        # el nieto (sleep) murió con el grupo: no quedan huérfanos
        deadline = time.monotonic() + 10
        while H.pid_alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not H.pid_alive(grandchild), "quedó huérfano el subproceso nieto"

        # y el servicio sigue sano: puede correr otra cosa
        health = c.get("/health").json()
        assert health["worker"]["current_run"] is None
        assert health["queue"]["cancelled"] == 1
