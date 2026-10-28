"""Entry point de los sidecars `sifid` y `sifi` (PyInstaller, one-dir).

Un solo binario, dos nombres (el bundle copia el ejecutable como `sifid` y como
`sifi`); el dispatch es por `argv[0]`, que es lo que cambia al copiarlo:

* `sifi ...`              → CLI headless (`core/cli.py`, sin duplicar código).
* `sifid ...`             → API local (FastAPI) + worker.
* `sifid --runner ...`    → runner de una corrida (lo lanza el worker).

Dos ajustes necesarios para el binario congelado:

1. el worker lanza el runner como subproceso con `sys.executable`; congelado no
   existe `python3 -m service.runner`, así que se le pasa `[sifid, "--runner"]`
   (abajo) y `create_app` se parchea para inyectarlo en `runner_argv`
   (`core/service` ya expone ese parámetro: no se toca el core).
2. los binarios externos se buscan primero en `SIFI_BOWTIE` / `SIFI_RNAPLFOLD`;
   acá se rellenan con el `packaging/vendor/<plat>/` del bundle si el usuario no
   los fijó (misma ruta que resuelve `core/sifi/tools.py`).
"""
from __future__ import annotations

import os
import platform
import sys


def _bootstrap_path() -> None:
    if getattr(sys, "frozen", False):
        return
    core = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "core")
    if core not in sys.path:
        sys.path.insert(0, core)


def _bundle_root() -> str | None:
    """Raíz del bundle one-dir (la carpeta que contiene `_internal/`)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return os.path.dirname(meipass)
    return None


def _export_vendor_env() -> None:
    """SIFI_BOWTIE / SIFI_RNAPLFOLD → bundle, si no los fijó el usuario."""
    root = _bundle_root()
    if not root:
        return
    exe = ".exe" if os.name == "nt" else ""
    vendor = os.path.join(root, "packaging", "vendor",
                          f"{sys.platform}-{platform.machine()}")
    for tool in ("bowtie", "RNAplfold"):
        path = os.path.join(vendor, tool + exe)
        if os.path.isfile(path):
            os.environ.setdefault("SIFI_" + tool.upper(), path)


def _patch_runner_argv() -> None:
    """`create_app(..., runner_argv=[sys.executable, "--runner"])` cuando está congelado."""
    if not getattr(sys, "frozen", False):
        return
    import service.app as appmod

    original = appmod.create_app

    def create_app(*args, **kwargs):
        kwargs.setdefault("runner_argv", [sys.executable, "--runner"])
        return original(*args, **kwargs)

    appmod.create_app = create_app


def main(argv=None) -> int:
    _bootstrap_path()
    argv = list(sys.argv[1:] if argv is None else argv)

    # `sifi` es una copia del mismo ejecutable: el nombre decide el modo.
    prog = os.path.basename(sys.argv[0] or "")
    if prog.lower() in ("sifi", "sifi.exe"):
        from cli import main as cli_main
        return cli_main(argv)

    if argv[:1] == ["--runner"]:
        from service.runner import main as runner_main
        return runner_main(argv[1:])

    _export_vendor_env()
    _patch_runner_argv()
    from service.app import main as app_main
    return app_main(argv)


if __name__ == "__main__":
    sys.exit(main())
