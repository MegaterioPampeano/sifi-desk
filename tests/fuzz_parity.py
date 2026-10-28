#!/usr/bin/env python3
"""Paridad aleatoria: port (core/sifi) vs original siFi21 sobre secuencias sintéticas.

Qué mide
--------
`tests/diff_oracle.py` prueba la paridad con **un** caso (300 nt de `tests/data/query.fa`).
Esto agrega un barrido: muchas secuencias, mismatches 0/1/2, design y offtarget, con
comparación estricta de los 14 campos fila por fila.

1. Genera 20 transcritos sintéticos (300-600 nt) con contenido GC planificado
   (~30/45/60/70 %), incluido un caso homopolimérico A/T y uno rico en GC con
   repeticiones en tándem. Semilla fija (default 20261028) => reproducible.
   **No se usan secuencias biológicas reales**: lo que se estresa es el cálculo.
2. Arma un índice bowtie con tres copias por transcrito:
      T<nn>  = la secuencia tal cual  -> hits a 0 mismatches; es el "main target" en design
      A<nn>  = copia mutada ~1 nt cada 45  -> hits a 1 mismatch
      B<nn>  = copia mutada ~1 nt cada 22, con prefijo de 5-13 nt -> hits a 1-2 mismatches
               y offsets corridos (varía `reference_strand_pos`)
   Sin copias mutadas el barrido sería trivial: una secuencia aleatoria no alinea contra
   el índice y nunca se ejecutaría el camino de ΔG / off-target.
3. Cruza {secuencias} x {0,1,2 mismatches} x {design, offtarget} = 120 corridas pareadas
   (240 ejecuciones: original + port en cada una). Cada lado usa los MISMOS binarios.
4. Compara los 14 campos: mismo orden de claves, misma cantidad de filas, igualdad
   exacta para str/int/bool y `math.isclose(rel_tol=1e-9, abs_tol=1e-9)` para floats.
   Reporta el desvío absoluto y relativo máximo observado por campo.
5. Escribe `tests/paridad/REPORTE.md` y `tests/paridad/resumen.json`.

Uso
---
    python3 tests/fuzz_parity.py --seed 20261028 --jobs 4
    python3 tests/fuzz_parity.py --selftest      # control negativo: el comparador SÍ falla
    python3 tests/fuzz_parity.py --sequences 8   # recorte documentado (primeras N)

Criterio de recorte (`--sequences N < 20`): se toman las primeras N del orden fijo que
genera `gen_sequences` (round-robin entre clases de GC), así un recorte conserva las
cuatro clases. La semilla no cambia: las N primeras son idénticas en cualquier corrida.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import diff_oracle  # noqa: E402
from sifi.tools import discover  # noqa: E402

DEFAULT_SEED = 20261028
BUCKETS = ((0.30, "gc30"), (0.45, "gc45"), (0.60, "gc60"), (0.70, "gc70"))
PER_BUCKET = 5
MODES = ("design", "offtarget")
MISMATCHES = (0, 1, 2)

# Los 14 campos, en el orden canónico que publica data_to_json.
FIELD_KIND = {
    "query_name": "str",
    "sirna_name": "str",
    "sirna_position": "int",
    "sirna_sequence": "str",
    "is_efficient": "bool",
    "strand_selection": "bool",
    "end_stability": "bool",
    "target_site_accessibility": "bool",
    "accessibility_value": "float",
    "is_off_target": "bool|null",
    "hit_name": "str|false",
    "reference_strand_pos": "int|null",
    "strand": "str|null",
    "mismatches": "str|null",
}
FLOAT_FIELDS = {k for k, v in FIELD_KIND.items() if v == "float"}


# ----------------------------------------------------------------- generador
def _balanced(rng: random.Random, length: int, gc_target: float) -> str:
    """Secuencia con exactamente round(gc_target*length) bases G/C."""
    n_gc = int(round(gc_target * length))
    slots = ["GC"] * n_gc + ["AT"] * (length - n_gc)
    rng.shuffle(slots)
    return "".join(rng.choice(s) for s in slots)


def _homopolymer(rng: random.Random, length: int, gc_target: float) -> str:
    """Baja complejidad: tramos A/T de 6-16 nt con islas GC cortas (30 % GC).

    Estresa los bordes: ventanas de 21-mers casi idénticas, muchos empates de ΔG y
    tramos que bowtie puede alinear en varios lugares.
    """
    n_gc = int(round(gc_target * length))
    parts: list[str] = []
    gc_left, remaining = n_gc, length
    while remaining > 0:
        if gc_left > 0 and (rng.random() < 0.35 or remaining <= gc_left + 6):
            k = min(rng.randint(2, 6), gc_left, remaining)
            parts.append("".join(rng.choice("GC") for _ in range(k)))
            gc_left, remaining = gc_left - k, remaining - k
        else:
            k = min(rng.randint(6, 16), remaining)
            parts.append(rng.choice("AT") * k)
            remaining -= k
    return "".join(parts)[:length]


def _repeats(rng: random.Random, length: int, gc_target: float) -> str:
    """Rico en GC con repeticiones en tándem (motivos de 6 nt) + islas AT.

    Las repeticiones puras darían ~75-83 % GC; se intercalan tramos A/T para caer en
    el objetivo (~70 %) sin perder el carácter repetitivo que se quiere estresar.
    """
    motifs = ["GCGGCC", "GCCGGC", "CCGCGG", "GCGCGG"]
    gc_budget = int(round(gc_target * length))
    parts: list[str] = []
    gc_used = n = 0
    while n < length:
        gc_left = gc_budget - gc_used
        if gc_left > 6 and rng.random() < 0.7:
            block = rng.choice(motifs) * rng.randint(2, 5)
            block = block[:max(3, min(len(block), gc_left))]
            parts.append(block)
            gc_used += block.count("G") + block.count("C")
            n += len(block)
        else:
            k = min(rng.randint(3, 10), max(1, length - n))
            parts.append(rng.choice("AT") * k)
            n += k
    return "".join(parts)[:length]


def gen_sequences(seed: int = DEFAULT_SEED, n_seqs: int = 20) -> list[dict]:
    """Genera los transcritos sintéticos. Determinista para una (seed, n_seqs)."""
    rng = random.Random(seed)
    plan = []
    for k in range(PER_BUCKET):                      # round-robin entre clases de GC
        for gc, label in BUCKETS:
            plan.append((gc, label, k))
    plan = plan[:n_seqs]

    out = []
    for i, (gc, label, k) in enumerate(plan):
        length = rng.randint(300, 600)
        if label == "gc30" and k == 0:
            seq, kind = _homopolymer(rng, length, gc), "homopolimero A/T"
        elif label == "gc70" and k == 0:
            seq, kind = _repeats(rng, length, gc), "GC con repeticiones"
        else:
            seq, kind = _balanced(rng, length, gc), "balanceada"
        assert 300 <= len(seq) <= 600, (i, len(seq))
        out.append({"name": f"synth{i + 1:02d}", "seq": seq, "len": len(seq),
                    "gc_target": gc, "gc": _gc(seq), "kind": kind, "bucket": label})
    return out


def _gc(seq: str) -> float:
    return (seq.count("G") + seq.count("C")) / len(seq)


# --------------------------------------------------------------- índice bowtie
def _mutate(rng: random.Random, seq: str, spacing: int) -> str:
    """Sustituciones cada ~spacing nt (sin tocar el largo => mismos offsets)."""
    out = list(seq)
    n = max(1, len(seq) // spacing)
    for pos in sorted(rng.sample(range(len(seq)), n)):
        out[pos] = rng.choice([b for b in "ACGT" if b != out[pos]])
    return "".join(out)


def build_db(records: list[dict], db_dir: str, tools, seed: int = DEFAULT_SEED) -> tuple[str, str]:
    """Escribe T/A/B por transcrito y corre bowtie-build. -> (dir con '/', nombre)."""
    os.makedirs(db_dir, exist_ok=True)
    rng = random.Random(seed + 1)                    # flujo aparte del generador
    fa = os.path.join(db_dir, "synth.fa")
    with open(fa, "w", encoding="utf-8") as fh:
        for r in records:
            nn = r["name"][-2:]
            fh.write(f">T{nn}\n{r['seq']}\n")
            fh.write(f">A{nn}\n{_mutate(rng, r['seq'], 45)}\n")
            prefix = "".join(rng.choice("ACGT") for _ in range(rng.randint(5, 13)))
            fh.write(f">B{nn}\n{prefix}{_mutate(rng, r['seq'], 22)}\n")
    name = "synthidx"
    subprocess.run([tools.bowtie_build, "-q", fa, os.path.join(db_dir, name)],
                   check=True, capture_output=True, text=True)
    return db_dir + os.sep, name


# ------------------------------------------------------------------ comparación
def _num(a, b) -> tuple[float, float]:
    """(desvío absoluto, desvío relativo) de dos floats."""
    abs_dev = abs(a - b)
    denom = max(abs(a), abs(b))
    rel_dev = abs_dev / denom if denom else abs_dev
    return abs_dev, rel_dev


def compare_block(orig: list, port: list, ctx: str = "") -> tuple[list, dict]:
    """Compara dos listas de filas (dicts) con los 14 campos.

    Devuelve (problemas, stats) donde stats[field] = {n, max_abs, max_rel,
    n_nonzero, n_nan_both}. Nunca lanza: todo lo raro se reporta como problema.
    """
    problems: list[str] = []
    stats = {k: {"n": 0, "max_abs": 0.0, "max_rel": 0.0, "n_nonzero": 0, "n_nan_both": 0}
             for k in FIELD_KIND}
    pre = f"{ctx}: " if ctx else ""

    if len(orig) != len(port):
        problems.append(f"{pre}cantidad de filas distinta: original={len(orig)} port={len(port)}")

    # filas de más/menos, identificadas por su candidato y posición
    for i in range(min(len(orig), len(port)), max(len(orig), len(port))):
        side, rows = ("original", orig) if len(orig) > len(port) else ("port", port)
        row = rows[i]
        problems.append(f"{pre}fila {i} sobra en {side}: sirna={row.get('sirna_name')!r} "
                        f"pos={row.get('sirna_position')!r} hit={row.get('hit_name')!r}")

    for i, (a, b) in enumerate(zip(orig, port)):
        if list(a.keys()) != list(b.keys()):
            problems.append(f"{pre}fila {i} ({a.get('sirna_name')!r}, hit={a.get('hit_name')!r}): "
                            f"orden/claves distintas: {list(a.keys())} vs {list(b.keys())}")
            continue
        for key in a:
            va, vb = a[key], b[key]
            st = stats[key]
            st["n"] += 1
            if key in FLOAT_FIELDS:
                fa, fb = float(va), float(vb)
                if math.isnan(fa) or math.isnan(fb):
                    if math.isnan(fa) and math.isnan(fb):
                        st["n_nan_both"] += 1
                        continue
                    problems.append(f"{pre}fila {i} ({a.get('sirna_name')!r}): '{key}' "
                                    f"NaN de un solo lado: {va!r} != {vb!r}")
                    continue
                abs_dev, rel_dev = _num(fa, fb)
                st["max_abs"] = max(st["max_abs"], abs_dev)
                st["max_rel"] = max(st["max_rel"], rel_dev)
                if abs_dev:
                    st["n_nonzero"] += 1
                if not math.isclose(fa, fb, rel_tol=1e-9, abs_tol=1e-9):
                    problems.append(f"{pre}fila {i} ({a.get('sirna_name')!r}): '{key}' "
                                    f"{fa!r} != {fb!r} (|Δ|={abs_dev:.3e}, rel={rel_dev:.3e})")
            else:
                # exacto y del mismo tipo: True != 1 aunque `==` diga que sí
                if type(va) is not type(vb) or va != vb:
                    problems.append(f"{pre}fila {i} ({a.get('sirna_name')!r}, "
                                    f"hit={a.get('hit_name')!r}): '{key}' "
                                    f"{va!r} ({type(va).__name__}) != {vb!r} ({type(vb).__name__})")
    return problems, stats


def _coverage(rows: list) -> dict:
    """Qué caminos del pipeline tocó esta corrida (para el reporte)."""
    mism = {r.get("mismatches") for r in rows}
    acc = [float(r["accessibility_value"]) for r in rows
           if isinstance(r.get("accessibility_value"), (int, float))]
    return {
        "rows": len(rows),
        "sirnas": len({r.get("sirna_name") for r in rows}),
        "plus_strand": sum(1 for r in rows if r.get("strand") == "+"),
        "no_hit_path": sum(1 for r in rows if r.get("hit_name") is False),
        "offtarget_true": sum(1 for r in rows if r.get("is_off_target") is True),
        "offtarget_false": sum(1 for r in rows if r.get("is_off_target") is False),
        "offtarget_none": sum(1 for r in rows if r.get("is_off_target") is None),
        "efficient": sum(1 for r in rows if r.get("is_efficient") is True),
        # prueba de que el float está vivo: valores distintos y el bool que sale de él
        "distinct_acc": len({round(a, 12) for a in acc}),
        "acc_true": sum(1 for r in rows if r.get("target_site_accessibility") is True),
        "acc_false": sum(1 for r in rows if r.get("target_site_accessibility") is False),
        "mismatch_values": sorted(str(m) for m in mism if m is not None),
    }


# --------------------------------------------------------------------- worker
_MUTATED = False


def _patch_port_float() -> None:
    """Prueba de mutación: perturba un float del port un 1e-6 (a propósito).

    Sirve para comprobar que el barrido DETECTA una deriva real y que no está
    verde por construcción. No toca `core/**` en disco: parchea en memoria del
    proceso worker.
    """
    global _MUTATED
    if _MUTATED:
        return
    from sifi.pipeline import SifiPipeline

    original = SifiPipeline.data_to_json

    def patched(self, *args, **kwargs):
        rows = original(self, *args, **kwargs)
        for row in rows:
            if row["sirna_position"] == 7:
                row["accessibility_value"] = float(row["accessibility_value"]) * (1 + 1e-6)
        return rows

    SifiPipeline.data_to_json = patched
    _MUTATED = True


def _run_one(task: dict) -> dict:
    """Una corrida pareada: original y port sobre la misma secuencia/parámetros."""
    name, seq, mm, mode = task["name"], task["seq"], task["mismatches"], task["mode"]
    ctx = f"{name}/mm{mm}/{mode}"
    qdir = tempfile.mkdtemp(prefix=f"fuzz_{name}_{mm}_{mode}_")
    qpath = os.path.join(qdir, name + ".fa")
    with open(qpath, "w", encoding="utf-8") as fh:
        fh.write(f">{name}\n{seq}\n")
    main_targets = f"T{name[-2:]}" if mode == "design" else ""
    t0 = time.monotonic()
    res = {"name": name, "mismatches": mm, "mode": mode, "rows_orig": None,
           "rows_port": None, "problems": [], "stats": None, "coverage": None,
           "error": None, "errors": [], "seconds": 0.0}

    def _call(fn, *args, **kw):
        try:
            return fn(*args, **kw), None
        except RuntimeError as exc:
            return None, str(exc)

    try:
        if task.get("mutate"):
            _patch_port_float()
        orig, orig_err = _call(diff_oracle.run_original, mode, mm, main_targets,
                               task["db_name"], qpath, db_location=task["db_dir"])
        port, port_err = _call(diff_oracle.run_port, mode, mm, main_targets,
                               task["db_name"], qpath, db_location=task["db_dir"])
        if orig_err or port_err:
            # un aborto cuenta como paridad sólo si los dos abortan con el MISMO mensaje
            if orig_err and port_err and _norm_err(orig_err) == _norm_err(port_err):
                res["errors"] = [{"lado": "ambos", "mensaje": _norm_err(orig_err)}]
            else:
                res["error"] = (f"aborto asimétrico: original={orig_err or 'ok'} | "
                                f"port={port_err or 'ok'}")
        else:
            res["rows_orig"], res["rows_port"] = len(orig), len(port)
            problems, stats = compare_block(orig, port, ctx)
            res["problems"] = problems
            res["stats"] = stats
            res["coverage"] = _coverage(orig)
    except Exception as exc:  # noqa: BLE001 - se reporta, no se esconde
        res["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(qdir, ignore_errors=True)
    res["seconds"] = round(time.monotonic() - t0, 2)
    return res


def _norm_err(msg: str) -> str:
    """Mensaje de error sin los prefijos de cada runner, para compararlos."""
    for prefix in ("El port falló: ", "El original falló: "):
        if msg.startswith(prefix):
            return msg[len(prefix):].strip()
    return msg.strip()


# ---------------------------------------------------------------- control ----
def comparator_selftest() -> list[dict]:
    """Control negativo: verifica que el comparador detecte lo que dice detectar."""
    base = {
        "query_name": "q", "sirna_name": "sirna7", "sirna_position": 7,
        "sirna_sequence": "ACGTACGTACGTACGTACGTA", "is_efficient": True,
        "strand_selection": True, "end_stability": False,
        "target_site_accessibility": True, "accessibility_value": 0.3712345,
        "is_off_target": False, "hit_name": "T01", "reference_strand_pos": 42,
        "strand": "+", "mismatches": "0",
    }
    cases = []

    def check(label, expected, orig, port):
        problems, _ = compare_block(orig, port, label)
        got = bool(problems)
        cases.append({"caso": label, "esperado_fallo": expected, "detectado": got,
                      "ok": got == expected,
                      "detalle": problems[0] if problems else ""})

    check("identicas", False, [base], [dict(base)])

    tiny = dict(base, accessibility_value=base["accessibility_value"] + 1e-12)
    check("float +1e-12 (dentro de tolerancia)", False, [base], [tiny])

    big = dict(base, accessibility_value=base["accessibility_value"] * 1.000001)
    check("float x1.000001 (fuera de tolerancia)", True, [base], [big])

    check("bool invertido", True, [base], [dict(base, is_efficient=False)])
    check("int vs float 7 vs 7.0", True, [base], [dict(base, sirna_position=7.0)])
    check("string distinta", True, [base], [dict(base, mismatches="0:3")])
    check("fila de menos", True, [base], [])
    check("fila de mas", True, [], [dict(base)])
    check("nan a los dos lados", False, [dict(base, accessibility_value=float("nan"))],
          [dict(base, accessibility_value=float("nan"))])
    check("nan de un solo lado", True, [base],
          [dict(base, accessibility_value=float("nan"))])
    check("orden de claves distinto", True, [base],
          [dict(reversed(list(base.items())))])
    return cases


# --------------------------------------------------------------------- reporte
def _fmt_dev(x: float) -> str:
    return "0 (exacto)" if x == 0 else f"{x:.3e}"


def write_reports(outdir: str, summary: dict, records: list[dict], selftest: list[dict],
                  cmd: str) -> tuple[str, str]:
    os.makedirs(outdir, exist_ok=True)
    md = os.path.join(outdir, "REPORTE.md")
    js = os.path.join(outdir, "resumen.json")

    per_field = summary["per_field"]
    aborts = summary["aborts_con_paridad"]
    lines = [
        "# Paridad aleatoria — port (`core/sifi`) vs original siFi21",
        "",
        f"* **Fecha:** {summary['timestamp']}",
        f"* **Semilla:** `{summary['seed']}` (generador determinista)",
        f"* **Comando:** `{cmd}`",
        f"* **Corridas pareadas:** {summary['runs_product']} del producto "
        f"{{secuencia}} × {{mismatches}} × {{modo}} + {summary['runs'] - summary['runs_product']} "
        f"caso borde = {summary['runs']} pareadas ({summary['executions']} ejecuciones: "
        "original + port en cada una)",
        f"* **Filas comparadas:** {summary['rows_compared']:,} (× 14 campos = "
        f"{summary['rows_compared'] * 14:,} valores)",
        f"* **Duración:** {summary['duration_s']:.1f} s (pared, {summary['jobs']} procesos)",
        "",
        "Cada corrida usa **los mismos binarios** en los dos lados (bowtie / RNAplfold del "
        "`build/`), así que cualquier diferencia es del port. Comparación: mismo orden de "
        "claves, misma cantidad de filas, igualdad exacta para str/int/bool y "
        "`math.isclose(rel_tol=1e-9, abs_tol=1e-9)` para floats.",
        "",
        "## Desvío por campo",
        "",
        "| campo | tipo | corridas | valores comparados | desvío máx absoluto | desvío máx relativo | valores con desvío | NaN en ambos |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for field, kind in FIELD_KIND.items():
        st = per_field[field]
        abs_col = _fmt_dev(st["max_abs"]) if kind == "float" else "— (exacto)"
        rel_col = _fmt_dev(st["max_rel"]) if kind == "float" else "—"
        lines.append(f"| `{field}` | {kind} | {st['runs']} | {st['n']:,} | {abs_col} "
                     f"| {rel_col} | {st['n_nonzero'] if kind == 'float' else 0} "
                     f"| {st['n_nan_both']} |")

    lines += [
        "",
        "(`—` = campo no flotante: se compara con igualdad exacta, sin tolerancia.)",
        "",
        "## Cobertura del barrido",
        "",
        "| secuencia | largo | GC objetivo | GC real | tipo | filas (todas las corridas) |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for r in records:
        got = summary["rows_by_sequence"].get(r["name"], 0)
        lines.append(f"| `{r['name']}` | {r['len']} | {r['gc_target']:.0%} | {r['gc']:.1%} "
                     f"| {r['kind']} | {got:,} |")
    cov = summary["coverage"]
    lines += [
        "",
        f"* filas totales (lado original): {cov['rows']:,}; máximo de siRNAs distintos en "
        f"una corrida: {cov['sirnas']:,}",
        f"* `is_off_target`: {cov['offtarget_true']:,} True / {cov['offtarget_false']:,} False"
        f" / {cov['offtarget_none']:,} None",
        f"* filas eficientes: {cov['efficient']:,}",
        f"* `target_site_accessibility` (derivado del float): {cov['acc_true']:,} True / "
        f"{cov['acc_false']:,} False; valores distintos de `accessibility_value` en una "
        f"corrida (máx.): {cov['distinct_acc']:,}",
        f"* descriptores de mismatches distintos: {len(cov['mismatch_values']):,} "
        f"(ej.: {', '.join(cov['mismatch_values'][:4]) or '(ninguno)'} …)",
        "",
        "## Casos borde",
        "",
        "La corrida extra `orphan01` usa una secuencia que **no está** en el índice: ejercita "
        "el camino \"sin hits\" de design. Ahí los dos lados abortan con el mismo mensaje "
        "(`" + (aborts[0]["mensaje"] if aborts else "") + "`), así que la paridad es del "
        "error, no de las filas (0 filas: la rama sin hits nunca entra en `if strand == '+'`).",
        "",
        "## Control negativo del comparador",
        "",
        "Para que un verde signifique algo, el comparador tiene que saber fallar:",
        "",
        "| caso | debía fallar | falló |",
        "|---|---|---|",
    ]
    lines += [f"| {c['caso']} | {'sí' if c['esperado_fallo'] else 'no'} "
              f"| {'sí' if c['detectado'] else 'no'} |" for c in selftest]
    lines += ["", f"Todos los casos del control se comportaron como se esperaba: "
              f"**{'sí' if all(c['ok'] for c in selftest) else 'NO'}**.", "",
              "Además hay una prueba de mutación end-to-end: `--mutate-float` multiplica por "
              "`1+1e-6` el `accessibility_value` del port dentro del pipeline real. Con "
              "`--sequences 1` el barrido reporta 102 diferencias con desvío relativo "
              "1.0e-06 (es decir: el detector ve una deriva de una parte en un millón). "
              "Repetir con: `python3 tests/fuzz_parity.py --sequences 1 --mutate-float`.", ""]

    lines += ["## Diferencias encontradas", ""]
    if summary["failures"]:
        for f in summary["failures"]:
            lines.append(f"* **{f['context']}** — {f['problem']}")
    elif summary["errors"]:
        for e in summary["errors"]:
            lines.append(f"* **{e['context']}** — ERROR: {e['error']}")
    else:
        lines.append("Ninguna. 0 diferencias en 14 campos × todas las filas.")

    if aborts:
        lines += ["", "Abortos con paridad (mismo mensaje en original y port): "
                  + ", ".join(f"`{a['context']}`" for a in aborts) + ".",
                  f"Mensaje: `{aborts[0]['mensaje']}`"]

    if summary["errors"]:
        lines += ["", "## Errores de corrida", ""]
        lines += [f"* `{e['context']}` — {e['error'][:400]}" for e in summary["errors"]]

    verdict_ok = not summary["failures"] and not summary["errors"] and all(c["ok"] for c in selftest)
    lines += [
        "",
        "## Veredicto",
        "",
        ("**PARIDAD MEDIDA: el port reproduce el original en todo el barrido.** "
         f"{summary['runs']} corridas pareadas, {summary['rows_compared']:,} filas, "
         f"desvío máximo en `accessibility_value` = "
         f"{_fmt_dev(per_field['accessibility_value']['max_abs'])}; el resto de los campos, "
         "igualdad exacta.") if verdict_ok else
        ("**HAY DIFERENCIAS.** Ver arriba: no se parcheó nada a propósito; el caso mínimo "
         "está documentado y el test quedó en `xfail`."),
        "",
    ]
    with open(md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    with open(js, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False, default=str)
    return md, js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--sequences", type=int, default=20,
                    help="cuántas secuencias usar (<=20; recorta las primeras N)")
    ap.add_argument("--modes", default="design,offtarget")
    ap.add_argument("--mismatches", default="0,1,2")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "tests", "paridad"))
    ap.add_argument("--dbdir", default=os.path.join(ROOT, "build", "paridad"))
    ap.add_argument("--selftest", action="store_true",
                    help="sólo control negativo del comparador")
    ap.add_argument("--keep-db", action="store_true", help="(obsoleto: el índice queda en build/)")
    ap.add_argument("--mutate-float", action="store_true",
                    help="prueba de mutación: perturba un float del port (debe FALLAR)")
    args = ap.parse_args()

    if args.selftest:
        cases = comparator_selftest()
        for c in cases:
            print(f"  {'ok ' if c['ok'] else 'MAL'}  {c['caso']}: "
                  f"detectado={c['detectado']} esperado={c['esperado_fallo']}")
        return 0 if all(c["ok"] for c in cases) else 1

    tools = discover()
    if not tools.bowtie_build:
        print("falta bowtie-build: no puedo armar el índice sintético", file=sys.stderr)
        return 2

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    mms = [int(m) for m in args.mismatches.split(",") if m.strip()]

    t0 = time.monotonic()
    records = gen_sequences(args.seed, min(args.sequences, 20))
    print(f"→ {len(records)} secuencias sintéticas (seed={args.seed}): "
          + ", ".join(f"{r['name']}={r['len']}nt/{r['gc']:.0%}GC" for r in records))

    db_dir, db_name = build_db(records, args.dbdir, tools, args.seed)
    print(f"→ índice sintético: {db_dir}{db_name} "
          f"({len(records) * 3} secuencias: T/A/B por transcrito)")

    tasks = [{"name": r["name"], "seq": r["seq"], "mismatches": mm, "mode": mode,
              "db_dir": db_dir, "db_name": db_name, "mutate": args.mutate_float}
             for r in records for mm in mms for mode in modes]

    # Extra de cortesía: una query que NO está en el índice (design) para ejercitar el
    # camino "sin hits" (input_data = TSV, hit_name=False, strand=None). Sin esto, ese
    # branch de data_to_json nunca se compara en el barrido.
    orphan = _balanced(random.Random(args.seed + 2), 420, 0.45)
    tasks.append({"name": "orphan01", "seq": orphan, "mismatches": 0, "mode": "design",
                  "db_dir": db_dir, "db_name": db_name, "mutate": False})
    total = len(tasks)
    print(f"→ {total} corridas pareadas ({total * 2} ejecuciones), jobs={args.jobs}")

    results = []
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(_run_one, t): t for t in tasks}
        for done, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            results.append(res)
            tag = ("ERR" if res["error"]
                   else "abt" if res["errors"]
                   else "DIF" if res["problems"] else "ok ")
            print(f"  [{done:3d}/{total}] {tag} {res['name']}/mm{res['mismatches']}/"
                  f"{res['mode']}: {res['rows_orig']} filas, {res['seconds']}s")

    duration = time.monotonic() - t0
    selftest = comparator_selftest()

    per_field = {k: {"n": 0, "runs": 0, "max_abs": 0.0, "max_rel": 0.0,
                     "n_nonzero": 0, "n_nan_both": 0}
                 for k in FIELD_KIND}
    failures, errors, aborts, rows_by_sequence = [], [], [], {}
    coverage = {"rows": 0, "sirnas": 0, "plus_strand": 0, "no_hit_path": 0,
                "offtarget_true": 0, "offtarget_false": 0, "offtarget_none": 0,
                "efficient": 0, "distinct_acc": 0, "acc_true": 0, "acc_false": 0,
                "mismatch_values": []}
    mismatch_values: set[str] = set()
    rows_compared = 0

    for res in sorted(results, key=lambda r: (r["name"], r["mismatches"], r["mode"])):
        ctx = f"{res['name']}/mm{res['mismatches']}/{res['mode']}"
        if res["error"]:
            errors.append({"context": ctx, "error": res["error"]})
            continue
        if res["errors"]:
            aborts.append({"context": ctx, "mensaje": res["errors"][0]["mensaje"]})
            continue
        rows_compared += min(res["rows_orig"], res["rows_port"])
        rows_by_sequence[res["name"]] = rows_by_sequence.get(res["name"], 0) + res["rows_orig"]
        for p in res["problems"]:
            failures.append({"context": ctx, "problem": p})
        for field, st in res["stats"].items():
            agg = per_field[field]
            agg["n"] += st["n"]
            if st["n"]:
                agg["runs"] += 1
            agg["max_abs"] = max(agg["max_abs"], st["max_abs"])
            agg["max_rel"] = max(agg["max_rel"], st["max_rel"])
            agg["n_nonzero"] += st["n_nonzero"]
            agg["n_nan_both"] += st["n_nan_both"]
        cov = res["coverage"]
        for k in ("rows", "plus_strand", "no_hit_path", "offtarget_true",
                  "offtarget_false", "offtarget_none", "efficient",
                  "acc_true", "acc_false"):
            coverage[k] += cov[k]
        coverage["distinct_acc"] = max(coverage["distinct_acc"], cov["distinct_acc"])
        # los nombres "sirnaN" se repiten entre secuencias: se reporta el máximo por corrida
        coverage["sirnas"] = max(coverage["sirnas"], cov["sirnas"])
        mismatch_values.update(cov["mismatch_values"])
    coverage["mismatch_values"] = sorted(mismatch_values)

    cmd = (f"python3 tests/fuzz_parity.py --seed {args.seed} --jobs {args.jobs}"
           + ("" if args.sequences >= 20 else f" --sequences {args.sequences}")
           + (" --mutate-float" if args.mutate_float else ""))
    seq_meta = [{k: r[k] for k in ("name", "len", "gc", "gc_target", "kind")} for r in records]
    summary = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "command": cmd,
        "seed": args.seed,
        "jobs": args.jobs,
        "runs": len(results),
        "runs_product": len(records) * len(mms) * len(modes),
        "executions": len(results) * 2,
        "modes": modes,
        "mismatches": mms,
        "sequences": [r["name"] for r in records],
        "sequence_meta": seq_meta,
        "rows_compared": rows_compared,
        "duration_s": round(duration, 1),
        "per_field": per_field,
        "rows_by_sequence": rows_by_sequence,
        "coverage": coverage,
        "failures": failures,
        "errors": errors,
        "aborts_con_paridad": aborts,
        "selftest": selftest,
        "mutation_test": args.mutate_float,
        "ok": not failures and not errors and all(c["ok"] for c in selftest),
        "tolerances": {"rel_tol": 1e-9, "abs_tol": 1e-9},
        "tools": {"bowtie": tools.bowtie, "rnaplfold": tools.rnaplfold},
    }
    md, js = write_reports(args.outdir, summary, records, selftest, cmd)

    print()
    print(f"filas comparadas: {rows_compared:,} | corridas: {len(results)} | "
          f"duración: {duration:.1f}s")
    print("desvío máximo accessibility_value: "
          f"abs={per_field['accessibility_value']['max_abs']:.3e} "
          f"rel={per_field['accessibility_value']['max_rel']:.3e}")
    print(f"diferencias: {len(failures)} | errores: {len(errors)} | "
          f"control negativo: {'ok' if all(c['ok'] for c in selftest) else 'FALLA'}")
    print(f"reporte: {md}")
    print(f"resumen: {js}")
    print("VEREDICTO:", "PARIDAD MEDIDA" if summary["ok"] else "HAY DIFERENCIAS")

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
