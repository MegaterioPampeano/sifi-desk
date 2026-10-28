"""Caja de arena del agente: dónde puede trabajar y qué no puede tocar.

El agente corre como el usuario del escritorio, sin privilegios extra. Todo lo que
ejecuta pasa por acá:

- Su carpeta es `~/.sifidesk/agente/` (trabajo, descargas, scripts). Cualquier ruta
  relativa se resuelve ahí y las rutas absolutas fuera de esa carpeta se rechazan
  para escritura.
- Lo que **no** puede: tocar el programa instalado (el bundle, el repo, `agent/`),
  usar sudo, ni borrar árboles del sistema. La lista de vetos es explícita y se
  aplica sobre el texto del comando y sobre las rutas que se detectan en él.
- Los comandos tienen tope de tiempo y la salida se recorta: el chat no es una
  terminal, es un registro de lo que hizo.

Esto es una barrera de contención razonable para un asistente de escritorio, no un
sandbox de seguridad fuerte: si el agente necesita más aislamiento, el paso siguiente
es un contenedor o `bwrap`, no más reglas acá.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

RAIZ = os.path.expanduser(os.environ.get("SIFI_AGENT_WORKSPACE", "~/.sifidesk/agente"))
TRABAJO = os.path.join(RAIZ, "trabajo")
DESCARGAS = os.path.join(RAIZ, "descargas")

TIMEOUT_DEFECTO = 180
MAX_SALIDA = 8000

# Rutas del programa instalado: se pueden leer, nunca modificar.
_PROTEGIDAS = [
    "/opt/sifi-desk",
    "/mnt/datos/proyectos/sifi-desk",
    os.path.expanduser("~/.openclaw"),
    "/usr/lib", "/usr/bin", "/etc", "/boot", "/var/lib", "/home",
]

_NEGADOS = [
    r"\bsudo\b", r"\bsu\s+-", r"\bpkexec\b", r"\bpasswd\b", r"\bchown\b", r"\bchattr\b",
    r"\bdd\s+if=", r"\bmkfs", r"\bshutdown\b", r"\breboot\b", r"\bpoweroff\b",
    r"\bapt(-get)?\s+(remove|purge|install|upgrade)\b", r"\bdpkg\s+-[rP]",
    r"\bsystemctl\s+(stop|disable|mask|restart)\b",
    r"rm\s+(-[a-zA-Z]*\s+)*-?[rf]{1,2}[a-zA-Z]*\s+(/|~|\$HOME|/\*)\s*$",
    r">\s*/dev/(sd|nvme)", r"\bnc\s+-l", r"\bcurl[^|]*\|\s*(ba)?sh",
]


class Denegado(Exception):
    """El pedido no pasa la política: se le devuelve el motivo al agente."""


def _dentro(ruta: str, base: str) -> bool:
    ruta = os.path.realpath(ruta)
    base = os.path.realpath(base)
    return ruta == base or ruta.startswith(base + os.sep)


def asegurar() -> None:
    for d in (RAIZ, TRABAJO, DESCARGAS):
        os.makedirs(d, exist_ok=True)


def resolver(ruta: str, para_escritura: bool = False) -> str:
    """Convierte una ruta del agente en absoluta y verifica que sea suya."""
    asegurar()
    if not ruta:
        return TRABAJO
    ruta = os.path.expanduser(ruta)
    absoluta = ruta if os.path.isabs(ruta) else os.path.join(TRABAJO, ruta)
    absoluta = os.path.normpath(absoluta)
    if para_escritura and not _dentro(absoluta, RAIZ):
        raise Denegado(f"no puedo escribir fuera de tu carpeta ({RAIZ}); "
                       f"para eso está el botón de la interfaz")
    return absoluta


def _revisar(cmd: str) -> None:
    bajo = cmd.lower()
    for patron in _NEGADOS:
        if re.search(patron, bajo):
            raise Denegado("ese comando está bloqueado por política "
                           "(privilegios, instalación del sistema o borrado masivo)")
    # escrituras a rutas protegidas: "> /opt/...", "tee /opt/...", "cp x /opt/..."
    for prot in _PROTEGIDAS:
        if prot in cmd and re.search(r"(>|>>|\btee\b|\bcp\b|\bmv\b|\brm\b|\bsed\s+-i\b|"
                                     r"\bpython3?\b.*open\()", cmd):
            raise Denegado(f"no puedo modificar {prot}: es parte del programa o del sistema. "
                           "Si hace falta un cambio ahí, lo hace Mariano o se pide por código.")


def _entorno() -> Dict[str, str]:
    base = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": RAIZ,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "SIFI_AGENT_WORKSPACE": RAIZ,
    }
    for k in ("SIFI_BOWTIE", "SIFI_RNAPLFOLD", "SIFI_PANELS_ROOT", "PYTHONPATH",
              "DISPLAY", "XDG_RUNTIME_DIR"):
        if os.environ.get(k):
            base[k] = os.environ[k]
    return base


def _recortar(texto: str, limite: int = MAX_SALIDA) -> str:
    if len(texto) <= limite:
        return texto
    mitad = limite // 2
    return texto[:mitad] + f"\n… ({len(texto) - limite} caracteres recortados) …\n" + texto[-mitad:]


def correr(cmd: str, timeout: int = TIMEOUT_DEFECTO) -> Dict[str, Any]:
    """Ejecuta un comando de shell dentro de la carpeta del agente."""
    asegurar()
    _revisar(cmd)
    t0 = time.time()
    try:
        proc = subprocess.run(["/bin/bash", "-lc", cmd], cwd=TRABAJO, env=_entorno(),
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "salida": f"corté el comando a los {timeout}s",
                "ms": int((time.time() - t0) * 1000), "rc": None}
    salida = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr.strip() else "")
    return {"ok": proc.returncode == 0, "rc": proc.returncode,
            "salida": _recortar(salida.strip() or "(sin salida)"),
            "ms": int((time.time() - t0) * 1000)}


def python(codigo: str, timeout: int = TIMEOUT_DEFECTO) -> Dict[str, Any]:
    """Corre un script suelto en la carpeta de trabajo."""
    asegurar()
    destino = os.path.join(TRABAJO, f".agent_{int(time.time() * 1000)}.py")
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(codigo)
    try:
        return correr(f"{sys.executable} {os.path.basename(destino)}", timeout=timeout)
    finally:
        try:
            os.unlink(destino)
        except OSError:
            pass


def descargar(url: str, destino: Optional[str] = None,
              limite_mb: int = 800, timeout: int = 600) -> Dict[str, Any]:
    """Baja un archivo a `descargas/` (o a la ruta pedida dentro de la carpeta)."""
    asegurar()
    if not re.match(r"^https?://", url or ""):
        raise Denegado("sólo descargo por http(s)")
    nombre = destino or os.path.basename(url.split("?")[0]) or "descarga.bin"
    ruta = resolver(nombre if os.path.isabs(nombre) or os.sep in nombre
                    else os.path.join("descargas", nombre), para_escritura=True)
    cmd = (f"curl -L --fail --max-time {timeout} --max-filesize {limite_mb}M "
           f"-o {shlex_quote(ruta)} {shlex_quote(url)}")
    res = correr(cmd, timeout=timeout + 20)
    if res.get("ok") and os.path.exists(ruta):
        res["ruta"] = ruta
        res["bytes"] = os.path.getsize(ruta)
        res["salida"] = f"{res['salida']}\n→ {ruta} ({res['bytes']} bytes)".strip()
    return res


def shlex_quote(texto: str) -> str:
    import shlex
    return shlex.quote(texto)


def leer(ruta: str, lineas: int = 200) -> str:
    absoluta = resolver(ruta)
    if not os.path.isfile(absoluta):
        raise Denegado(f"no existe {absoluta}")
    with open(absoluta, encoding="utf-8", errors="replace") as fh:
        out: List[str] = []
        for i, linea in enumerate(fh):
            if i >= lineas:
                out.append(f"… (cortado a {lineas} líneas)")
                break
            out.append(linea.rstrip("\n"))
    return _recortar("\n".join(out))


def escribir(ruta: str, contenido: str) -> str:
    absoluta = resolver(ruta, para_escritura=True)
    os.makedirs(os.path.dirname(absoluta) or TRABAJO, exist_ok=True)
    with open(absoluta, "w", encoding="utf-8") as fh:
        fh.write(contenido)
    return f"escrito {absoluta} ({len(contenido)} caracteres)"


def inventario() -> Dict[str, Any]:
    asegurar()
    def listar(d: str) -> List[str]:
        try:
            return sorted(os.listdir(d))[:50]
        except OSError:
            return []
    total = 0
    for base, _dirs, files in os.walk(RAIZ):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return {"raiz": RAIZ, "trabajo": listar(TRABAJO), "descargas": listar(DESCARGAS),
            "mb": round(total / 1e6, 1)}
