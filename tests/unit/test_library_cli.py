"""CLI de la biblioteca: puerta de edición, búsqueda, etiquetas y anotaciones."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from library import cli, store  # noqa: E402


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "data" / "library.db"


@pytest.fixture()
def populated(db_path):
    lib = store.Library(path=db_path)
    one = lib.add_paper({"doi": "10.9999/a", "title": "dsRNA delivery in Tribolium",
                         "year": 2026, "journal": "J Test",
                         "authors": "Doe, Jane", "abstract": "RNAi in beetles."})
    two = lib.add_paper({"doi": "10.9999/b", "title": "Maize yield under drought",
                         "year": 2024, "journal": "Agro"})
    lib.set_text(one["id"], "dsRNA delivery by injection silenced the target gene.", pages=9)
    lib.set_pdf(one["id"], "pdfs/a.pdf", "a" * 64, 123456, 9,
                "dsRNA delivery by injection silenced the target gene.")
    lib.add_tag(one["id"], "entrega")
    lib.add_annotation(one["id"], "idea_test", "probar el panel de entrega",
                       author="mariano")
    lib.close()
    return db_path


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_stable_edition_returns_clear_error(capsys, monkeypatch, db_path):
    monkeypatch.delenv("SIFI_EDITION", raising=False)
    code, out, err = run(capsys, "--db", str(db_path), "stats")
    assert code == 2
    assert "edición developer" in err
    assert "Traceback" not in err and "Traceback" not in out


def test_stable_edition_hides_import_watch(capsys, monkeypatch, db_path, tmp_path):
    monkeypatch.setenv("SIFI_EDITION", "stable")
    digest = tmp_path / "novedades.json"
    digest.write_text('{"items": []}', encoding="utf-8")
    code, _, err = run(capsys, "--db", str(db_path), "import-watch", str(digest))
    assert code == 2 and "edición developer" in err


def test_search_and_stats(capsys, monkeypatch, populated):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    code, out, err = run(capsys, "--db", str(populated), "search", "dsrna delivery")
    assert code == 0, err
    assert "1 resultado" in out
    assert "Tribolium" in out and "SIN PDF" not in out

    code, out, _ = run(capsys, "--db", str(populated), "search", "tag:entrega")
    assert code == 0 and "dsRNA delivery" in out

    code, out, _ = run(capsys, "--db", str(populated), "search", "nadaquever")
    assert code == 0 and "0 resultado" in out

    code, out, _ = run(capsys, "--db", str(populated), "stats")
    assert code == 0 and "con PDF: 1" in out and "entrega(1)" in out


def test_search_json(capsys, monkeypatch, populated):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    code, out, _ = run(capsys, "--db", str(populated), "--json", "search", "dsrna")
    data = json.loads(out)
    assert code == 0 and data["count"] == 1
    assert data["results"][0]["doi"] == "10.9999/a"


def test_tag_note_show(capsys, monkeypatch, populated):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    code, out, _ = run(capsys, "--db", str(populated), "tag", "2", "+riesgo", "+test")
    assert code == 0 and "riesgo" in out
    code, out, _ = run(capsys, "--db", str(populated), "tag", "2", "-riesgo")
    assert code == 0

    code, out, _ = run(capsys, "--db", str(populated), "note", "1", "--kind",
                        "mejora_plataforma", "--author", "mariano", "agregar score por panel")
    assert code == 0 and "mejora_plataforma" in out

    code, out, _ = run(capsys, "--db", str(populated), "show", "1")
    assert code == 0
    assert "dsRNA delivery in Tribolium" in out
    assert "idea_test" in out and "probar el panel de entrega" in out
    assert "mejora_plataforma" in out

    code, out, _ = run(capsys, "--db", str(populated), "show", "10.9999/a", "--text")
    assert code == 0 and "silenced the target gene" in out


def test_note_rejects_unknown_kind(capsys, monkeypatch, populated):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    code, _, err = run(capsys, "--db", str(populated), "note", "1", "--kind", "otro", "x")
    assert code == 2 and "kind inválido" in err


def test_show_missing_paper(capsys, monkeypatch, populated):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    code, _, err = run(capsys, "--db", str(populated), "show", "999")
    assert code == 1 and "no existe" in err


def test_export(capsys, monkeypatch, populated, tmp_path):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    # el export copia el PDF sólo si está en disco
    lib = store.Library(path=populated)
    (lib.pdf_dir / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    lib.close()
    out_dir = tmp_path / "out"
    code, out, err = run(capsys, "--db", str(populated), "export", "--tag", "entrega",
                         "--out", str(out_dir))
    assert code == 0, err
    assert "exportados 1" in out
    assert (out_dir / "index.json").is_file() and (out_dir / "notas.md").is_file()


def test_import_watch_offline_does_not_crash(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("SIFI_EDITION", "dev")
    digest = tmp_path / "novedades.json"
    digest.write_text(json.dumps({
        "schema": "sifi.watch.digest/1",
        "items": [{"doi": "10.9999/x", "title": "Paper X", "source": "crossref"},
                  {"pmid": "123456", "title": "Paper Y", "source": "pubmed"}],
    }), encoding="utf-8")
    code, out, err = run(capsys, "--db", str(tmp_path / "db" / "library.db"),
                         "--cache-dir", str(tmp_path / "cache"), "--offline",
                         "import-watch", str(digest))
    assert code == 0
    assert "sin PDF 2" in out
    assert "Traceback" not in err


def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        cli.main([])
