#!/usr/bin/env python3
"""Genera los DOS gráficos del siFi original a partir de su propio JSON.

Usa el código de plotting de `vendor/siFi21/create_plots.py` sin tocarlo: sólo le pasa la
salida del pipeline original y los `general_helpers` parcheados para Python 3.

    old_plots.py --json out.json --query query.fa --out-dir /tmp/x
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import matplotlib

matplotlib.use("Agg")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="salida del pipeline original (lista de filas)")
    ap.add_argument("--query", required=True, help="FASTA de la consulta")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    # `general_helpers` viene de tests/oracle (parcheado a Python 3); `create_plots` se carga
    # por ruta desde vendor/ porque el de tests/oracle es sólo un stub.
    sys.path.insert(0, os.path.join(ROOT, "tests", "oracle"))
    import importlib.util

    ruta = os.path.join(ROOT, "vendor", "siFi21", "create_plots.py")
    spec = importlib.util.spec_from_file_location("create_plots_vendor", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    CreatePlots = modulo.CreatePlots

    datos = json.load(open(args.json, encoding="utf-8"))
    filas = datos[0] if datos and isinstance(datos[0], list) else datos
    if not filas:
        print("El JSON no tiene filas: nada que graficar.")
        return 2
    seq = "".join(l.strip() for l in open(args.query, encoding="utf-8") if not l.startswith(">"))

    cp = CreatePlots(sirna_size=21, query_sequence=seq,
                     sifi_data=json.dumps(filas), off_target_pos_list=[],
                     region_plot_lst=[], temp_location=args.out_dir, scoret_lst=[],
                     main_targets=["Hit_A"], f_in=args.json)

    diseno, _ot, _mt = cp.create_design_plot()
    objetivo, _t = cp.create_off_target_plot()
    a = os.path.join(args.out_dir, "sifi-original-diseno.png")
    b = os.path.join(args.out_dir, "sifi-original-offtarget.png")
    shutil.copy(diseno, a)
    shutil.copy(objetivo, b)
    print(a)
    print(b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
