"""Tests de la cola persistente (SQLite) del servicio.

Lo que importa: orden FIFO, transiciones de estado válidas, progreso, cancelación
(encolada inmediata / corriendo diferida) y que un reinicio no pierda nada.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from service.queue import STATUSES, Store  # noqa: E402

SPEC = {"run_id": None, "query_path": "/tmp/q.fa", "db_dir": "/tmp/db", "db_name": "toyidx",
        "out_dir": "/tmp/out", "params": {}, "tools": {}, "public": {"mode": "design"}}


@pytest.fixture()
def store(tmp_path):
    st = Store(str(tmp_path / "sifid.sqlite3"))
    yield st
    st.close()


def _mk(store, n=1):
    return [store.create(dict(SPEC), 1) for _ in range(n)]


def test_create_y_get(store):
    run = _mk(store)[0]
    assert run["status"] == "queued"
    assert run["phase"] == "queued"
    assert run["progress"] == {"done": 0, "total": 1, "percent": 0.0}
    assert run["created_at"] and run["started_at"] is None and run["finished_at"] is None
    assert run["results_url"] == f"/runs/{run['run_id']}/results"
    assert store.get("no-existe") is None


def test_orden_fifo_y_claim(store):
    a, b, c = _mk(store, 3)
    claimed = [store.claim_next()["run_id"] for _ in range(3)]
    assert claimed == [a["run_id"], b["run_id"], c["run_id"]]
    assert store.claim_next() is None

    # una corrida reclamada no vuelve a salir
    assert store.get(a["run_id"])["status"] == "running"
    assert store.get(a["run_id"])["started_at"] is not None


def test_estados_y_timestamps(store):
    run = _mk(store)[0]
    rid = run["run_id"]
    store.claim_next()
    store.set_progress(rid, done=1, total=2, phase="running")
    mid = store.get(rid)
    assert mid["progress"]["percent"] == 50.0
    store.finish(rid, "done", exit_code=0, core_run_id="abc123", result_path="/tmp/r.json")
    done = store.get(rid)
    assert done["status"] == "done" and done["phase"] == "done"
    assert done["finished_at"] and done["core_run_id"] == "abc123"
    assert done["exit_code"] == 0
    assert store.counts()["done"] == 1
    assert store.counts()["total"] == 1


def test_finish_rechaza_estado_invalido(store):
    rid = _mk(store)[0]["run_id"]
    with pytest.raises(ValueError):
        store.finish(rid, "running")


def test_cancelar_encolada(store):
    a, b = _mk(store, 2)
    result, row = store.request_cancel(b["run_id"])
    assert result == "cancelled"
    assert row["status"] == "cancelled" and row["cancel_requested"] is True
    assert row["finished_at"]
    # el worker saltea la cancelada y toma la que sigue
    assert store.claim_next()["run_id"] == a["run_id"]
    assert store.claim_next() is None


def test_cancelar_corriendo_es_diferida(store):
    rid = _mk(store)[0]["run_id"]
    store.claim_next()
    result, row = store.request_cancel(rid)
    assert result == "running"
    assert row["status"] == "running" and row["cancel_requested"] is True
    assert row["phase"] == "cancelling"
    # el estado final lo pone el worker (que ya está matando el subproceso)
    store.finish(rid, "cancelled", exit_code=-15, phase="cancelled")
    assert store.get(rid)["status"] == "cancelled"


def test_cancelar_terminada_es_conflicto(store):
    rid = _mk(store)[0]["run_id"]
    store.finish(rid, "done")
    assert store.request_cancel(rid) == ("conflict", store.get(rid))
    missing, row = store.request_cancel("no-existe")
    assert missing == "missing" and row is None


def test_persistencia_entre_instancias(tmp_path):
    path = str(tmp_path / "sifid.sqlite3")
    st = Store(path)
    rid = st.create(dict(SPEC), 3)["run_id"]
    st.claim_next()
    st.set_progress(rid, done=2, phase="running")
    st.close()

    st2 = Store(path)
    try:
        row = st2.get(rid)
        assert row["status"] == "running"
        assert row["progress"] == {"done": 2, "total": 3, "percent": 66.7}
        assert st2.spec(rid)["db_name"] == "toyidx"
    finally:
        st2.close()


def test_recover_interrupted(store):
    rid = _mk(store)[0]["run_id"]
    queued = _mk(store)[0]["run_id"]
    store.claim_next()
    recovered = store.recover_interrupted("interrupted: el servicio se reinició")
    assert [r["run_id"] for r in recovered] == [rid]
    row = store.get(rid)
    assert row["status"] == "error"
    assert row["error"].startswith("interrupted")
    # las encoladas siguen vivas: la cola se retoma al arrancar
    assert store.get(queued)["status"] == "queued"


def test_list_filtra_y_pagina(store):
    a, b, c = _mk(store, 3)
    store.request_cancel(b["run_id"])
    assert [r["run_id"] for r in store.list()] == [c["run_id"], b["run_id"], a["run_id"]]
    assert [r["run_id"] for r in store.list(status="queued")] == [c["run_id"], a["run_id"]]
    assert [r["run_id"] for r in store.list(limit=1, offset=1)] == [b["run_id"]]
    assert set(store.counts()) == set(STATUSES) | {"total"}
