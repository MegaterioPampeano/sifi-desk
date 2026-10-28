# NOTAS — hallazgos al implementar M4 (agente)

Fecha: 2026-10-28 · Frente `agente` (`w/agente`)

## 1. `deepseek-harness` (dsh) no es instalable todavía ⚠️

`npm view deepseek-harness`:

```
deepseek-harness@0.0.1 | MIT | deps: none | versions: 1
Reserved package name for the DeepSeek Harness TUI project (dsh-tui).
The real package will be published here when development completes.
```

Contenido real del tarball: **sólo `package.json` (4 campos) y `README.md`**. Sin `main`, sin
`exports`, sin `files`, 581 B desempaquetado, cero dependencias. `require`/`import` del paquete
falla con `ERR_MODULE_NOT_FOUND: .../node_modules/deepseek-harness/index.js`.

Conclusión: **no existe API de dsh que podamos llamar hoy**. El roadmap (§5.4) asumía
`ctx.tools.register(defineTool({...}))`; eso queda como *expectativa documentada*, no como algo
verificado. No inventamos el resto de la API (jobs, permisos, trajectory tracing): no hay código
que inspeccionar.

### Qué hicimos al respecto

1. `package.json` igual incluye `deepseek-harness` **pinneado a `0.0.1`** (lo pide el entregable y
   deja el lockfile listo para el día que publiquen). Se instala sin romper nada porque no tiene
   código ni deps.
2. `adapter/index.mjs` es la **capa de adaptación** explícita:
   - `probeDsh()` intenta `import('deepseek-harness')` y busca `defineTool`. Hoy devuelve
     `{available:false, reason:'Cannot find package ...'}`.
   - `registerTools(ctx, client)`:
     * si `probeDsh().available` **y** el contexto tiene `ctx.tools.register` → registra las 7
       tools con `toDshTool()` (mapea `parameters`, `output.schema`, `render`, y pasa
       `exec.signal` al `fetch`);
     * si no → publica el servicio cordis `ctx.sifiTools` con `list()/get()/call()`.
   - Cuando dsh publique su versión real: se sube el pin, se corre `npm ci`, y si la API difiere
     se ajusta **sólo** `toDshTool()`/`hasDshToolsService()`.
3. El binario de dev (`bin/sifi-agent.mjs`) y los tests corren en modo **standalone**; no
   dependen de dsh.

## 2. Cordis sí es real (y tiene trampas)

`cordis@4.0.0-rc.12` (Shigma, el framework de Koishi) está publicado y funciona. Lo verificado
en este host:

- API ESM, `new Context()`, `ctx.plugin(plugin, config)`, `await`.
- Un plugin puede ser un **módulo ESM** con `export const name`, `export const inject`,
  `export const Config`, `export async function apply(ctx, config)`.
- Servicios: `ctx.reflect.provide(name, value)` devuelve un *thenable disposable*;
  `await` sobre él da la función de cleanup. Se registra cleanup con `ctx.effect(() => dispose)`.
- **Trampa 1:** `Config` debe ser un **Standard Schema v1** (`Config['~standard'].validate`), no
  un objeto plano. Si le pasás un objeto, explota con
  `Cannot read properties of undefined (reading 'validate')`. Implementamos el schema a mano para
  no sumar `zod`.
- **Trampa 2:** `apply()` **no debe devolver un objeto**. Cordis lo interpreta como
  disposable/servicio y falla en el teardown con `TypeError: Invalid effect`. Devolver
  `undefined` (o nada).
- **Trampa 3:** `ctx.effect()` vale después de `await` dentro de `apply` (el fiber sigue activo),
  pero el valor que devuelve el callback tiene que ser función/`null`/thenable-disposable.

Versión pinneada: `cordis: 4.0.0-rc.12` (es un `rc`; el pin exacto evita sorpresas). Queda
anotado que al pasar a 4.x estable hay que revalidar los tres puntos de arriba.

## 3. Supuestos de contrato con `sifid`

El contrato entregado en la consigna no incluye dos endpoints que las tools necesitan:

| Tool | Endpoint usado | Origen |
|---|---|---|
| `sifi_report` | `POST /reports` `{run_id, template, format}` | ROADMAP §5.3 (no estaba en la lista de la consigna) |
| `sifi_news` | `GET /news?since=` | M7 / vigilante (§5.4.3), endpoint no definido aún |

Decisión: se programó contra esas rutas y, si el servicio responde **404**, la tool devuelve un
error explícito (`not_implemented`) que dice qué falta y qué hacer mientras tanto — nunca un
resultado inventado. Cuando el frente `servicio`/`reportes`/`novedades` fije las rutas reales,
alcanza con tocar `src/client.mjs` (una línea por endpoint).

Otros supuestos sobre la forma de las respuestas (todos tolerantes):

- `GET /runs` puede ser `[...]` o `{runs:[...]}`.
- `GET /runs/{id}/results` es el manifest `sifi.results/1`; los candidatos pueden venir en
  `candidates` / `top` / `sirnas`, y el score en `score` (o `efficiency`/`eff` como fallback).
  Los off-targets en `hits_by_panel` / `offtargets` / `panels`.
- `POST /runs` acepta `{query_path, panel_ids[], mode, mismatches, main_target}` y devuelve el run
  creado (`run_id` o `id`) con `status`.
- `sifi_offtarget {run_id, panel_ids}` (forma del roadmap §5.4.1): como el contrato de `POST /runs`
  exige `query_path`, la tool **lee primero** `GET /runs/{id}` y reusa `query_path` +
  `main_target` del run original, con `mode:"offtarget"`. Si el run no expone `query_path`, da
  error claro en vez de adivinar.
- Estados terminales: `done|error|cancelled|interrupted`. `sifi_design` con `wait:true` hace
  polling de `GET /runs/{id}` (default 120 s, configurable) y si termina en `error` **no** devuelve
  resultados: relanza el error del servicio.
- Token de sesión: se manda `x-sifi-token` si `SIFID_TOKEN` está seteado (el nombre del header es
  supuesto; el servicio de M3 debe confirmarlo).

## 4. Lo que falta (para el supervisor)

- [ ] Verificar contra el `sifid` real cuando M3 mergee: `npm test` usa un doble, no el servicio.
      Un smoke real sería: `python3 -m service.app --port 8765` + `node bin/sifi-agent.mjs --health`
      + `--tool sifi_panels`.
- [ ] Confirmar rutas de `/reports` y `/news` con M6/M7.
- [ ] Cuando dsh publique código: subir el pin y probar `toDshTool()` de verdad.
- [ ] `prompts/system.md` todavía no lo consume ningún harness (no hay harness): el bin lo imprime
      con `--prompt`. Cuando exista dsh, se referencia desde `cordis.yml`.
- [ ] Permisos (§5.4.4) están **declarados** en `cordis.yml` (`allow`/`ask`/`deny`), pero no hay
      motor que los aplique: eso lo tiene que hacer el harness o la ventana (M5).
- [ ] Skills (§5.4.2, `dsh-sifi-skills`) fuera del alcance de este entregable: quedan para
      cuando exista el provider de skills del harness.
- [ ] Trabajo largo: el roadmap pide `run_in_background` + `ctx.jobs.start`. No se implementó
      porque es API de dsh inexistente; hoy se resuelve con `wait:false` + `sifi_status`
      (el agente no bloquea el turno).
