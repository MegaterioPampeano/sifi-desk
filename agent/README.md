# `agent/` — el agente del producto Si-Fi

Implementa el **M4** del roadmap: las siete herramientas con las que el agente opera el
producto, más su persona y su capa de adaptación al harness.

```
agent/
├── package.json              # cordis + deepseek-harness, versión exacta
├── cordis.yml                # config del producto (plugin + permisos)
├── prompts/system.md         # persona y reglas duras del agente
├── src/client.mjs            # cliente HTTP de sifid (errores accionables)
├── src/tools.mjs             # las 7 tools: esquema + validación + execute + render
├── adapter/index.mjs         # capa de adaptación dsh ↔ standalone
├── plugins/sifi-tools/       # plugin de Cordis (publica las tools)
├── bin/sifi-agent.mjs        # entry de desarrollo (sin harness)
└── test/tools.test.mjs       # 12 tests contra un sifid falso (node:http)
```

**Regla de oro:** este paquete **no importa el core de Python**. Todo va por HTTP a `sifid`.
Si el servicio no está, la tool devuelve el comando exacto para arrancarlo.

## Requisitos

- Node **22+** (usa `fetch`, `AbortSignal.any`, `node:test`).
- `sifid` corriendo (frente M3): `python3 -m service.app --port 8765`.

## Instalación

```bash
cd agent
npm ci            # reproducible, usa package-lock.json
```

## Levantarlo (dev)

```bash
# 1) el servicio (en otra terminal, desde la raíz del repo)
python3 -m service.app --port 8765

# 2) el agente
cd agent
export SIFID_URL=http://127.0.0.1:8765      # default si no se exporta
node bin/sifi-agent.mjs                     # imprime el estado y las tools
```

Comandos útiles:

```bash
node bin/sifi-agent.mjs --health                       # ¿está sifid?
node bin/sifi-agent.mjs --list-tools                   # esquemas de las 7 tools
node bin/sifi-agent.mjs --prompt                       # system prompt (para el harness)
node bin/sifi-agent.mjs --tool sifi_panels             # llamar una tool
node bin/sifi-agent.mjs --tool sifi_design \
  --args '{"query_path":"tests/data/query.fa","panel_ids":["maiz"]}'
node bin/sifi-agent.mjs --tool sifi_score --args '{"run_id":"run_1"}' --json
```

Variables:

| Variable | Default | Para qué |
|---|---|---|
| `SIFID_URL` | `http://127.0.0.1:8765` | base URL del servicio |
| `SIFID_TOKEN` | — | token de sesión (se manda como `x-sifi-token`) |

## Tests

```bash
npm test
```

Levanta un `sifid` falso con `node:http` (endpoints del contrato) y verifica las 7 tools sin
depender del servicio real ni de Python. 12 tests: contrato, ordenamiento por score, filtros,
off-target sobre un run existente, validación de argumentos, error accionable con el servicio
caído, y registro real del plugin en un `Context` de Cordis.

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

## Cómo se engancha al harness (dsh)

`deepseek-harness@0.0.1`, el paquete npm actual, es un **placeholder sin código**: no hay API
que llamar todavía (detalle en [`NOTAS.md`](NOTAS.md)). Por eso:

- `adapter/index.mjs` define el contrato neutral (`{name, description, parameters, execute, render}`).
- Si el contexto de Cordis tiene un servicio `tools` con `register()` (lo que el roadmap espera
  de dsh) y el paquete exporta `defineTool`, las tools se registran ahí, mapeando
  `output.schema` + `render()` y propagando `exec.signal`.
- Si no, se publica el servicio cordis **`ctx.sifiTools`** con `list()/get()/call()`, que es lo
  que usa `bin/sifi-agent.mjs` y lo que podrá usar la ventana (M5).

Cuando dsh publique su API real, el único archivo a tocar es `adapter/index.mjs`.

## Producción

El binario final lo arma el frente de empaquetado (M8): `sifid` como sidecar + este agente en
modo standalone, con `cordis.yml` y `prompts/system.md` empaquetados. El puerto del servicio se
inyecta por `SIFID_URL` (el servicio usa puerto efímero y token de sesión).
