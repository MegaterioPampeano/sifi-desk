"""Entry point del CLI `sifi` (PyInstaller, one-dir).

No duplica la CLI: importa `core/cli.py` tal cual. Congelado, el paquete `sifi`
y el módulo `cli` vienen del PYZ (`pathex=core/`), así que no hace falta tocar
`sys.path`; en modo fuente sí, para poder probar el entry sin compilar.
"""
from __future__ import annotations

import os
import sys


def _bootstrap_path() -> None:
    if getattr(sys, "frozen", False):
        return
    core = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "core")
    if core not in sys.path:
        sys.path.insert(0, core)


def main(argv=None) -> int:
    _bootstrap_path()
    from cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
