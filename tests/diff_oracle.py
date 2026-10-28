#!/usr/bin/env python3
"""Test diferencial: pipeline portado (core/sifi) vs pipeline ORIGINAL de si-Fi.

El original (tests/oracle/sifi_pipeline_orig.py) es el fuente de siFi21 con parches
mecánicos mínimos (print, np.float) y la GUI stubbeada. Corre con los MISMOS binarios
de bowtie/RNAplfold, así que cualquier diferencia en el JSON es un bug del port.

Uso:  python3 tests/diff_oracle.py [--mode design|offtarget] [--mismatches N] [--main GeneA]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from sifi import SifiParams, SifiPipeline, ToolPaths  # noqa: E402

BOWTIE = os.path.join(ROOT, "build/bowtie-1.3.1-linux-x86_64/bowtie")
RNAPLFOLD = os.path.join(ROOT, "build/vienna/bin/RNAplfold")
DATA = os.path.join(ROOT, "tests/data")


def run_original(mode: str, mismatches: int, main_targets: str, db: str, query: str) -> list:
    """Corre el pipeline original en un subproceso y devuelve el JSON."""
    tmp = tempfile.mkdtemp(prefix="oracle_")
    path = os.pathsep.join([os.path.join(ROOT, "build/bowtie-1.3.1-linux-x86_64"),
                             os.path.join(ROOT, "build/vienna/bin"), os.environ.get("PATH", "")])
    env = dict(os.environ, TMPDIR=tmp, PATH=path, SIFI_MAIN_TARGETS=main_targets,
               PYTHONPATH=os.path.join(ROOT, "tests/oracle"))
    code = f"""
import sys
sys.path.insert(0, {os.path.join(ROOT, 'tests/oracle')!r})
from sifi_pipeline_orig import SifiPipeline
p = SifiPipeline({db!r}, {DATA + os.sep!r}, {query!r}, 21, {mismatches}, {mode == 'design'}, 8,
                 {os.path.join(ROOT, 'build/vienna/bin')!r}, {os.path.join(ROOT, 'build/bowtie-1.3.1-linux-x86_64')!r},
                 {0 if mode == 'design' else 1},
                 True, {mode == 'design'}, 1.0, 0.1, {tmp!r}, True, False)
out = p.run_pipeline
print('RESULT', out[5] if out else 'none')
"""
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    jsons = [os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith(".json")]
    if not jsons:
        raise RuntimeError(f"El original no generó JSON.\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-3000:]}")
    with open(max(jsons, key=os.path.getsize)) as fh:
        data = json.load(fh)
    shutil.rmtree(tmp, ignore_errors=True)
    return data


def run_port(mode: str, mismatches: int, main_targets: str, db: str, query: str) -> list:
    params = SifiParams(
        mode=mode, mismatches=mismatches,
        end_check=(mode == "design"), accessibility_check=(mode == "design"),
    )
    tools = ToolPaths(bowtie=BOWTIE, rnaplfold=RNAPLFOLD)
    work = tempfile.mkdtemp(prefix="port_")
    pipe = SifiPipeline(db, DATA, query, params, tools, work,
                        main_targets=[t for t in main_targets.split(",") if t],
                        main_target_mode="explicit")
    results = pipe.run()
    pipe.cleanup()
    shutil.rmtree(work, ignore_errors=True)
    res = results[0]
    if res.error:
        raise RuntimeError(f"El port falló: {res.error}")
    return res.sirnas


FLOAT_KEYS = ("accessibility_value",)


def compare(orig: list, port: list) -> tuple[bool, list]:
    problems = []
    if len(orig) != len(port):
        problems.append(f"largo distinto: original={len(orig)} port={len(port)}")
    for i, (a, b) in enumerate(zip(orig, port)):
        for key in a:
            va, vb = a.get(key), b.get(key)
            if key in FLOAT_KEYS:
                if abs(float(va) - float(vb)) > 1e-9:
                    problems.append(f"fila {i} '{key}': {va} != {vb}")
            elif va != vb:
                problems.append(f"fila {i} '{key}': {va!r} != {vb!r}")
        for key in b:
            if key not in a:
                problems.append(f"fila {i}: clave extra en el port: {key}")
    return (not problems), problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="design", choices=["design", "offtarget"])
    ap.add_argument("--mismatches", type=int, default=1)
    ap.add_argument("--main", default="GeneA")
    ap.add_argument("--db", default="toyidx")
    ap.add_argument("--query", default="tests/data/query.fa")
    args = ap.parse_args()

    print(f"→ original ({args.mode}, mismatches={args.mismatches}, main={args.main}) ...")
    orig = run_original(args.mode, args.mismatches, args.main, args.db, os.path.join(ROOT, args.query))
    print(f"  {len(orig)} filas")
    print("→ port ...")
    port = run_port(args.mode, args.mismatches, args.main, args.db, os.path.join(ROOT, args.query))
    print(f"  {len(port)} filas")

    ok, problems = compare(orig, port)
    if ok:
        print("\n✅ IDÉNTICOS: %d filas, %d campos por fila" % (len(orig), len(orig[0]) if orig else 0))
        return 0
    print(f"\n❌ {len(problems)} diferencias:")
    for p in problems[:40]:
        print("   -", p)
    return 1


if __name__ == "__main__":
    sys.exit(main())
