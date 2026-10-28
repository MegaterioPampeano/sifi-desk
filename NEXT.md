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
- [ ] **M2 dominio (paneles + scoring)** ← en curso
- [ ] M3 servicio local `sifid`
- [ ] M4 agente dsh + plugins
- [ ] M5 ventana nativa
- [ ] M6 reportes
- [ ] M7 novedades/actualizaciones
- [ ] M8 distribución

## Paso actual: 2.1 — registro de paneles

Implementar `core/domain/panels.py`:

* [ ] `PanelSpec` (id, nombre, rol, fuente, versión, sha256 del FASTA, sha256 del índice).
* [ ] `PanelsRegistry` que lee/escribe `panels/<id>/<version>/meta.yaml`.
* [ ] `ingest(panel_spec, fasta_path)` → copia el FASTA, corre `bowtie-build`, calcula
      fingerprints, escribe `meta.yaml` y devuelve el `PanelSpec` resultante.
* [ ] `resolve(panel_ids)` → lista de rutas de índice listas para bowtie; error claro si
      falta alguno.
* [ ] Test: ingestar `tests/data/toy.fa` como panel `toy`, verificar fingerprint estable
      (mismo resultado si se ingesta dos veces) y detección de cambio si cambia el FASTA.
* [ ] Commit.

### Siguientes (en orden, no adelantar)

2.2 scoring v2 sobre `results.json` (E/R/T/S/D, T sale de la eficiencia de siFi)
2.3 comparación contra el shortlist histórico de chicharrita (documentar diferencias)
3.1 esqueleto de `sifid` (FastAPI, cola SQLite, endpoints de ROADMAP §5.3)
3.2 cancelación + reanudación (matar el proceso a mitad → estado `interrupted`)
4.1 scaffold de `agent/` con dsh pinneado + `cordis.yml`
4.2 plugin `sifi-tools` con las 7 tools

## Registro

| fecha (UTC) | paso | resultado |
|---|---|---|
| 2026-10-28 18:10 | M0/M1 | port idéntico al original en 6 configuraciones |
