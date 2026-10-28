"""Tests de `watch.cli` de punta a punta, con las APIs simuladas por fixtures.

Verifican el contrato que usa el agente (`sifi_watch`): correr, escribir el JSON,
no repetir lo ya visto, y que `--offline` funcione con la caché de la corrida anterior.
"""
import json
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from watch import cli, sources  # noqa: E402
from watch.digest import render_digest, summarize_item  # noqa: E402

FIX = os.path.join(ROOT, "core", "watch", "fixtures")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


class FakeTransport:
    def __init__(self, mapping):
        self.mapping = list(mapping)
        self.calls = []

    def __call__(self, url, params, headers, timeout):
        self.calls.append({"url": url, "params": dict(params)})
        for prefix, payload in self.mapping:
            if url.startswith(prefix):
                return 200, {}, json.dumps(payload)
        raise AssertionError(f"request inesperado: {url}")


def transport():
    return FakeTransport([
        (sources.CROSSREF_URL, load("crossref_rnai.json")),
        (sources.PUBMED_ESEARCH, load("pubmed_esearch.json")),
        (sources.PUBMED_ESUMMARY, load("pubmed_esummary.json")),
        ("https://api.biorxiv.org/details/biorxiv/", load("biorxiv_details.json")),
        ("https://api.github.com/repos/", load("github_releases.json")),
    ])


def config():
    return {
        "schema": "sifi.watch.config/1",
        "window_days": 7,
        "cache": {"ttl_hours": 24},
        "inventory": {},
        "limits": {"per_source": 5, "biorxiv_max_pages": 1},
        "queries": [
            {"id": "rnai", "text": "RNAi insect pest control", "why": "sustrato del producto",
             "keywords": ["RNAi", "dsRNA", "siRNA", "insect"], "sources": ["crossref", "pubmed"]},
            {"id": "preprints", "text": "bioRxiv RNAi", "why": "preprints",
             "keywords": ["RNAi", "dsRNA", "insect"], "sources": ["biorxiv"]},
        ],
    }


def fake_client(tmp_path, offline=False):
    cache = sources.DiskCache(tmp_path / "cache", ttl_hours=24)
    return sources.HttpClient(cache=cache, transport=transport(), offline=offline,
                              sleep=lambda s: None)


def run(tmp_path, **kw):
    kw.setdefault("client", fake_client(tmp_path))
    kw.setdefault("config_dict", config())
    kw.setdefault("since", "2026-10-01")
    kw.setdefault("today", date(2026, 10, 28))
    return cli.run(**kw)


# --------------------------------------------------------------------------- #

def test_parse_since():
    assert cli.parse_since("7d", today=date(2026, 10, 28))[0] == date(2026, 10, 21)
    assert cli.parse_since("2w", today=date(2026, 10, 28))[0] == date(2026, 10, 14)
    assert cli.parse_since("36h", today=date(2026, 10, 28))[0] == date(2026, 10, 26)
    assert cli.parse_since("2026-09-15", today=date(2026, 10, 28))[0] == date(2026, 9, 15)
    assert cli.parse_since(None, today=date(2026, 10, 28), window_days=7)[0] == date(2026, 10, 21)
    with pytest.raises(cli.ConfigError):
        cli.parse_since("3 meses")


def test_in_window_descarta_viejo():
    since = date(2026, 10, 21)
    assert cli._in_window({"date": "2026-10-21"}, since)
    assert cli._in_window({"date": "2026-10-27"}, since)
    assert not cli._in_window({"date": "2026-10-20"}, since)
    assert not cli._in_window({"date": "2026-09"}, since)
    assert cli._in_window({"date": "2026-10"}, since)   # mismo mes: no lo descartamos
    assert cli._in_window({"date": ""}, since)          # sin fecha: decide la fuente


def test_run_escribe_digest_y_novedades(tmp_path):
    out = tmp_path / "novedades.json"
    inv = tmp_path / "inventory.json"
    digest = run(tmp_path, out=out, inventory=inv)

    assert out.is_file()
    data = json.loads(out.read_text())
    assert data["schema"] == "sifi.watch.digest/1"
    assert data["since"] == "2026-10-01"
    assert data["items"]
    assert data["counts"]["new"] == len(data["items"])
    assert inv.is_file()

    srcs = {it["source"] for it in data["items"]}
    assert "crossref" in srcs and "pubmed" in srcs and "biorxiv" in srcs
    for it in data["items"]:
        assert it["title"] and it["date"] and it["id"]
        assert it["resumen"]
        assert it["query"] and it["why"]
        assert it["date"][:7] >= data["since"][:7]  # fechas parciales (YYYY-MM) son válidas
    assert digest["counts"]["new"] == len(data["items"])


def test_segunda_corrida_no_repite(tmp_path):
    out1, inv = tmp_path / "n1.json", tmp_path / "inventory.json"
    first = run(tmp_path, out=out1, inventory=inv)
    assert first["counts"]["new"] > 0

    second = run(tmp_path, out=tmp_path / "n2.json", inventory=inv)
    assert second["counts"]["new"] == 0
    assert second["items"] == []
    assert second["counts"]["fetched"] == first["counts"]["fetched"]


def test_dry_run_no_toca_el_inventario(tmp_path):
    inv = tmp_path / "inventory.json"
    d = run(tmp_path, inventory=inv, update_inventory=False)
    assert d["counts"]["new"] > 0
    assert not inv.exists()


def test_offline_reusa_la_cache(tmp_path):
    inv = tmp_path / "inventory.json"
    online = run(tmp_path, out=tmp_path / "a.json", inventory=inv)
    assert online["counts"]["new"] > 0

    # mismo cache, cero red: el transporte explota si lo llaman
    cache = sources.DiskCache(tmp_path / "cache", ttl_hours=24)
    offline_client = sources.HttpClient(cache=cache, offline=True,
                                        transport=FakeTransport([]), sleep=lambda s: None)
    off = cli.run(config_dict=config(), since="2026-10-01", today=date(2026, 10, 28),
                  inventory=inv, client=offline_client, offline=True)
    assert off["counts"]["new"] == 0          # ya estaba en el inventario
    assert off["counts"]["fetched"] == online["counts"]["fetched"]
    assert not off["warnings"]


def test_offline_sin_cache_avisa_y_no_explota(tmp_path):
    cache = sources.DiskCache(tmp_path / "vacia")
    offline_client = sources.HttpClient(cache=cache, offline=True,
                                        transport=FakeTransport([]), sleep=lambda s: None)
    d = cli.run(config_dict=config(), since="2026-10-01", today=date(2026, 10, 28),
                inventory=tmp_path / "inv.json", client=offline_client, offline=True)
    assert d["counts"]["fetched"] == 0
    assert any("offline" in w for w in d["warnings"])


def test_config_invalida_falla(tmp_path):
    with pytest.raises(cli.ConfigError):
        cli.load_config(tmp_path / "no-existe.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema: sifi.watch.config/1\nqueries: []\n")
    with pytest.raises(cli.ConfigError):
        cli.load_config(bad)


def test_config_real_del_repo_es_valida():
    cfg = cli.load_config()
    ids = [q["id"] for q in cfg["queries"]]
    assert "rnai-insect-pest" in ids
    assert "dalbulus-maidis" in ids
    assert "upstream-sifi" in ids
    assert all(q["why"] for q in cfg["queries"])
    assert all(q["keywords"] or "github" in q["sources"] for q in cfg["queries"])


def test_digest_texto(tmp_path):
    d = run(tmp_path, inventory=tmp_path / "inv.json")
    text = render_digest(d, max_items=3)
    assert "Novedades siFi-Desk" in text
    assert "[Crossref]" in text or "[PubMed]" in text or "[bioRxiv]" in text
    assert "por qué:" in text
    assert "doi:" in text
    assert text.count("Relevante") == 0  # el texto usa "por qué:", no la línea del agente


def test_summarize_item_incluye_fuente_fecha_doi_y_porque():
    item = sources.make_item(source="pubmed", title="dsRNA delivery in Dalbulus maidis",
                            date="2026-10-24", doi="10.1/x", pmid="123",
                            url="https://pubmed.ncbi.nlm.nih.gov/123/",
                            query_id="dalbulus", query_text="Dalbulus maidis",
                            why="vector del maíz")
    text = summarize_item(item, index=1)
    assert text.startswith("1. [PubMed] 2026-10-24")
    assert "dsRNA delivery" in text
    assert "vector del maíz" in text
    assert "doi:10.1/x" in text and "pmid:123" in text
    assert "https://pubmed.ncbi.nlm.nih.gov/123/" in text
