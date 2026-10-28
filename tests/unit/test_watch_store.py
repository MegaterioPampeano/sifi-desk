"""Tests de `watch.store`: inventario, dedupe y diff.

Lo que tienen que garantizar: que el mismo paper no aparezca dos veces en un digest
(aunque lo devuelvan Crossref y PubMed), y que un paper ya visto **no vuelva a
aparecer** en la corrida siguiente.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from watch import sources  # noqa: E402
from watch.store import Inventory, dedupe, item_keys, normalize_title  # noqa: E402


def paper(title="RNAi-based control of spider mites", doi="10.1127/entomologia/4935",
          pmid="", source="crossref", date="2026-10-08"):
    return sources.make_item(source=source, title=title, date=date, doi=doi, pmid=pmid,
                             url="https://doi.org/" + doi, query_id="q1",
                             query_text="RNAi insect", why="sustrato del producto")


def test_keys_por_doi_pmid_y_titulo():
    keys = item_keys(paper(pmid="12345"))
    assert "doi:10.1127/entomologia/4935" in keys
    assert "pmid:12345" in keys
    assert any(k.startswith("title:rnai based control") for k in keys)
    # títulos cortos no generan clave (evitan falsos positivos)
    assert item_keys({"title": "RNAi"}) == []


def test_normalize_title_ignora_puntuacion_acentos_y_mayusculas():
    a = normalize_title("RNAi-based control of spider mites: from target screening…")
    b = normalize_title("RNAi based CONTROL of spider mites from target screening")
    assert a == b
    assert normalize_title("Eficacia del dsRNA en Diaphorina citri") == \
        normalize_title("eficacia del dsRNA en Diaphorina citri")


def test_dedupe_por_doi_entre_fuentes():
    a = paper(source="crossref")
    b = paper(source="pubmed", pmid="42940970")
    out = dedupe([a, b])
    assert len(out) == 1
    assert out[0]["pmid"] == "42940970"      # se completa el dato que faltaba
    assert len(out[0]["matched_by"]) == 1


def test_dedupe_por_titulo_normalizado():
    a = paper(title="RNAi-based control of spider mites: from target screening", doi="10.1/a")
    b = paper(title="RNAi based control of spider mites — from target screening.", doi="10.1/b")
    assert len(dedupe([a, b])) == 1


def test_dedupe_junta_las_queries():
    a = paper()
    b = paper()
    b["matched_by"] = [{"query_id": "q2", "query": "dsRNA delivery", "why": "entrega"}]
    out = dedupe([a, b])
    assert len(out) == 1
    ids = [m["query_id"] for m in out[0]["matched_by"]]
    assert ids == ["q1", "q2"]


def test_diff_solo_lo_nuevo_y_no_repite():
    inv = Inventory()
    items = [paper(), paper(doi="10.1/otro", title="Otra cosa sobre dsRNA en insectos")]
    first = inv.diff(items)
    assert len(first) == 2
    assert len(inv.diff(items)) == 2      # diff() es puro: no consume el inventario
    inv.mark(first)
    assert inv.diff(items) == []          # ya visto
    assert len(inv) == 2


def test_item_viejo_no_vuelve_a_aparecer(tmp_path):
    path = tmp_path / "inventory.json"
    inv = Inventory.load(path)
    old = paper(source="crossref")
    inv.mark(inv.diff([old]))
    inv.save()

    # la corrida siguiente lo vuelve a traer, ahora por PubMed y con otro título menor
    again = paper(source="pubmed", pmid="42940970",
                  title="RNAi-based control of spider mites: from target screening to delivery")
    inv2 = Inventory.load(path)
    assert inv2.diff([again]) == []
    assert inv2.known(again)


def test_diff_dedupea_dentro_del_mismo_lote():
    inv = Inventory()
    a = paper()
    b = paper(source="pubmed", pmid="42940970")
    assert len(inv.diff([a, b])) == 1


def test_mark_es_idempotente_y_cuenta_repeticiones():
    inv = Inventory()
    item = paper()
    assert inv.mark([item]) == 1
    assert inv.mark([item]) == 0
    entry = inv.entries["doi:10.1127/entomologia/4935"]
    assert entry["seen_count"] == 2
    assert len(inv) == 1


def test_mark_agrega_aliases_si_aparece_el_pmid_despues():
    inv = Inventory()
    inv.mark([paper()])
    inv.mark([paper(pmid="42940970", source="pubmed")])
    assert len(inv) == 1
    assert inv.has("pmid:42940970")
    assert inv.n_keys >= 3


def test_roundtrip_json(tmp_path):
    path = tmp_path / "sub" / "inventory.json"
    inv = Inventory.load(path)
    inv.mark(inv.diff([paper()]))
    inv.save()
    raw = json.loads(path.read_text())
    assert raw["schema"] == "sifi.watch.inventory/1"
    assert len(raw["entries"]) == 1

    inv2 = Inventory.load(path)
    assert len(inv2) == 1
    assert inv2.known(paper())           # el índice se reconstruye de `keys`
    assert "doi:10.1127/entomologia/4935" in inv2.entries


def test_inventario_de_otro_schema_falla(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"schema": "otra.cosa/9", "entries": {}}))
    with pytest.raises(ValueError):
        Inventory.load(path)


def test_sin_ruta_no_puede_guardar():
    with pytest.raises(ValueError):
        Inventory().save()
