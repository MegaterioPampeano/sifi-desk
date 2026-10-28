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
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    for extra in (os.path.join(repo, "core"),
                  os.path.join(repo, "packaging", "agent")):   # agent_doctor
        if extra not in sys.path:
            sys.path.insert(0, extra)


def main(argv=None) -> int:
    _bootstrap_path()
    argv = list(sys.argv[1:] if argv is None else argv)
    from cli import main as cli_main
    if argv[:1] != ["doctor"]:
        return cli_main(argv)
    rc = cli_main(argv)
    try:
        from agent_doctor import default_root, report as agent_report
        meipass = getattr(sys, "_MEIPASS", None)
        bundle = os.path.dirname(meipass) if meipass else None
        arc = agent_report(bundle or default_root())
    except Exception as exc:  # el agente nunca rompe doctor
        print(f"· agente: no se pudo verificar ({exc.__class__.__name__}: {exc})")
        arc = 0
    return rc or arc


if __name__ == "__main__":
    sys.exit(main())
