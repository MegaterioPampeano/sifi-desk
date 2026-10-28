"""Tests de `watch.sources` (frente M7) — sin red, con fixtures grabadas.

Lo que se prueba es el contrato con el resto del frente: parseo de cada fuente,
filtro local de bioRxiv, ventana de GitHub, y las garantías del cliente HTTP
(caché, reintentos con backoff, `Retry-After`, offline y errores no reintentables).
Ningún test abre un socket: todo pasa por un `transport` inyectado.
"""
import json
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from watch import sources  # noqa: E402

FIXTURES = os.path.join(ROOT, "core", "watch", "fixtures")

QUERY = {
    "id": "rnai-insect-pest",
    "text": "RNAi insect pest control",
    "why": "RNAi en insectos plaga.",
    "keywords": ["RNAi", "dsRNA", "insect", "pest"],
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def fixture_name_for(url):
    if "crossref" in url:
        return "crossref_rnai.json"
    if "esearch" in url:
        return "pubmed_esearch.json"
    if "esummary" in url:
        return "pubmed_esummary.json"
    if "biorxiv" in url:
        return "biorxiv_details.json"
    if "github" in url:
        return "github_releases.json"
    raise AssertionError(f"URL no grabada en fixtures: {url}")


class FakeTransport:
    """Transport HTTP que devuelve fixtures grabadas y cuenta los requests."""

    def __init__(self, status=200):
        self.calls = []
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def __call__(self, url, params, headers, timeout):
        name = fixture_name_for(url)
        self.calls.append((url, dict(params)))
        return self.status, dict(self.headers), open(
            os.path.join(FIXTURES, name), encoding="utf-8").read()


def client(transport=None, **kw):
    kw.setdefault("sleep", lambda _s: None)
    return sources.HttpClient(transport=transport or FakeTransport(), **kw)


# --------------------------------------------------------------------------- #
# User-Agent y normalización
# --------------------------------------------------------------------------- #

def test_user_agent_identificable(monkeypatch):
    monkeypatch.delenv("SIFI_WATCH_CONTACT", raising=False)
    ua = sources.user_agent()
    assert ua.startswith("sifi-desk/")
    assert "mailto:" in ua and sources.DEFAULT_CONTACT in ua

    monkeypatch.setenv("SIFI_WATCH_CONTACT", "otro@ejemplo.org")
    assert "otro@ejemplo.org" in sources.user_agent()
    assert "explicito@ejemplo.org" in sources.user_agent("explicito@ejemplo.org")


def test_normalize_title_colapsa_puntuacion_y_acentos():
    a = sources.normalize_title("RNAi-based control of Dalbulus maidis!")
    b = sources.normalize_title("RNAi based control of  Dalbulus  maidis")
    assert a == b
    assert sources.normalize_text("Chicharrita del Maíz") == "chicharrita del maiz"


def test_matched_terms_respeta_bordes_de_palabra():
    assert sources.matched_terms("RNAi silencing in insects", ["RNAi", "insect"]) == [
        "RNAi", "insect"]
    # `RNAi` no debe matchear dentro de otra palabra, ni `pest` dentro de `pesticide`
    assert sources.matched_terms("RNAinterference-ish pesticides", ["RNAi", "pest"]) == []


def test_item_id_prioriza_doi_y_cae_a_titulo():
    assert sources.item_id({"doi": "10.1/ABC", "title": "x"}) == "doi:10.1/abc"
    assert sources.item_id({"pmid": "123"}) == "pmid:123"
    assert sources.item_id({"title": "Hola, Mundo!"}) == "title:hola mundo"


# --------------------------------------------------------------------------- #
# Crossref
# --------------------------------------------------------------------------- #

def test_fetch_crossref_parsea_la_fixture():
    transport = FakeTransport()
    items = sources.fetch_crossref(QUERY, date(2026, 1, 1), 25, client(transport))

    raw = load_fixture("crossref_rnai.json")["message"]["items"]
    expected = [r for r in raw if (r.get("title") or [""])[0].strip()]
    assert len(items) == len(expected)
    assert all(it["source"] == "crossref" for it in items)
    first = items[0]
    assert first["doi"] == raw[0]["DOI"].lower()
    assert first["date"] == "2026-10-08"  # date-parts anidado, no vacío
    assert first["url"].endswith(first["doi"])
    assert "<" not in first["title"]  # HTML de Crossref fuera
    assert "" not in {it["date"] for it in items if it.get("doi")}
    assert first["query_id"] == QUERY["id"]
    assert first["matched_by"][0]["why"] == QUERY["why"]

    # el request lleva mailto y filtro de fecha
    url, params = transport.calls[0]
    assert url == sources.CROSSREF_URL
    assert params["filter"].startswith("from-pub-date:2026-01-01")
    assert "@" in params["mailto"]


def test_fetch_crossref_date_parts_plano_y_parcial():
    assert sources._iso_from_parts([[2026, 10, 27]]) == "2026-10-27"
    assert sources._iso_from_parts([2026, 10]) == "2026-10"
    assert sources._iso_from_parts([2026]) == "2026"
    assert sources._iso_from_parts(None) == ""
    assert sources._iso_from_parts([[]]) == ""


# --------------------------------------------------------------------------- #
# PubMed
# --------------------------------------------------------------------------- #

def test_fetch_pubmed_esearch_mas_esummary():
    transport = FakeTransport()
    items = sources.fetch_pubmed(QUERY, date(2026, 10, 1), 25, client(transport))

    assert [it["pmid"] for it in items] == [
        "42940970", "42940954", "42940908", "42939453", "42934163"]
    assert all(it["source"] == "pubmed" for it in items)
    assert items[0]["doi"] == "10.3390/insects17101061"
    assert items[0]["date"] == "2026-10-14"
    assert items[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/42940970/"
    assert items[0]["authors"].startswith("Cen Y")

    assert [c[0] for c in transport.calls] == [
        sources.PUBMED_ESEARCH, sources.PUBMED_ESUMMARY]
    search_params = transport.calls[0][1]
    assert "[PDAT]" in search_params["term"]
    assert "2026-10-01" in search_params["term"]
    assert transport.calls[1][1]["id"] == ",".join(it["pmid"] for it in items)


def test_fetch_pubmed_sin_ids_no_pide_summary():
    calls = []

    def empty_esearch(url, params, headers, timeout):
        calls.append(url)
        return 200, {}, json.dumps({"esearchresult": {"idlist": []}})

    assert sources.fetch_pubmed(QUERY, date(2026, 10, 1), 25,
                                client(empty_esearch)) == []
    assert calls == [sources.PUBMED_ESEARCH]


@pytest.mark.parametrize("pubdate,sortpubdate,expected", [
    ("2026 Oct 20", "", "2026-10-20"),
    ("2026 Oct", "", "2026-10"),
    ("2026", "", "2026"),
    ("2026 Oct 20", "2026/10/20 00:00", "2026-10-20"),
    ("", "", ""),
])
def test_pubmed_date(pubdate, sortpubdate, expected):
    assert sources._pubmed_date(pubdate, sortpubdate) == expected


# --------------------------------------------------------------------------- #
# bioRxiv
# --------------------------------------------------------------------------- #

def test_fetch_biorxiv_filtra_por_keywords():
    transport = FakeTransport()
    items = sources.fetch_biorxiv(QUERY, date(2026, 10, 1), 100, client(transport),
                                  until=date(2026, 10, 28), max_pages=1)

    # de los 11 preprints de la página sólo pasan los que matchean el filtro local
    n_page = len(load_fixture("biorxiv_details.json")["collection"])
    assert 0 < len(items) < n_page
    assert all(it["matched_terms"] for it in items)
    assert all(it["preprint"] is True for it in items)
    assert all(it["source"] == "biorxiv" for it in items)
    # una sola página
    assert len(transport.calls) == 1
    assert "2026-10-01/2026-10-28/0" in transport.calls[0][0]


def test_fetch_biorxiv_pagina_hasta_total():
    pages = {
        0: {"messages": [{"total": "3"}], "collection": [
            {"title": "dsRNA in insect pest control", "abstract": "x", "doi": "10.1/a",
             "date": "2026-10-27", "version": "1"},
            {"title": "nada relevante", "abstract": "y", "doi": "10.1/b",
             "date": "2026-10-27", "version": "1"}]},
        2: {"messages": [{"total": "3"}], "collection": [
            {"title": "pest management with dsRNA", "abstract": "z", "doi": "10.1/c",
             "date": "2026-10-26", "version": "2"}]},
    }
    calls = []

    def transport(url, params, headers, timeout):
        cursor = int(url.rsplit("/", 1)[1])
        calls.append(cursor)
        return 200, {}, json.dumps(pages[cursor])

    items = sources.fetch_biorxiv(QUERY, date(2026, 10, 1), 10,
                                  client(transport), until=date(2026, 10, 28),
                                  max_pages=8)
    assert calls == [0, 2]
    assert [it["doi"] for it in items] == ["10.1/a", "10.1/c"]
    # ordenado por fecha descendente
    assert items[0]["date"] >= items[1]["date"]


def test_fetch_biorxiv_respeta_max_pages():
    def transport(url, params, headers, timeout):
        return 200, {}, json.dumps({"messages": [{"total": "999"}], "collection": [
            {"title": "insect dsRNA", "abstract": "", "doi": "10.1/x",
             "date": "2026-10-27", "version": "1"}]})

    items = sources.fetch_biorxiv(QUERY, date(2026, 10, 1), 10, client(transport),
                                  until=date(2026, 10, 28), max_pages=2)
    assert len(items) == 2  # una por página, tope de páginas respetado


# --------------------------------------------------------------------------- #
# GitHub releases
# --------------------------------------------------------------------------- #

def test_fetch_github_filtra_por_ventana():
    transport = FakeTransport()
    old = sources.fetch_github_releases(QUERY, date(2026, 1, 1), 25, client(transport),
                                        repo="snowformatics/siFi21-")
    assert old == []

    fresh = sources.fetch_github_releases(QUERY, date(2016, 1, 1), 25, client(transport),
                                          repo="snowformatics/siFi21-")
    assert len(fresh) == 2
    assert fresh[0]["source"] == "github"
    assert fresh[0]["release"] is True
    assert fresh[0]["date"] == "2017-08-18"
    assert "v1.2.3" in fresh[0]["title"]
    assert "snowformatics/siFi21-" in transport.calls[-1][0]


# --------------------------------------------------------------------------- #
# cliente HTTP: caché, reintentos, offline
# --------------------------------------------------------------------------- #

def test_cache_evita_segundo_request(tmp_path):
    transport = FakeTransport()
    c = client(transport, cache=sources.DiskCache(tmp_path, ttl_hours=24))
    a = c.get_json(sources.CROSSREF_URL, {"q": "x"})
    b = c.get_json(sources.CROSSREF_URL, {"q": "x"})
    assert a == b
    assert len(transport.calls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_offline_sin_cache_falla_y_con_cache_funciona(tmp_path):
    cache = sources.DiskCache(tmp_path, ttl_hours=24)
    c = client(FakeTransport(), cache=cache)
    c.get_json(sources.CROSSREF_URL, {"q": "x"})

    offline = sources.HttpClient(cache=cache, offline=True,
                                 transport=FakeTransport())
    assert offline.get_json(sources.CROSSREF_URL, {"q": "x"})["status"] == "ok"
    with pytest.raises(sources.OfflineCacheMiss):
        offline.get_json(sources.CROSSREF_URL, {"q": "otra"})


def test_reintenta_429_respetando_retry_after():
    statuses = [429, 200]
    delays = []

    def transport(url, params, headers, timeout):
        status = statuses.pop(0)
        if status == 200:
            return 200, {}, json.dumps({"ok": True})
        return status, {"Retry-After": "3"}, "rate limited"

    c = sources.HttpClient(transport=transport, retries=3, sleep=delays.append)
    assert c.get_json("https://api.crossref.org/works", {}) == {"ok": True}
    assert delays == [3.0]


def test_no_reintenta_404():
    calls = []

    def transport(url, params, headers, timeout):
        calls.append(url)
        return 404, {}, "not found"

    c = sources.HttpClient(transport=transport, retries=3, sleep=lambda _s: None)
    with pytest.raises(sources.FetchError) as exc:
        c.get_json("https://api.crossref.org/works", {})
    assert exc.value.status == 404
    assert len(calls) == 1


def test_backoff_exponencial_si_no_hay_retry_after():
    delays = []

    def transport(url, params, headers, timeout):
        return 503, {}, "boom"

    c = sources.HttpClient(transport=transport, retries=3, backoff=1.0,
                           sleep=delays.append)
    with pytest.raises(sources.FetchError):
        c.get_json("https://api.crossref.org/works", {})
    assert len(delays) == 2  # no duerme después del último intento
    assert 1.0 <= delays[0] < 2.0
    assert 2.0 <= delays[1] < 3.0


def test_respuesta_no_json_es_error():
    c = sources.HttpClient(transport=lambda *a: (200, {}, "<html>"), sleep=lambda _s: None)
    with pytest.raises(sources.FetchError):
        c.get_json("https://api.crossref.org/works", {})


# --------------------------------------------------------------------------- #
# despacho
# --------------------------------------------------------------------------- #

def test_fetch_query_junta_fuentes_y_anota_errores():
    q = dict(QUERY, sources=["crossref", "pubmed", "inventada"])
    items, errors = sources.fetch_query(q, date(2026, 10, 1), 25, client())
    n_crossref = len(load_fixture("crossref_rnai.json")["message"]["items"])
    n_pubmed = len(load_fixture("pubmed_esummary.json")["result"]) - 1  # sin `uids`
    assert len(items) == n_crossref + n_pubmed
    assert errors == ["inventada: fuente desconocida"]


def test_fetch_query_no_tumba_la_corrida_si_una_fuente_falla():
    def transport(url, params, headers, timeout):
        if "crossref" in url:
            raise OSError("DNS caído")
        return 200, {}, open(os.path.join(FIXTURES, fixture_name_for(url)),
                             encoding="utf-8").read()

    q = dict(QUERY, sources=["crossref", "pubmed"])
    items, errors = sources.fetch_query(q, date(2026, 10, 1), 25,
                                        client(transport, retries=1))
    assert len(items) == 5
    assert len(errors) == 1 and errors[0].startswith("crossref/rnai-insect-pest:")
