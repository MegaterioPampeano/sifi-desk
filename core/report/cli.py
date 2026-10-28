"""CLI del reporte.

Desde ``core/``::

    python3 -m report.cli --results out/results.json --out reporte.pdf

Se puede repetir ``--results`` para un informe de varias corridas. ``--out`` acepta un
archivo (se infiere el formato por la extensión) o un directorio.
"""
from __future__ import annotations

import argparse
import os
import sys

# permite `python3 -m report.cli` desde core/ y desde la raíz del repo
_CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from report.model import ReportError  # noqa: E402
from report.render import REPORT_VERSION, render  # noqa: E402


def _split_out(out: str, fmt: str) -> tuple:
    """Devuelve (out_dir, filename) a partir de --out."""
    suffix = "." + fmt
    if out.lower().endswith(suffix):
        directory = os.path.dirname(os.path.abspath(out)) or "."
        return directory, os.path.basename(out)
    return out, None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m report.cli",
        description="Genera el informe A4 (PDF/HTML) de una o varias corridas siFi.",
    )
    p.add_argument("--results", action="append", required=True, metavar="RESULTS.JSON",
                   help="manifest sifi.results/1 (repetir para varias corridas)")
    p.add_argument("--out", required=True, metavar="SALIDA",
                   help="archivo de salida (reporte.pdf) o directorio")
    p.add_argument("--fmt", choices=("pdf", "html"), default=None,
                   help="formato (por defecto: por extensión de --out, si no pdf)")
    p.add_argument("--filename", default=None,
                   help="nombre del archivo cuando --out es un directorio")
    p.add_argument("--version", action="version",
                   version=f"reporte Si-Fi Agent Integration v{REPORT_VERSION}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    fmt = args.fmt
    if fmt is None:
        low = args.out.lower()
        fmt = "html" if low.endswith(".html") else "pdf"

    out_dir, filename = _split_out(args.out, fmt)
    if args.filename:
        filename = args.filename

    try:
        path = render(args.results, out_dir, fmt=fmt, filename=filename)
    except (ReportError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
