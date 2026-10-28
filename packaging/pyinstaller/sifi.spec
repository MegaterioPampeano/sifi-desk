# -*- mode: python ; coding: utf-8 -*-
"""CLI `sifi` standalone — bundle one-dir (siFi-Desk / M8).

Para el instalable de escritorio alcanza con `sifid.spec` (ya trae `sifi` como
copia del mismo ejecutable). Este spec existe para distribuir **sólo** el CLI
headless (`dist/sifi-cli/sifi`), por ejemplo para correr en un servidor:

    python3 -m PyInstaller --noconfirm --clean packaging/pyinstaller/sifi.spec

No incluye el servicio ni deps de servidor (fastapi/uvicorn quedan afuera).
"""
import os
import sys

sys.path.insert(0, SPECPATH)

from _common import CORE, PLAT, analysis_kwargs  # noqa: E402

from PyInstaller.utils.hooks import collect_submodules  # noqa: E402

sys.path.insert(0, CORE)

hidden = collect_submodules("sifi") + [
    "cli", "yaml", "pydantic", "pydantic_core", "bio", "Bio", "numpy",
]

kwargs = analysis_kwargs(hidden)
kwargs["excludes"] = kwargs["excludes"] + ["fastapi", "starlette", "uvicorn", "service"]

a = Analysis([os.path.join(SPECPATH, "sifi_entry.py")], **kwargs)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="sifi",
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
    name="sifi-cli",
)

print(f"[sifi.spec] bundle: dist/sifi-cli  (binarios: {PLAT})")
