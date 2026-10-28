#!/usr/bin/env python3
"""CLI del núcleo siFi-Desk (sin GUI, sin agente).

  sifi design    -q query.fa -d /ruta/db --db-name maiz -o out/
  sifi offtarget -q trigger.fa -d /ruta/db --db-name maiz -o out/
  sifi doctor
  sifi version

Salida: results.json (+ sirnas.tsv) y un resumen por stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sifi import SifiParams, __version__
from sifi import panels as panelmod
from sifi.run import run_once
from sifi.tools import discover

PANELS_ROOT = os.environ.get("SIFI_PANELS_ROOT", os.path.expanduser("~/.sifidesk/panels"))


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("-q", "--query", required=True, help="FASTA de entrada")
    p.add_argument("-d", "--db-dir", required=True, help="Directorio del índice bowtie")
    p.add_argument("--db-name", required=True, help="Nombre base del índice (sin .ebwt)")
    p.add_argument("-o", "--out", default="out", help="Directorio de salida")
    p.add_argument("--mismatches", type=int, default=0, help="Mismatches permitidos (0-3, default 0)")
    p.add_argument("--sirna-size", type=int, default=21)
    p.add_argument("--main-target", default="auto",
                   help="'auto' (coincidencia con el id de la query) o nombres separados por coma")
    p.add_argument("--bowtie", default=None)
    p.add_argument("--rnaplfold", default=None)
    p.add_argument("--no-terminal-check", action="store_true")
    p.add_argument("--no-strand-check", action="store_true")
    p.add_argument("--quiet", action="store_true")


def cmd_design(args) -> int:
    params = SifiParams(
        mode="design",
        sirna_size=args.sirna_size,
        mismatches=args.mismatches,
        terminal_check=not args.no_terminal_check,
        strand_check=not args.no_strand_check,
    )
    return _run(args, params)


def cmd_offtarget(args) -> int:
    params = SifiParams(
        mode="offtarget",
        sirna_size=args.sirna_size,
        mismatches=args.mismatches,
        end_check=False,
        accessibility_check=False,
        terminal_check=not args.no_terminal_check,
        strand_check=not args.no_strand_check,
    )
    return _run(args, params)


def _run(args, params: SifiParams) -> int:
    tools = discover(args.bowtie, args.rnaplfold)
    mode = "auto" if args.main_target == "auto" else "explicit"
    targets = None if mode == "auto" else [t.strip() for t in args.main_target.split(",") if t.strip()]
    manifest = run_once(args.query, args.db_dir, args.db_name, params, tools, args.out,
                        main_targets=targets, main_target_mode=mode)
    if not args.quiet:
        print(json.dumps(_resumen(manifest), indent=2, ensure_ascii=False))
    return 0 if all(r.get("error") is None for r in manifest["records"]) else 2


def _resumen(m: dict) -> dict:
    out = {"run_id": m["run_id"], "results": m["path"], "tsv": m["tsv_path"],
           "database": m["database"]["name"], "fingerprint": m["database"]["fingerprint"],
           "mode": m["params"]["mode"], "mismatches": m["params"]["mismatches"], "records": []}
    for r in m["records"]:
        s = r.get("summary") or {}
        out["records"].append({
            "query": r["query_name"],
            "length": r["query_length"],
            "error": r.get("error"),
            "sirnas": s.get("n_sirnas"),
            "efficient": s.get("n_sirnas_efficient"),
            "hits": s.get("n_hits"),
            "offtarget_rows": s.get("n_offtarget_rows"),
            "warnings": r.get("warnings", []),
        })
    return out


def cmd_panel(args) -> int:
    root = args.panels_root
    if args.action == "add":
        tools = discover(args.bowtie, args.rnaplfold)
        meta = panelmod.build_panel(
            args.panel_id, args.fasta, root, bowtie_build=args.bowtie_build or tools.bowtie_build or "bowtie-build",
            nombre=args.nombre or "", rol=args.rol, fuente=args.fuente or "",
            notas=args.notas or "", version=args.version)
        print(json.dumps(meta, indent=2, ensure_ascii=False))
        return 0
    if args.action == "list":
        rows = panelmod.list_panels(root)
        if not rows:
            print(f"(no hay paneles en {root})")
            return 0
        for m in rows:
            print(f"{m['id']:<18} {m['version']:<10} {m['rol']:<10} "
                  f"{m['n_seqs']:>7} seqs  {m['fingerprint']}  {m['nombre']}")
        return 0
    if args.action == "show":
        meta = panelmod.resolve_panel(root, args.panel_id, args.version)
        print(json.dumps(meta, indent=2, ensure_ascii=False))
        return 0
    return 1


def cmd_doctor(_args) -> int:
    try:
        tools = discover(_args.bowtie, _args.rnaplfold)
    except FileNotFoundError as exc:
        print("✗", exc)
        return 1
    from sifi.run import _bin_version, _sha256_file
    for name, path in (("bowtie", tools.bowtie), ("RNAplfold", tools.rnaplfold)):
        print(f"✓ {name}: {path}")
        print(f"    versión: {_bin_version(path, ['--version'])}")
        print(f"    sha256:  {_sha256_file(path)}")
    import numpy, Bio  # noqa: E401
    print(f"✓ python {sys.version.split()[0]} · numpy {numpy.__version__} · biopython {Bio.__version__}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sifi", description="siFi-Desk core (headless)")
    ap.add_argument("--version", action="version", version=f"siFi-Desk core {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("design", help="diseño de siRNAs (evalúa eficiencia + off-target)")
    _add_common(d)
    d.set_defaults(func=cmd_design)

    o = sub.add_parser("offtarget", help="predicción de off-targets de un trigger dado")
    _add_common(o)
    o.set_defaults(func=cmd_offtarget)

    pan = sub.add_parser("panel", help="gestiona paneles (bases de secuencias) indexadas")
    pan.add_argument("action", choices=["add", "list", "show"])
    pan.add_argument("--panels-root", default=PANELS_ROOT)
    pan.add_argument("--panel-id", default=None)
    pan.add_argument("--fasta", default=None, help="FASTA del panel (action=add)")
    pan.add_argument("--nombre", default=None)
    pan.add_argument("--rol", default="no_blanco", choices=list(panelmod.ROLES))
    pan.add_argument("--fuente", default=None)
    pan.add_argument("--notas", default=None)
    pan.add_argument("--version", default=None)
    pan.add_argument("--bowtie-build", default=None)
    pan.add_argument("--bowtie", default=None)
    pan.add_argument("--rnaplfold", default=None)
    pan.set_defaults(func=cmd_panel)

    doc = sub.add_parser("doctor", help="verifica binarios y entorno")
    doc.add_argument("--bowtie", default=None)
    doc.add_argument("--rnaplfold", default=None)
    doc.set_defaults(func=cmd_doctor)

    ver = sub.add_parser("version", help="versión del core")
    ver.set_defaults(func=lambda a: (print(f"siFi-Desk core {__version__}"), 0)[1])

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
