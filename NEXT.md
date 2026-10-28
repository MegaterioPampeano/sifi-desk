# NEXT — cola de trabajo del agente

> Este archivo es la **única** fuente de verdad sobre "qué sigue". Se actualiza al final de
> cada paso: se marca lo hecho y se anota el próximo. Si algo requiere una decisión de
> Mariano, va a `docs/PREGUNTAS.md` y **no se implementa**.

## Modo paralelo (desde 2026-10-28 19:20 UTC)

A partir de acá el trabajo se reparte en **tres frentes independientes** que corren en
worktrees separados: ver `docs/STREAMS.md`. El supervisor (cron `sifi-reporte`) lanza un
subagente por frente, verifica tests y mergea a `master` en orden.

* `w/servicio`  → M3 (`core/service/**`)
* `w/reportes`  → M6 (`core/report/**`)
* `w/novedades` → M7 (`core/watch/**`)

Lo que sigue en `master` (secuencial, lo hago yo): M2.3 comparación con el shortlist histórico,
M4 agente (dsh + plugins), M5 ventana, M8 empaquetado.

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
- [~] **M2 dominio (paneles + scoring)** ← en curso (2.3)
- [ ] M3 servicio local `sifid`
- [ ] M4 agente dsh + plugins
- [ ] M5 ventana nativa
- [ ] M6 reportes
- [ ] M7 novedades/actualizaciones
- [ ] M8 distribución

## Paso actual: 2.3 — comparación contra el shortlist histórico de chicharrita

Tomar el shortlist de candidatos que ya tenemos de chicharrita, correr el core headless
sobre las mismas secuencias y documentar en qué coincide y en qué se aparta
(`docs/COMPARACION.md`), incluyendo el scoring v2 vs el histórico. El objetivo no es
"que gane" el nuevo: es saber por qué cambian los números antes de mostrárselos a nadie.

* [ ] Armar el set de secuencias de entrada (mismo FASTA que el pipeline histórico).
* [ ] Correr el core y el scoring v2; guardar `results.json` + scores como artefactos.
* [ ] Tabla de diferencias por candidato (posición, eficiencia, hits, score) y explicación
      de las divergencias (parámetros de RNAplfold, versión de panel, pesos).
* [ ] Commit.

## Hecho: 2.2 — scoring v2 (`core/sifi/scoring.py`)

* [x] `core/sifi/score.yaml` con pesos E 40 · R 15 · S 15 · T 15 · D 15 (suman 100, se valida),
      umbrales de banda y parámetros por eje. `version: 2` viaja en cada resultado.
* [x] `score_candidates(results, params?, panel_roles?)` → lista ordenada con `total` (0..100),
      `banda`, `notas` y `desglose` por eje (valor, peso, aporte y detalle).
* [x] Ejes: E = accesibilidad + hebra + extremo (0.5/0.25/0.25); T = `is_efficient` (+ `score`
      de siFi si viene); S = decaimiento por hits distintos; R = severidad del peor hit según
      mismatches × rol del panel (patógeno no resta, humano/no-blanco sí); D = GC, homopolímeros
      y extremo 5'.
* [x] Acepta el manifest de `run.py` (`records[].sirnas[]`), el esquema canónico (`sirnas[].hits[]`)
      o una lista de filas; agrupa por siRNA y descarta el main target como off-target.
* [x] `NA` en accesibilidad se marca (`sin_accesibilidad`) y usa el valor declarado, no cero.
* [x] Test: 14 casos (`tests/unit/test_scoring.py`) con fixture `tests/data/results_fixture.json`:
      cierre del desglose contra el total, monotonía (0.90 > 0.60 > 0.20 de accesibilidad),
      hit perfecto en humano, hit en patógeno, rol desconocido conservador, override de pesos.
* [x] Commit (`55a1956`).

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
| 2026-10-28 18:50 | M2 · 2.2 | scoring v2: score.yaml + score_candidates con desglose E/R/S/T/D, 14 tests (55a1956) |
