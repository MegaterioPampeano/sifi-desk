"""Worker único: toma corridas de la cola y las ejecuta en un subproceso.

Por qué un solo worker: siFi escribe temporales y llama binarios externos; correr dos
cosas a la vez no acelera nada y ensucia la reproducibilidad. El worker **no** importa
el core: lanza `python3 -m service.runner` con `start_new_session=True` (grupo de
procesos propio), lee sus eventos JSON de stdout y, si hay que cancelar, mata el grupo
entero (el runner + cualquier binario nieto) para no dejar huérfanos.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from .queue import Store

CORE_DIR = str(Path(__file__).resolve().parents[1])  # .../core  (para PYTHONPATH)
TERM_GRACE = 3.0     # segundos entre SIGTERM y SIGKILL
POLL = 0.1           # intervalo de chequeo de cancelación


def _pgid(pid: int) -> Optional[int]:
    try:
        return os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        return None


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover
        return True


def kill_process_group(pid: int, grace: float = TERM_GRACE,
                       proc: Optional[subprocess.Popen] = None) -> None:
    """SIGTERM al grupo; si no muere en `grace`, SIGKILL. Nunca lanza.

    Si se pasa `proc`, se lo reapea mientras se espera: el líder puede quedar zombie
    y hacer que el grupo parezca vivo hasta el timeout (cancelaría 3 s más lento).
    """
    pgid = _pgid(pid)
    if pgid is None:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if proc is not None:
            proc.poll()
        if not _group_alive(pgid):
            return
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _is_our_runner(pid: int, run_id: str) -> bool:
    """True sólo si ese PID sigue siendo *nuestro* runner (evita matar por PID reciclado)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # existe pero no es nuestro
        return False
    cmd = _cmdline(pid)
    return "service.runner" in cmd and run_id in cmd


class Worker(threading.Thread):
    """Un hilo que ejecuta corridas; el trabajo real vive en el subproceso."""

    def __init__(self, store: Store, data_dir: str,
                 runner_argv: Optional[List[str]] = None):
        super().__init__(name="sifid-worker", daemon=True)
        self.store = store
        self.data_dir = os.path.abspath(data_dir)
        self.runs_dir = os.path.join(self.data_dir, "runs")
        os.makedirs(self.runs_dir, exist_ok=True)
        self.runner_argv = list(runner_argv or [sys.executable, "-m", "service.runner"])
        self._stop_evt = threading.Event()
        self._proc: Optional[subprocess.Popen] = None
        self._current: Optional[str] = None
        self._current_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # ciclo de vida
    # ------------------------------------------------------------------ #
    @property
    def current(self) -> Optional[str]:
        with self._current_lock:
            return self._current

    @property
    def alive(self) -> bool:
        return self.is_alive() and not self._stop_evt.is_set()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_evt.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            kill_process_group(proc.pid, proc=proc)
        if self.is_alive():
            self.join(timeout=timeout)

    def run(self) -> None:  # noqa: D401 - hilo
        while not self._stop_evt.is_set():
            try:
                row = self.store.claim_next()
            except Exception:  # pragma: no cover - la DB no debería fallar
                time.sleep(0.5)
                continue
            if row is None:
                self._stop_evt.wait(0.15)
                continue
            run_id = row["run_id"]
            with self._current_lock:
                self._current = run_id
            try:
                self._execute(run_id)
            except Exception as exc:  # noqa: BLE001 - una corrida rota no puede matar al worker
                self.store.finish(run_id, "error", error=f"worker: {type(exc).__name__}: {exc}",
                                  phase="error")
            finally:
                with self._current_lock:
                    self._current = None
                self._proc = None

    # ------------------------------------------------------------------ #
    # una corrida
    # ------------------------------------------------------------------ #
    def _execute(self, run_id: str) -> None:
        spec = self.store.spec(run_id)
        if spec is None:  # pragma: no cover
            self.store.finish(run_id, "error", error="spec perdido", phase="error")
            return

        run_dir = os.path.join(self.runs_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        spec_path = os.path.join(run_dir, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, indent=2, ensure_ascii=False)

        log_path = os.path.join(run_dir, "stderr.log")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [CORE_DIR] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env["PYTHONUNBUFFERED"] = "1"

        argv = self.runner_argv + ["--spec", spec_path]
        events: dict = {}

        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(argv, cwd=CORE_DIR, env=env, stdout=subprocess.PIPE,
                                    stderr=log, text=True, bufsize=1,
                                    start_new_session=True)
            self._proc = proc
            self.store.set_pid(run_id, proc.pid)

            pump = threading.Thread(target=self._pump, args=(proc, run_id, events),
                                    name=f"sifid-pump-{run_id}", daemon=True)
            pump.start()

            aborted = False
            while proc.poll() is None:
                if (self.store.raw(run_id)["cancel_requested"]
                        or self._stop_evt.is_set()):
                    aborted = True
                    kill_process_group(proc.pid, proc=proc)
                    break
                time.sleep(POLL)

            if aborted:
                try:
                    proc.wait(timeout=TERM_GRACE + 2)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    kill_process_group(proc.pid, grace=0, proc=proc)
                    proc.wait(timeout=5)
            pump.join(timeout=5)

        rc = proc.returncode
        raw = self.store.raw(run_id)
        if aborted and raw["cancel_requested"]:
            self.store.set_progress(run_id, phase="cancelled")
            self.store.finish(run_id, "cancelled", exit_code=rc, phase="cancelled")
            return
        if aborted:
            # el servicio se está apagando: no es una cancelación del usuario
            self.store.finish(run_id, "error", exit_code=rc, phase="interrupted",
                              error="interrupted: el servicio se detuvo durante la corrida")
            return

        if rc == 0 and events.get("manifest_path"):
            self.store.finish(run_id, "done", exit_code=rc,
                              core_run_id=events.get("core_run_id"),
                              result_path=events.get("manifest_path"), phase="done")
            return

        err = events.get("error")
        if not err:
            tail = "\n".join(_tail(log_path, 20)).strip()
            err = f"el runner salió con código {rc}" + (f": {tail}" if tail else "")
        self.store.finish(run_id, "error", error=err[:4000], exit_code=rc, phase="error")

    def _pump(self, proc: subprocess.Popen, run_id: str, events: dict) -> None:
        """Lee eventos JSON del stdout del runner y actualiza progreso/estado."""
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue  # log suelto del runner: va a stderr.log
            kind = ev.get("event")
            if kind == "progress":
                self.store.set_progress(run_id, done=ev.get("done"), total=ev.get("total"),
                                        phase=ev.get("phase"))
            elif kind == "manifest":
                events["manifest_path"] = ev.get("path")
                events["manifest_tsv"] = ev.get("tsv_path")
                events["core_run_id"] = ev.get("run_id")
            elif kind == "error":
                events["error"] = ev.get("message") or "error en el runner"


def _tail(path: str, n: int) -> List[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()[-n:]
    except OSError:
        return []


def recover_interrupted(store: Store) -> List[dict]:
    """Al arrancar: mata runners huérfanos de una vida anterior y marca `error`.

    El runner corre en su propia sesión (`start_new_session`), así que si el servicio
    muere no se lleva a sus hijos: hay que matarlos explícitamente. Se valida el PID
    contra `/proc/<pid>/cmdline` para no matar un proceso cualquiera por reciclado.
    Las `queued` no se tocan: la cola es persistente y se retoma al arrancar.
    """
    recovered: List[dict] = []
    for row in store.list(status="running", limit=500):
        raw = store.raw(row["run_id"])
        pid = raw["pid"] if raw else None
        if pid and _is_our_runner(int(pid), row["run_id"]):
            kill_process_group(int(pid))
        store.finish(row["run_id"], "error", phase="interrupted",
                     error="interrupted: el servicio se reinició durante la corrida")
        recovered.append(store.get(row["run_id"]))
    return recovered
