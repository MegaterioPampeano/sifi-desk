# VENDOR — código de terceros

## si-Fi / siFi21 (upstream del núcleo científico)

| | |
|---|---|
| Repo | https://github.com/snowformatics/siFi21- |
| Commit vendorizado | `d6296b73c08a2176e9d0257e0a175278cff8c231` (2025-03-18) |
| Versión | si-Fi v1.2.3-0008 |
| Licencia | CC BY-NC-SA 2.0 — ver `LICENSE-siFi.md` |
| Ubicación | `vendor/siFi21/` (copia verbatim, **no se edita**) |
| Paper | Lück et al., *Front. Plant Sci.* 10:1023 (2019), doi:10.3389/fpls.2019.01023 |

**Qué se usa:** el algoritmo (`sifi_pipeline.py`, `free_energy.py`) y las tablas
termodinámicas. **Qué no se usa:** toda la GUI (`main.py`, `show_plot.py`,
`create_plots.py`, `popup.py`, `db_wizard.py`, `imageviewer.py`, recursos `.ui`/`.qrc`,
`sifi_2015_rc.py`).

El port vive en `core/sifi/` y está documentado en `PORT_NOTES.md`.

## Binarios

| Herramienta | Versión | Licencia | Uso |
|---|---|---|---|
| bowtie | 1.3.1 (linux-x86_64) | Artistic License 2.0 | alineamiento de x-mers (`-a -v N -y`) |
| ViennaRNA (RNAplfold) | 2.7.2 (compilado desde fuente) | ViennaRNA License (académico/no comercial) | accesibilidad del sitio blanco (`_lunp`) |

Ambos se empaquetan por plataforma en `packaging/vendor/`. Se registra el hash de cada
binario en `results.json` para que una corrida sea reproducible.

> ⚠️ Las tres licencias (siFi, ViennaRNA) son no comerciales. Es coherente con la
> decisión del proyecto (ver `ROADMAP.md` §9.1).

## Agente

| | |
|---|---|
| DeepSeek Harness (dsh) | MIT · https://github.com/deepseek-ai/deepseek-harness |
| Cordis | MIT · https://github.com/cordiverse/cordis |
| Versión | **pinnear** en `agent/package.json` + lockfile (developer preview, cambios rompientes) |
