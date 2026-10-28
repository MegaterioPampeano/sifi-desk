"""Store + extracción + FTS de la biblioteca, con un PDF real generado en el momento.

WeasyPrint arma un PDF de varias páginas: se extrae con `pdftotext -layout` como cualquier
paper bajado, y se indexa en `papers_fts`. Nada de texto inventado: el PDF existe.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from library import extract, search, store  # noqa: E402


def make_pdf(path, paragraphs=420, extra=""):
    from weasyprint import HTML

    body = "".join(
        "<p>Section %d. dsRNA delivery experiments in Tribolium castaneum showed a systemic "
        "RNAi response in the gut and fat body.</p>" % i
        for i in range(paragraphs))
    html = ("<html><head><meta charset='utf-8'><style>body{font-family:serif;font-size:11pt}"
            "h1{font-size:16pt}p{text-align:justify}</style></head><body>"
            "<h1>RNAi in Tribolium castaneum: dsRNA delivery and systemic spread</h1>"
            "<p>Abstract. We tested dsRNA delivery in Tribolium castaneum by injection and "
            "feeding. Knockdown efficiency was compared across tissues.</p>"
            + body + extra + "</body></html>")
    HTML(string=html).write_pdf(str(path))
    return path


@pytest.fixture()
def lib(tmp_path):
    library = store.Library(data_dir=tmp_path / "data")
    yield library
    library.close()


@pytest.fixture()
def pdf_path(tmp_path):
    return make_pdf(tmp_path / "paper.pdf")


def add_paper(lib, doi="10.9999/test.1", title="dsRNA delivery in Tribolium castaneum",
              **kw):
    meta = {"doi": doi, "title": title, "journal": "J Test", "year": 2026,
            "authors": "Doe, Jane; Roe, Rick", "abstract": "Abstract about RNAi.", **kw}
    return lib.add_paper(meta)


def test_schema_has_all_tables_and_fts(lib):
    names = {r[0] for r in lib.db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','trigger')")}
    for table in ("papers", "tags", "annotations", "papers_fts"):
        assert table in names
    cols = {r[1] for r in lib.db.execute("PRAGMA table_info(papers)")}
    for col in ("doi", "pmid", "pmcid", "title", "authors", "journal", "year", "abstract",
                "oa_status", "license", "pdf_path", "pdf_sha256", "pages", "text_chars",
                "status", "motivo", "added_at", "source"):
        assert col in cols
    assert lib.db.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION


def test_add_paper_dedupes_by_doi_and_title(lib):
    first = add_paper(lib)
    assert first["created"] is True
    again = add_paper(lib, title="otro título")
    assert again["id"] == first["id"] and again["created"] is False
    # dedupe por título normalizado (otra fila, mismo título con puntuación distinta)
    other = lib.add_paper({"title": "Nanoparticles for dsRNA delivery", "year": 2025})
    dup = lib.add_paper({"title": "Nanoparticles for dsRNA-delivery!", "year": 2025})
    assert dup["id"] == other["id"] and dup["created"] is False
    # el enriquecimiento no borra el DOI ya guardado
    assert lib.get(first["id"])["doi"] == "10.9999/test.1"


def test_extract_real_pdf_and_index_text(lib, pdf_path):
    ok, motivo, info = extract.verify_pdf(pdf_path)
    assert ok, motivo
    assert info["pages"] >= 5
    data = extract.extract(pdf_path)
    assert data["sha256"] and len(data["sha256"]) == 64
    assert data["text_chars"] > 5000
    assert "%PDF" not in data["text"]

    paper = add_paper(lib, abstract="")
    lib.set_pdf(paper["id"], "pdfs/x.pdf", data["sha256"], data["bytes"],
                data["pages"], data["text"])
    saved = lib.get(paper["id"])
    assert saved["status"] == "ok" and saved["pdf_sha256"] == data["sha256"]
    assert saved["pages"] == data["pages"] and saved["text_chars"] == data["text_chars"]

    out = search.search(lib, "dsrna delivery")
    assert out["count"] == 1
    hit = out["results"][0]
    assert "[[" in hit["snippet"], hit["snippet"]
    assert "Tribolium" in hit["snippet"] or "delivery" in hit["snippet"].lower()


def test_search_phrase_and_tag_filter(lib, pdf_path):
    data = extract.extract(pdf_path)
    p1 = add_paper(lib, doi="10.9999/a", title="Nanoparticle dsRNA formulation")
    lib.set_pdf(p1["id"], "pdfs/a.pdf", data["sha256"], data["bytes"], data["pages"], data["text"])
    add_paper(lib, doi="10.9999/b", title="Unrelated paper about maize yield")
    lib.add_tag(p1["id"], "entrega")

    phrase = search.search(lib, '"systemic RNAi response"')
    assert phrase["count"] == 1 and phrase["results"][0]["id"] == p1["id"]

    tagged = search.search(lib, "tag:entrega")
    assert tagged["count"] == 1 and tagged["results"][0]["id"] == p1["id"]

    both = search.search(lib, "dsrna", tags=["entrega"])
    assert both["count"] == 1

    none = search.search(lib, "dsrna", tags=["otra"])
    assert none["count"] == 0


def test_search_or_and_year_filter(lib):
    add_paper(lib, doi="10.9999/or1", title="alpha beta", year=2024)
    add_paper(lib, doi="10.9999/or2", title="gamma delta", year=2026)
    out = search.search(lib, "alpha OR gamma")
    assert out["count"] == 2
    only = search.search(lib, "alpha OR gamma", year=2026)
    assert only["count"] == 1
    parsed = search.parse('tag:entrega "dsrna delivery" dsrna OR sirna year:2025')
    assert parsed["tags"] == ["entrega"] and parsed["year"] == 2025
    assert '"dsrna delivery"' in parsed["match"] and " OR " in parsed["match"]


def test_annotations_are_typed_and_counted(lib):
    paper = add_paper(lib)
    idea = lib.add_annotation(paper["id"], "idea_test", "probar silenciamiento de RpS3",
                              author="mariano")
    lib.add_annotation(paper["id"], "mejora_plataforma", "agregar panel de Dalbulus",
                       author="mariano")
    lib.add_annotation(paper["id"], "riesgo", "el ensayo usó microinyección")
    assert idea["kind"] == "idea_test" and idea["author"] == "mariano"
    assert idea["created_at"].endswith("Z")
    assert len(lib.annotations(paper["id"])) == 3
    assert [a["kind"] for a in lib.annotations(paper["id"], kind="riesgo")] == ["riesgo"]
    with pytest.raises(ValueError):
        lib.add_annotation(paper["id"], "otro", "no existe")
    with pytest.raises(ValueError):
        lib.add_annotation(paper["id"], "nota", "   ")
    assert lib.stats()["annotations"] == [{"kind": "idea_test", "n": 1},
                                          {"kind": "mejora_plataforma", "n": 1},
                                          {"kind": "riesgo", "n": 1}]


def test_tags_add_remove(lib):
    paper = add_paper(lib)
    assert lib.add_tag(paper["id"], "Entrega") is True
    assert lib.add_tag(paper["id"], "entrega") is False
    assert lib.tags(paper["id"]) == ["entrega"]
    assert lib.remove_tag(paper["id"], "entrega") is True
    assert lib.remove_tag(paper["id"], "entrega") is False
    assert lib.tags(paper["id"]) == []


def test_stats_and_export(lib, pdf_path, tmp_path):
    data = extract.extract(pdf_path)
    paper = add_paper(lib)
    lib.set_pdf(paper["id"], "pdfs/a.pdf", data["sha256"], data["bytes"], data["pages"], data["text"])
    lib.add_tag(paper["id"], "entrega")
    lib.add_annotation(paper["id"], "idea_test", "usar el diseño de la figura 3")

    stats = lib.stats()
    assert stats["papers"] == 1 and stats["with_pdf"] == 1
    assert stats["pdf_bytes"] == data["bytes"] and stats["pages"] == data["pages"]

    out = tmp_path / "export"
    result = lib.export(out, tag="entrega")
    assert result["count"] == 1
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["papers"][0]["doi"] == "10.9999/test.1"
    assert index["papers"][0]["annotations"][0]["kind"] == "idea_test"
    assert "usar el diseño de la figura 3" in (out / "notas.md").read_text(encoding="utf-8")
    # el export copia el PDF sólo si existe en disco
    lib.set_pdf(paper["id"], "pdfs/a.pdf", data["sha256"], data["bytes"], data["pages"], data["text"])
    real = lib.pdf_dir / "a.pdf"
    real.write_bytes(pdf_path.read_bytes())
    result2 = lib.export(out, tag="entrega")
    assert (out / "pdfs" / "a.pdf").is_file() and result2["count"] == 1


def test_normalize_text_only_touches_spaces():
    raw = "line   one\r\nline two\t\twith tabs\r" + "\f" + "x\n\n\n\ny   "
    out = extract.normalize_text(raw)
    assert out == "line one\nline two with tabs\n\nx\n\ny"


def test_verify_rejects_non_pdf_and_small_files(tmp_path):
    html = tmp_path / "x.pdf"
    html.write_bytes(b"<!doctype html><html><head><title>Just a moment...</title></head>"
                     + b"x" * 30000)
    ok, motivo, _ = extract.verify_pdf(html)
    assert not ok and "no es un PDF" in motivo

    small = tmp_path / "small.pdf"
    small.write_bytes(b"%PDF-1.4\n" + b"0" * 1000)
    ok, motivo, _ = extract.verify_pdf(small)
    assert not ok and "chico" in motivo

    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    ok, motivo, _ = extract.verify_pdf(empty)
    assert not ok


def test_fts_is_synced_by_triggers(lib):
    paper = add_paper(lib, title="initial title", abstract="")
    assert search.search(lib, "initial")["count"] == 1
    lib.db.execute("UPDATE papers SET title = 'cambiado a otra cosa' WHERE id = ?", (paper["id"],))
    lib.db.commit()
    assert search.search(lib, "initial")["count"] == 0
    assert search.search(lib, "cambiado")["count"] == 1
    lib.db.execute("DELETE FROM papers WHERE id = ?", (paper["id"],))
    lib.db.commit()
    assert search.search(lib, "cambiado")["count"] == 0
