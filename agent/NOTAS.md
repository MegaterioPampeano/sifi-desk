# NOTAS — M4b: agente sobre dsh REAL

Fecha: 2026-10-28 (corrección de M4) · Frente `agente` (`w/agente`)

## 0. Corrección del error de M4 (2026-10-28, M4b)

M4 concluyó —mal— que "dsh no está publicado" y armó un adaptador especulativo. Dos errores:

1. **Paquete equivocado.** Se inspeccionó `deepseek-harness@0.0.1` de npm. Ese nombre está
   **reservado por un tercero** (mantenedor `ccchimneyyy`, descripción: *"Reserved package name
   for the DeepSeek Harness TUI project (dsh-tui)"*): 581 B, sin código, sin deps. De ahí salió
   la conclusión falsa "no hay API que llamar".
2. **Conclusión falsa.** dsh **sí** está publicado, con scope propio **`@deepseek-ai/*`**: ~20+
   paquetes y un árbol de plugins (`dsh-base`, `dsh-headless`, `dsh-tools`, `dsh-session`,
   `dsh-agent-loop`, `dsh-skill`, `dsh-jobs`, `dsh-subprocess`, `dsh-api-gateway`,
   `dsh-tool-bash`, `dsh-tool-fs`, `dsh-tool-web`, …). El CLI es **`@deepseek-ai/dsh`**
   (última publicada al momento de esta corrección: **`0.2.1-rc.2`**), ya instalado en este host
   (`~/.dsh/profiles/{headless,acp}`).

Qué se tiró: `adapter/index.mjs` (sondeo de paquetes inexistentes + mapeo adivinado), el pin de
`deepseek-harness@0.0.1`, el `cordis.yml` propio y el plugin "dual mode" con fallback
`ctx.sifiTools`.

Qué se conservó: `src/tools.mjs` (las 7 tools, formato neutral), `src/client.mjs`,
`prompts/system.md`, los tests con sifid falso.

Qué se agregó: un **perfil de dsh propio** en `dsh/` con un bundle `sifi-tools` que usa la API
real (`defineTool` de `@deepseek-ai/dsh-tools` + `ctx.tools.register`) y la persona del producto
como sección del system prompt (`ctx.systemPrompt.section`), leyendo `prompts/system.md`.

## 1. Cómo funciona dsh (verificado en este host)

- `dsh --profile <nombre>` arranca un **perfil**: una lista ordenada de **bundles** declarada en
  `$DSH_HOME/profiles/<nombre>/package.json` → `dsh.profile.bundles`. `DSH_HOME` por defecto es
  `~/.dsh` y se puede pisar por entorno (esto usa el repo: `DSH_HOME=agent/dsh`).
- Un **bundle** es un paquete npm que declara `dsh.bundle.patch: "./cordis.patch.yml"`. Su patch
  es una **capa YAML** que inserta/configura filas de plugins. No hay fusión de configs: cada
  capa reemplaza la config completa de la fila que toca (`- id: <fila>`), y `insert:` agrega filas.
- Los **plugins** son paquetes Cordis (`export const name`, `inject`, `Config`, `apply(ctx, cfg)`).
  Los servicios relevantes acá: `ctx.tools` (`@deepseek-ai/dsh-tools`) y
  `ctx.systemPrompt` (`@deepseek-ai/dsh-system-prompt`).
- Modos: `dsh headless "<tarea>"` (una tarea, imprime el resultado; `--json` emite eventos),
  `dsh web`, `dsh tui`. `--dump-config` imprime el árbol compuesto sin montar.
- Cordis acá es el fork **`@deepseek-ai/cordis`** (no el `cordis` de npm); un plugin de dsh no
  debe importar `cordis` de npm porque sería otra clase de `Context`.

### API real de tools (leída en `node_modules/@deepseek-ai/dsh-tools`)

```js
defineTool({
  name, description,
  parameters: { clave: { type, description, required, default, enum, items } }, // author-schema
  output: { schema: { type: 'json' }, render(args, value) => [{ type: 'text', text }] },
  async execute(args, exec) { /* exec.signal */ return valorJSON },
})
ctx.tools.register(def) // => disposer exacto
```

Trampas verificadas (a golpes, no leyendo):

- `output.schema` es **author-schema**, no JSON Schema crudo: `{}` falla con
  `JsonSchemaError: schema.type must be …`; se usa `{ type: 'json' }`.
- El author-schema **no acepta** `min`/`max`/`minItems`: `defineTool` rechaza el nodo. El puente
  (`src/dsh-tools.mjs`) los descarta y `callTool()` sigue validando rangos antes de ejecutar.
- `integer: true` del spec neutral se traduce a `type: 'integer'`.
- `ctx.tools.restrict()` **no** se puede llamar desde `apply` global: exige un contexto de agente
  (`agent.ctx`) y tira `tools.restrict() requires a scoped context` (verificado en el código).
  Restringir la superficie de tools es una decisión de agente/ventana, no del bundle.
- `ctx.systemPrompt.section({ name, order, text, interpolate })`: `order` ascendente, `text`
  puede ser string o función; `interpolate:false` deja el `{{...}}` literal.

## 2. Estructura entregada

```
agent/
├── package.json          # sin deps de harness; tests + bin de desarrollo
├── src/tools.mjs         # 7 tools neutrales (conservado)
├── src/client.mjs        # cliente HTTP de sifid (conservado)
├── src/dsh-tools.mjs     # puente real: author-schema + defineTool + register (nuevo)
├── prompts/system.md     # persona (conservado; ahora la lee el plugin)
├── bin/sifi-agent.mjs    # banco de pruebas sin LLM (sin cordis)
├── test/tools.test.mjs   # 14 tests con sifid falso
├── test/fake-sifid.mjs   # sifid falso mínimo para smoke manual
└── dsh/                  # DSH_HOME del producto
    ├── package.json      # pins exactos @deepseek-ai/* + sifi-tools (file:)
    ├── package-lock.json
    ├── .gitignore        # node_modules/, .env
    ├── profiles/sifi/
    │   ├── package.json  # bundles: dsh-base, dsh-headless, sifi-tools
    │   ├── cordis.yml    # [] (raíz vacía; todo se compone por capas)
    │   └── cordis.patch.yml  # personaPrefix '' + config de sifi-tools
    └── bundles/sifi-tools/
        ├── package.json  # dsh.bundle.patch + engines.dsh exacto
        ├── cordis.patch.yml  # inserta la fila sifi-tools (env: SIFID_URL/SIFID_TOKEN)
        └── index.mjs     # plugin: registra 7 tools + sección de prompt
```

Versiones pinneadas exactas: `@deepseek-ai/dsh@0.2.1-rc.2`,
`@deepseek-ai/dsh-tools@0.2.1-rc.2`, `@deepseek-ai/schemastery@3.18.5`.
El bundle declara `engines.dsh: "0.2.1-rc.2"`: si se sube el harness sin tocar esto, dsh lo
**saltea con warning** (`entry did not activate`), no falla en silencio.

## 3. Verificación real (salidas crudas)

(a) **Monta sin errores**:

```
$ cd agent/dsh && npm run config        # DSH_HOME=$PWD dsh --profile sifi --dump-config
# == sifi-tools
- id: sifi-tools
  name: sifi-tools
  config:
    baseUrl: !!js process.env.SIFID_URL ?? 'http://127.0.0.1:8765'
    token: !!js process.env.SIFID_TOKEN ?? ''
    timeoutMs: 30000
# == @deepseek-ai/dsh-base, patched by …, agent/dsh/profiles/sifi/cordis.patch.yml
- id: system-prompt
  name: '@deepseek-ai/dsh-system-prompt'
  config:
    personaPrefix: ''
```

(b) **Arranca headless y expone las tools**. Sin clave falla sólo por credencial (y el plugin ya
montó — no aparece `entry did not activate`):

```
$ env -u DEEPSEEK_API_KEY DSH_HOME=$PWD dsh --profile sifi headless "Decime solamente OK"
dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"; …
EXIT=1
```

Con `DEEPSEEK_API_KEY` en el entorno, contra el `sifid-mock` que estaba corriendo en `:8765`,
el loop llamó **nuestra** tool, ejecutó el cliente HTTP y el resultado volvió al modelo:

```
$ DSH_HOME=$PWD SIFID_URL=http://127.0.0.1:8765 dsh --profile sifi headless --json \
    "Llamá a sifi_panels y decime los ids de panel separados por coma."
{"type":"tool_call","tool":"sifi_panels","input":{}}
{"type":"tool_result","status":"completed","result":"- dalbulus_maidis n=14211\n- maiz n=39432\n- sulcia n=241\n- humano n=194893\n- universal n=5000"}
{"type":"final","text":"…`dalbulus_maidis, maiz, sulcia, humano, universal`…"}
EXIT=0
```

(c) **Tests**: `cd agent && npm test` → `# tests 14 / # pass 14 / # fail 0`.

## 4. Supuestos de contrato con `sifid` (sin cambios)

Dos endpoints no estaban en la consigna y se programaron contra la ruta del roadmap; si el
servicio responde 404 la tool devuelve `not_implemented` (nunca un resultado inventado):

| Tool | Endpoint usado | Origen |
|---|---|---|
| `sifi_report` | `POST /reports` `{run_id, template, format}` | ROADMAP §5.3 |
| `sifi_news` | `GET /news?since=` | M7 / vigilante (§5.4.3) |

Otros supuestos tolerantes (detalle en `src/client.mjs`): `GET /runs` como `[...]` o `{runs}`;
candidatos en `candidates`/`top`/`sirnas` con score en `score`/`efficiency`/`eff`;
`POST /runs` acepta `{query_path, panel_ids[], mode, mismatches, main_target}`; `sifi_offtarget`
relee el run de origen para reusar `query_path` + `main_target`; estados terminales
`done|error|cancelled|interrupted`; token por header `x-sifi-token` (nombre **supuesto**, lo debe
confirmar M3).

## 5. Lo que NO se pudo probar acá (explícito)

- **`dsh web` y `dsh tui` con este perfil**: el perfil es headless; la UI de dsh no se montó.
  La ventana del producto (M5) es otra cosa y no se tocó.
- **Persistencia de sesión / historial**: el smoke corre una tarea y sale; no se probó reanudar
  sesiones ni `dsh-session-log` con este perfil.
- **Permisos (§5.4.4)**: no se configuró ninguna política. El perfil headless deshabilita la
  autorización interactiva; si el producto necesita allow/ask/deny, va en el perfil del agente
  (`ctx.tools.guard`/`restrict` desde un contexto de agente), no en este bundle.
- **Superficie de tools**: el perfil hereda todas las tools de `dsh-base` (bash, fs, web…)
  además de las 7. No se restringió (ver trampa de `restrict()` arriba). Decisión pendiente.
- **`sifi_report` / `sifi_news` contra el servicio real**: el mock no implementa esos endpoints.
- **Skills (§5.4.2)**: no se tocó; `dsh-skill` existe y se podría envolver, pero no es parte de M4b.

## 6. Para correrlo

```bash
cd agent/dsh
npm ci                       # baja dsh 0.2.1-rc.2 + deps (618 paquetes)
export DEEPSEEK_API_KEY=...   # o creá agent/dsh/.env (gitignored)
export SIFID_URL=http://127.0.0.1:8765
npm run config                # árbol compuesto
npm run headless -- "Llamá a sifi_panels y resumí los paneles"
```

`npm run smoke` corre una tarea trivial (`Respondé solamente OK`) para chequear credenciales.
