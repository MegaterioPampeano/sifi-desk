"""Paridad aleatoria: generador determinista, comparador estricto y mini-barrido.

Lo que se protege acá:
  1. **El generador es reproducible**: misma semilla => mismas secuencias, con el GC
     pedido. Si alguien cambia el generador, el `REPORTE.md` deja de ser reproducible
     y este test lo dice.
  2. **El comparador sabe fallar**: los 11 casos del control negativo (float fuera de
     tolerancia, bool invertido, fila de más/menos, NaN de un lado, orden de claves).
     Un verde del barrido no significa nada si el comparador no detecta una deriva.
  3. **Mini-barrido end-to-end** (1 secuencia × 3 mismatches × 2 modos, ~10 s): el port
     reproduce el original campo por campo contra un índice sintético. El barrido
     grande es `make paridad` (`tests/fuzz_parity.py`), fuera del ciclo corto.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import fuzz_parity  # noqa: E402
from sifi.tools import discover  # noqa: E402

TOOLS = discover()
HAVE_TOOLS = bool(TOOLS.bowtie and TOOLS.rnaplfold and TOOLS.bowtie_build)
needs_tools = pytest.mark.skipif(not HAVE_TOOLS, reason="faltan bowtie/bowtie-build/RNAplfold")


def test_generador_reproducible_y_con_gc_pedido():
    a = fuzz_parity.gen_sequences(20261028, 20)
    b = fuzz_parity.gen_sequences(20261028, 20)
    assert [r["seq"] for r in a] == [r["seq"] for r in b]

    c = fuzz_parity.gen_sequences(20261029, 20)
    assert [r["seq"] for r in a] != [r["seq"] for r in c]

    assert len(a) == 20
    for r in a:
        assert 300 <= r["len"] <= 600, r["name"]
        assert abs(r["gc"] - r["gc_target"]) < 0.02, (r["name"], r["gc"])
        assert len(r["seq"]) == r["len"]

    # las dos secuencias "especiales" que pide el barrido
    kinds = {r["kind"] for r in a}
    assert "homopolimero A/T" in kinds
    assert "GC con repeticiones" in kinds
    # las cuatro clases de GC están representadas
    assert {round(r["gc_target"], 2) for r in a} == {0.30, 0.45, 0.60, 0.70}


def test_generador_recorte_documentado():
    """`--sequences N` toma las primeras N: las mismas de la corrida completa."""
    full = fuzz_parity.gen_sequences(20261028, 20)
    for n in (1, 5, 8):
        part = fuzz_parity.gen_sequences(20261028, n)
        assert [r["seq"] for r in part] == [r["seq"] for r in full[:n]]


def test_comparador_detecta_deriva():
    for caso in fuzz_parity.comparator_selftest():
        assert caso["ok"], f"{caso['caso']}: detectado={caso['detectado']} " \
                            f"esperado={caso['esperado_fallo']}"


@needs_tools
def test_mini_barrido_paridad(tmp_path, monkeypatch):
    argv = ["fuzz_parity.py", "--seed", "20261028", "--jobs", "2", "--sequences", "1",
            "--outdir", str(tmp_path), "--dbdir", str(tmp_path / "db")]
    monkeypatch.setattr(sys, "argv", argv)
    rc = fuzz_parity.main()
    assert rc == 0
    informe = (tmp_path / "REPORTE.md").read_text(encoding="utf-8")
    assert "PARIDAD MEDIDA" in informe
    resumen = (tmp_path / "resumen.json").read_text(encoding="utf-8")
    assert '"rows_compared"' in resumen
