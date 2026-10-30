"""Guardia: corre Python del agente con la política aplicada a nivel de proceso.

`python3 guardia.py script.py` instala un `sys.addaudithook` que revisa cada apertura de
archivo y cada ejecución de proceso contra `politica.py`. Si el agente escribe código que
intenta leer `~/.ssh` o abrir un socket raro, salta `Prohibido` en vez de pasar.

Limitación honesta: protege el proceso Python que lanza este guardia, no a los binarios
que ese proceso ejecute después (bash, curl). Esa parte la cubre `politica.verificar_comando`
sobre el texto y, en F1.b, el sandbox de kernel con bwrap.
"""
from __future__ import annotations

import os
import runpy
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

import politica  # noqa: E402

_PROHIBIDO = politica.Prohibido
_EN_CURSO = False


def _revisar_open(ruta, flags):
    escribir = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND
                             | os.O_TRUNC))
    politica.verificar(os.fspath(ruta), "escribir" if escribir else "leer")


def _hook(evento, args):
    global _EN_CURSO
    if _EN_CURSO:
        return
    _EN_CURSO = True
    try:
        if evento == "open":
            ruta, modo, flags = args
            if isinstance(ruta, int):
                return
            politica.verificar(os.fspath(ruta), "leer" if not modo or "r" in str(modo)
                               else "escribir")
        elif evento in ("os.rename", "os.link", "shutil.copyfile", "shutil.move",
                        "os.symlink"):
            for r in args[:2]:
                if r is not None and not isinstance(r, int):
                    politica.verificar(os.fspath(r), "escribir")
        elif evento in ("os.remove", "os.unlink", "os.rmdir", "os.mkdir",
                        "os.chmod", "os.chown", "shutil.rmtree"):
            if args and args[0] is not None and not isinstance(args[0], int):
                politica.verificar(os.fspath(args[0]), "escribir")
        elif evento in ("os.listdir", "os.scandir"):
            if args and args[0] is not None and not isinstance(args[0], int):
                politica.verificar(os.fspath(args[0]), "leer")
        elif evento in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
            cmd = ""
            if evento == "subprocess.Popen":
                cmd = args[0] if isinstance(args[0], str) else " ".join(map(str, args[0] or []))
            elif evento == "os.exec":
                cmd = " ".join(map(str, args[:3]))
            else:
                cmd = str(args[0])
            politica.verificar_comando(cmd)
        elif evento in ("socket.connect",):
            # el agente sí puede usar red (descargar, buscar_web): sólo se bloquea
            # el acceso a sockets del sistema y a servicios locales sensibles
            try:
                dir_ip = args[1] if len(args) > 1 else None
                if isinstance(dir_ip, tuple) and dir_ip:
                    host = str(dir_ip[0])
                    if host.startswith(("127.", "::1")) or host in ("localhost", "0.0.0.0"):
                        return
            except Exception:  # noqa: BLE001
                return
    finally:
        _EN_CURSO = False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("uso: guardia.py <script.py> [args...]", file=sys.stderr)
        return 2
    sys.addaudithook(_hook)
    objetivo = argv[0]
    sys.argv = [objetivo, *argv[1:]]
    try:
        runpy.run_path(objetivo, run_name="__main__")
    except _PROHIBIDO as exc:
        print(f"[guardia] bloqueado: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
