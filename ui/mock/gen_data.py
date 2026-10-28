#!/usr/bin/env python3
"""Genera los datos de ejemplo que sirve ``ui/mock/server.py``.

Este script corre *fuera* del servidor (es una herramienta de desarrollo) y sí puede
importar el core: usa el scoring real (``core/sifi/scoring.py``) para que la maqueta
tenga exactamente el mismo desglose E/R/S/T/D, las mismas bandas y los mismos totales
que un ``results.json`` de verdad. El servidor de maqueta, en cambio, sólo usa la
biblioteca estándar: lee el JSON ya generado.

    python3 ui/mock/gen_data.py            # reescribe ui/mock/data/mock_data.json

Los datos son sintéticos pero realistas: 3 genes de *Dalbulus maidis*, 5 paneles con
roles distintos, 36 candidatos por gen, hits de off-target coherentes con los
mismatches y narrativa (descripciones, log de corrida, respuestas del agente) que
acompaña al producto.

Nada de esto es evidencia biológica: es una maqueta para revisar la interfaz.
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timezone


def shutil_copy(src, dst):
    while True:
        bloque = src.read(1 << 20)
        if not bloque:
            break
        dst.write(bloque)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "core"))

import sifi.scoring as scoring  # noqa: E402

OUT = os.path.join(HERE, "data", "mock_data.json")
SEED = 20261028
SIRNA_SIZE = 21

PANELES = [
    {
        "id": "dalbulus_maidis",
        "nombre": "Dalbulus maidis",
        "titulo": "Genoma de referencia (DIACI v3)",
        "rol": "blanco",
        "version": "2026.09",
        "n_seqs": 14211,
        "tamano": "412 MB",
        "sha256": "9f2c41ab7d3e0c58a1f4b6d9e7c20314",
        "descripcion": (
            "Organismo blanco. Genoma ensamblado y anotado de la chicharrita del maíz; "
            "es la base contra la que se buscan los sitios de corte."
        ),
    },
    {
        "id": "maiz",
        "nombre": "Zea mays B73",
        "titulo": "RefGen_v5 — no blanco",
        "rol": "no_blanco",
        "version": "2026.07",
        "n_seqs": 39432,
        "tamano": "2,1 GB",
        "sha256": "1b7ae0c4d2f98563ac0d7e41f5b8c926",
        "descripcion": (
            "Cultivo que se quiere proteger. Cualquier hit con pocos mismatches acá "
            "descalifica al candidato por más eficiencia que tenga."
        ),
    },
    {
        "id": "sulcia",
        "nombre": "Candidatus Sulcia muelleri",
        "titulo": "Simbionte primario de D. maidis",
        "rol": "simbionte",
        "version": "2025.11",
        "n_seqs": 241,
        "tamano": "245 KB",
        "sha256": "c4e81f30b97a2d65e0f13a8c76b52d09",
        "descripcion": (
            "Simbionte obligado del insecto. Se incluye porque su genoma es rico en A+T "
            "y genera hits espurios que conviene ver explícitamente."
        ),
    },
    {
        "id": "humano",
        "nombre": "Homo sapiens GRCh38",
        "titulo": "Control de especificidad",
        "rol": "control",
        "version": "2026.05",
        "n_seqs": 194893,
        "tamano": "3,1 GB",
        "sha256": "77d0ae1c9b4f28e6a3c50d1f8b2e6497",
        "descripcion": (
            "Panel de control. Un hit perfecto acá bloquea el candidato sin importar el "
            "score: así se comporta la política de riesgo del producto."
        ),
    },
    {
        "id": "universal",
        "nombre": "Transcritos no relacionados",
        "titulo": "Control negativo",
        "rol": "universal",
        "version": "2026.02",
        "n_seqs": 5000,
        "tamano": "18 MB",
        "sha256": "e3a5c98d02b7416fa9d1e6c470b83f52",
        "descripcion": (
            "Muestreo de transcritos de organismos no emparentados. Sirve para estimar "
            "cuánto ruido de off-target aparece por azar."
        ),
    },
]

PANELES_POR_ID = {p["id"]: p for p in PANELES}

GENES = [
    {
        "id": "Dm_COPI",
        "nombre": "COPI coatomer, subunidad alfa",
        "descripcion": (
            "Componente del complejo COPI que media el transporte retrógrado "
            "Golgi→RE. Silenciarlo compromete la secreción y la envoltura nuclear; "
            "es el gen de referencia del pipeline porque tiene expresión estable "
            "en todos los tejidos del insecto."
        ),
        "longitud": 780,
        "regiones": [
            {"inicio": 1, "fin": 96, "tipo": "5' UTR"},
            {"inicio": 97, "fin": 690, "tipo": "CDS"},
            {"inicio": 691, "fin": 780, "tipo": "3' UTR"},
        ],
        "panel_hits": ["maiz", "sulcia"],
        "n_candidatos": 36,
    },
    {
        "id": "Dm_VATP",
        "nombre": "V-ATPasa, subunidad A",
        "descripcion": (
            "Subunidad catalítica de la ATPasa vacuolar. Es un blanco clásico de RNAi "
            "en hemípteros: el silenciamiento produce parálisis digestiva en 48-72 h. "
            "Se eligió por su alta conservación de dominio."
        ),
        "longitud": 640,
        "regiones": [
            {"inicio": 1, "fin": 48, "tipo": "5' UTR"},
            {"inicio": 49, "fin": 585, "tipo": "CDS"},
            {"inicio": 586, "fin": 640, "tipo": "3' UTR"},
        ],
        "panel_hits": ["maiz", "humano", "universal"],
        "n_candidatos": 30,
    },
    {
        "id": "Dm_CHS2",
        "nombre": "Quitina sintasa 2",
        "descripcion": (
            "Enzima terminal de la vía de síntesis de quitina, específica de artrópodos. "
            "El panel de humano está incluido justamente para verificar que no haya "
            "parecido con quitina sintasas de vertebrados (no existen)."
        ),
        "longitud": 520,
        "regiones": [
            {"inicio": 1, "fin": 30, "tipo": "5' UTR"},
            {"inicio": 31, "fin": 470, "tipo": "CDS"},
            {"inicio": 471, "fin": 520, "tipo": "3' UTR"},
        ],
        "panel_hits": ["maiz", "humano", "sulcia"],
        "n_candidatos": 24,
    },
]

NARRATIVA = {
    "resumen": (
        "Corrida de diseño sobre tres genes blanco de Dalbulus maidis contra cinco "
        "paneles. El ranking usa scoring v2 (E 40 · R 15 · S 15 · T 15 · D 15); los "
        "candidatos de la banda «recomendado» no tienen hits con menos de dos "
        "mismatches en maíz ni en humano."
    ),
    "aviso": (
        "Predicción in silico. La eficiencia y la accesibilidad son estimaciones "
        "termodinámicas: antes de sintetizar cualquier dsRNA hay que validar en "
        "bioensayo y confirmar la dosis."
    ),
}


def _seq(rnd: random.Random, n: int, gc: float = 0.48) -> str:
    return "".join(rnd.choice("GC") if rnd.random() < gc else rnd.choice("AT") for _ in range(n))


def _gc(seq: str) -> float:
    if not seq:
        return 0.0
    return 100.0 * sum(1 for c in seq if c in "GC") / len(seq)


def _dg(seq: str) -> float:
    """ΔG aproximado (kcal/mol) sólo para la maqueta: más GC, más negativo."""
    return round(-(18.0 + 0.42 * _gc(seq)), 2)


def _gene_seq(gene: dict, rnd: random.Random) -> str:
    return _seq(rnd, gene["longitud"], gc=0.46 + 0.04 * (GENES.index(gene) % 3))


def _build_rows(gene: dict, seq: str, rnd: random.Random) -> list:
    """Filas crudas con el mismo formato que ``records[].sirnas[]`` del manifest."""
    rows = []
    n = gene["n_candidatos"]
    paso = max(1, (gene["longitud"] - SIRNA_SIZE - 40) // n)
    usadas = set()
    for i in range(n):
        pos = 25 + i * paso + rnd.randint(0, 6)
        if pos > gene["longitud"] - SIRNA_SIZE:
            pos = gene["longitud"] - SIRNA_SIZE
        while pos in usadas:
            pos -= 1
        usadas.add(pos)
        site = seq[pos - 1:pos - 1 + SIRNA_SIZE]
        gcp = _gc(site)
        acc = round(min(0.97, max(0.03, rnd.gauss(0.62, 0.2))), 2)
        hebra = rnd.random() < 0.84
        extremo = rnd.random() < 0.76
        eficiente = (acc > 0.5 and hebra and rnd.random() < 0.8) or (rnd.random() < 0.06)
        sifi = round(min(0.99, max(0.02, 0.55 * acc + 0.3 * rnd.random() + (0.1 if eficiente else -0.15))), 2)
        nombre = "sirna%03d" % pos
        base = {
            "query_name": gene["id"],
            "sirna_name": nombre,
            "sirna_position": pos,
            "sirna_sequence": site,
            "is_efficient": eficiente,
            "strand_selection": hebra,
            "end_stability": extremo,
            "target_site_accessibility": acc >= 0.5,
            "accessibility_value": acc,
            "is_off_target": False,
            "hit_name": gene["id"],
            "reference_strand_pos": pos,
            "strand": "+",
            "mismatches": 0,
            "score": sifi,
            "dg": _dg(site),
        }
        rows.append(base)

        # hits de off-target: no todos, y nunca en el panel blanco
        if rnd.random() < 0.46:
            for panel_id in gene["panel_hits"]:
                if rnd.random() > 0.55:
                    continue
                if panel_id == "humano":
                    mm = rnd.choice([2, 3, 3, 4])
                elif panel_id == "maiz":
                    mm = rnd.choice([1, 2, 2, 3])
                elif panel_id == "sulcia":
                    mm = rnd.choice([1, 2, 3])
                else:
                    mm = rnd.choice([2, 3, 4])
                hit = dict(base)
                hit.update({
                    "is_off_target": True,
                    "hit_name": "%s_%s_%05d" % (panel_id[:3].upper(), gene["id"][-4:], rnd.randint(1, 99999)),
                    "reference_strand_pos": rnd.randint(60, 2400),
                    "strand": rnd.choice(["+", "-"]),
                    "mismatches": mm,
                    "panel": panel_id,
                })
                rows.append(hit)
    return rows


def _extras(rows: list, panels_sel: list) -> dict:
    """Datos 'de presentación' por candidato (ΔG, accesibilidad, hits por panel).

    El scoring produce el veredicto; estos campos son los que la tabla y el detalle
    necesitan mostrar y que un servicio real puede agregar sin romper el esquema.
    """
    out = {}
    for row in rows:
        if not row.get("is_off_target"):
            key = (row["sirna_name"], row["sirna_sequence"])
            out.setdefault(key, {
                "dg": row.get("dg"),
                "acc": row.get("accessibility_value"),
                "gc": round(_gc(row["sirna_sequence"]), 1),
                "strand": row.get("strand", "+"),
                "end_stability": row.get("end_stability"),
                "strand_selection": row.get("strand_selection"),
                "efficient": row.get("is_efficient"),
                "sifi_score": row.get("score"),
                "hits": [],
            })
        else:
            key = (row["sirna_name"], row["sirna_sequence"])
            cand = out.get(key)
            if cand is None:
                continue
            panel = row.get("panel", "")
            if panels_sel and panel not in panels_sel:
                continue
            cand["hits"].append({
                "panel": panel,
                "panel_nombre": PANELES_POR_ID.get(panel, {}).get("nombre", panel),
                "rol": PANELES_POR_ID.get(panel, {}).get("rol", "desconocido"),
                "seq_id": row.get("hit_name"),
                "mismatch": row.get("mismatches"),
                "pos": row.get("reference_strand_pos"),
                "strand": row.get("strand"),
            })
    return out


def build_variant(panels_sel: list, genes_sel: list, rnd: random.Random) -> dict:
    panel_roles = {p["id"]: p["rol"] for p in PANELES if p["id"] in panels_sel}
    records = []
    for gene in GENES:
        if gene["id"] not in genes_sel:
            continue
        seq = _gene_seq(gene, random.Random(SEED + sum(ord(c) for c in gene["id"])))
        rows = _build_rows(gene, seq, rnd)
        rows_v = [r for r in rows if not r.get("is_off_target") or r.get("panel") in panels_sel]
        scored = scoring.score_candidates(rows_v, panel_roles=panel_roles)
        resumen = scoring.summarize(scored)
        extras = _extras(rows_v, panels_sel)
        candidatos = []
        for cand in scored:
            key = (cand["id"], cand["seq"])
            ex = extras.get(key, {})
            candidatos.append({
                **cand,
                "dg": ex.get("dg"),
                "acc": ex.get("acc"),
                "gc": ex.get("gc"),
                "strand": ex.get("strand", "+"),
                "end_stability": ex.get("end_stability"),
                "strand_selection": ex.get("strand_selection"),
                "efficient": ex.get("efficient"),
                "sifi_score": ex.get("sifi_score"),
                "hits": [h for h in ex.get("hits", []) if h["panel"] in panels_sel],
            })
        records.append({
            "query_name": gene["id"],
            "gene": {
                "id": gene["id"],
                "nombre": gene["nombre"],
                "descripcion": gene["descripcion"],
                "longitud": gene["longitud"],
                "regiones": gene["regiones"],
                "secuencia": seq,
            },
            "candidates": candidatos,
            "scoring": resumen,
        })

    total = sum(len(r["candidates"]) for r in records)
    banda = {}
    for rec in records:
        for c in rec["candidates"]:
            banda[c["banda"]] = banda.get(c["banda"], 0) + 1
    mejor_total = max((c["total"] for r in records for c in r["candidates"]), default=0)
    mejor = None
    for rec in records:
        for c in rec["candidates"]:
            if c["total"] == mejor_total:
                mejor = {"run_gene": rec["query_name"], "id": c["id"], "total": c["total"], "seq": c["seq"]}
                break
        if mejor:
            break
    return {
        "schema": "sifi.results/1",
        "run_id": None,
        "generated_at": None,
        "params": {
            "sirna_size": SIRNA_SIZE,
            "mismatches": 2,
            "mode": "design",
            "rnaplfold": {"W": 80, "span": 40, "T": 37.0},
        },
        "scoring": {
            "schema": "sifi.score/2",
            "version": 2,
            "pesos": {"E": 40, "R": 15, "S": 15, "T": 15, "D": 15},
        },
        "panel_ids": panels_sel,
        "panels": [PANELES_POR_ID[p] for p in panels_sel],
        "records": records,
        "summary": {
            "n_genes": len(records),
            "n_candidates": total,
            "por_banda": banda,
            "mejor": mejor,
        },
        "narrativa": NARRATIVA,
        "warnings": [],
    }


def main() -> None:
    rnd = random.Random(SEED)
    panels_ids = [p["id"] for p in PANELES]
    genes_ids = [g["id"] for g in GENES]

    # todas las combinaciones de paneles (2^5) × {todo, un gen}
    genesets = {"all": genes_ids}
    for gid in genes_ids:
        genesets["only_" + gid] = [gid]

    # Combinaciones curadas: el servidor de maqueta resuelve cualquier otra elección
    # con la variante más parecida (documentado en ui/README.md). Generar las 31
    # combinaciones posibles multiplicaba el JSON sin aportar nada a la revisión.
    subconjuntos = [
        ["dalbulus_maidis"],
        ["dalbulus_maidis", "maiz"],
        ["dalbulus_maidis", "maiz", "sulcia"],
        ["dalbulus_maidis", "maiz", "humano"],
        ["dalbulus_maidis", "maiz", "universal"],
        ["dalbulus_maidis", "maiz", "sulcia", "humano"],
        panels_ids,
    ]
    variants = {}
    for idx, sel in enumerate(subconjuntos):
        for gname, gsel in genesets.items():
            key = ",".join(sel) + "|" + gname
            variants[key] = build_variant(sel, gsel, random.Random(SEED + idx * 17 + sum(ord(c) for c in gname) % 97))

    data = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": SEED,
        "paneles": PANELES,
        "genes": [{k: v for k, v in g.items() if k != "secuencia"} for g in GENES],
        "variantes": variants,
        "narrativa": NARRATIVA,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    # el JSON plano se ignora en git; lo que se versiona es el gzip (166 KB vs 2,4 MB)
    import gzip
    with open(OUT, "rb") as src, gzip.open(OUT + ".gz", "wb", compresslevel=9) as dst:
        shutil_copy(src, dst)
    print("escrito %s (%d variantes, %.1f KB; gz %.1f KB)" % (
        OUT, len(variants), os.path.getsize(OUT) / 1024, os.path.getsize(OUT + ".gz") / 1024))


if __name__ == "__main__":
    main()
