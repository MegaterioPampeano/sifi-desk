"""Extracción de texto y verificación de PDFs, con `pdftotext` y `pdfinfo`.

Nada acá genera PDFs: sólo se abre el archivo que bajó `fetch`. La verificación es la
aduana de la biblioteca:

1. los primeros bytes son `%PDF`;
2. el archivo pesa más de `MIN_BYTES` (20 KB): un PDF de una carátula de error no entra;
3. `pdfinfo` lo abre y reporta al menos una página.

Si algo falla, el archivo se descarta y se devuelve el motivo (texto corto, para guardar
en `papers.motivo`).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

MIN_BYTES = 20 * 1024
PDF_MAGIC = b"%PDF"
PDFTOTEXT = "pdftotext"
PDFINFO = "pdfinfo"
TIMEOUT = 120


class ExtractError(RuntimeError):
    pass


def _run(cmd, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_pdf(path: str | Path) -> Tuple[bool, str, Dict[str, Any]]:
    """¿Es un PDF real y legible? Devuelve `(ok, motivo, info)`."""
    path = Path(path)
    if not path.is_file():
        return False, "no existe el archivo", {}
    size = path.stat().st_size
    if size <= MIN_BYTES:
        return False, f"archivo demasiado chico ({size} bytes < {MIN_BYTES})", {"bytes": size}
    with open(path, "rb") as fh:
        head = fh.read(1024)
    if not head.startswith(PDF_MAGIC):
        sniff = head[:60].decode("utf-8", "replace").strip().replace("\n", " ")
        return False, f"no es un PDF (empieza con: {sniff[:40]!r})", {"bytes": size}
    try:
        res = _run([PDFINFO, str(path)])
    except FileNotFoundError:
        raise ExtractError("falta `pdfinfo` (paquete poppler-utils)")
    except subprocess.TimeoutExpired:
        return False, "pdfinfo no terminó (timeout)", {"bytes": size}
    if res.returncode != 0:
        err = (res.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        detail = err[0] if err else f"rc={res.returncode}"
        return False, f"pdfinfo no abre el archivo: {detail[:120]}", {"bytes": size}
    info = parse_pdfinfo((res.stdout or b"").decode("utf-8", "replace"))
    info["bytes"] = size
    pages = info.get("pages") or 0
    if pages < 1:
        return False, "el PDF no tiene páginas según pdfinfo", info
    return True, "", info


def parse_pdfinfo(text: str) -> Dict[str, Any]:
    """`pdfinfo` devuelve `Clave: valor`; sólo interesan páginas y metadatos básicos."""
    out: Dict[str, Any] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "pages":
            try:
                out["pages"] = int(value)
            except ValueError:
                pass
        elif key in ("title", "author", "producer", "creator", "creationdate"):
            out[key] = value
    return out


def pdf_pages(path: str | Path) -> int:
    try:
        res = _run([PDFINFO, str(path)])
    except FileNotFoundError:
        raise ExtractError("falta `pdfinfo` (paquete poppler-utils)")
    if res.returncode != 0:
        return 0
    return int(parse_pdfinfo((res.stdout or b"").decode("utf-8", "replace")).get("pages") or 0)


def pdf_text(path: str | Path, layout: bool = True) -> str:
    """Texto del PDF con `pdftotext`. `-layout` preserva columnas/tablas."""
    cmd = [PDFTOTEXT]
    if layout:
        cmd.append("-layout")
    cmd += [str(path), "-"]
    try:
        res = _run(cmd, timeout=180)
    except FileNotFoundError:
        raise ExtractError("falta `pdftotext` (paquete poppler-utils)")
    except subprocess.TimeoutExpired:
        raise ExtractError("pdftotext no terminó (timeout)")
    if res.returncode != 0:
        err = (res.stderr or b"").decode("utf-8", "replace").strip()
        raise ExtractError(f"pdftotext falló: {err[:160]}")
    return (res.stdout or b"").decode("utf-8", "replace")


_WS = re.compile(r"[ \t\u00a0]+")


def normalize_text(text: str) -> str:
    """Normaliza **sólo espacios**: no reescribe ni resume el contenido.

    * `\\r\\n` → `\\n`;
    * espacios/tabs repetidos → uno;
    * se recortan los espacios al final de cada línea;
    * se colapsan 3+ líneas en blanco a dos (párrafo);
    * se quitan los `\\f` (saltos de página de pdftotext).
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    lines = [_WS.sub(" ", line).rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(path: str | Path) -> Dict[str, Any]:
    """`pages`, `text`, `text_chars`, `sha256`, `bytes` de un PDF ya verificado."""
    path = Path(path)
    text = normalize_text(pdf_text(path, layout=True))
    return {
        "pages": pdf_pages(path),
        "text": text,
        "text_chars": len(text),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def first_page_snippet(path: str | Path, limit: int = 400) -> str:
    """Primeras líneas útiles (para mostrar en el CLI sin volcar todo)."""
    try:
        text = normalize_text(pdf_text(path, layout=True))
    except ExtractError:
        return ""
    lines = [ln for ln in text.split("\n") if ln.strip()][:12]
    return " / ".join(lines)[:limit]


def looks_like_html(data: bytes) -> bool:
    head = data[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def describe_rejection(data: bytes) -> Optional[str]:
    """Motivo corto cuando el cuerpo descargado no es un PDF."""
    if looks_like_html(data):
        title = re.search(rb"<title[^>]*>(.*?)</title>", data[:4096], re.I | re.S)
        extra = title.group(1).decode("utf-8", "replace").strip()[:60] if title else "html"
        return f"el servidor devolvió HTML, no un PDF ({extra})"
    if not data:
        return "respuesta vacía"
    if not data.startswith(PDF_MAGIC):
        return "el archivo no empieza con %PDF"
    return None
