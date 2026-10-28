"""Descubrimiento de los binarios externos (bowtie, RNAplfold).

Orden de búsqueda:
  1. flags de la CLI
  2. variables de entorno SIFI_BOWTIE / SIFI_RNAPLFOLD
  3. packaging/vendor/<sys>-<machine>/  (layout del instalable)
  4. build/  (layout de desarrollo)
  5. PATH
"""
from __future__ import annotations

import os
import platform
import shutil
import sys

from .params import ToolPaths

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raíz del repo


def _candidates(name: str):
    exe = name + (".exe" if os.name == "nt" else "")
    plat = f"{sys.platform}-{platform.machine()}"
    yield os.path.join(ROOT, "packaging", "vendor", plat, exe)
    yield os.path.join(ROOT, "build", "bowtie-1.3.1-linux-x86_64", exe)
    yield os.path.join(ROOT, "build", "vienna", "bin", exe)
    found = shutil.which(name)
    if found:
        yield found


def find_tool(name: str) -> str | None:
    env = os.environ.get("SIFI_" + name.upper())
    if env and os.path.exists(env):
        return env
    for cand in _candidates(name):
        if os.path.exists(cand):
            return cand
    return None


def discover(bowtie: str | None = None, rnaplfold: str | None = None,
             bowtie_build: str | None = None) -> ToolPaths:
    b = bowtie or find_tool("bowtie")
    r = rnaplfold or find_tool("RNAplfold")
    bb = bowtie_build or find_tool("bowtie-build")
    missing = [n for n, v in (("bowtie", b), ("RNAplfold", r)) if not v]
    if missing:
        raise FileNotFoundError(
            "No encuentro: " + ", ".join(missing) +
            ". Pasá las rutas con --bowtie/--rnaplfold o definí SIFI_BOWTIE / SIFI_RNAPLFOLD."
        )
    return ToolPaths(bowtie=b, rnaplfold=r, bowtie_build=bb)
