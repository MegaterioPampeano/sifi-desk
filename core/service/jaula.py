"""Jaula de kernel (bwrap) para los comandos del agente.

La política de `politica.py` decide qué rutas se *nombran*. Esto decide qué rutas
*existen*: el comando corre en un namespace de montaje donde sólo están montadas las
raíces permitidas, así que `ls /home/mariano` no devuelve "permiso denegado", devuelve
que el directorio no existe. Un binario que llame directo a `open()` tampoco llega:
no hay inodo al que llegar.

Se arma un rootfs mínimo:
  /            tmpfs vacío
  /usr /bin /sbin /lib* /opt   solapas de sólo lectura del sistema
  /etc         sólo lectura (shadow sigue sin ser legible: es 640 root:shadow)
  /proc /dev   propios del namespace
  /tmp         tmpfs; el agente además tiene /tmp/sifi_agent persistente
  carpeta del agente   lectura/escritura
  programa + datos     sólo lectura

Si bwrap no está disponible o falla, `disponible()` devuelve False y `sandbox.correr`
sigue con la política sola: nunca se rompe por esto.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Dict, List, Optional

from . import politica

_ESTADO: Dict[str, object] = {"ok": None, "ts": 0.0, "motivo": ""}
_TTL = 120.0

_SISTEMA = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/opt")


def _fijar(ok: bool, motivo: str = "") -> bool:
    _ESTADO.update(ok=ok, ts=time.time(), motivo=motivo)
    if not ok:
        print(f"[jaula] sin bwrap: {motivo}", flush=True)
    return ok


def disponible(forzar: bool = False) -> bool:
    """¿Se puede usar bwrap ahora? Se prueba de verdad y se cachea un rato."""
    if os.environ.get("SIFI_BWRAP") == "0":
        return bool(_ESTADO["ok"]) if forzar else False
    if os.environ.get("SIFI_BWRAP") == "1":
        return True
    if not forzar and _ESTADO["ok"] is not None and time.time() - float(_ESTADO["ts"]) < _TTL:
        return bool(_ESTADO["ok"])
    exe = shutil.which("bwrap")
    if not exe:
        return _fijar(False, "no está instalado")
    try:
        proc = subprocess.run(
            [exe, "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
             "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
             "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev",
             "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent",
             "--chdir", "/tmp", "/bin/sh", "-c", "exit 0"],
            capture_output=True, text=True, timeout=20)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip().splitlines()
            return _fijar(False, err[-1] if err else f"rc={proc.returncode}")
    except Exception as exc:  # noqa: BLE001
        return _fijar(False, f"{type(exc).__name__}: {exc}")
    return _fijar(True)


def _binds(exe: str) -> List[str]:
    args: List[str] = []
    for d in _SISTEMA:
        if os.path.exists(d):
            args += ["--ro-bind", d, d]
    for enlace, destino in (("/usr/bin", "/bin"), ("/usr/sbin", "/sbin"),
                            ("/usr/lib", "/lib"), ("/usr/lib64", "/lib64"),
                            ("/usr/lib32", "/lib32"), ("/usr/libx32", "/libx32")):
        if os.path.islink(enlace) and os.path.exists(destino):
            args += ["--symlink", os.path.basename(enlace), destino]
    if os.path.isdir("/etc"):
        args += ["--ro-bind", "/etc", "/etc"]
    for ruta in ("/run/systemd/resolve", "/run/nscd", "/run/dbus"):
        if os.path.exists(ruta):
            args += ["--ro-bind", ruta, ruta]
    args += ["--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev"]
    # RO primero y RW al final: el último bind gana, y la carpeta del agente tiene que
    # ganarle al RO de /mnt/datos/sifidesk (que la contiene).
    for ruta in politica.RO:
        if ruta in _SISTEMA or ruta.startswith(("/etc", "/proc", "/sys", "/dev")):
            continue
        if os.path.exists(ruta):
            args += ["--ro-bind", ruta, ruta]
    for ruta in (*politica.TMP_RW, *politica.RW):
        os.makedirs(ruta, exist_ok=True)
        args += ["--bind", ruta, ruta]
    return args


def envolver(argv: List[str], cwd: str, entorno: Dict[str, str]) -> List[str]:
    """Devuelve el argv a ejecutar: adentro de la jaula si se puede, si no tal cual."""
    if not disponible():
        return argv
    exe = shutil.which("bwrap") or "bwrap"
    args = [exe, "--unshare-pid", "--unshare-ipc", "--unshare-uts",
            "--die-with-parent", "--new-session", "--clearenv"]
    args += _binds(exe)
    for k, v in entorno.items():
        args += ["--setenv", k, v]
    args += ["--chdir", cwd, *argv]
    return args


def estado() -> Dict[str, object]:
    return {"disponible": bool(_ESTADO["ok"]), "motivo": _ESTADO["motivo"],
            "probado_hace": round(time.time() - float(_ESTADO["ts"]), 1) if _ESTADO["ts"] else None}
