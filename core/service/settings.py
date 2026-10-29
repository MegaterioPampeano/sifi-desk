"""Ajustes locales del servicio: clave del LLM y modelo.

La clave vive en `~/.sifidesk/agent.env` (0600, fuera del bundle y fuera del repo),
con el mismo formato que usa el lanzador del agente, así el CLI y la interfaz leen
de un solo lugar. Nunca se devuelve completa por HTTP: sólo el largo y los últimos
cuatro caracteres, lo justo para reconocerla.

Precedencia: variable de entorno (`SIFI_LLM_API_KEY` / `DEEPSEEK_API_KEY`) gana
sobre el archivo, para no romper instalaciones que ya venían configuradas así.
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
from typing import Any, Dict, Optional

ENV_PATH = os.environ.get("SIFI_AGENT_ENV",
                          os.path.expanduser("~/.sifidesk/agent.env"))

# DeepSeek y compatibles (openrouter, together, vLLM local) usan el mismo dialecto.
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
VAR_CLAVE = "SIFI_LLM_API_KEY"
VAR_ALTERNATIVA = "DEEPSEEK_API_KEY"
VAR_MODELO = "SIFI_LLM_MODEL"
VAR_BASE = "SIFI_LLM_BASE_URL"

_CLAVE_OK = re.compile(r"^[A-Za-z0-9._\-]{20,200}$")


def _leer_archivo() -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(ENV_PATH, encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                k, v = linea.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def _escribir_archivo(clave: Optional[str], modelo: Optional[str],
                      base_url: Optional[str], previo: Dict[str, str]) -> None:
    """Reescribe el archivo conservando las variables que no tocamos."""
    datos = dict(previo)
    for k, v in ((VAR_CLAVE, clave), (VAR_MODELO, modelo), (VAR_BASE, base_url)):
        if v:
            datos[k] = v
        else:
            datos.pop(k, None)
    # la clave vieja del harness no debe quedar duplicada y confundir al agente
    if clave:
        datos.pop(VAR_ALTERNATIVA, None)

    os.makedirs(os.path.dirname(ENV_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ENV_PATH), prefix=".agent.", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("# siFi Desk — ajustes locales. No se versiona ni se comparte.\n")
            for k in sorted(datos):
                fh.write(f"{k}={datos[k]}\n")
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, ENV_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def estado() -> Dict[str, Any]:
    """Lo que la UI puede mostrar: nunca la clave."""
    archivo = _leer_archivo()
    del_entorno = os.environ.get(VAR_CLAVE) or os.environ.get(VAR_ALTERNATIVA)
    clave = del_entorno or archivo.get(VAR_CLAVE) or ""
    origen = "entorno" if del_entorno else ("archivo" if archivo.get(VAR_CLAVE) else None)
    modelo = os.environ.get(VAR_MODELO) or archivo.get(VAR_MODELO) or DEFAULT_MODEL
    base = os.environ.get(VAR_BASE) or archivo.get(VAR_BASE) or DEFAULT_BASE_URL
    return {
        "configurada": bool(clave),
        "origen": origen,
        "pista": (f"…{clave[-4:]}" if len(clave) >= 8 else None),
        "largo": len(clave) if clave else 0,
        "modelo": modelo,
        "base_url": base,
        "archivo": ENV_PATH,
        "editable": origen != "entorno",
    }


def clave_actual() -> Optional[str]:
    return (os.environ.get(VAR_CLAVE) or os.environ.get(VAR_ALTERNATIVA)
            or _leer_archivo().get(VAR_CLAVE) or None)


def guardar(api_key: str, modelo: Optional[str] = None,
            base_url: Optional[str] = None) -> Dict[str, Any]:
    api_key = (api_key or "").strip()
    if not _CLAVE_OK.match(api_key):
        raise ValueError("la clave no tiene forma de clave de API (20 a 200 caracteres "
                         "alfanuméricos, sin espacios)")
    modelo = (modelo or "").strip() or DEFAULT_MODEL
    base_url = (base_url or "").strip() or DEFAULT_BASE_URL
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url debe empezar con http:// o https://")
    _escribir_archivo(api_key, modelo, base_url, _leer_archivo())
    return estado()


def borrar() -> Dict[str, Any]:
    previo = _leer_archivo()
    _escribir_archivo(None, None, None, previo)
    return estado()
