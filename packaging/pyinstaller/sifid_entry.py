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
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    for extra in (os.path.join(repo, "core"),
                  os.path.join(repo, "packaging", "agent")):   # agent_doctor
        if extra not in sys.path:
            sys.path.insert(0, extra)


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


def _doctor_con_agente(argv: list[str]) -> int:
    """`sifi doctor` + el bloque del agente incluido en el bundle (M10).

    El chequeo del agente vive en `packaging/agent/agent_doctor.py` porque el
    agente (dsh sobre Node) lo aporta el instalable, no el core científico: así
    `core/` no se entera de que existe un harness. Si el desinstalador borró
    `agent/`, se informa `·` y doctor sigue siendo el de siempre.
    """
    from cli import main as cli_main
    rc = cli_main(argv)
    try:
        from agent_doctor import default_root, report as agent_report
        arc = agent_report(_bundle_root() or default_root())
    except Exception as exc:  # nunca romper doctor por el agente
        print(f"· agente: no se pudo verificar ({exc.__class__.__name__}: {exc})")
        arc = 0
    return rc or arc


def main(argv=None) -> int:
    _bootstrap_path()
    argv = list(sys.argv[1:] if argv is None else argv)

    # `sifi` es una copia del mismo ejecutable: el nombre decide el modo.
    prog = os.path.basename(sys.argv[0] or "")
    if prog.lower() in ("sifi", "sifi.exe"):
        if argv[:1] == ["doctor"]:
            return _doctor_con_agente(argv)
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
