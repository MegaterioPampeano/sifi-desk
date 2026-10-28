"""Utilidades compartidas por los .spec de PyInstaller (siFi-Desk / M8).

Los `.spec` son scripts Python que PyInstaller ejecuta con `exec()`; importan este
módulo para no repetir rutas, listas de datos ocultos y deps problemáticas.

Qué entra en el bundle one-dir:

* `core/sifi/**`    → módulos (PYZ) + `score.yaml` como dato.
* `core/service/**` → módulos (PYZ). El worker lanza el runner como subproceso
  usando el mismo ejecutable (`sifid --runner`), ver `sifid_entry.py`.
* `packaging/vendor/<sys.platform>-<machine>/` → binarios externos, copiados tal
  cual al bundle en la MISMA ruta relativa. `core/sifi/tools.py` calcula
  `ROOT = dirname(dirname(dirname(__file__)))`; congelado, `sifi/tools.py` vive en
  `<bundle>/_internal/sifi/tools.py`, así que ROOT = `<bundle>` y la ruta que
  busca primero es `<bundle>/packaging/vendor/<plat>/`. Por eso el destino es
  `packaging/vendor/<plat>` y no `bin/`.
* Licencias (siFi CC BY-NC-SA, bowtie Artistic-2.0, ViennaRNA) en `licenses/`.
"""
from __future__ import annotations

import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # .../packaging/pyinstaller
REPO = os.path.dirname(os.path.dirname(HERE))              # raíz del repo
CORE = os.path.join(REPO, "core")
PLAT = f"{sys.platform}-{platform.machine()}"
VENDOR_REL = os.path.join("packaging", "vendor", PLAT)
BUNDLE_NAME = "sifi-desk-" + ("windows" if os.name == "nt" else "linux")


def vendor_dir(required: bool = True) -> str:
    """Directorio de binarios de esta plataforma (`packaging/vendor/<plat>/`)."""
    d = os.path.join(REPO, "packaging", "vendor", PLAT)
    if required and not os.path.isdir(d):
        raise SystemExit(
            f"falta {os.path.relpath(d, REPO)}: corré antes\n"
            f"    bash scripts/fetch_binaries.sh\n"
            f"(o definí SIFI_VENDOR_OPTIONAL=1 para compilar sin binarios)"
        )
    return d


def optional_vendor() -> bool:
    return os.environ.get("SIFI_VENDOR_OPTIONAL", "") not in ("", "0", "false")


def vendor_datas() -> list[tuple[str, str]]:
    """(src, dest) de cada archivo de `packaging/vendor/<plat>/` → mismo path relativo."""
    d = vendor_dir(required=not optional_vendor())
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        src = os.path.join(d, name)
        if os.path.isfile(src):
            out.append((src, VENDOR_REL))
    return out


def core_datas() -> list[tuple[str, str]]:
    """Datos que `core/` lee del disco en runtime (no son módulos).

    `sifi/scoring.py` resuelve `DEFAULT_YAML` como
    `os.path.join(os.path.dirname(__file__), "score.yaml")`; congelado eso es
    `<bundle>/_internal/sifi/score.yaml`, así que el destino es `sifi/`.
    """
    out = []
    for rel in ("sifi/score.yaml",):
        src = os.path.join(CORE, rel)
        if os.path.isfile(src):
            out.append((src, os.path.dirname(rel)))
        else:  # sin score.yaml el pipeline no arranca: mejor fallar en el build
            raise SystemExit(f"falta core/{rel}: el bundle quedaría inservible")
    return out


def license_datas() -> list[tuple[str, str]]:
    """Licencias que el instalador tiene que redistribuir."""
    out = []
    for name in ("LICENSE-siFi.md", "VENDOR.md"):
        src = os.path.join(REPO, name)
        if os.path.isfile(src):
            out.append((src, "licenses"))
    vend = os.path.join(REPO, "packaging", "vendor", PLAT)
    for name in ("LICENSE-bowtie.txt", "LICENSE-ViennaRNA.txt"):
        src = os.path.join(vend, name)
        if os.path.isfile(src):
            out.append((src, "licenses"))
    return out


# Dependencias que se importan de forma dinámica (no las ve el análisis estático).
HIDDEN_UVICORN = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# Nada de GUI ni de tooling de tests dentro del bundle.
EXCLUDES = [
    "tkinter", "_tkinter", "matplotlib", "IPython", "pytest", "pytest_asyncio",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "notebook", "jupyter", "sqlite3_cli",
]


def analysis_kwargs(extra_hidden: list[str] | None = None) -> dict:
    """kwargs comunes de `Analysis(...)` para los dos sidecars."""
    hidden = list(HIDDEN_UVICORN)
    if extra_hidden:
        hidden += list(extra_hidden)
    return {
        "pathex": [CORE],
        "datas": core_datas() + vendor_datas() + license_datas(),
        "hiddenimports": hidden,
        "excludes": EXCLUDES,
        "noarchive": False,
        "optimize": 0,
    }
