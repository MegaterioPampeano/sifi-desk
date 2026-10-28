"""El scoring tiene que estar en el manifest y cerrar contra sus propios pesos."""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from sifi.run import rescore_manifest  # noqa: E402
from sifi.scoring import load_params  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "data", "results_fixture.json")


@pytest.fixture(scope="module")
def manifest():
    with open(FIXTURE, encoding="utf-8") as fh:
        return rescore_manifest(json.load(fh))


def test_manifest_declara_version_y_hash(manifest):
    sc = manifest["scoring"]
    assert sc["version"] == 2
    assert sc["schema"] == "sifi.score/2"
    assert len(sc["yaml_sha256"]) == 64
    assert abs(sum(sc["pesos"].values()) - 100) < 1e-9


def test_cada_candidato_cierra_contra_sus_pesos(manifest):
    params = load_params()
    for rec in manifest["records"]:
        for cand in rec["candidates"]:
            total = 0.0
            for eje, d in cand["desglose"].items():
                assert d["peso"] == params["pesos"][eje]
                assert 0.0 <= d["valor"] <= 1.0
                assert d["aporte"] == pytest.approx(d["peso"] * d["valor"], abs=1e-9)
                total += d["aporte"]
            assert cand["total"] == pytest.approx(total, abs=0.01)


def test_candidatos_ordenados_y_banda_coherente(manifest):
    rec = manifest["records"][0]
    totales = [c["total"] for c in rec["candidates"]]
    assert totales == sorted(totales, reverse=True)
    for c in rec["candidates"]:
        if c["total"] >= 70:
            assert c["banda"] == "recomendado"
        elif c["total"] >= 50:
            assert c["banda"] == "revisar"


def test_resumen_cuenta_todas_las_bandas(manifest):
    rec = manifest["records"][0]
    s = rec["scoring"]
    assert s["n"] == len(rec["candidates"])
    assert sum(s["por_banda"].values()) == s["n"]
    assert s["mejor"] == rec["candidates"][0]["id"]
    assert s["mejor_total"] == rec["candidates"][0]["total"]


def test_no_inventa_scoring_sin_filas():
    """Una corrida sin sirnas (p.ej. sin hits) no debe fabricar candidatos."""
    vacio = {"schema": "sifi.results/1", "records": [
        {"query_name": "X", "query_length": 10, "sirnas": [], "error": "sin hits"}]}
    out = rescore_manifest(vacio)
    assert out["records"][0]["candidates"] == []
    assert out["records"][0]["scoring"]["n"] == 0
    assert out["records"][0]["scoring"]["mejor"] is None
