"""Resolución y descarga del PDF real, con la red simulada por fixtures grabados.

Casos que pide el frente M11:

(a) un PDF válido se guarda tal cual, con sha256, páginas y texto indexado;
(b) si el servidor devuelve HTML (captcha / error), se rechaza y queda `sin_pdf` con motivo;
(c) si no hay versión abierta **no se baja nada**, aunque exista una URL de PDF;
(d) la resolución usa caché en disco y sobrevive a que Europe PMC esté caído (503).

Las fixtures están en `core/library/fixtures/` (respuestas reales recortadas).
"""
import hashlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from library import edition, extract, fetch, store  # noqa: E402

FIX = os.path.join(ROOT, "core", "library", "fixtures")
MDPI_DOI = "10.3390/plants15203237"
CLOSED_DOI = "10.1242/jeb.251768"


def fixture_bytes(name):
    with open(os.path.join(FIX, name), "rb") as fh:
        return fh.read()


def make_pdf_bytes(tmp_path, paragraphs=420):
    from weasyprint import HTML

    body = "".join(
        "<p>Section %d. dsRNA delivery experiments in Tribolium castaneum showed systemic "
        "RNAi in the gut.</p>" % i for i in range(paragraphs))
    html = ("<html><head><meta charset='utf-8'><style>body{font-family:serif;font-size:11pt}"
            "p{text-align:justify}</style></head><body>"
            "<h1>Foliar application of dsRNA against a plant virus</h1>"
            "<p>Abstract. dsRNA delivery by foliar spray reduced viral RNA accumulation.</p>"
            + body + "</body></html>")
    out = tmp_path / "generated.pdf"
    HTML(string=html).write_pdf(str(out))
    return out.read_bytes()


HTML_CHALLENGE = (b"<!doctype html><html><head><title>Just a moment...</title></head>"
                  b"<body>enable javascript</body></html>")


class FakeTransport:
    """Rutea por prefijo de URL y anota los pedidos."""

    def __init__(self, routes):
        self.routes = list(routes)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        for prefix, status, headers_, body in self.routes:
            if url.startswith(prefix):
                return status, dict(headers_), body
        return 404, {"content-type": "text/html"}, HTML_CHALLENGE

    def pdf_calls(self):
        return [u for u in self.calls if "pdf" in u.lower() or u.endswith(".pdf")]


def mdpi_routes(pdf_bytes):
    return [
        ("https://api.crossref.org/works/", 200, {"content-type": "application/json"},
         fixture_bytes("crossref_10.3390_plants15203237.json")),
        ("https://api.unpaywall.org/v2/", 200, {"content-type": "application/json"},
         fixture_bytes("unpaywall_10.3390_plants15203237.json")),
        ("https://pmc.ncbi.nlm.nih.gov/tools/idconv/", 200, {"content-type": "application/json"},
         fixture_bytes("idconv_10.3390_plants15203237.json")),
        ("https://www.ebi.ac.uk/europepmc/webservices/rest/search", 503,
         {"content-type": "application/json"},
         json.dumps({"errCode": 503, "errMsg": "Search service is temporarily unavailable."}).encode()),
        ("https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13709202/fullTextXML", 200,
         {"content-type": "application/xml"}, fixture_bytes("epmc_fulltext_PMC13709202.xml")),
        ("https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi", 404, {"content-type": "text/html"},
         HTML_CHALLENGE),
        ("https://pmc.ncbi.nlm.nih.gov/articles/", 200, {"content-type": "text/html"},
         HTML_CHALLENGE),
        ("https://www.mdpi.com/", 403, {"content-type": "text/html"}, HTML_CHALLENGE),
        ("https://doi.org/", 403, {"content-type": "text/html"}, HTML_CHALLENGE),
        ("https://mdpi-res.com/", 200, {"content-type": "application/pdf"}, pdf_bytes),
    ]


@pytest.fixture()
def lib(tmp_path):
    library = store.Library(data_dir=tmp_path / "data")
    yield library
    library.close()


def build_http(routes, tmp_path, offline=False):
    transport = FakeTransport(routes)
    http = fetch.Http(cache_dir=tmp_path / "cache", transport=transport,
                      offline=offline, sleep=lambda _s: None)
    return http, transport


def test_valid_pdf_is_saved_verbatim_with_sha(lib, tmp_path):
    pdf = make_pdf_bytes(tmp_path)
    http, transport = build_http(mdpi_routes(pdf), tmp_path)

    out = fetch.ingest(lib, doi=MDPI_DOI, tags=["entrega"], http=http)

    assert out["status"] == "ok", out["motivo"]
    paper = lib.get(out["id"])
    assert paper["doi"] == MDPI_DOI
    assert paper["status"] == "ok" and paper["motivo"] == ""
    assert paper["license"] == "cc-by" and paper["oa_status"] == "gold"
    assert paper["pdf_sha256"] == hashlib.sha256(pdf).hexdigest()
    assert paper["pdf_bytes"] == len(pdf)
    assert paper["pages"] > 3 and paper["text_chars"] > 2000

    saved = (lib.data_dir / paper["pdf_path"]).read_bytes()
    assert saved == pdf, "el PDF se guarda tal cual lo entregó el servidor"

    # el texto quedó indexado (búsqueda por cuerpo)
    from library import search
    hits = search.search(lib, "foliar dsrna")
    assert hits["count"] == 1 and "[[" in hits["results"][0]["snippet"]

    # Europe PMC estaba 503 y aun así se resolvió: la caída no rompe la importación
    assert any("europepmc" in n for n in out["resolution"]["notes"])
    assert any("mdpi-res.com" in u for u in transport.calls)


def test_html_instead_of_pdf_is_rejected(lib, tmp_path):
    pdf = make_pdf_bytes(tmp_path)
    routes = mdpi_routes(pdf)
    routes = [(prefix, status, hdr, HTML_CHALLENGE if prefix == "https://mdpi-res.com/" else body)
              for prefix, status, hdr, body in routes]
    http, transport = build_http(routes, tmp_path)

    out = fetch.ingest(lib, doi=MDPI_DOI, http=http)

    assert out["status"] == "sin_pdf"
    assert "HTML" in out["motivo"] or "html" in out["motivo"]
    paper = lib.get(out["id"])
    assert paper["pdf_path"] == "" and paper["pdf_sha256"] == ""
    assert not list(lib.pdf_dir.glob("*.pdf")), "no debe quedar ningún archivo guardado"


def test_too_small_pdf_is_rejected(lib, tmp_path):
    tiny = b"%PDF-1.4\n" + b"0" * 5000
    http, _ = build_http(mdpi_routes(tiny), tmp_path)
    out = fetch.ingest(lib, doi=MDPI_DOI, http=http)
    assert out["status"] == "sin_pdf"
    assert "chico" in out["motivo"]


def test_closed_access_downloads_nothing(lib, tmp_path):
    routes = [
        ("https://api.crossref.org/works/", 200, {"content-type": "application/json"},
         fixture_bytes("crossref_10.1242_jeb251768.json")),
        ("https://api.unpaywall.org/v2/", 200, {"content-type": "application/json"},
         fixture_bytes("unpaywall_10.1242_jeb251768.json")),
        ("https://pmc.ncbi.nlm.nih.gov/tools/idconv/", 200, {"content-type": "application/json"},
         b'{"status":"ok","records":[{"doi":"10.1242/jeb.251768","status":"error",'
         b'"errmsg":"Identifier not found in PMC"}]}'),
        ("https://www.ebi.ac.uk/europepmc/webservices/rest/search", 503,
         {"content-type": "application/json"}, b'{"errCode":503}'),
        ("https://doi.org/", 200, {"content-type": "text/html"},
         b"<html><head></head><body>closed</body></html>"),
    ]
    http, transport = build_http(routes, tmp_path)

    out = fetch.ingest(lib, doi=CLOSED_DOI, http=http)

    assert out["status"] == "sin_pdf"
    assert "acceso abierto" in out["motivo"], out["motivo"]
    paper = lib.get(out["id"])
    assert paper["pdf_path"] == "" and paper["status"] == "sin_pdf"
    # hay una URL de PDF en Crossref, pero NO se pidió: la licencia no es abierta
    assert "journals.biologists.com" not in " ".join(transport.calls)
    assert not list(lib.pdf_dir.glob("*.pdf"))


def test_resolution_is_cached(lib, tmp_path):
    pdf = make_pdf_bytes(tmp_path)
    http, transport = build_http(mdpi_routes(pdf), tmp_path)
    fetch.resolve(doi=MDPI_DOI, http=http)
    first = len(transport.calls)
    assert first > 0

    http2, transport2 = build_http([], tmp_path)
    res = fetch.resolve(doi=MDPI_DOI, http=http2)
    assert res.meta["doi"] == MDPI_DOI
    assert res.candidates, "la caché tiene que devolver los candidatos"
    # no se repiten los pedidos de metadatos: salen de la caché
    for prefix in ("api.crossref.org", "api.unpaywall.org", "idconv", "fullTextXML"):
        assert not any(prefix in u for u in transport2.calls), prefix


def test_import_items_limited_and_tagged(lib, tmp_path):
    pdf = make_pdf_bytes(tmp_path)
    http, transport = build_http(mdpi_routes(pdf), tmp_path)
    items = [
        {"doi": MDPI_DOI, "title": "uno", "source": "crossref", "query_id": "entrega"},
        {"doi": "10.9999/no-existe", "title": "dos", "source": "crossref"},
    ]
    out = fetch.import_items(lib, items, limit=1, tags=["papers"], tag_from_query=True,
                             http=http)
    assert out["total"] == 1 and out["ok"] == 1
    paper = lib.get(out["items"][0]["id"])
    assert set(paper["tags"]) == {"papers", "entrega"}

    # segunda pasada: ya está, no vuelve a bajar
    before = len(transport.calls)
    out2 = fetch.import_items(lib, items, limit=1, http=http)
    assert out2["items"][0]["motivo"] == "ya estaba"
    assert len(transport.calls) == before


def test_open_license_rules():
    assert fetch.license_is_open("https://creativecommons.org/licenses/by/4.0/")
    assert fetch.license_is_open("cc-by-nc-nd")
    assert fetch.license_is_open("CC0")
    assert not fetch.license_is_open("http://www.biologists.com/user-licence-1-1/")
    assert fetch.oa_is_open(["cc-by"], "hybrid")
    assert fetch.oa_is_open([], "gold")
    assert fetch.oa_is_open([], "green")
    assert not fetch.oa_is_open([], "bronze")
    assert not fetch.oa_is_open([], "closed")
    assert not fetch.oa_is_open(["elsevier user license"], "hybrid")


def test_edition_gate_defaults_to_stable(monkeypatch):
    monkeypatch.delenv("SIFI_EDITION", raising=False)
    assert edition.current() == "stable"
    with pytest.raises(edition.EditionError) as exc:
        edition.require_dev()
    assert "developer" in str(exc.value)
    monkeypatch.setenv("SIFI_EDITION", "dev")
    assert edition.is_dev() is True
    monkeypatch.setenv("SIFI_EDITION", "cualquier-cosa")
    assert edition.current() == "stable"
