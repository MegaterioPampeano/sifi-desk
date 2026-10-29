"""Tests de relevancia: cómo se arma la query de PubMed y qué descarta Crossref.

Dos decisiones que valen un test propio porque son las que separan un digest útil de
una lista de ruido:

1. PubMed hace **AND** de todas las palabras, así que el `text` suelto devolvía cero.
   Se usa `pubmed_term` cuando está configurado (sintaxis PubMed con OR/AND).
2. Crossref ordena por relevancia pero igual cuela papers de otro tema; con
   `keywords` configuradas se descarta lo que no matchea ninguna (`strict`, default true).
"""
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from watch import cli, sources  # noqa: E402


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, url, params, headers, timeout):
        self.calls.append({"url": url, "params": dict(params)})
        return 200, {}, json.dumps(self.payload)


def crossref_payload(*titles):
    items = []
    for i, title in enumerate(titles):
        items.append({
            "DOI": f"10.9999/test.{i}",
            "title": [title],
            "issued": {"date-parts": [[2026, 10, 20]]},
            "URL": f"https://doi.org/10.9999/test.{i}",
            "container-title": ["Journal of Tests"],
            "author": [{"family": "Test", "given": "A."}],
            "abstract": "",
            "score": 10.0 - i,
        })
    return {"message": {"items": items, "total-results": len(items)}}


def query(**kw):
    base = {"id": "q", "text": "RNAi dsRNA insect pest control", "why": "porque sí",
            "keywords": ["RNAi", "dsRNA", "insect", "pest"]}
    base.update(kw)
    return base


def test_pubmed_usa_pubmed_term_configurado():
    transport = FakeTransport({"esearchresult": {"idlist": []}})
    client = sources.HttpClient(transport=transport, sleep=lambda s: None)
    q = query(pubmed_term='(RNAi[tiab] OR dsRNA[tiab]) AND (insect*[tiab])',
              keywords=["RNAi"])
    # `until` explícito: sin esto el test depende del día en que se corre
    # (fetch_pubmed usa today_utc() y fallaba al cambiar la fecha).
    assert sources.fetch_pubmed(q, date(2026, 10, 21), 5, client,
                                until=date(2026, 10, 28)) == []

    term = transport.calls[0]["params"]["term"]
    assert term.startswith('(RNAi[tiab] OR dsRNA[tiab]) AND (insect*[tiab])')
    assert '"2026-10-21"[PDAT]' in term and '"2026-10-28"[PDAT]' in term


def test_pubmed_sin_pubmed_term_envuelve_el_text():
    term = sources._pubmed_term(query(), date(2026, 10, 21), date(2026, 10, 28))
    assert term.startswith("(RNAi dsRNA insect pest control)")
    assert "[PDAT]" in term


def test_crossref_strict_descarta_lo_que_no_matchea_keywords():
    payload = crossref_payload(
        "RNAi-mediated control of aphids",
        "Role-based access control with JWT claims",
        "dsRNA delivery to insect cells",
    )
    client = sources.HttpClient(transport=FakeTransport(payload), sleep=lambda s: None)
    items = sources.fetch_crossref(query(), date(2026, 10, 1), 10, client)
    titles = [it["title"] for it in items]
    assert len(items) == 2
    assert "RNAi-mediated control of aphids" in titles
    assert not any("JWT" in t for t in titles)
    assert all(it["matched_terms"] for it in items)


def test_crossref_strict_false_deja_pasar_todo():
    payload = crossref_payload("RNAi in aphids", "Role-based access control with JWT claims")
    client = sources.HttpClient(transport=FakeTransport(payload), sleep=lambda s: None)
    items = sources.fetch_crossref(query(strict=False), date(2026, 10, 1), 10, client)
    assert len(items) == 2
    assert [it["matched_terms"] for it in items][1] == []


def test_crossref_sin_keywords_no_filtra():
    payload = crossref_payload("Algo sin relación aparente")
    client = sources.HttpClient(transport=FakeTransport(payload), sleep=lambda s: None)
    items = sources.fetch_crossref(query(keywords=[]), date(2026, 10, 1), 10, client)
    assert len(items) == 1


def test_crossref_descarta_anios_imposibles():
    payload = crossref_payload("RNAi en insectos del futuro")
    payload["message"]["items"][0]["issued"] = {"date-parts": [[2117, 1, 1]]}
    client = sources.HttpClient(transport=FakeTransport(payload), sleep=lambda s: None)
    assert sources.fetch_crossref(query(), date(2026, 10, 1), 10, client,
                                  until=date(2026, 10, 28)) == []


def test_abstract_acotado_a_1200_chars():
    item = sources.make_item(source="biorxiv", title="x", abstract="a" * 5000)
    assert len(item["abstract"]) == 1200


def test_config_real_tiene_pubmed_term_para_las_queries_de_pubmed():
    cfg = cli.load_config()
    for q in cfg["queries"]:
        if "pubmed" in q["sources"] and "github" not in q["sources"]:
            assert q.get("pubmed_term"), f"{q['id']} sin pubmed_term (PubMed haría AND de todo)"
            assert "[tiab]" in q["pubmed_term"]
