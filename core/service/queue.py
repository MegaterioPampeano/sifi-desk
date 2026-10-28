"""Cola persistente de corridas en SQLite.

Una corrida es una fila de `runs`: orden de llegada (`n`), estado, timestamps,
progreso, error y el *spec* completo (JSON) que el runner necesita para ejecutarla.
El archivo SQLite es la única fuente de verdad: si el proceso del servicio se cae,
al arrancar de nuevo se reencuentra todo (ver `Worker.recover_interrupted`).

Estados: `queued | running | done | error | cancelled`.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

STATUSES = ("queued", "running", "done", "error", "cancelled")
TERMINAL = ("done", "error", "cancelled")
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    n                INTEGER PRIMARY KEY AUTOINCREMENT,
    id               TEXT    NOT NULL UNIQUE,
    status           TEXT    NOT NULL,
    phase            TEXT    NOT NULL DEFAULT 'queued',
    created_at       TEXT    NOT NULL,
    started_at       TEXT,
    finished_at      TEXT,
    error            TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    records_done     INTEGER NOT NULL DEFAULT 0,
    records_total    INTEGER NOT NULL DEFAULT 0,
    exit_code        INTEGER,
    core_run_id      TEXT,
    result_path      TEXT,
    pid              INTEGER,
    spec_json        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_status_n ON runs (status, n);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return "r-" + uuid.uuid4().hex[:12]


class Store:
    """Acceso a la cola. Thread-safe (una conexión + lock; un solo proceso escribe)."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False,
                                     timeout=30.0, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),))

    # ------------------------------------------------------------------ #
    # introspección
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # pragma: no cover
                pass

    @staticmethod
    def public(row: sqlite3.Row, with_spec: bool = False) -> dict:
        """Fila -> JSON de la API (nunca expone el SQL ni el PID)."""
        spec = json.loads(row["spec_json"])
        total = int(row["records_total"] or 0)
        done = int(row["records_done"] or 0)
        out = {
            "run_id": row["id"],
            "status": row["status"],
            "phase": row["phase"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "progress": {
                "done": done,
                "total": total,
                "percent": round(100.0 * done / total, 1) if total else 0.0,
            },
            "cancel_requested": bool(row["cancel_requested"]),
            "error": row["error"],
            "exit_code": row["exit_code"],
            "core_run_id": row["core_run_id"],
            "results_url": f"/runs/{row['id']}/results",
            "request": spec.get("public", {}),
        }
        if with_spec:
            out["spec"] = spec
        return out

    # ------------------------------------------------------------------ #
    # escritura
    # ------------------------------------------------------------------ #
    def create(self, spec: dict, records_total: int,
               run_id: Optional[str] = None) -> dict:
        run_id = run_id or new_run_id()
        spec = dict(spec)
        spec["run_id"] = run_id
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (id, status, phase, created_at, records_total, spec_json)"
                " VALUES (?, 'queued', 'queued', ?, ?, ?)",
                (run_id, utcnow(), int(records_total), json.dumps(spec, ensure_ascii=False)))
        return self.get(run_id)  # type: ignore[return-value]

    def claim_next(self) -> Optional[dict]:
        """Toma la corrida más vieja en `queued` y la pasa a `running` (atómico)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM runs WHERE status='queued' ORDER BY n LIMIT 1").fetchone()
            if row is None:
                return None
            changed = self._conn.execute(
                "UPDATE runs SET status='running', started_at=?, phase='starting'"
                " WHERE id=? AND status='queued'", (utcnow(), row["id"])).rowcount
            if not changed:  # carrera con un cancel: se descarta el claim
                return None
        return self.get(row["id"])

    def set_pid(self, run_id: str, pid: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE runs SET pid=? WHERE id=?", (int(pid), run_id))

    def set_progress(self, run_id: str, done: Optional[int] = None,
                     total: Optional[int] = None, phase: Optional[str] = None) -> None:
        sets, args = [], []
        if done is not None:
            sets.append("records_done=?")
            args.append(max(0, int(done)))
        if total is not None:
            sets.append("records_total=?")
            args.append(max(0, int(total)))
        if phase is not None:
            sets.append("phase=?")
            args.append(str(phase))
        if not sets:
            return
        args.append(run_id)
        with self._lock:
            self._conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", args)

    def finish(self, run_id: str, status: str, *, error: Optional[str] = None,
               exit_code: Optional[int] = None, core_run_id: Optional[str] = None,
               result_path: Optional[str] = None, phase: Optional[str] = None) -> None:
        if status not in TERMINAL:
            raise ValueError(f"estado final inválido: {status!r}")
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET status=?, phase=?, finished_at=?, error=?, exit_code=?,"
                " core_run_id=?, result_path=? WHERE id=?",
                (status, phase or status, utcnow(), error, exit_code, core_run_id,
                 result_path, run_id))

    def request_cancel(self, run_id: str) -> tuple[str, Optional[dict]]:
        """Devuelve ('cancelled'|'running'|'conflict'|'missing', fila)."""
        with self._lock:
            row = self.get(run_id)
            if row is None:
                return "missing", None
            if row["status"] == "queued":
                changed = self._conn.execute(
                    "UPDATE runs SET status='cancelled', cancel_requested=1, phase='cancelled',"
                    " finished_at=? WHERE id=? AND status='queued'",
                    (utcnow(), run_id)).rowcount
                if changed:
                    return "cancelled", self.get(run_id)
                # el worker se la llevó justo ahora: se reintenta como 'running'
                row = self.get(run_id)
            if row["status"] == "running":
                self._conn.execute(
                    "UPDATE runs SET cancel_requested=1, phase='cancelling' WHERE id=?",
                    (run_id,))
                return "running", self.get(run_id)
            return "conflict", row

    def recover_interrupted(self, reason: str) -> List[dict]:
        """Marca `error` las corridas que quedaron `running` de un proceso anterior."""
        out: List[dict] = []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs WHERE status='running' ORDER BY n").fetchall()
            for row in rows:
                self.finish(row["id"], "error", error=reason, phase="interrupted")
                out.append(self.get(row["id"]))
        return out

    # ------------------------------------------------------------------ #
    # lectura
    # ------------------------------------------------------------------ #
    def get(self, run_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return None if row is None else self.public(row)

    def raw(self, run_id: str) -> Optional[sqlite3.Row]:
        """Fila cruda (la usa el worker: necesita spec, pid y cancel_requested)."""
        with self._lock:
            return self._conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()

    def spec(self, run_id: str) -> Optional[dict]:
        row = self.raw(run_id)
        return None if row is None else json.loads(row["spec_json"])

    def list(self, status: Optional[str] = None, limit: int = 50,
             offset: int = 0) -> List[dict]:
        sql = "SELECT * FROM runs"
        args: list = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY n DESC LIMIT ? OFFSET ?"
        args += [max(1, min(int(limit), 500)), max(0, int(offset))]
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self.public(r) for r in rows]

    def counts(self) -> Dict[str, int]:
        out = {s: 0 for s in STATUSES}
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM runs GROUP BY status").fetchall()
        for row in rows:
            out[row["status"]] = int(row["n"])
        out["total"] = sum(v for k, v in out.items() if k in STATUSES)
        return out
