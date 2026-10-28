"""Utilidades compartidas por los tests del servicio (no contiene tests).

Resuelve los binarios externos (bowtie / RNAplfold / bowtie-build) y arma el índice
de juguete (`toyidx`) en un directorio temporal, para no escribir nada en `tests/data`.

Orden de búsqueda de binarios: variables SIFI_* -> PATH -> `build/` del checkout.
En un worktree de git, `build/` vive en el checkout principal: se lo ubica con
`git rev-parse --git-common-dir` (así los tests corren igual desde `w/servicio`).
"""
from __future__ import annotations

import atexit
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(ROOT, "core")
if CORE not in sys.path:
    sys.path.insert(0, CORE)

TOY_FA = os.path.join(ROOT, "tests", "data", "toy.fa")
QUERY_FA = os.path.join(ROOT, "tests", "data", "query.fa")
INDEX_SUFFIXES = (".1.ebwt", ".2.ebwt", ".3.ebwt", ".4.ebwt", ".rev.1.ebwt", ".rev.2.ebwt")


def _repo_roots():
    yield ROOT
    try:
        out = subprocess.run(["git", "-C", ROOT, "rev-parse", "--path-format=absolute",
                              "--git-common-dir"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            parent = os.path.dirname(out.stdout.strip())
            if parent and parent != ROOT:
                yield parent
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return


def _find(name: str):
    env = os.environ.get("SIFI_" + name.upper().replace("-", "_"))
    if env and os.path.exists(env):
        return env
    found = shutil.which(name)
    if found:
        return found
    for root in _repo_roots():
        pats = [os.path.join(root, "build", "bowtie-*", name),
                os.path.join(root, "build", "vienna", "bin", name),
                os.path.join(root, "build", "ViennaRNA-*", "src", "bin", name),
                os.path.join(root, "vendor", "siFi21", "ToCopy", name)]
        for pat in pats:
            for cand in sorted(glob.glob(pat)):
                if os.path.isfile(cand) and os.access(cand, os.X_OK):
                    return cand
    return None


TOOLS = {
    "bowtie": _find("bowtie"),
    "RNAplfold": _find("RNAplfold"),
    "bowtie-build": _find("bowtie-build"),
}
HAVE_TOOLS = all(TOOLS.values())

# El servicio descubre los binarios por entorno; fijarlos acá hace que la API y el
# runner (subproceso) usen los mismos.
if HAVE_TOOLS:
    os.environ.setdefault("SIFI_BOWTIE", TOOLS["bowtie"])
    os.environ.setdefault("SIFI_RNAPLFOLD", TOOLS["RNAplfold"])


def make_toy_db() -> tuple[str, str]:
    """Directorio temporal con el índice bowtie del juguete. -> (db_dir, db_name)."""
    d = tempfile.mkdtemp(prefix="sifid_toydb_")
    atexit.register(shutil.rmtree, d, True)
    name = "toyidx"
    prebuilt = os.path.join(ROOT, "tests", "data", name)
    if os.path.exists(prebuilt + ".1.ebwt"):
        for suf in INDEX_SUFFIXES:
            if os.path.exists(prebuilt + suf):
                shutil.copyfile(prebuilt + suf, os.path.join(d, name + suf))
        return d, name
    if not TOOLS["bowtie-build"]:  # pragma: no cover
        raise RuntimeError("falta bowtie-build para armar el índice de juguete")
    subprocess.run([TOOLS["bowtie-build"], "-q", TOY_FA, os.path.join(d, name)],
                   check=True, capture_output=True, text=True)
    return d, name


def query_text() -> str:
    with open(QUERY_FA, encoding="utf-8") as fh:
        return fh.read()


def wait_for(client, run_id: str, statuses, timeout: float = 90.0) -> dict:
    """Espera (sondeando la API) a que la corrida llegue a alguno de `statuses`."""
    statuses = {statuses} if isinstance(statuses, str) else set(statuses)
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last["status"] in statuses:
            return last
        time.sleep(0.05)
    raise AssertionError(f"timeout esperando {statuses} para {run_id}: último={json.dumps(last)}")


def wait_file(path: str, timeout: float = 20.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return open(path, encoding="utf-8").read().strip()
        time.sleep(0.05)
    raise AssertionError(f"timeout esperando {path}")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover
        return True
    return True
