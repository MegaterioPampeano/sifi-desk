"""Runner de una sola corrida. Lo lanza el worker de sifid en un proceso aparte.

Uso (lo arma el servicio, no hace falta a mano):

    python3 -m service.runner --spec <run_dir>/spec.json

Contrato con el worker: escribe **una línea JSON por evento** en stdout:

    {"event": "progress", "phase": "running", "done": 0, "total": 1}
    {"event": "manifest", "run_id": "...", "path": "/.../results.json",
     "tsv_path": "/.../sirnas.tsv", "records": 1}
    {"event": "progress", "phase": "done", "done": 1, "total": 1}
    {"event": "error", "message": "..."}          # y sale con código 3

Todo lo demás (log del core, trazas) va por stderr, que el worker guarda en
`<run_dir>/stderr.log`.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run_spec(spec: dict) -> int:
    """Ejecuta el spec y emite los eventos. Devuelve el código de salida."""
    total = int(spec.get("records_total") or 0)
    _emit({"event": "progress", "phase": "starting", "done": 0, "total": total})

    core_path = spec.get("core_path")
    if core_path and core_path not in sys.path:
        sys.path.insert(0, core_path)

    try:
        from sifi.params import SifiParams, ToolPaths
        from sifi.run import run_once

        params = SifiParams(**spec["params"])
        tools = ToolPaths(**spec["tools"])

        _emit({"event": "progress", "phase": "running", "done": 0, "total": total})
        manifest = run_once(
            spec["query_path"],
            spec["db_dir"],
            spec["db_name"],
            params,
            tools,
            spec["out_dir"],
            main_targets=spec.get("main_targets"),
            main_target_mode=spec.get("main_target_mode", "auto"),
            extra_meta=spec.get("extra_meta") or {},
        )
        records = len(manifest.get("records") or [])
        _emit({"event": "manifest", "run_id": manifest.get("run_id"),
               "path": manifest.get("path"), "tsv_path": manifest.get("tsv_path"),
               "records": records})
        _emit({"event": "progress", "phase": "done", "done": records or total,
               "total": total or records})
        return 0
    except Exception as exc:  # noqa: BLE001 - cualquier falla del core es un run con error
        _emit({"event": "error", "message": f"{type(exc).__name__}: {exc}"})
        traceback.print_exc(file=sys.stderr)
        return 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="service.runner",
                                 description="Ejecuta una corrida de siFi y reporta por stdout")
    ap.add_argument("--spec", required=True, help="JSON con la corrida (lo escribe sifid)")
    args = ap.parse_args(argv)

    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    return run_spec(spec)


if __name__ == "__main__":
    raise SystemExit(main())
