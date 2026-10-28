"""Tests del registro de paneles (paso 2.1).

Cubren lo que importa para la trazabilidad de un resultado: que el fingerprint sea
estable al reingestar, que cambie si cambia el FASTA, y que resolver un panel que no
existe falle fuerte en vez de seguir con menos base de la pedida.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "core"))

from sifi.panels import PanelError, PanelSpec, PanelsRegistry  # noqa: E402
from sifi.tools import find_tool  # noqa: E402

TOY = os.path.join(ROOT, "tests", "data", "toy.fa")
BOWTIE_BUILD = find_tool("bowtie-build")

pytestmark = pytest.mark.skipif(not BOWTIE_BUILD, reason="falta bowtie-build")


@pytest.fixture()
def reg(tmp_path):
    return PanelsRegistry(root=str(tmp_path / "panels"), bowtie_build=BOWTIE_BUILD)


def test_ingest_completa_spec(reg):
    spec = reg.ingest(PanelSpec("toy", nombre="Panel de juguete", rol="no_blanco",
                                fuente="tests/data/toy.fa", version="v1"), TOY)

    assert spec.id == "toy"
    assert spec.version == "v1"
    assert spec.n_seqs == 2
    assert len(spec.sha256_fasta) == 64
    assert len(spec.sha256_index) == 64
    assert spec.fingerprint == spec.sha256_index[:16]

    assert os.path.isfile(os.path.join(spec.path, "seqs.fa"))
    assert os.path.isfile(os.path.join(spec.path, "meta.yaml"))
    assert os.path.isfile(spec.index_path + ".1.ebwt")

    # el FASTA guardado queda normalizado: sólo ID, secuencia en una línea
    with open(os.path.join(spec.path, "seqs.fa"), encoding="utf-8") as fh:
        lineas = [l for l in fh.read().splitlines() if l]
    assert len(lineas) == 4
    assert lineas[0] == ">GeneA"


def test_reingesta_es_idempotente(reg):
    sp = PanelSpec("toy", version="v1")
    a = reg.ingest(sp, TOY)
    b = reg.ingest(sp, TOY)

    assert a.sha256_index == b.sha256_index
    assert a.sha256_fasta == b.sha256_fasta
    assert a.path == b.path
    # no se reescribió: el meta conserva la fecha original
    assert a.version == b.version
    with open(os.path.join(a.path, "meta.yaml"), encoding="utf-8") as fh:
        creado = fh.read()
    assert a.sha256_fasta in creado


def test_fasta_distinto_cambia_fingerprint(reg):
    a = reg.ingest(PanelSpec("toy", version="v1"), TOY)

    otro = os.path.join(os.path.dirname(TOY), "toy_extra.fa")
    try:
        with open(TOY, encoding="utf-8") as fh:
            base = fh.read()
        with open(otro, "w", encoding="utf-8") as fh:
            fh.write(base)
            fh.write(">NuevaC\nACGTTGCAACGTTGCAACGTTGCAACGTTGCAA\n")

        b = reg.ingest(PanelSpec("toy", version="v2"), otro)
    finally:
        if os.path.exists(otro):
            os.remove(otro)

    assert b.n_seqs == a.n_seqs + 1
    assert b.sha256_fasta != a.sha256_fasta
    assert b.sha256_index != a.sha256_index
    assert b.path != a.path
    # v1 sigue intacta
    assert reg.get("toy", "v1").sha256_index == a.sha256_index


def test_misma_version_con_otro_contenido_falla(reg):
    reg.ingest(PanelSpec("toy", version="v1"), TOY)
    otro = os.path.join(os.path.dirname(TOY), "toy_otro.fa")
    try:
        with open(otro, "w", encoding="utf-8") as fh:
            fh.write(">GeneA\nACGTACGTACGTACGTACGTACGTACGT\n")
        with pytest.raises(PanelError, match="otro contenido"):
            reg.ingest(PanelSpec("toy", version="v1"), otro)
    finally:
        if os.path.exists(otro):
            os.remove(otro)


def test_resolve_devuelve_indices(reg):
    reg.ingest(PanelSpec("toy", version="v1"), TOY)
    rutas = reg.resolve(["toy"])
    assert len(rutas) == 1
    assert rutas[0].endswith(os.path.join("toy", "v1", "idx"))
    assert os.path.exists(rutas[0] + ".1.ebwt")


def test_resolve_panel_inexistente_falla_claro(reg):
    reg.ingest(PanelSpec("toy", version="v1"), TOY)
    with pytest.raises(PanelError) as exc:
        reg.resolve(["toy", "chicharrita"])
    assert "chicharrita" in str(exc.value)
    assert "toy" in str(exc.value)


def test_get_version_pedida(reg):
    reg.ingest(PanelSpec("toy", version="v1"), TOY)
    with pytest.raises(PanelError, match="v9"):
        reg.get("toy", "v9")
