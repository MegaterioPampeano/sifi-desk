"""Test de red real (skippeado por defecto).

    SIFI_NET_TESTS=1 python3 -m pytest -q tests/unit/test_library_net.py -m net

Baja un PDF de bioRxiv (acceso abierto) y verifica que sea un archivo real.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from library import extract, fetch, store  # noqa: E402

pytestmark = [
    pytest.mark.net,
    pytest.mark.skipif(not os.environ.get("SIFI_NET_TESTS"),
                       reason="test de red: correr con SIFI_NET_TESTS=1"),
]

DOI = "10.1101/2025.08.31.673361"  # bioRxiv, CC-BY


def test_downloads_real_biorxiv_pdf(tmp_path):
    lib = store.Library(data_dir=tmp_path / "data")
    try:
        out = fetch.ingest(lib, doi=DOI, tags=["net"], http=fetch.Http(cache_dir=tmp_path / "cache"))
        assert out["status"] == "ok", out["motivo"]
        paper = lib.get(out["id"])
        path = lib.data_dir / paper["pdf_path"]
        ok, motivo, info = extract.verify_pdf(path)
        assert ok, motivo
        assert info["pages"] > 3
        assert paper["pdf_bytes"] > 200_000
        assert paper["pdf_sha256"] == extract.sha256_file(path)
        assert paper["text_chars"] > 5000
    finally:
        lib.close()
