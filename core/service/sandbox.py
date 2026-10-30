"""Caja de arena del agente: dónde puede trabajar y qué puede ver.

Desde v2 la política vive en `politica.py` y es **deny-by-default**: el agente sólo
accede a su carpeta (`~/.sifidesk/agente`, lectura y escritura), al programa
(`/mnt/datos/proyectos/sifi-desk`, sólo lectura), a los datos del laboratorio
(`/mnt/datos/biotech`, `/mnt/datos/sifidesk`, sólo lectura), a su tmp
(`/tmp/sifi_agent`) y a binarios/librerías del sistema. Todo el resto de la máquina
—el resto de `$HOME`, `~/.ssh`, `~/.openclaw`, `~/.config`, `/etc` sensible, `/root`,
`/var`— no existe para él, ni para leer.

Los tres caminos pasan por la misma política:

- shell (`correr`): se valida el texto del comando y cada ruta que menciona;
- python (`python`): el script corre bajo `guardia.py`, con un `sys.addaudithook`
  que corta cualquier `open`, `listdir` o `subprocess` fuera de las raíces;
- archivos (`leer`, `escribir`, `listar_archivos`): validación directa de la ruta.

Y además, desde F1.b, los comandos corren dentro de una jaula de kernel (`jaula.py`,
bubblewrap): namespace de montaje con un rootfs mínimo donde sólo están las raíces
permitidas. Ahí `ls /home/mariano` no da "permiso denegado": el home no está montado.
La política sigue actuando primero, para dar errores claros; la jaula es la barrera
real. Si bwrap no está disponible (`SIFI_BWRAP=0`, host sin userns), la app sigue
funcionando con la política sola y `correr()` devuelve `jaula: false`.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import signal
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from . import jaula, politica

# RAIZ se toma ya resuelta (realpath) porque ~/.sifidesk es un symlink a /mnt/datos:
# la jaula monta rutas reales y un chdir a la ruta con symlink no existiría adentro.
RAIZ = politica.RAIZ
TRABAJO = os.path.join(RAIZ, "trabajo")
DESCARGAS = os.path.join(RAIZ, "descargas")

# Datos del laboratorio: sólo lectura, para que el agente pueda citar lo que ya
# calculamos (TSA de Dalbulus maidis, anotación contra Drosophila, shortlists).
DATOS = [os.environ.get("SIFI_DATOS_ROOT", "/mnt/datos/biotech")]

TIMEOUT_DEFECTO = 180
MAX_SALIDA = 8000

# Credenciales y estado privado: ni se leen. (El programa y los datos del
# laboratorio sí se leen; lo que no se puede es escribir fuera de su carpeta,
# y de eso se encarga `_revisar` mirando las rutas reales del comando.)
_SECRETOS = [
    os.path.expanduser("~/.openclaw"),
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/.aws"),
    os.path.expanduser("~/.sifidesk/agent.env"),
    os.path.expanduser("~/.sifidesk/token"),
    os.path.expanduser("~/.sifidesk/sifid"),
    "/etc/shadow", "/etc/sudoers",
]

# Operadores que escriben. Se buscan sobre el comando sin comillas: así
# `grep -c '>' archivo` (un `>` citado) no se confunde con una redirección.
_ESCRITURA = re.compile(
    r"(>>?\s*\S|\btee\b|\bcp\b|\bmv\b|\brm\b|\bmkdir\b|\btouch\b|\bln\b|"
    r"\bchmod\b|\bsed\s+-i\b|\btruncate\b)")
# Python puede escribir sin pasar por el shell: se detecta el patrón.
_PY_ESCRITURA = re.compile(
    r"open\s*\([^)]*['\"][wax+]|os\.(remove|unlink|rename|replace|rmdir)|"
    r"shutil\.(rmtree|move|copy)|write_text|write_bytes|\.unlink\s*\(")
_RUTA = re.compile(r"""(?:^|[\s'"=(])(~?/[^\s'";|&)]*|\./[^\s'";|&)]*)""")

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


class Pendiente(Denegado):
    """Escritura fuera de la carpeta del agente: se puede aprobar desde la app."""

    def __init__(self, mensaje: str, cmd: str = "", motivo: str = ""):
        super().__init__(mensaje)
        self.cmd = cmd
        self.motivo = motivo or mensaje


def _dentro(ruta: str, base: str) -> bool:
    ruta = os.path.realpath(ruta)
    base = os.path.realpath(base)
    return ruta == base or ruta.startswith(base + os.sep)


def asegurar() -> None:
    for d in (RAIZ, TRABAJO, DESCARGAS, *politica.TMP_RW):
        os.makedirs(d, exist_ok=True)


def resolver(ruta: str, para_escritura: bool = False) -> str:
    """Convierte una ruta del agente en absoluta y la valida contra la política."""
    asegurar()
    try:
        return politica.verificar(ruta, "escribir" if para_escritura else "leer",
                                  base=TRABAJO)
    except politica.Prohibido as exc:
        raise Denegado(str(exc)) from None


def _sin_comillas(cmd: str) -> str:
    """Saca los tramos entrecomillados, para no leer un `>` citado como redirección."""
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", cmd)


def _rutas_mencionadas(cmd: str) -> List[str]:
    """Rutas absolutas o `./` que aparecen en el comando (aunque estén entre comillas)."""
    return [m.group(1) for m in _RUTA.finditer(cmd)]


def _absoluta(ruta: str) -> str:
    ruta = os.path.expanduser(ruta)
    if not os.path.isabs(ruta):
        ruta = os.path.join(TRABAJO, ruta)
    return os.path.realpath(ruta)


_SEPARADORES = re.compile(r"[;\n]|&&|\|\||\|")
_COMANDOS_DESTINO_FINAL = {"cp", "rsync", "mv", "install"}
_COMANDOS_SOBRE_ARCHIVOS = {"rm", "mkdir", "rmdir", "touch", "chmod", "ln",
                            "truncate", "tee", "unlink"}


def _tokens(segmento: str) -> List[str]:
    """Tokens del segmento conservando las comillas.

    Con `posix=False` un `'>'` citado llega como "'>'" y no se confunde con una
    redirección (era el falso positivo del `grep -c '>' archivo`).
    """
    try:
        return shlex.split(segmento, posix=False)
    except ValueError:
        return segmento.split()


def _limpio(tok: str) -> str:
    return tok.strip("'\"")


def _es_operador(tok: str) -> bool:
    return not tok[:1] in "'\"" and bool(re.fullmatch(r"\d?>>?&?|\d?>\|", tok))


def _objetivos_de_escritura(cmd: str) -> List[str]:
    """Rutas que el comando va a escribir, no todas las que menciona.

    Antes se miraba el comando entero: `ls -ld /home/mariano` en la misma línea
    que un `>` disparaba el pedido de permiso sin que nadie fuera a escribir ahí.
    """
    objetivos: List[str] = []
    for segmento in _SEPARADORES.split(cmd):
        if not segmento.strip():
            continue
        toks = _tokens(segmento)
        if not toks:
            continue
        # redirecciones: `> ruta`, `>> ruta`, `>ruta`, `2> ruta`
        for i, tok in enumerate(toks):
            if _es_operador(tok):
                if i + 1 < len(toks):
                    objetivos.append(_limpio(toks[i + 1]))
                continue
            pegado = re.fullmatch(r"\d?>>?(\S+)", tok)
            if pegado and not _es_operador(tok):
                objetivos.append(_limpio(pegado.group(1)))
        # el comando en sí (salteando `VAR=x` y `sudo`)
        palabras = [_limpio(t) for t in toks if not _es_operador(t)]
        palabras = [t for t in palabras if "=" not in t.split("/")[0]]
        if not palabras:
            continue
        base = os.path.basename(palabras[0])
        args = [t for t in palabras[1:] if not t.startswith("-")]
        if base in _COMANDOS_DESTINO_FINAL and args:
            objetivos.append(args[-1])
        elif base in _COMANDOS_SOBRE_ARCHIVOS:
            objetivos.extend(args)
        elif base == "sed" and any(t.startswith("-i") for t in palabras[1:]):
            objetivos.extend(args)
    if _PY_ESCRITURA.search(cmd):
        objetivos.extend(_rutas_mencionadas(cmd))
    return objetivos


def _revisar(cmd: str) -> None:
    """Política deny-by-default: el comando no puede salir de las raíces permitidas."""
    try:
        politica.verificar_comando(cmd)
    except politica.Prohibido as exc:
        raise Denegado(str(exc)) from None


def _site_usuario() -> str:
    """site-packages de usuario (+ el PYTHONPATH heredado, si hay)."""
    usuario = os.path.expanduser("~/.local/lib/python%d.%d/site-packages"
                                 % sys.version_info[:2])
    partes = [usuario] if os.path.isdir(usuario) else []
    if os.environ.get("PYTHONPATH"):
        partes.append(os.environ["PYTHONPATH"])
    return ":".join(partes)


def _entorno() -> Dict[str, str]:
    base = {
        # HOME apunta a la carpeta del agente, y eso deja afuera el site-packages de
        # usuario (~/.local/...): biopython y matplotlib viven ahí. Se agrega al path
        # de Python para que `python3` y el CLI `sifi` importen lo mismo que el servicio.
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": RAIZ,
        "PYTHONPATH": _site_usuario(),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "SIFI_AGENT_WORKSPACE": RAIZ,
        "TMPDIR": politica.TMP_RW[0],
        "XDG_CACHE_HOME": os.path.join(politica.TMP_RW[0], "cache"),
        "MPLCONFIGDIR": os.path.join(politica.TMP_RW[0], "mpl"),
        "XDG_CONFIG_HOME": os.path.join(RAIZ, ".config"),
    }
    for k in ("SIFI_BOWTIE", "SIFI_RNAPLFOLD", "SIFI_PANELS_ROOT",
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
    """Ejecuta un comando de shell dentro de la carpeta del agente.

    Pasa por la política (rutas permitidas) y por la jaula de kernel (esas rutas son
    las únicas que existen dentro del comando).
    """
    asegurar()
    _revisar(cmd)
    return _ejecutar(cmd, timeout)


def correr_aprobado(cmd: str, timeout: int = TIMEOUT_DEFECTO) -> Dict[str, Any]:
    """Igual que `correr`, pero salteando el chequeo de rutas.

    Lo llama sólo `aprobaciones.resolver` cuando Mariano apretó "aprobar". Los vetos
    duros y la jaula de kernel se siguen aplicando: aprobar no abre la máquina.
    """
    asegurar()
    bajo = cmd.lower()
    for patron in _NEGADOS:
        if re.search(patron, bajo):
            raise Denegado("ese comando está vetado por política y no se aprueba desde la app")
    return _ejecutar(cmd, timeout)


def _ejecutar(cmd: str, timeout: int) -> Dict[str, Any]:
    entorno = _entorno()
    argv = jaula.envolver(["/bin/bash", "-lc", cmd], TRABAJO, entorno)
    enjaulado = argv[0] != "/bin/bash"
    t0 = time.time()
    try:
        proc = subprocess.run(argv, cwd=None if enjaulado else TRABAJO, env=entorno,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "salida": f"corté el comando a los {timeout}s",
                "ms": int((time.time() - t0) * 1000), "rc": None}
    salida = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr.strip() else "")
    return {"ok": proc.returncode == 0, "rc": proc.returncode,
            "salida": _recortar(salida.strip() or "(sin salida)"),
            "ms": int((time.time() - t0) * 1000), "jaula": enjaulado}


# --------------------------------------------------------------------------- #
# trabajos en segundo plano
# --------------------------------------------------------------------------- #
_PROCESOS = os.path.join(politica.RAIZ, ".procesos.json")
_LOGS = os.path.join(politica.TMP_RW[0], "procesos")


def _leer_procesos() -> Dict[str, Any]:
    try:
        with open(_PROCESOS, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _guardar_procesos(datos: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(_PROCESOS), exist_ok=True)
        with open(_PROCESOS, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _pid_vivo(pid: int) -> bool:
    """Vivo de verdad: si es hijo nuestro y terminó, se cosecha (si no queda zombi)."""
    if not pid:
        return False
    try:
        cosechado, _ = os.waitpid(int(pid), os.WNOHANG)
        if cosechado == int(pid):
            return False
    except ChildProcessError:
        pass
    except (OSError, TypeError, ValueError):
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError):
        return False


def lanzar(cmd: str, nombre: str = "") -> Dict[str, Any]:
    """Arranca un comando y vuelve enseguida: sirve para corridas largas.

    El proceso queda en su propia sesión (sobrevive al request), con stdout y stderr a un
    archivo que después se lee con `proceso(accion='log')`. Pasa por la misma política y
    la misma jaula que `correr`.
    """
    asegurar()
    _revisar(cmd)
    os.makedirs(_LOGS, exist_ok=True)
    ident = (nombre or time.strftime("%H%M%S")) + "-" + secrets.token_hex(3)
    log = os.path.join(_LOGS, ident + ".log")
    argv = jaula.envolver(["/bin/bash", "-lc", cmd], TRABAJO, _entorno())
    with open(log, "wb") as fh:
        fh.write(f"# {time.strftime('%Y-%m-%d %H:%M:%S')} · {cmd}\n".encode())
        fh.flush()
        proc = subprocess.Popen(argv, cwd=None if len(argv) > 2 else TRABAJO,
                                env=_entorno(), stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    datos = _leer_procesos()
    datos[ident] = {"pid": proc.pid, "cmd": cmd, "log": log,
                    "inicio": time.time()}
    _guardar_procesos(datos)
    return {"ok": True, "salida": f"lanzado en segundo plano: id {ident} · pid {proc.pid}\n"
                                  f"log: {log}\n"
                                  f"Consultá con proceso(accion='estado', id='{ident}')",
            "id": ident, "pid": proc.pid, "log": log}


def proceso(accion: str = "listar", ident: str = "", lineas: int = 80) -> Dict[str, Any]:
    datos = _leer_procesos()
    if accion == "listar":
        if not datos:
            return {"ok": True, "salida": "no hay trabajos en segundo plano"}
        filas = []
        for k, v in sorted(datos.items(), key=lambda kv: kv[1].get("inicio") or 0,
                           reverse=True)[:20]:
            vivo = _pid_vivo(v.get("pid"))
            filas.append(f"{k} · {'corriendo' if vivo else 'terminado'} · "
                         f"{time.strftime('%H:%M:%S', time.localtime(v.get('inicio') or 0))} · "
                         f"{v.get('cmd','')[:70]}")
        return {"ok": True, "salida": "\n".join(filas)}

    item = datos.get(ident)
    if not item:
        return {"ok": False, "salida": f"no existe el trabajo {ident}"}

    if accion == "estado":
        vivo = _pid_vivo(item.get("pid"))
        try:
            tam = os.path.getsize(item.get("log"))
        except OSError:
            tam = 0
        return {"ok": True, "salida": json.dumps(
            {"id": ident, "pid": item.get("pid"), "estado": "corriendo" if vivo else "terminado",
             "log": item.get("log"), "log_bytes": tam}, ensure_ascii=False)}

    if accion == "log":
        try:
            with open(item.get("log"), encoding="utf-8", errors="replace") as fh:
                todo = fh.readlines()
        except OSError:
            return {"ok": False, "salida": "no pude leer el log"}
        cola = "".join(todo[-max(1, int(lineas)):])
        vivo = _pid_vivo(item.get("pid"))
        return {"ok": True, "salida": f"[{'corriendo' if vivo else 'terminado'}] "
                                      f"{len(todo)} líneas\n" + _recortar(cola)}

    if accion == "matar":
        pid = item.get("pid")
        if not _pid_vivo(pid):
            return {"ok": True, "salida": f"el trabajo {ident} ya había terminado"}
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            time.sleep(1)
            if _pid_vivo(pid):
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError as exc:
            return {"ok": False, "salida": f"no pude matarlo: {exc}"}
        return {"ok": True, "salida": f"trabajo {ident} (pid {pid}) terminado"}

    return {"ok": False, "salida": f"acción desconocida: {accion}"}


def python(codigo: str, timeout: int = TIMEOUT_DEFECTO) -> Dict[str, Any]:
    """Corre un script suelto en la carpeta de trabajo, con el guardia de política."""
    asegurar()
    destino = os.path.join(TRABAJO, f".agent_{int(time.time() * 1000)}.py")
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(codigo)
    guardia = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guardia.py")
    try:
        return correr(f"{shlex_quote(sys.executable)} {shlex_quote(guardia)} "
                      f"{shlex_quote(os.path.basename(destino))}", timeout=timeout)
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


def leer(ruta: str, lineas: int = 200, desde: int = 1) -> str:
    """Lee un archivo de la carpeta (o de las raíces RO) con números de línea."""
    absoluta = resolver(ruta)
    if not os.path.isfile(absoluta):
        raise Denegado(f"no existe {absoluta}")
    desde = max(1, int(desde or 1))
    with open(absoluta, encoding="utf-8", errors="replace") as fh:
        out: List[str] = []
        total = 0
        for i, linea in enumerate(fh, 1):
            total = i
            if i < desde:
                continue
            if len(out) >= lineas:
                break
            out.append(f"{i:6d}  {linea.rstrip(chr(10))}")
    if not out:
        return f"(el archivo tiene {total} líneas; pediste desde {desde})"
    cola = f"\n… (cortado a {lineas} líneas; el archivo sigue)" if total > desde + len(out) - 1 else ""
    return _recortar("\n".join(out) + cola)


def editar(ruta: str, viejo: str, nuevo: str, todas: bool = False) -> str:
    """Reemplazo exacto de texto en un archivo (como el edit del asistente)."""
    absoluta = resolver(ruta, para_escritura=True)
    if not os.path.isfile(absoluta):
        raise Denegado(f"no existe {absoluta}")
    with open(absoluta, encoding="utf-8") as fh:
        original = fh.read()
    if viejo == "":
        raise Denegado("el texto a reemplazar no puede estar vacío")
    apariciones = original.count(viejo)
    if apariciones == 0:
        raise Denegado("no encontré ese texto exacto en el archivo: revisá espacios, "
                       "tabulaciones y acentos (leé la zona con `leer`)")
    if apariciones > 1 and not todas:
        raise Denegado(f"ese texto aparece {apariciones} veces: pasá más contexto para que "
                       f"sea único, o usá `todas: true`")
    actualizado = original.replace(viejo, nuevo) if todas else original.replace(viejo, nuevo, 1)
    with open(absoluta, "w", encoding="utf-8") as fh:
        fh.write(actualizado)
    return (f"editado {absoluta}: {apariciones if todas else 1} reemplazo(s), "
            f"{len(original)} → {len(actualizado)} caracteres")


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
            return sorted(os.listdir(d))[:8]
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
            "mb": round(total / 1e6, 1), "jaula": jaula.estado()}


# --------------------------------------------------------------------------- #
# datos del laboratorio (sólo lectura)
# --------------------------------------------------------------------------- #
def _datos_root() -> List[str]:
    return [d for d in DATOS if os.path.isdir(d)]


def buscar_gen(termino: str, maximo: int = 40) -> str:
    """Busca un gen/proteína en lo que ya calculamos y devuelve las líneas con evidencia."""
    termino = (termino or "").strip()
    if len(termino) < 2:
        raise Denegado("buscá con al menos dos caracteres")
    patron = re.compile(re.escape(termino), re.I)
    salida: List[str] = []
    for raiz in _datos_root():
        out = os.path.join(raiz, "out")
        if not os.path.isdir(out):
            continue
        nombres = sorted(os.listdir(out), key=lambda n: (not n.endswith((".tsv", ".txt")), n))
        for nombre in nombres:
            if not nombre.endswith((".tsv", ".txt", ".json")):
                continue
            ruta = os.path.join(out, nombre)
            try:
                tam = os.path.getsize(ruta)
                if tam > 40_000_000 or (nombre.endswith(".json") and tam > 2_000_000):
                    continue
                with open(ruta, encoding="utf-8", errors="replace") as fh:
                    for i, linea in enumerate(fh, 1):
                        if len(linea) > 2000:
                            continue
                        if patron.search(linea):
                            salida.append(f"{nombre}:{i}: {linea.strip()[:300]}")
                            if len(salida) >= maximo:
                                break
            except OSError:
                continue
            if len(salida) >= maximo:
                break
    if not salida:
        return (f"sin coincidencias para '{termino}' en {', '.join(_datos_root()) or '(sin datos)'}. "
                "Probá con el nombre de la proteína de Drosophila, el símbolo del gen "
                "(por ejemplo BicC) o el ID del transcrito.")
    return "\n".join(salida)


def transcrito(ident: str, contexto: int = 0) -> str:
    """Devuelve la secuencia de un transcrito del TSA de D. maidis (o un trozo)."""
    if not re.match(r"^[A-Za-z0-9_.\-]+$", ident or ""):
        raise Denegado("ID inválido")
    for raiz in _datos_root():
        for base, _d, files in os.walk(os.path.join(raiz, "data")):
            for f in files:
                if not f.endswith((".fna", ".fa", ".fasta")):
                    continue
                ruta = os.path.join(base, f)
                try:
                    if os.path.getsize(ruta) > 400_000_000:
                        continue
                    with open(ruta, encoding="utf-8", errors="replace") as fh:
                        cabecera, buf = None, []
                        for linea in fh:
                            if linea.startswith(">"):
                                if cabecera and ident in cabecera:
                                    seq = "".join(buf)
                                    if contexto:
                                        return f"{cabecera.strip()}\n{seq[:contexto]}"
                                    return f"{cabecera.strip()}\nlen={len(seq)}\n{seq}"
                                cabecera, buf = linea, []
                            else:
                                buf.append(linea.strip())
                        if cabecera and ident in cabecera:
                            seq = "".join(buf)
                            return f"{cabecera.strip()}\nlen={len(seq)}\n{seq}"
                except OSError:
                    continue
    raise Denegado(f"no encontré el transcrito {ident} en los FASTA de {_datos_root()}")


# --------------------------------------------------------------------------- #
# web
# --------------------------------------------------------------------------- #
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def _http_texto(url: str, timeout: int = 30, limite: int = 2_000_000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept-Language": "es,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        datos = res.read(limite)
    return datos.decode("utf-8", "replace")


def buscar_web(consulta: str, maximo: int = 6) -> str:
    """Búsqueda web simple (DuckDuckGo HTML): títulos, URLs y fragmentos."""
    consulta = (consulta or "").strip()
    if not consulta:
        raise Denegado("falta la consulta")
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(consulta)
    html = _http_texto(url)
    bloques = re.findall(r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?result__snippet"[^>]*>(.*?)</a>',
                         html, re.S)
    if not bloques:
        bloques = [(u, t, "") for u, t in re.findall(
            r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)]
    filas: List[str] = []
    for href, titulo, snip in bloques[:maximo]:
        if "uddg=" in href:
            href = urllib.parse.unquote(re.search(r"uddg=([^&]+)", href).group(1))
        filas.append(f"- {_limpio(titulo)}\n  {href}\n  {_limpio(snip)[:280]}")
    return "\n".join(filas) or "sin resultados"


def abrir_url(url: str, maximo: int = 12000) -> str:
    """Trae una página o un PDF y la devuelve en un markdown mínimo, acotada.

    No es un navegador: alcanza para leer un paper, una ficha de NCBI o una doc. Se tiran
    scripts, estilos, nav y footer, y se conservan títulos, listas, párrafos y links.
    """
    if not re.match(r"^https?://", url or ""):
        raise Denegado("sólo http(s)")
    if re.search(r"\.pdf($|\?)", url, re.I):
        try:
            destino = os.path.join(DESCARGAS, "pdf_" + str(abs(hash(url)) % 10**8) + ".pdf")
            descargar(url, destino, 120)
            return _pdf_texto(destino, maximo)
        except Exception as exc:  # noqa: BLE001
            return f"(no pude leer el PDF: {type(exc).__name__}: {exc})"
    html = _http_texto(url)
    if not re.search(r"(?i)<html|<body|<p|<div", html or ""):
        return _recortar((html or "").strip()[:maximo])

    # si hay <article> o <main>, quedarse con el más largo: menos menú, más contenido
    candidatos = re.findall(r"(?is)<(article|main)[^>]*>(.*?)</\1>", html)
    if candidatos:
        html = max(candidatos, key=lambda c: len(c[1]))[1]
    crudo = re.sub(r"(?is)<(script|style|noscript|svg|iframe|form)[^>]*>.*?</\1>", " ", html)
    crudo = re.sub(r"(?is)<(nav|footer|header|aside)[^>]*>.*?</\1>", " ", crudo)
    crudo = re.sub(r"(?is)<br\s*/?>", "\n", crudo)
    crudo = re.sub(r"(?is)</(p|div|section|article|tr|li|h[1-6]|blockquote)>", "\n", crudo)
    crudo = re.sub(r"(?is)<h([1-3])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", crudo)
    crudo = re.sub(r"(?is)<li[^>]*>", "\n- ", crudo)
    crudo = re.sub(r"(?is)<a\s[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                   lambda m: f"[{_limpio(m.group(2))}]({m.group(1)})", crudo)
    crudo = re.sub(r"(?s)<[^>]+>", " ", crudo)
    crudo = html_unescape(crudo)
    crudo = re.sub(r"[ \t\r\f\v]+", " ", crudo)
    crudo = re.sub(r" *=+ *\n", "\n", crudo)
    lineas = []
    for linea in crudo.splitlines():
        linea = linea.strip()
        if not linea or linea in ("-", "*", "#", "##", "###"):
            continue
        lineas.append(linea)
    crudo = "\n".join(lineas)
    return _recortar(crudo[:maximo])


def _pdf_texto(ruta: str, maximo: int) -> str:
    """Texto de un PDF, si hay herramienta para sacarlo."""
    for cmd in (["pdftotext", "-layout", ruta, "-"], ["python3", "-c",
                "import sys;from pypdf import PdfReader;"
                "print(chr(10).join((p.extract_text() or '') for p in PdfReader(sys.argv[1]).pages))",
                ruta]):
        if not shutil.which(cmd[0]):
            continue
        try:
            salida = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if salida.returncode == 0 and salida.stdout.strip():
                return _recortar(salida.stdout.strip()[:maximo])
        except (OSError, subprocess.SubprocessError):
            continue
    return "(el PDF se descargó pero no pude extraer el texto)"


def _limpio(fragmento: str) -> str:
    return re.sub(r"\s+", " ", html_unescape(re.sub(r"(?s)<[^>]+>", "", fragmento))).strip()


from html import unescape as html_unescape  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402
