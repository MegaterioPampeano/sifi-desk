"""Política de acceso del agente: deny-by-default.

Antes el agente tenía una lista de vetos ("no toques ~/.ssh, no uses sudo") y todo lo
demás estaba permitido: podía leer `~/.openclaw`, `~/.config`, el home entero. Eso es
una barrera de contención, no un permiso.

Ahora es al revés: el agente ve **sólo** lo que está en estas raíces y el resto no
existe para él. Cualquier ruta fuera de la lista se rechaza antes de ejecutarse, en los
tres caminos (shell, python y herramientas de archivo).

Raíces:
  - RW  ~/.sifidesk/agente            su carpeta (trabajo, descargas, scripts, memoria)
  - RO  /mnt/datos/proyectos/sifi-desk  el programa (leer código, no modificarlo)
  - RO  /mnt/datos/biotech            datos del laboratorio (TSA, anotación, shortlists)
  - RO  /mnt/datos/sifidesk           corridas y paneles del servicio
  - RO  site-packages de usuario      biopython, matplotlib, etc.
  - RO  binarios y librerías del sistema

Todo lo demás (el resto de $HOME, ~/.ssh, ~/.openclaw, ~/.config, /etc sensible, /root,
/var, /media, otros usuarios) queda denegado, incluso para lectura.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, List, Tuple

RAIZ = os.path.realpath(os.path.expanduser(
    os.environ.get("SIFI_AGENT_WORKSPACE", "~/.sifidesk/agente")))
PROGRAMA = os.path.realpath(os.environ.get(
    "SIFI_PROGRAMA_ROOT", "/mnt/datos/proyectos/sifi-desk"))
DATOS = [os.path.realpath(p) for p in (
    os.environ.get("SIFI_DATOS_ROOT", "/mnt/datos/biotech"),
    os.environ.get("SIFI_PANELES_ROOT", "/mnt/datos/sifidesk"),
)]

_SITE = os.path.realpath(os.path.expanduser(
    "~/.local/lib/python%d.%d/site-packages" % __import__("sys").version_info[:2]))

#: se puede leer y escribir
RW: Tuple[str, ...] = (RAIZ,)

#: sólo lectura
RO: Tuple[str, ...] = tuple(dict.fromkeys(
    [PROGRAMA, *DATOS, _SITE,
     "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/opt",
     "/etc/ssl", "/etc/ca-certificates", "/etc/alternatives", "/etc/ld.so.cache",
     "/etc/localtime", "/etc/timezone", "/etc/resolv.conf", "/etc/hosts",
     "/etc/nsswitch.conf", "/etc/passwd", "/etc/group", "/etc/fonts",
     "/etc/mime.types", "/etc/python3", "/etc/bash.bashrc",
     "/dev/null", "/dev/zero", "/dev/full", "/dev/random", "/dev/urandom",
     "/dev/stdin", "/dev/stdout", "/dev/stderr", "/dev/tty",
     "/proc/cpuinfo", "/proc/meminfo", "/proc/version", "/proc/uptime",
     "/proc/loadavg", "/proc/self/status", "/proc/self/stat",
     "/sys/devices/system/cpu", "/sys/fs/cgroup/memory.stat"]))

#: temporales propios del agente (única ventana fuera de su carpeta, y es suya)
TMP_RW: Tuple[str, ...] = (os.path.realpath(os.environ.get("SIFI_AGENT_TMP", "/tmp/sifi_agent")),)

#: nunca, ni para leer
DENEGADO: Tuple[str, ...] = (
    os.path.expanduser("~/.ssh"), os.path.expanduser("~/.gnupg"),
    os.path.expanduser("~/.openclaw"), os.path.expanduser("~/.config"),
    os.path.expanduser("~/.local/share/keyrings"), os.path.expanduser("~/.aws"),
    os.path.expanduser("~/.password-store"), "/root", "/boot", "/etc/shadow",
    "/etc/sudoers", "/etc/sudoers.d", "/etc/gshadow", "/etc/ssh",
    "/var/lib", "/var/log", "/media", "/run/user", "/home",
)

_CMD_VETADO = [
    r"\bsudo\b", r"\bsu\s+-", r"\bpkexec\b", r"\bpasswd\b", r"\bchown\b",
    r"\bchattr\b", r"\bdd\s+if=", r"\bmkfs", r"\bshutdown\b", r"\breboot\b",
    r"\bpoweroff\b", r"\bapt(-get)?\s+(remove|purge|install|upgrade)\b",
    r"\bdpkg\s+-[rP]", r"\bsystemctl\b", r"\bcrontab\b", r"\bmodprobe\b",
    r"\bmount\b", r"\bumount\b", r"\biptables\b", r"\bnft\b",
    r"\bnc\s+-l", r"\bcurl[^|]*\|\s*(ba)?sh", r"\bwget[^|]*\|\s*(ba)?sh",
    r"\bkill\s+-9\s+1\b", r"\bnsenter\b", r"\bunshare\b", r"\bsetcap\b",
]

# rutas que aparecen en el texto de un comando
_RUTA = re.compile(r"""(?:^|[\s'"=(<>|;&])(~?/[^\s'";|&)<>]*|\.{1,2}/[^\s'";|&)<>]*)""")
_ESCRITURA = re.compile(
    r"(>>?\s*\S|\btee\b|\bcp\b|\bmv\b|\brm\b|\bmkdir\b|\btouch\b|\bln\b|"
    r"\bchmod\b|\bsed\s+-i\b|\btruncate\b|\bdd\b|\binstall\b)")


class Prohibido(Exception):
    """La ruta o el comando quedan fuera de la política."""


def _real(ruta: str) -> str:
    """realpath sin exigir que exista (resuelve symlinks del tramo existente)."""
    ruta = os.path.expanduser(ruta or "")
    if not ruta:
        return RAIZ
    if not os.path.isabs(ruta):
        ruta = os.path.join(RAIZ, ruta)
    ruta = os.path.normpath(ruta)
    # resolver symlinks del prefijo que exista, para que un link no sea un atajo
    partes, actual = [], ruta
    while actual and actual != "/" and not os.path.exists(actual):
        partes.append(os.path.basename(actual))
        actual = os.path.dirname(actual)
    real = os.path.realpath(actual)
    return os.path.join(real, *reversed(partes)) if partes else real


def _dentro(ruta: str, base: str) -> bool:
    return ruta == base or ruta.startswith(base.rstrip("/") + "/")


def absoluta(ruta: str, base: str = "") -> str:
    """Normaliza una ruta del agente (relativa a su carpeta o a `base`)."""
    ruta = os.path.expanduser(ruta or "")
    if not os.path.isabs(ruta):
        ruta = os.path.join(base or RAIZ, ruta)
    return _real(ruta)


def verificar(ruta: str, modo: str = "leer", base: str = "") -> str:
    """Valida una ruta contra la política y la devuelve normalizada.

    modo: 'leer' | 'escribir' | 'existe'
    """
    real = absoluta(ruta, base)
    if modo not in ("leer", "escribir", "existe"):
        raise ValueError(f"modo inválido: {modo}")

    if modo != "escribir" and real == "/":
        return real  # listar la raíz está bien: adentro de la jaula son cuatro carpetas

    for d in DENEGADO:
        if _dentro(real, _real(d)):
            raise Prohibido(
                f"{ruta} está fuera de lo que puedo ver: la política del agente sólo "
                f"permite su carpeta ({RAIZ}) y los datos del laboratorio")

    if modo == "escribir":
        if any(_dentro(real, b) for b in RW):
            return real
        if any(_dentro(real, _real(t)) for t in TMP_RW):
            return real
        raise Prohibido(
            f"no puedo escribir en {ruta}: sólo escribo dentro de {RAIZ} "
            f"(y en /tmp para archivos temporales)")

    if any(_dentro(real, b) for b in (*RW, *RO, *TMP_RW)):
        return real
    raise Prohibido(
        f"{ruta} no está en mi espacio de trabajo: sólo veo {RAIZ}, el programa "
        f"(/mnt/datos/proyectos/sifi-desk) y los datos del laboratorio")


def rutas_del_comando(cmd: str) -> List[str]:
    return [m.group(1) for m in _RUTA.finditer(cmd or "")]


def verificar_comando(cmd: str) -> None:
    """Revisa el texto de un comando de shell antes de ejecutarlo.

    Es la barrera de la política (la barrera fuerte es bwrap, fase F1.b). No pretende
    ser perfecta contra un atacante; sí evita que el agente, por error o por invención,
    toque cosas que no debe.
    """
    bajo = (cmd or "").lower()
    for patron in _CMD_VETADO:
        if re.search(patron, bajo):
            raise Prohibido(
                "ese comando está bloqueado: toca privilegios, el sistema o la red "
                "del host, y no forma parte de mi trabajo")

    escribe = bool(_ESCRITURA.search(re.sub(r"'[^']*'|\"[^\"]*\"", "''", cmd or "")))
    for mencionada in rutas_del_comando(cmd):
        modo = "escribir" if escribe else "leer"
        if escribe and re.search(r"(^|\s)(cat|ls|head|tail|grep|wc|file|stat|du|less|more)\b",
                                 bajo):
            modo = "leer"
        verificar(mencionada, modo)


def resumen() -> dict:
    """Para la UI / documentación: qué ve el agente."""
    return {"rw": list(RW), "ro": list(RO), "tmp": list(TMP_RW),
            "denegado": list(DENEGADO)}


if __name__ == "__main__":  # pragma: no cover - utilidad de diagnóstico
    import json
    print(json.dumps(resumen(), indent=1, ensure_ascii=False))
