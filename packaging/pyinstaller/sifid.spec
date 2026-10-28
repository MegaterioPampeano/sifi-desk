# -*- mode: python ; coding: utf-8 -*-
"""Sidecar `sifid` + CLI `sifi` — bundle one-dir (siFi-Desk / M8).

Resultado (`dist/sifi-desk-<platform>/`):

    sifid                        API local (FastAPI) + worker
    sifi                         CLI headless (copia del mismo ejecutable)
    _internal/                   Python embebido + numpy/biopython/fastapi/uvicorn
    packaging/vendor/<plat>/     bowtie, bowtie-build, RNAplfold
    licenses/                    siFi (CC BY-NC-SA), bowtie, ViennaRNA

Decisión: **one-dir, nunca one-file**. One-file descomprime en /tmp en cada
arranque (3-5 s de latencia), rompe la ejecución de binarios externos y no deja
inspeccionar el bundle. Un único `Analysis` y un único EXE (los dos entry points
comparten el 99 % de las dependencias); `sifi` es una copia del ejecutable y
`sifid_entry.py` despacha por `argv[0]`.

Uso:
    python3 -m PyInstaller --noconfirm --clean packaging/pyinstaller/sifid.spec
    # standalone (sin servicio):
    python3 -m PyInstaller --noconfirm --clean packaging/pyinstaller/sifi.spec
"""
import os
import shutil
import sys

sys.path.insert(0, SPECPATH)

from _common import BUNDLE_NAME, CORE, PLAT, analysis_kwargs  # noqa: E402

from PyInstaller.utils.hooks import collect_submodules  # noqa: E402

sys.path.insert(0, CORE)

hidden = (
    collect_submodules("sifi")
    + collect_submodules("service")
    + ["cli", "yaml", "pydantic", "pydantic_core", "fastapi", "starlette", "anyio",
       "bio", "Bio", "numpy"]
)

a = Analysis([os.path.join(SPECPATH, "sifid_entry.py")], **analysis_kwargs(hidden))
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="sifid",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=BUNDLE_NAME,
)

# `sifi` = mismo ejecutable con otro nombre (el dispatch es por argv[0]).
# Hardlink cuando el filesystem lo permite: son 13 MB idénticos y en el .deb /
# AppImage (tar + squashfs) se deduplican; si no se puede, copia.
_src = os.path.join(DISTPATH, BUNDLE_NAME, "sifid" + (".exe" if os.name == "nt" else ""))
_dst = os.path.join(DISTPATH, BUNDLE_NAME, "sifi" + (".exe" if os.name == "nt" else ""))
try:
    if os.path.exists(_dst):
        os.unlink(_dst)
    os.link(_src, _dst)
except OSError:
    shutil.copy2(_src, _dst)

print(f"[sifid.spec] bundle: dist/{BUNDLE_NAME}  (binarios: {PLAT})")
