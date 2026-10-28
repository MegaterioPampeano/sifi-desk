"""Tests del scoring v2 (paso 2.2).

Lo que se prueba no es "que dé lindo" sino que el número sea auditable:
* el desglose cierra exacto contra el total con los pesos declarados;
* más eficiencia no puede dar menos score (monotonía);
* un hit perfecto en humano/no-blanco castiga el riesgo aunque el resto sea bueno;
* el score propio de siFi, cuando viene, mueve el eje T;
* faltantes (``NA``) se marcan, no se inventan como cero.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from sifi.scoring import (  # noqa: E402
    EJE_ORDEN,
    ScoringError,
    load_params,
    score_candidates,
    summarize,
)

FIXTURE = os.path.join(ROOT, "tests", "data", "results_fixture.json")


@pytest.fixture(scope="module")
def results():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def scored(results):
    return score_candidates(results, panel_roles={"humano": "control", "maiz": "no_blanco"})


def _by_id(scored, sid):
    return next(r for r in scored if r["id"] == sid)


def test_pesos_versionados():
    p = load_params()
    assert p["version"] == 2
    assert p["schema"] == "sifi.score/2"
    assert sum(float(p["pesos"][e]) for e in EJE_ORDEN) == pytest.approx(100.0)


def test_desglose_cierra_contra_el_total(scored):
    for r in scored:
        aportes = [r["desglose"][e]["aporte"] for e in EJE_ORDEN]
        # el total se publica redondeado al centésimo: la suma exacta cierra a media unidad
        assert sum(aportes) == pytest.approx(r["total"], abs=0.005)
        for e in EJE_ORDEN:
            d = r["desglose"][e]
            assert 0.0 <= d["valor"] <= 1.0
            assert d["aporte"] == pytest.approx(d["peso"] * d["valor"], abs=1e-9)


def test_monotonicidad_en_eficiencia(scored):
    # mismas condiciones salvo accesibilidad/hebra/extremo (0.90 → 0.60 → 0.20)
    alta, media, baja = (_by_id(scored, s) for s in ("sirna10", "sirna20", "sirna30"))
    assert alta["total"] > media["total"] > baja["total"]
    assert alta["banda"] == "recomendado"


def test_orden_por_total(scored):
    totales = [r["total"] for r in scored]
    assert totales == sorted(totales, reverse=True)


def test_hit_perfecto_en_control_castiga_riesgo(scored):
    baja = _by_id(scored, "sirna30")
    assert baja["desglose"]["R"]["valor"] < 0.35          # riesgo alto
    assert "riesgo_alto" in baja["notas"]
    assert "hit_perfecto" in baja["notas"]
    assert baja["n_hits"] == 2
    assert baja["desglose"]["S"]["valor"] < 0.4           # dos hits perfectos


def test_hit_contra_patogeno_no_es_riesgo():
    rows = [{
        "sirna_name": "s1", "sirna_position": 1, "sirna_sequence": "ATGCGATCGATCGTAGCTAGC",
        "is_efficient": True, "strand_selection": True, "end_stability": True,
        "accessibility_value": 0.8, "is_off_target": True, "hit_name": "pat_1",
        "panel": "patogeno", "mismatches": 0,
    }]
    r = score_candidates(rows, panel_roles={"patogeno": "patogeno"})[0]
    assert r["desglose"]["R"]["valor"] == pytest.approx(1.0)   # pegarle al patógeno no resta
    assert r["desglose"]["S"]["valor"] < 1.0                    # pero sí es un hit


def test_rol_desconocido_es_conservador():
    rows = [{
        "sirna_name": "s1", "sirna_position": 1, "sirna_sequence": "ATGCGATCGATCGTAGCTAGC",
        "is_efficient": True, "accessibility_value": 0.8, "is_off_target": True,
        "hit_name": "x", "mismatches": 0,
    }]
    r = score_candidates(rows)[0]
    # sin rol declarado no se asume que el hit es inofensivo: 0.8 de peso
    assert r["desglose"]["R"]["valor"] == pytest.approx(0.2, abs=1e-6)


def test_el_main_target_no_cuenta_como_offtarget(scored):
    assert _by_id(scored, "sirna10")["n_hits"] == 0
    assert _by_id(scored, "sirna40")["n_hits"] == 0


def test_diseno_penaliza_gc_y_homopolimeros(scored):
    malo, bueno = _by_id(scored, "sirna40"), _by_id(scored, "sirna10")
    assert malo["desglose"]["D"]["valor"] < bueno["desglose"]["D"]["valor"]
    assert malo["desglose"]["D"]["detalle"]["homopolimero"] >= 4
    assert "homopolimero" in malo["notas"]
    assert "gc_fuera_rango" in malo["notas"]


def test_score_de_sifi_mueve_el_eje_t():
    base = {
        "sirna_name": "s1", "sirna_position": 1, "sirna_sequence": "ATGCGATCGATCGTAGCTAGC",
        "is_efficient": True, "strand_selection": True, "end_stability": True,
        "accessibility_value": 0.8,
    }
    sin = score_candidates([dict(base)])[0]
    con = score_candidates([dict(base, score=0.4)])[0]
    assert con["desglose"]["T"]["valor"] < sin["desglose"]["T"]["valor"]
    assert sin["desglose"]["T"]["valor"] == pytest.approx(1.0)


def test_na_se_marca_y_no_vale_cero(scored):
    r = _by_id(scored, "sirna90")
    assert "sin_accesibilidad" in r["notas"]
    # con el valor declarado (0.5), el eje E no colapsa a 0
    assert r["desglose"]["E"]["valor"] >= 0.5


def test_override_de_pesos_y_ejes(scored):
    solo_e = score_candidates(
        [{"sirna_name": "s1", "sirna_position": 1,
          "sirna_sequence": "ATGCGATCGATCGTAGCTAGC", "is_efficient": True,
          "accessibility_value": 1.0, "strand_selection": True, "end_stability": True}],
        params={"E": {"acceso": 1.0, "hebra": 0.0, "extremo": 0.0}},
    )[0]
    assert solo_e["desglose"]["E"]["valor"] == pytest.approx(1.0)
    assert solo_e["desglose"]["E"]["aporte"] == pytest.approx(40.0)


def test_pesos_invalidos_fallan(results):
    with pytest.raises(ScoringError):
        score_candidates(results, params={"pesos": {"E": 10, "R": 10, "S": 10, "T": 10, "D": 10}})


def test_summarize_reproducible(scored):
    s = summarize(scored)
    assert s["n"] == len(scored)
    assert s["scoring"]["version"] == 2
    assert sum(s["por_banda"].values()) == len(scored)
