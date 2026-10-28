# `agent/` — el agente del producto Si-Fi

Implementa el **M4** del roadmap: las siete herramientas con las que el agente opera el
producto, su persona y su integración con **dsh** (`@deepseek-ai/dsh`, el harness real).

```
agent/
├── package.json              # sin deps de harness; tests + bin de desarrollo
├── prompts/system.md         # persona y reglas duras del agente (única fuente)
├── src/client.mjs            # cliente HTTP de sifid (errores accionables)
├── src/tools.mjs             # las 7 tools: esquema + validación + execute + render
├── src/dsh-tools.mjs         # puente a la API real de @deepseek-ai/dsh-tools
├── bin/sifi-agent.mjs        # banco de pruebas sin LLM
├── test/tools.test.mjs       # 14 tests contra un sifid falso (node:http)
├── test/fake-sifid.mjs       # sifid falso mínimo para smoke manual
└── dsh/                      # DSH_HOME del producto + perfil `sifi`
    ├── profiles/sifi/        # package.json (bundles) + cordis.patch.yml
    └── bundles/sifi-tools/   # bundle: registra las 7 tools + la persona
```

**Regla de oro:** este paquete **no importa el core de Python**. Todo va por HTTP a `sifid`.
Si el servicio no está, la tool devuelve el comando exacto para arrancarlo.

## Requisitos

- Node **22+** (usa `fetch`, `AbortSignal.any`, `node:test`).
- `sifid` corriendo (frente M3): `python3 -m service.app --port 8765`.
- Para el agente con LLM: una `DEEPSEEK_API_KEY` (o `agent/dsh/.env`, gitignored).

## Instalación

```bash
cd agent && npm ci          # tests + bin (sin dependencias)
cd dsh && npm ci            # harness: dsh 0.2.1-rc.2 y sus ~600 paquetes
```

## El agente real (dsh)

`dsh/` es un **DSH_HOME** propio: el perfil `sifi` se compone con
`@deepseek-ai/dsh-base` + `@deepseek-ai/dsh-headless` + nuestro bundle `sifi-tools`.

```bash
cd agent/dsh
export DEEPSEEK_API_KEY=...          # o ponelo en agent/dsh/.env
export SIFID_URL=http://127.0.0.1:8765
export SIFID_TOKEN=...               # opcional

npm run config                       # dsh --profile sifi --dump-config
npm run headless -- "Llamá a sifi_panels y resumí los paneles disponibles"
npm run smoke                        # tarea trivial: valida credenciales
```

`npm run headless` es `DSH_HOME=$PWD dsh --profile sifi headless ...`. Otros modos de dsh
(`web`, `tui`) no están configurados para este perfil.

## Banco de pruebas (sin LLM)

```bash
cd agent
node bin/sifi-agent.mjs --health                       # ¿está sifid?
node bin/sifi-agent.mjs --list-tools                   # esquemas de las 7 tools
node bin/sifi-agent.mjs --prompt                       # system prompt
node bin/sifi-agent.mjs --tool sifi_panels             # llamar una tool
node bin/sifi-agent.mjs --tool sifi_design \
  --args '{"query_path":"tests/data/query.fa","panel_ids":["maiz"]}'
node bin/sifi-agent.mjs --tool sifi_score --args '{"run_id":"run_1"}' --json
```

Variables: `SIFID_URL` (default `http://127.0.0.1:8765`) y `SIFID_TOKEN` (header
`x-sifi-token`).

## Tests

```bash
npm test        # 14 tests, sifid falso con node:http
```

Cubren contrato, ordenamiento por score, filtros, off-target sobre un run existente,
validación de argumentos, error accionable con el servicio caído, y el **puente a dsh**:
mapeo al author-schema (`integer`, sin `min`/`max`), `output.schema = {type:'json'}`,
`execute` delegando en la tool y `register`/disposer.

## Las 7 tools

| Tool | args principales | devuelve |
|---|---|---|
| `sifi_design` | `query_path`, `panel_ids[]`, `sirna_size`, `mismatches`, `wait`, `top_n` | `{run_id, status, n_sirnas, top[]}` |
| `sifi_offtarget` | `run_id`, `panel_ids[]`, `wait` | `{run_id, origin_run_id, hits_by_panel[]}` |
| `sifi_status` | `run_id?`, `limit` | run normalizado, o `{runs[], total}` |
| `sifi_score` | `run_id`, `top_n`, `min_score` | `{run_id, n_candidates, top[]}` con desglose E/R/T/S/D |
| `sifi_report` | `run_id`, `format`, `template` | `{run_id, report_path}` |
| `sifi_panels` | — | `{panels[]}` |
| `sifi_news` | `since`, `limit` | `{novedades[]}` |

Contrato con `sifid`: `POST /runs`, `GET /runs`, `GET /runs/{id}`, `POST /runs/{id}/cancel`,
`GET /runs/{id}/results`, `GET /panels`, `GET /health` — más `POST /reports` (ROADMAP §5.3)
y `GET /news` (M7). Si estos dos no existen, la tool lo dice y no inventa nada.

## Cómo se engancha al harness

El bundle `dsh/bundles/sifi-tools` es un plugin de dsh normal:

- `defineTool(...)` de `@deepseek-ai/dsh-tools` para cada una de las 7 tools, registradas con
  `ctx.tools.register()` (el registro que usa el loop del agente).
- `ctx.systemPrompt.section()` publica `prompts/system.md` como persona del producto.
- `dsh.bundle.patch` inserta la fila del plugin en el árbol; el perfil la re-configura por id.

El detalle de la API, las trampas y las verificaciones (con salidas crudas) está en
[`NOTAS.md`](NOTAS.md). Si se sube la versión de dsh, `engines.dsh` hace que el bundle se
**saltee con warning** en vez de fallar en silencio: hay que revalidar y actualizar el pin.

## Producción

El binario final lo arma el frente de empaquetado (M8): `sifid` como sidecar + `agent/dsh`
(perfil incluido) y `prompts/system.md` empaquetados. El puerto del servicio se inyecta por
`SIFID_URL` (el servicio usa puerto efímero y token de sesión).
