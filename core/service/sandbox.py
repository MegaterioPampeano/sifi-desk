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
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

RAIZ = os.path.expanduser(os.environ.get("SIFI_AGENT_WORKSPACE", "~/.sifidesk/agente"))
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
    bajo = cmd.lower()
    for patron in _NEGADOS:
        if re.search(patron, bajo):
            raise Denegado("ese comando está bloqueado por política "
                           "(privilegios, instalación del sistema o borrado masivo)")

    rutas = _rutas_mencionadas(cmd)
    escribe = bool(_ESCRITURA.search(_sin_comillas(cmd))) or bool(_PY_ESCRITURA.search(cmd))

    for mencionada in rutas:
        real = _absoluta(mencionada)
        for secreto in _SECRETOS:
            if _dentro(real, secreto):
                raise Denegado(f"{mencionada} tiene credenciales o estado privado: no lo toco")

    for objetivo in _objetivos_de_escritura(cmd):
        real = _absoluta(objetivo)
        for secreto in _SECRETOS:
            if _dentro(real, secreto):
                raise Denegado(f"{objetivo} tiene credenciales o estado privado: no lo toco")
        if (real in ("/dev/null", "/dev/stdout", "/dev/stderr")
                or _dentro(real, RAIZ) or _dentro(real, "/tmp")
                or _dentro(real, "/var/tmp")):
            continue
        raise Pendiente(
            f"escribir en {objetivo} está fuera de tu carpeta ({RAIZ}) y necesita "
            f"la aprobación de Mariano", cmd=cmd,
            motivo=f"escritura fuera de la carpeta del agente: {objetivo}")


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


def correr_aprobado(cmd: str, timeout: int = TIMEOUT_DEFECTO) -> Dict[str, Any]:
    """Igual que `correr`, pero salteando el chequeo de rutas.

    Lo llama sólo `aprobaciones.resolver` cuando Mariano apretó "aprobar". Los
    vetos duros (sudo, mkfs, apagado, borrado de la raíz) se siguen aplicando.
    """
    asegurar()
    bajo = cmd.lower()
    for patron in _NEGADOS:
        if re.search(patron, bajo):
            raise Denegado("ese comando está vetado por política y no se aprueba desde la app")
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
            "mb": round(total / 1e6, 1)}


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


def abrir_url(url: str, maximo: int = 6000) -> str:
    """Trae una página y la devuelve como texto plano acotado."""
    if not re.match(r"^https?://", url or ""):
        raise Denegado("sólo http(s)")
    html = _http_texto(url)
    texto = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    texto = re.sub(r"(?s)<[^>]+>", " ", texto)
    texto = html_unescape(texto)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n", texto)
    return _recortar(texto.strip()[:maximo])


def _limpio(fragmento: str) -> str:
    return re.sub(r"\s+", " ", html_unescape(re.sub(r"(?s)<[^>]+>", "", fragmento))).strip()


from html import unescape as html_unescape  # noqa: E402
import urllib.parse  # noqa: E402
