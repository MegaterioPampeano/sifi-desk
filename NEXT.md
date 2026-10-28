# NEXT — cola de trabajo del agente

> Este archivo es la **única** fuente de verdad sobre "qué sigue". Se actualiza al final de
> cada paso: se marca lo hecho y se anota el próximo. Si algo requiere una decisión de
> Mariano, va a `docs/PREGUNTAS.md` y **no se implementa**.

## Reglas permanentes

1. `vendor/` es upstream verbatim: **no se edita nunca**.
2. Si se toca `core/sifi/pipeline.py` o `core/sifi/free_energy.py`: correr `make golden`
   (test diferencial) **antes** de commitear. Si falla, no se commitea.
3. Un commit por paso, mensaje `Mx: <qué se hizo>`.
4. Nada de `sudo`, nada de borrar `build/` (tiene los binarios compilados).
5. Español en docs y mensajes; inglés en identificadores de código.

## Estado

- [x] M0 fundaciones (repo, vendor, licencias, notas)
- [x] M1 core headless + test diferencial idéntico al original
- [~] **M2 dominio (paneles + scoring)** ← en curso
- [ ] M3 servicio local `sifid`
- [ ] M4 agente dsh + plugins
- [ ] M5 ventana nativa
- [ ] M6 reportes
- [ ] M7 novedades/actualizaciones
- [ ] M8 distribución

## Paso actual: 2.2 — scoring v2

Implementar el scoring sobre `results.json`: componentes E (eficiencia), R (riesgo),
S (especificidad), T (que sale de la eficiencia de siFi) y D (diseño), con pesos
versionados y desglose explicable por candidato (ver `docs/ROADMAP.md`).

* [ ] Definir `core/sifi/score.yaml` (pesos + umbrales) y versionarlo.
* [ ] `core/sifi/scoring.py`: `score_candidates(results, params) -> list[dict]` con el
      desglose por componente, no sólo el total.
* [ ] Test con un `results.json` fixture: monotonicidad (mejor eficiencia ⇒ mejor score)
      y que el desglose cierre contra el total con los pesos declarados.
* [ ] Commit.

## Hecho: 2.1 — registro de paneles (`core/sifi/panels.py`)

* [x] `PanelSpec` (id, nombre, rol, fuente, versión, sha256 del FASTA y del índice).
* [x] `PanelsRegistry` que lee/escribe `panels/<id>/<version>/meta.yaml`.
* [x] `ingest(panel_spec, fasta_path)` → normaliza y copia el FASTA, corre `bowtie-build`,
      calcula fingerprints, escribe `meta.yaml` y devuelve el `PanelSpec`.
* [x] `resolve(panel_ids)` → prefijos de índice bowtie en orden; error claro si falta alguno.
* [x] Test: `toy.fa` como panel `toy`, fingerprint estable al reingestar y cambio detectado
      si cambia el FASTA (`tests/unit/test_panels.py`, 7 tests).
* [x] Commit (`cc10041`).

### Siguientes (en orden, no adelantar)

2.3 comparación contra el shortlist histórico de chicharrita (documentar diferencias)
3.1 esqueleto de `sifid` (FastAPI, cola SQLite, endpoints de ROADMAP §5.3)
3.2 cancelación + reanudación (matar el proceso a mitad → estado `interrupted`)
4.1 scaffold de `agent/` con dsh pinneado + `cordis.yml`
4.2 plugin `sifi-tools` con las 7 tools

## Registro

| fecha (UTC) | paso | resultado |
|---|---|---|
| 2026-10-28 18:10 | M0/M1 | port idéntico al original en 6 configuraciones |
| 2026-10-28 18:20 | M2 · panel build/list/show | índice bowtie1 + meta.yaml con sha256 (431d362) |
| 2026-10-28 18:35 | M2 · 2.1 | PanelSpec + PanelsRegistry (ingest idempotente, resolve multi-panel) + 7 tests (cc10041) |
