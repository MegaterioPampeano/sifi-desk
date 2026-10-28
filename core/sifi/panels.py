"""Registro de paneles (bases de secuencias) con versionado e indexado bowtie.

Un panel es un directorio inmutable:

    <panels_root>/<panel_id>/<version>/
        seqs.fa         FASTA normalizado (una línea por secuencia)
        idx.*.ebwt      índice bowtie1
        meta.yaml       metadatos + hashes

Nada se reescribe: construir el mismo panel con otro FASTA genera otra versión.
La corrida guarda el fingerprint del índice, así que un resultado siempre se puede
atar a la base exacta con la que se calculó.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from Bio import SeqIO

INDEX_SUFFIXES = (".1.ebwt", ".2.ebwt", ".3.ebwt", ".4.ebwt", ".rev.1.ebwt", ".rev.2.ebwt")
ROLES = ("no_blanco", "blanco", "patogeno", "simbionte", "control", "universal")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,40}$")


class PanelError(RuntimeError):
    pass


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fingerprint(index_prefix: str) -> Optional[str]:
    h = hashlib.sha256()
    found = False
    for suf in INDEX_SUFFIXES:
        p = index_prefix + suf
        if os.path.exists(p):
            found = True
            h.update(suf.encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()[:16] if found else None


def _normalize_fasta(src: str, dst: str) -> int:
    """Reescribe el FASTA con un ID limpio (sin descripción) y secuencia en una línea.

    Los IDs importan: siFi usa el nombre del hit como 'main target', así que un FASTA con
    descripciones largas o caracteres raros produce resultados difíciles de interpretar.
    """
    n = 0
    seen = set()
    with open(dst, "w", encoding="utf-8") as out:
        for rec in SeqIO.parse(src, "fasta"):
            rid = rec.id.strip().replace(" ", "_")
            if rid in seen:
                raise PanelError(f"ID duplicado en el FASTA: {rid}")
            seen.add(rid)
            seq = str(rec.seq).upper().replace("U", "T")
            if not seq:
                continue
            out.write(f">{rid}\n{seq}\n")
            n += 1
    if not n:
        raise PanelError("El FASTA no contiene secuencias.")
    return n


def build_panel(
    panel_id: str,
    fasta_path: str,
    panels_root: str,
    bowtie_build: str,
    nombre: str = "",
    rol: str = "no_blanco",
    fuente: str = "",
    notas: str = "",
    version: Optional[str] = None,
) -> dict:
    """Construye (o reconstruye) un panel y devuelve su meta."""
    if not ID_RE.match(panel_id):
        raise PanelError("panel_id inválido: usar minúsculas, números, '-' o '_' (2-41 chars)")
    if rol not in ROLES:
        raise PanelError(f"rol inválido: {rol!r} (usar uno de {', '.join(ROLES)})")
    if not os.path.exists(fasta_path):
        raise PanelError(f"no existe el FASTA: {fasta_path}")

    version = version or datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = os.path.join(panels_root, panel_id, version)
    if os.path.exists(dest):
        # mismo contenido -> reutilizar; distinto -> error (nunca se pisa un panel)
        meta = read_meta(dest)
        if meta and meta.get("sha256_fasta") == _sha256(fasta_path):
            return meta
        raise PanelError(f"ya existe {dest} con otro contenido; usá otra version")

    os.makedirs(dest, exist_ok=False)
    seqs = os.path.join(dest, "seqs.fa")
    _normalize_fasta(fasta_path, seqs)

    prefix = os.path.join(dest, "idx")
    proc = subprocess.run([bowtie_build, "-q", "--ntoa", seqs, prefix],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise PanelError(f"bowtie-build falló: {proc.stderr.strip()[:400]}")

    fp = _fingerprint(prefix)
    if not fp:
        shutil.rmtree(dest, ignore_errors=True)
        raise PanelError("bowtie-build no generó el índice")

    meta = {
        "id": panel_id,
        "version": version,
        "nombre": nombre or panel_id,
        "rol": rol,
        "fuente": fuente,
        "notas": notas,
        "n_seqs": sum(1 for _ in SeqIO.parse(seqs, "fasta")),
        "sha256_fasta": _sha256(seqs),
        "fingerprint": fp,
        "index_prefix": "idx",
        "bowtie_build": os.path.basename(bowtie_build),
        "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes_fasta": os.path.getsize(seqs),
    }
    with open(os.path.join(dest, "meta.yaml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump(meta, fh, allow_unicode=True, sort_keys=True)
    return meta


def read_meta(panel_dir: str) -> Optional[dict]:
    p = os.path.join(panel_dir, "meta.yaml")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def list_panels(panels_root: str) -> List[dict]:
    """Todos los paneles, con todas sus versiones, ordenados por id y versión."""
    out = []
    if not os.path.isdir(panels_root):
        return out
    for pid in sorted(os.listdir(panels_root)):
        pdir = os.path.join(panels_root, pid)
        if not os.path.isdir(pdir):
            continue
        for ver in sorted(os.listdir(pdir)):
            meta = read_meta(os.path.join(pdir, ver))
            if meta:
                meta["path"] = os.path.join(pdir, ver)
                out.append(meta)
    return out


def resolve_panel(panels_root: str, panel_id: str, version: Optional[str] = None) -> dict:
    """Devuelve el meta del panel pedido (última versión si no se especifica)."""
    pdir = os.path.join(panels_root, panel_id)
    if not os.path.isdir(pdir):
        raise PanelError(f"no existe el panel {panel_id!r} en {panels_root}")
    versions = sorted(v for v in os.listdir(pdir) if read_meta(os.path.join(pdir, v)))
    if not versions:
        raise PanelError(f"el panel {panel_id!r} no tiene versiones válidas")
    ver = version or versions[-1]
    if ver not in versions:
        raise PanelError(f"el panel {panel_id!r} no tiene la versión {ver!r} (hay: {', '.join(versions)})")
    meta = read_meta(os.path.join(pdir, ver))
    meta["path"] = os.path.join(pdir, ver)
    return meta


def remove_panel(panels_root: str, panel_id: str, version: str) -> None:
    """Borra una versión de panel (operación explícita, no se usa automáticamente)."""
    dest = os.path.join(panels_root, panel_id, version)
    if not os.path.isdir(dest):
        raise PanelError(f"no existe {dest}")
    shutil.rmtree(dest)
    parent = os.path.dirname(dest)
    if not os.listdir(parent):
        os.rmdir(parent)
