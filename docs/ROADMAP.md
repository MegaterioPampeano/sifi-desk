---
title: "Si-Fi Agent Integration — Roadmap de ingeniería"
subtitle: "Programa instalable con agente de IA para diseño de dsRNA/siRNA y off-targets"
author: "Omnivac Science · documento interno"
date: "28 de octubre de 2026 · v1.0"
lang: es
---

# 0. Resumen ejecutivo

**Qué se construye.** Un programa de escritorio **instalable y distribuible por separado** (no un
feature de Multivac) que:

1. **incorpora siFi** (si-Fi / siRNA-Finder v1.2.3) en su funcionamiento, sin depender de Windows,
   de la GUI original ni de Wine;
2. tiene **un agente de IA enganchado** (DeepSeek Harness) que lo **controla**, lo **actualiza** y
   **busca novedades** de forma autónoma y auditable;
3. **genera reportes** reproducibles en PDF/HTML con la trazabilidad completa de cada corrida.

**Nombre de trabajo:** *Si-Fi Agent Integration* (a confirmar más adelante). **Org:** Omnivac Science.

**Por qué es posible.** El código de siFi ya está desacoplado: `SifiPipeline.run_pipeline()` calcula
todo, escribe el JSON completo (`sifi_pipeline.py:146`) y **recién después** llama a la capa de
gráficos. Ese `json.dump` es la costura por donde se corta el programa en headless. El trabajo no es
"reimplementar siFi", es **portar 2.700 líneas de Python 2 a Python 3 y desacoplar la GUI**.

**Por qué es delicado.** (a) la licencia de siFi es **CC BY-NC-SA 2.0** → el derivado hereda
no-comercial + share-alike; (b) DeepSeek Harness está en **developer preview** con cambios
rompientes; (c) la validez científica depende de reproducir *exactamente* los parámetros de
RNAplfold y de bowtie1: un cambio silencioso invalida todos los resultados.

---

# 1. El problema

## 1.1 Qué tenemos hoy

* **siFi / si-Fi v1.2.3-0008** — Lück, Kreszies, Strickert, Schweizer, Douchkov, *Front. Plant Sci.*
  2019 (doi:10.3389/fpls.2019.01023). Diseña siRNAs para una secuencia query y predice off-targets
  contra una base de secuencias. Es la referencia del área y es lo que el usuario final quiere usar.
* **Limitaciones de la herramienta original:**
  * `.exe` de Windows con GUI Qt4, empaquetado con py2exe, Python 2.7. Sin soporte, sin
    mantenimiento, dependiente de un entorno que ya no existe en máquinas nuevas.
  * **No tiene exportación implementada** ("the export function is not yet implemented"). El
    *workaround* oficial es abrir el JSON temporal que el programa deja en `%TEMP%`.
  * No es automatizable, no tiene CLI, no tiene API, no se puede encadenar en un pipeline.
* **Lo que ya construimos (chicharrita):** pipeline propio de priorización de blancos
  (`chicharrita/pipeline`), score v2 (E 40 · R 15 · T 15 · S 15 · D 15), paneles de no-blanco,
  informes HTML→PDF, y el skill `rnai-target-selection` con los criterios y las trampas aprendidas.

## 1.2 Qué falta y es el corazón del producto

No falta "un script más". Falta un **producto**: alguien que no sabe Python tiene que poder
descargar un instalador, abrirlo, pegar un gen, obtener candidatos con su evidencia, un reporte
presentable, y que el sistema se mantenga solo actualizado. Eso exige tres cosas que hoy no existen:

1. **siFi headless y portable** (sin Windows, sin GUI, sin Wine) con salida canónica.
2. **Un agente** que sepa operar ese núcleo: interpretar el pedido, elegir parámetros, correr, leer
   resultados, iterar, y explicar.
3. **Un ciclo de vida**: versiones, actualizaciones de bases, novedades científicas, reportes
   reproducibles.

## 1.3 Qué NO es este proyecto

* **No es una mejora de Multivac.** Es un binario/app independiente, con su propio instalador, su
  propio runtime y su propio ciclo de release. Multivac puede usarlo, pero no lo contiene.
* **No es un servicio web.** Es una app local (127.0.0.1), sin backend en la nube.
* **No es un reemplazo científico de siFi.** El objetivo de la Fase Core es **reproducir sus
  números**, no mejorarlos. Cualquier mejora va después y marcada como tal.
* **No es comercial.** La licencia del upstream lo impide (ver §9).

---

# 2. Objetivos y criterios de éxito

| Objetivo | Criterio de éxito medible |
|---|---|---|
| **O1 · Fidelidad** | Para ≥20 genes de prueba, el JSON del port es **idéntico** al del siFi original: mismas siRNAs, mismas posiciones, mismos hits, ΔG a ±0,01 kcal/mol |
| O2 | Independencia de plataforma | Corre en Windows 10/11, Linux x86_64 y macOS (arm64 y x64) **sin Wine y sin Qt4** |
| O3 | Control por agente | El 100 % de las operaciones (diseñar, off-target, construir DB, reportar, actualizar) se ejecuta desde el agente vía herramientas tipadas, sin tocar la GUI |
| O4 | Instalable | Un instalador por plataforma, con firma, que deja el sistema operativo en <10 min desde cero, offline para el core |
| O5 | Reproducibilidad | Cada reporte incluye un `run.json` que permite repetir la corrida bit a bit (versión de core, hash de DB, parámetros, commit) |
| O6 | Autonomía | El agente detecta novedades (papers, bases, versiones) y propone acciones; nada se aplica sin aprobación explícita del usuario |
| O7 | Trazabilidad | Toda acción del agente queda registrada (trajectory): qué tool, qué args, qué salida, quién aprobó |

---

# 3. Alcance

**Dentro (v1.0):**

* Port headless de siFi (modo *design* y modo *off-target*).
* Gestor de bases: paneles de no-blanco, versionado e indexado con bowtie1.
* Scoring propio v2 integrado (los 5 ejes E/R/T/S/D) usando la eficiencia de siFi como insumo del eje T.
* Agente DeepSeek Harness con 3 plugins propios y 2-3 skills.
* Ventana nativa con: proyectos, cola de corridas, visor de resultados, visor de reportes.
* Reportes PDF/HTML reproducibles.
* Watcher de novedades + updater con rollback.
* Instaladores firmados para las 3 plataformas.

**Fuera (v1.x o nunca):**

* Edición de secuencias / biología sintética / diseño de constructos.
* Simulación de entrega, formulación, cinética de silenciamiento.
* Multi-usuario, servidor, cuentas, nube.
* Modelos de IA propios entrenados (solo se usan los que ya existen).

---

# 4. Arquitectura general

## 4.1 Diagrama de capas

```
+----------------------------------------------------------------------+
|   VENTANA NATIVA (Tauri)                                             |
|   proyectos - cola - resultados - reportes - ajustes                 |
+------------------------------+---------------------------------------+
                               | IPC local 127.0.0.1 (token de sesion)
                               v
+------------------------------+-----------------------+---------------+
|   AGENTE - DeepSeek Harness (dsh)                                    |
|   +-------------+ +--------------+ +-------------------+             |
|   | sifi-tools  | | sifi-skills  | | sifi-watch        |             |
|   | (7 tools)   | | (3 skills)   | | (novedades)       |             |
|   +-------------+ +--------------+ +---------+---------+             |
+------------------------------+-----------------------+---------------+
                               | JSON-RPC / CLI        | HTTP lect.
                               v                       v
+------------------------------+-----------------------+---------------+
|   SERVICIO LOCAL  sifid  (Python 3 - FastAPI 127.0.0.1)              |
|   jobs - artifacts - runs - paneles - reportes - updater             |
+------------------------------+---------------------------------------+
                               |
                               v
+------------------------------+---------------------------------------+
|   CORE (Python 3, sin GUI)   | BINARIOS                              |
|   sifi/   port headless      | bowtie 1.3.x                          |
|   domain/ paneles y scoring  | RNAplfold (ViennaRNA 2.7)             |
|   thermo/ DeltaG             | empaquetados por plataforma           |
+------------------------------+---------------------------------------+
```

## 4.2 Flujo de una corrida (secuencia)

1. El usuario (o el agente) crea un **proyecto** y adjunta un FASTA / un ID de gen.
2. Se resuelve el **contexto**: genoma + anotación + paneles de no-blanco activos.
3. Se crea un **run** con `params.yaml` normalizado y un `run_id` determinista
   (`hash(seq + params + db.lock + core_version)`).
4. El servicio encola el job. El worker: corta la secuencia en *x*-mers → **bowtie1** contra la DB
   → **RNAplfold** sobre la query → reglas de eficiencia (selección de hebra, estabilidad de extremo,
   accesibilidad) → JSON canónico.
5. `domain/` agrega: scoring v2, veredicto, flags de riesgo, top-N.
6. Se emiten artefactos: `results.json`, `results.tsv`, `figs/*.png`.
7. El agente lee `results.json` (no el PDF), interpreta y **redacta**; el motor de reportes arma el PDF.
8. Todo queda en el `run` para replay.

## 4.3 Decisiones de arquitectura (con alternativas descartadas)

**A1. Port del código en vez de wrappear el .exe.**
*Alternativa:* correr el `.exe` bajo Wine + cosechar el JSON del `%TEMP%`.
*Decisión:* Wine **solo como oráculo de validación en desarrollo**, nunca en el producto.
*Motivo:* Wine no es instalable seriamente en macOS moderno ni en Windows ARM; el `%TEMP%` es
frágil; y el .exe es Python 2 congelado: no se puede instrumentar ni corregir.

**A2. Python para el core, Node para el agente.**
`dsh` es TypeScript sobre Cordis; el core científico es Python (Biopython, ViennaRNA, numpy,
matplotlib). Forzar uno solo de los dos lenguajes cuesta más que integrarlos.
*Consecuencia:* el producto es multi-runtime → el empaquetado (§5.8) es un problema de primer orden,
no un detalle final.

**A3. Servicio local con API estable, no import directo del core desde el agente.**
*Motivo:* el agente no debe poder ejecutar código arbitrario del core; debe hablar con un contrato
angosto y auditable. Además permite que la UI y el agente compartan estado y cola de trabajos.

**A4. El agente no genera el PDF: lo genera el motor de reportes.**
*Motivo:* reproducibilidad y consistencia. El agente redacta la narrativa; los números y figuras
salen de artefactos deterministas.

**A5. Tauri en vez de Electron.**
*Motivo:* instaladores de ~10-20 MB contra ~120 MB, webview del sistema, updater y sidecars nativos
integrados. *Alternativa de repliegue:* `pywebview` + PyInstaller si el toolchain de Rust se vuelve
un problema de cronograma (menos pulido, pero un solo lenguaje).

---

# 5. Componentes en detalle

## 5.1 Core: port headless de siFi

**Qué se porta.** El repo `snowformatics/siFi21-` (commit congelado y registrado en `VENDOR.md`):

| Archivo | Rol | Trabajo |
|---|---|---|
| `sifi_pipeline.py` (27,9 KB) | motor: corta, bowtie, RNAplfold, eficiencia, JSON | port Py2→Py3 + corte de la GUI |
| `free_energy.py` (≈8 KB) | ΔG con tablas NN propias | port a Biopython actual (`Bio.SeqUtils`) |
| `general_helpers.py` | tabla desde JSON | port menor |
| `database_helpers.py` | armado de DB | port + reemplazo de rutas Windows |
| `main.py`, `show_plot.py`, `create_plots.py`, `popup.py`, `threads.py` | GUI Qt4 | **NO se portan**: se reemplazan por `NullPresenter` |

**El corte exacto.** `run_pipeline()` se parte en dos:

```python
# core/sifi/pipeline.py
def run(self) -> PipelineResult:
    ...
    json_lst = self.data_to_json(query_name, input_data, no_target, lunp_data, main_targets)
    # ← CORTE: acá termina el cálculo
    return PipelineResult(query=query_name, sirnas=json_lst, table=self.table(json_lst),
                          diagnostics=self.diagnostics())
    # lo que sigue en el original (DrawPlot / plot.show) desaparece
```

Todo lo que era `plot.plot_design()` se reemplaza por `domain/` + `report/`, que trabajan sobre el
JSON, no sobre objetos de Qt.

**Puntos finos del port (los que rompen la fidelidad):**

1. **División entera / `print` / `xrange` / `.iteritems()` / `dict.keys()` como lista.**
2. **`free_energy.py` usa la API vieja de Biopython** (`Bio.Seq` previo a 1.71). Hay que mapear
   tabla por tabla y validar ΔG numéricamente.
3. **Codificación de archivos temporales** (Windows `cp1252` vs UTF-8) al leer/escribir FASTA.
4. **Rutas y `tempfile`**: el original asume `%TEMP%` de Windows; se reemplaza por un `run_dir` explícito.
5. **Parámetros de RNAplfold**: `-W 80 --span=… -u …` con la misma temperatura (37 °C) y el mismo
   modelo de energía. Si cambia uno, cambian las accesibilidades y todo el ranking.
6. **bowtie1 con `-v <mismatches>`** (no `-n`, no bowtie2). Se fija el binario y se registra su hash.

**Salida canónica.** `results.json` con esquema versionado:

```json
{
  "schema": "sifi.results/1",
  "run_id": "…",
  "query": {"id": "Gene_1", "length": 1532, "sha256": "…"},
  "params": {"sirna_size": 21, "mismatches": 2, "mode": "design", "rnaplfold": {"W": 80, "span": 40, "T": 37.0}},
  "core": {"version": "0.1.0", "vendor_commit": "…", "bowtie": "1.3.1", "viennarna": "2.7.2"},
  "sirnas": [
    {"id": "s1", "pos": 134, "seq": "…", "gc": 47.6, "dg": -34.21, "strand": "guide",
     "end_stability": 0.31, "accessibility": 0.72, "efficient": true, "score": 0.81,
     "hits": [{"db": "maiz", "seq_id": "Zm00001eb…", "mismatch": 1, "pos": 812}]}
  ],
  "summary": {"n_sirnas": 1512, "n_efficient": 233, "n_with_offtarget": 12},
  "warnings": []
}
```

## 5.2 Dominio: bases, paneles y scoring

**Registro de bases.** Cada panel es un objeto versionado:

```yaml
# panels/maiz.yaml
id: maiz
nombre: "Zea mays B73 (RefGen_v5)"
fuente: "https://download.maizegdb.org/…"
sha256_fasta: "…"
sha256_bowtie: "…"
bowtie_build: "1.3.1"
fecha_ingesta: "2026-10-01"
# todo panel debe declarar por qué está: no-blanco, patógeno, simbionte, control
rol: no_blanco
```

**Paneles mínimos para chicharrita** (a confirmar, §12): maíz, *Dalbulus maidis* (genoma), su
simbionte, polinizadores/enemigos naturales, humano (control de especificidad), y un panel
"universal" de transcritos no relacionados como control negativo.

**Scoring v2** (ya implementado, se reusa): E 40 · R 15 · T 15 · S 15 · D 15.
Lo que cambia es el insumo del eje **T**: pasa de una heurística propia a la
`efficient`/`score` de siFi. Se conserva el histórico para poder comparar v2 vs v3.

## 5.3 Servicio local (`sifid`)

* FastAPI + uvicorn en `127.0.0.1`, puerto efímero, **token de sesión** en cada request.
* Cola de trabajos en SQLite (WAL) + worker pool (`--jobs`).
* Endpoints (v1): `POST /runs`, `GET /runs/{id}`, `GET /runs/{id}/artifacts/{name}`, `POST /runs/{id}/cancel`,
  `GET /panels`, `POST /panels/{id}/build`, `POST /reports`, `GET /health`, `GET /version`.
* Reanudable: si el proceso muere, los runs `running` se marcan `interrupted` y se pueden relanzar
  (los artefactos parciales se descartan, nunca se mezclan).

## 5.4 Agente: DeepSeek Harness

**Por qué dsh.** Es open source (MIT), corre local, el *todo es un plugin* (model adapter, tool
registry, permisos y hasta el loop son reemplazables), tiene UI web local (`127.0.0.1:3080`),
configuración declarativa YAML (`cordis.yml`), HMR y *trajectory tracing*. Encaja con el requisito
"el agente es parte del producto, no un servicio externo".

**Riesgo asumido:** está en *developer preview* con cambios rompientes anunciados → se **pinnea la
versión** y se aísla tras una capa de adaptación (`agent/adapter/`), para poder cambiar de harness sin
reescribir el producto.

### 5.4.1 Plugin `dsh-sifi-tools` — el contrato con el core

Siete herramientas, todas tipadas, todas devolviendo JSON canónico (nunca prosa):

| Tool | Entrada | Salida |
|---|---|---|
| `sifi_design` | `{fasta?|gene_id, sirna_size?, mismatches?, panel_ids[]}` | `{run_id, n_sirnas, top10[]}` |
| `sifi_offtarget` | `{run_id, panel_ids[]}` | `{run_id, hits_by_panel[]}` |
| `sifi_list_panels` | `{}` | `{panels[]}` |
| `sifi_build_panel` | `{panel_id, fasta_url|path, bowtie_version}` | `{panel_id, sha256, n_seqs}` |
| `sifi_get_run` | `{run_id}` | `results.json` completo o resumen |
| `sifi_make_report` | `{run_id, template, formato}` | `{report_path}` |
| `sifi_watch` | `{since?}` | `{novedades[]}` |

Forma (referencia real del API de dsh):

```ts
export const name = 'sifi-tools'
export const inject = ['tools']

export function apply(ctx: Context) {
  ctx.tools.register(defineTool({
    name: 'sifi_design',
    description: 'Diseña siRNAs para una secuencia contra una base ya indexada.',
    parameters: {
      gene_id:   { type: 'string', required: true, description: 'ID del gen o ruta FASTA' },
      sirna_size:{ type: 'number', description: 'Largo del siRNA (default 21)' },
      mismatches:{ type: 'number', description: 'Mismatches permitidos en bowtie -v (default 2)' },
      panel_ids: { type: 'array', items: { type: 'string' } },
    },
    output: { schema: { type: 'object' }, render: (_a, v) => [{ type: 'text', text: summarize(v) }] },
    async execute(args, exec) {
      return sifid.post('/runs', args, { signal: exec.signal })   // el core hace el trabajo
    },
  }))
}
```

Reglas que se respetan (las exige el harness):
* `args` llega validado; igual se validan reglas cruzadas a mano (positivos, no vacíos).
* `output.schema` es la API programática: ids y campos directos, la prosa va en `render`.
* Cancelación: se propaga `exec.signal` al request HTTP.
* Trabajo largo (>30 s): `run_in_background` + `ctx.jobs.start({kind:'sifi', label, owner, run})`,
  devolviendo un handle `{kind:'background', jobId}` en vez de bloquear el turno.

### 5.4.2 Plugin `dsh-sifi-skills`

Empaqueta los procedimientos como *skills* (el harness tiene un provider de skills empaquetadas):

* `disenar-dsrna.md` — protocolo completo: validación de la secuencia, elección de tamaño/mismatches,
  qué paneles, cómo leer el JSON, qué NO concluir.
* `triaje-offtarget.md` — cómo clasificar un hit (UTR vs CDS, conservación del seed, si es letal en
  no-blanco) y cuándo **descartar** un candidato aunque tenga buena eficiencia.
* `redactar-informe.md` — estructura del reporte, qué gráficos, qué lenguaje, qué límites declarar.

Los skills son instrucciones, no código: viven en Markdown y se versionan con el producto.

### 5.4.3 Plugin `dsh-sifi-watch` — "buscar novedades"

Cuatro vigilantes, cada uno con su fuente y su criterio de relevancia:

| Vigilante | Fuente | Frecuencia | Qué produce |
|---|---|---|---|
| Literatura | PubMed/EuropePMC: `(RNAi OR dsRNA OR siRNA) AND (insect OR Hemiptera OR pest control)` | semanal | papers nuevos + resumen de 3 líneas |
| Upstream siFi | GitHub releases / SourceForge | semanal | ¿hay versión nueva? ¿cambia el algoritmo? |
| Bases | NCBI Datasets (genoma/anotación de *D. maidis*, maíz, simbiontes) | mensual | nuevas versiones → propone rebuild de panel |
| Toolchain | bowtie, ViennaRNA | mensual | changelog + riesgo de invalidar corridas |

Salida: un *digest* con `{titulo, url, fecha, por_que_importa, accion_sugerida}`.
**Nada se aplica solo.** El agente propone; el usuario aprueba (y esa aprobación queda en el log).

### 5.4.4 Permisos y sandbox

* Las tools de escritura (`build_panel`, `make_report`, `apply_update`) pasan por
  `tools/pre-execute` con política **allow/ask/deny**: por defecto `ask` para todo lo que toque
  bases o descargue de red.
* El agente **no** tiene shell libre por defecto: no necesita `bash` para operar el producto. Si se
  habilita, es un modo "avanzado" explícito y avisado en la UI.
* Descargas de red: solo dominios de la allowlist (NCBI, MaizeGDB, GitHub, SourceForge, EuropePMC).

## 5.5 Interfaz: la ventana nativa

Cinco vistas, nada más:

1. **Proyecto** — nombre, organismo, genoma de referencia, paneles activos.
2. **Secuencia** — pegar FASTA / buscar gen por ID / ver el gen con sus regiones.
3. **Corrida** — parámetros, cola, progreso real (no spinner infinito), log colapsable.
4. **Resultados** — tabla ordenable de siRNAs (eficiencia, ΔG, accesibilidad, hits), mapa del gen con
   las posiciones, y el detalle de cada off-target.
5. **Reporte** — preview del PDF + botón exportar.

Más un **panel de agente** lateral: el chat del harness embebido, con las tarjetas de cada tool call
(qué corrió, con qué parámetros, qué devolvió) y los botones de aprobación.

La UI **no recalcula nada**: todo viene del servicio. Es una vista.

## 5.6 Reportes

* Motor: **Jinja2 → HTML → PDF (WeasyPrint)**, figuras en matplotlib a 200 dpi (SVG cuando el
  template lo permita).
* Estructura fija: portada (proyecto, fecha, versión de core, hash de DB) · resumen ejecutivo ·
  método (parámetros exactos) · tabla de candidatos · mapas de off-target · riesgos y límites ·
  anexo de reproducibilidad (`run.json` embebido).
* **Trazabilidad obligatoria en el pie de cada página:** `run_id` corto + versión + fecha.
* Plantillas versionadas; el usuario puede elegir "técnico" o "ejecutivo".

## 5.7 Actualizaciones

* **Del producto:** releases firmados, updater de Tauri, canal `stable`/`beta`, **rollback** a la
  versión anterior desde la UI.
* **Del core científico (paneles, DBs):** versionado independiente del binario. Un panel nuevo no
  requiere reinstalar el programa.
* **Regla de oro:** antes de promover una actualización del core, se corre la **suite dorada**
  (§10) contra el oráculo. Si cambia un número sin explicación, no se promueve.

## 5.8 Empaquetado y distribución

**Composición del instalable:**

```
siFi-Desk-1.0.0-x64.msi / .AppImage / .dmg
├── ui/                 (Tauri: webview + sidecars)
├── sidecar: sifid      (PyInstaller onedir, Python 3.11 embebido)
├── sidecar: node       (runtime para dsh, versión pinneada)
├── bin/                bowtie, bowtie-build, RNAplfold (por plataforma)
├── panels/             (metadatos; las secuencias se bajan aparte por tamaño)
└── licenses/           (siFi CC BY-NC-SA, dsh MIT, bowtie Artistic-2.0, ViennaRNA)
```

**Reglas de empaquetado:**

* Nada de dependencias del sistema: Python y Node van embebidos. Bowtie y RNAplfold se compilan por
  plataforma y se incluyen como binarios.
* Las bases **no** viajan en el instalador (pesan GB): se descargan en el primer arranque con
  checksum verificado y reanudable.
* Firma de código: Authenticode (Windows), notarización (macOS), AppImage sin firma pero con checksum
  publicado (Linux).
* Primer arranque: asistente de 3 pasos (elegir paneles → descargar → verificar).

---

# 6. Contratos

## 6.1 `params.yaml` (entrada de una corrida)

```yaml
schema: sifi.params/1
mode: design            # design | offtarget
query: {kind: fasta, path: "…"}   # o {kind: gene, id: "…", genome: "dalbulus_v1"}
sirna: {size: 21, mismatches: 2}
rnaplfold: {W: 80, span: 40, temperature: 37.0}
panels: [maiz, dalbulus, simbionte]
scoring: {version: 2, weights: {E: 40, R: 15, T: 15, S: 15, D: 15}}
limits: {max_hits_per_sirna: 50, timeout_s: 900}
```

## 6.2 Estados de un run

`queued → running → (done | failed | canceled | interrupted)`
Cada transición se persiste con timestamp y causa. `interrupted` solo se alcanza por muerte del
proceso; nunca se reutiliza un `run_id`.

## 6.3 Versionado

* `core_version` (semver) — cambia si cambia cualquier número del output.
* `vendor_commit` — commit del repo de siFi del que se portó.
* `panel.version` — semver propio por panel.
* `schema` — `sifi.results/1`; los cambios incompatibles suben el número.

---

# 7. Modelo de datos y artefactos

```
~/siFiDesk/
├── projects/<proj>/project.json
├── runs/<run_id>/
│   ├── params.yaml        run.json         results.json
│   ├── results.tsv        figs/*.png       logs/worker.log
│   └── report.pdf
├── panels/<panel_id>/<version>/{seqs.fa, index/*.ebwt, meta.yaml}
└── cache/                 (descargas, temporales, limpieza automática)
```

Un `run` es **inmutable** una vez `done`. Reejecutar crea otro `run_id`.

---

# 8. Hitos

Cada hito tiene un **DoD** (definition of done) verificable. No hay fechas: hay orden y criterio de
salida.

## M0 — Fundaciones y legal

* Repo local (sin publicar) en `/mnt/datos/proyectos/sifi-desk`, estructura de §11, CI local, pre-commit.
* `VENDOR.md` con el commit exacto de siFi, su licencia y qué se porta y qué no.
* Decisión registrada sobre licencia del producto derivado (§9).
* **DoD:** `make bootstrap` deja el entorno listo en una máquina limpia; `LICENSES.md` completo.

## M1 — Core headless + oráculo

* SiFi original corriendo bajo Wine en una máquina de desarrollo (**solo dev**) con 20 genes de prueba
  y sus JSON guardados como *golden files*.
* Port Py3 de `sifi_pipeline.py` + `free_energy.py` + helpers, sin GUI.
* **DoD:** `pytest tests/golden` verde: JSON equivalente en los 20 genes; ΔG ±0,01; 0 diferencias en
  posiciones y hits. Cualquier diferencia está documentada y justificada en `PORT_NOTES.md`.

## M2 — Dominio

* Registro de paneles, ingesta + indexado bowtie, `db.lock`.
* Scoring v2 integrado con la eficiencia de siFi; comparación v2 vs v3 sobre el histórico de chicharrita.
* **DoD:** reconstruir el shortlist de chicharrita desde cero con un comando; diferencias contra el
  informe anterior explicadas una por una.

## M3 — Servicio local

* `sifid` con los endpoints de §5.3, cola SQLite, cancelación, reanudación.
* **DoD:** matar el proceso a mitad de un run y verificar que el estado queda `interrupted` y el run
  se puede relanzar limpio; 100 % de los endpoints con test.

## M4 — Agente

* dsh pinneado + `cordis.yml` del producto.
* `dsh-sifi-tools` (7 tools), `dsh-sifi-skills` (3 skills), política de permisos.
* **DoD:** un pedido en lenguaje natural ("diseñá dsRNA para el gen X contra maíz y el simbionte,
  dame el top 10") se completa de punta a punta sin intervención manual, y el log muestra cada tool
  call con sus args.

## M5 — Ventana nativa

* Tauri + las 5 vistas + panel de agente + aprobaciones.
* **DoD:** un usuario que nunca vio el proyecto completa el flujo completo sin tocar la terminal.

## M6 — Reportes

* Motor de plantillas, 2 plantillas, exportación, `run.json` embebido.
* **DoD:** dos PDFs del mismo run son byte-idénticos salvo timestamp; el anexo permite repetir la corrida.

## M7 — Novedades y actualizaciones

* Los 4 vigilantes + digest + updater con rollback + gate de la suite dorada.
* **DoD:** simular una "versión nueva" del core que rompe un número → el updater la bloquea y reporta.

## M8 — Distribución

* Instaladores firmados de las 3 plataformas, primer arranque, descarga de paneles, docs de usuario.
* **DoD:** máquina virtual limpia → instalado → corrida completa → reporte, en menos de 10 minutos y
  sin conexión después de bajar los paneles.

## Transversal (no es un hito, es una regla)

Testing, i18n (es/en), accesibilidad de la UI, telemetría **opt-in y local**, y documentación se
construyen dentro de cada hito, no al final.

---

# 9. Riesgos

## 9.1 Legales (bloqueantes si se ignoran)

| Riesgo | Detalle | Mitigación |
|---|---|---|
| **CC BY-NC-SA 2.0** | siFi prohíbe uso comercial y obliga share-alike. El port es obra derivada | Producto gratuito, código del port publicado/entregable con el binario, `LICENSES.md` visible. **Nada de venta, SaaS ni bundle comercial** |
| ViennaRNA | licencia académica/no comercial para uso comercial | Ya estamos en NC por siFi; igual se documenta |
| bowtie | Artistic License 2.0 | Compatible; se incluye el aviso |
| dsh | MIT | Compatible; se incluye el aviso |
| Datos genómicos | Términos de NCBI/MaizeGDB | Los paneles se descargan del origen, no se redistribuyen |

**Consecuencia dura:** si en algún momento se quiere vender, hay que **reescribir el core sin siFi**
(usando solo los papers y una implementación propia). Eso es otro proyecto. Conviene saberlo ahora.

## 9.2 Técnicos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| dsh en developer preview, cambios rompientes | El agente deja de arrancar tras un update | Versión pinneada + capa adaptadora + tests de contrato |
| Deriva numérica en el port | Todos los resultados quedan inválidos | Suite dorada contra el oráculo en cada commit |
| Multi-runtime (Python + Node + binarios) | Instaladores frágiles, soporte imposible | Empaquetado como problema de primer orden desde M0; CI en las 3 plataformas desde M1 |
| RNAplfold/bowtie no disponibles para alguna arquitectura | Se cae una plataforma | Verificar temprano; si macOS-arm64 falla, se documenta la limitación antes de prometer |
| Bases de datos enormes | Primer arranque eterno | Descarga por panel, reanudable, con checksum y opción "solo maíz" |

## 9.3 Científicos

| Riesgo | Mitigación |
|---|---|
| Un siRNA "eficiente" in silico no silencia in vivo | El reporte declara explícitamente que es predicción; se rankea, no se promete |
| Off-target en el propio insecto (no solo en no-blanco) | Panel del genoma del insecto siempre activo, no opcional |
| Falsos negativos por paneles incompletos | El reporte lista los paneles usados y advierte sobre los ausentes |

---

# 10. Testing y validación

1. **Suite dorada (la más importante).** 20 genes × 2 modos contra el oráculo (siFi bajo Wine).
   Comparación campo por campo del JSON. Se corre en cada commit y **bloquea releases**.
2. **Tests unitarios del dominio.** Scoring, parseo de FASTA, normalización de parámetros, `run_id`
   determinista.
3. **Tests de contrato del agente.** Cada tool: esquema de entrada, esquema de salida, cancelación,
   timeout, error de red.
4. **Tests de UI end-to-end.** Playwright sobre la ventana: flujo completo con un FASTA pequeño.
5. **Prueba de reproducibilidad.** Mismo run dos veces → `results.json` idéntico (hash).
6. **Prueba de regresión científica.** El shortlist de chicharrita debe reproducirse; si cambia, hay
   que explicar por qué en el changelog.

---

# 11. Estructura del repo

```
sifi-desk/
├── core/                     # Python 3, sin GUI
│   ├── sifi/                 # port de siFi (vendorizado, con PORT_NOTES.md)
│   ├── domain/               # paneles, scoring, ingesta
│   ├── thermo/               # ΔG
│   ├── report/               # Jinja2 + WeasyPrint
│   └── service/              # FastAPI, cola, jobs
├── agent/                    # TypeScript
│   ├── cordis.yml            # composición del producto
│   ├── plugins/sifi-tools/
│   ├── plugins/sifi-skills/skills/*.md
│   ├── plugins/sifi-watch/
│   └── adapter/              # aislamiento de la versión de dsh
├── ui/                       # Tauri (Rust + web)
├── packaging/                # PyInstaller, sidecars, firmas, instaladores
├── panels/                   # metadatos de paneles (no secuencias)
├── tests/{golden,unit,contract,e2e}/
├── docs/                     # usuario, ingeniería, ADRs
├── VENDOR.md  LICENSES.md  ROADMAP.md  CHANGELOG.md
└── Makefile                  # bootstrap, test, build, package, release
```

---

# 12. Decisiones tomadas (2026-10-28)

| # | Decisión | Estado |
|---|---|---|
| 1 | **Nombre** | *Si-Fi Agent Integration*, provisorio ("después vemos bien") |
| 2 | **Organización** | **Omnivac Science** |
| 3 | **Paneles** | configurables por el usuario; obligatorios por defecto: **humano**, y en nuestro caso **maíz** y **polinizadores** |
| 4 | **Alcance del agente** | opción 2: controla el core **y** redacta/conversa con el usuario dentro de la app |
| 5 | **Distribución** | local + GitHub Releases, y landing de descarga |
| 6 | **Plataformas** | **Windows primero**, después Linux. **macOS no** (por ahora) |
| 7 | **No comercial** | **aceptado**. Si el proyecto funciona, vendrán otros productos con IA encima |
| 8 | **RNAplfold** | no es prioridad *en sí*: la arquitectura debe permitir enchufar **nuevos evaluadores in silico** (bioquímicos o de otro tipo) sin reescribir el core. Se arranca por siFi |

**Consecuencia de 6:** el hito M8 se recorta a `.msi` (Windows) + `.AppImage`/`.deb` (Linux).
El toolchain de Tauri para macOS queda fuera de alcance; el diseño no se rompe si se agrega después.

**Consecuencia de 8:** el core expone un *registro de evaluadores* (§5.2) con una interfaz
común; siFi es el primero implementado. Un evaluador nuevo (p. ej. otro modelo de eficiencia,
otro predictor de estructura) se suma como plugin del core y aparece automáticamente en el
agente y en los reportes.

# 12bis. Decisiones todavía abiertas

Ninguna bloqueante. Quedan para más adelante: firma de código (requiere certificado),
identidad visual, e idioma de la UI (arranca en español, i18n en inglés preparada).

# 13. Glosario

* **siRNA / dsRNA** — ARN corto de interferencia / ARN doble cadena que dispara RNAi.
* **Off-target** — secuencia no buscada que también podría silenciarse.
* **bowtie1** — alineador de secuencias cortas; siFi usa esta versión y su modo `-v`.
* **RNAplfold** — calcula probabilidades de apareamiento local (accesibilidad del sitio blanco).
* **ΔG** — energía libre de unión; más negativa = unión más estable.
* **dsh** — DeepSeek Harness, el runtime del agente (todo es un plugin, sobre Cordis).
* **Cordis** — microkernel de composición sobre el que corre dsh.
* **Oráculo** — el siFi original corriendo bajo Wine, usado solo para validar el port.
