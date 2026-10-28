"""Ejecución de una corrida completa: core + artefactos + manifiesto reproducible."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .params import SifiParams, ToolPaths
from .pipeline import SifiPipeline, PipelineResult

SCHEMA = "sifi.results/1"


def _sha256_file(path: str, limit: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(limit)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _bin_version(exe: str, args: Sequence[str] = ("--version",)) -> str:
    import subprocess
    try:
        out = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20)
        txt = (out.stdout or out.stderr).strip().splitlines()
        return txt[0] if txt else "?"
    except Exception as exc:  # pragma: no cover
        return f"error: {exc}"


def run_once(
    query_path: str,
    db_dir: str,
    db_name: str,
    params: SifiParams,
    tools: ToolPaths,
    out_dir: str,
    main_targets: Optional[Sequence[str]] = None,
    main_target_mode: str = "auto",
    extra_meta: Optional[dict] = None,
) -> dict:
    """Corre el pipeline sobre `query_path` y escribe el manifest + results.json."""
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, "_work")
    pipe = SifiPipeline(db_name, db_dir, query_path, params, tools, work,
                        main_targets=main_targets, main_target_mode=main_target_mode)
    try:
        results: List[PipelineResult] = pipe.run()
    finally:
        pipe.cleanup()

    manifest = {
        "schema": SCHEMA,
        "run_id": None,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "core_version": __version__,
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine(), "python": sys.version.split()[0]},
        "params": params.as_dict(),
        "tools": {
            "bowtie": {"path": tools.bowtie, "version": _bin_version(tools.bowtie, ["--version"]),
                       "sha256": _sha256_file(tools.bowtie) if os.path.exists(tools.bowtie) else None},
            "rnaplfold": {"path": tools.rnaplfold, "version": _bin_version(tools.rnaplfold, ["--version"]),
                          "sha256": _sha256_file(tools.rnaplfold) if os.path.exists(tools.rnaplfold) else None},
        },
        "database": {"dir": os.path.abspath(db_dir), "name": db_name,
                     "fingerprint": _db_fingerprint(db_dir, db_name)},
        "query_file": os.path.abspath(query_path),
        "query_file_sha256": _sha256_file(query_path),
        "records": [],
        "extra": extra_meta or {},
    }
    for res in results:
        rec = res.to_dict()
        rec.pop("artifacts", None)
        manifest["records"].append(rec)

    payload = json.dumps(manifest, sort_keys=True).encode()
    manifest["run_id"] = hashlib.sha256(payload).hexdigest()[:16]

    path = os.path.join(out_dir, "results.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    manifest["path"] = path

    tsv = os.path.join(out_dir, "sirnas.tsv")
    _write_tsv(manifest, tsv)
    manifest["tsv_path"] = tsv

    shutil.rmtree(work, ignore_errors=True)
    return manifest


def _db_fingerprint(db_dir: str, db_name: str) -> Optional[str]:
    """Huella del índice bowtie: cambia si cambia la base."""
    h = hashlib.sha256()
    found = False
    for suffix in (".1.ebwt", ".2.ebwt", ".3.ebwt", ".4.ebwt", ".rev.1.ebwt", ".rev.2.ebwt"):
        p = os.path.join(db_dir, db_name + suffix)
        if os.path.exists(p):
            found = True
            h.update(suffix.encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()[:16] if found else None


TSV_COLS = ["query_name", "sirna_name", "sirna_position", "sirna_sequence", "is_efficient",
            "strand_selection", "end_stability", "target_site_accessibility",
            "accessibility_value", "is_off_target", "hit_name", "reference_strand_pos",
            "strand", "mismatches"]


def _write_tsv(manifest: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(TSV_COLS) + "\n")
        for rec in manifest["records"]:
            for row in rec.get("sirnas", []):
                fh.write("\t".join(str(row.get(c, "")) for c in TSV_COLS) + "\n")
