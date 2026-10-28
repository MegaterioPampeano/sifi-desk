/**
 * Capa de adaptación: el harness (dsh) puede cambiar su API y no queremos
 * reescribir el producto. Las tools se definen en formato neutral
 * (`src/tools.mjs`) y acá se publican en lo que haya disponible.
 *
 * Estado real (ver ../NOTAS.md): el paquete npm `deepseek-harness@0.0.1` es un
 * PLACEHOLDER ("Reserved package name ... The real package will be published
 * here when development completes"): no trae código ni API. Por eso:
 *
 *  - `mode: 'dsh'`        → hay un servicio `ctx.tools` con `register()` (API esperada
 *                           de dsh: `ctx.tools.register(defineTool({...}))`).
 *  - `mode: 'standalone'` → no hay harness: se publica `ctx.sifiTools` (cordis service)
 *                           con `list()/get()/call()`, usable por el bin de dev,
 *                           la UI o cualquier otro host.
 *
 * Nada acá inventa endpoints ni APIs del harness: si no está, se degrada y se dice.
 */

import { Context } from 'cordis'
import { TOOLS, callTool, ToolInputError } from '../src/tools.mjs'

export const DSH_PACKAGE = 'deepseek-harness'

let dshProbe = null

/** Prueba (una sola vez) si el harness real está instalado y exporta `defineTool`. */
export async function probeDsh() {
  if (dshProbe) return dshProbe
  try {
    const mod = await import(DSH_PACKAGE)
    const defineTool = mod.defineTool ?? mod.default?.defineTool
    dshProbe = defineTool
      ? { available: true, defineTool, version: mod.version ?? null }
      : { available: false, reason: 'el paquete instalado no exporta defineTool', exports: Object.keys(mod) }
  } catch (err) {
    dshProbe = { available: false, reason: err?.message ?? String(err) }
  }
  return dshProbe
}

/** ¿Este contexto cordis ya tiene el servicio de tools que registra dsh? */
export function hasDshToolsService(ctx) {
  return Boolean(ctx && ctx.tools && typeof ctx.tools.register === 'function')
}

/**
 * Traduce una tool neutral al formato `defineTool` de dsh.
 * Se usa SÓLO si el harness real está presente; si su API cambia, se toca acá.
 */
export function toDshTool(tool, defineTool, ctx) {
  return defineTool({
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters,
    output: {
      schema: { type: 'object' },
      render: (_args, value) => [{ type: 'text', text: tool.render(value) }],
    },
    async execute(args, exec = {}) {
      return callTool(tool.name, args, { client: ctx.sifiClient, signal: exec.signal, log: ctx.logger })
    },
  })
}

/**
 * Registra las tools en el contexto.
 * @returns {{mode:'dsh'|'standalone', count:number, reason?:string}}
 */
export async function registerTools(ctx, client) {
  const probe = await probeDsh()

  if (probe.available && hasDshToolsService(ctx)) {
    for (const tool of TOOLS) ctx.tools.register(toDshTool(tool, probe.defineTool, ctx))
    return { mode: 'dsh', count: TOOLS.length }
  }

  const registry = {
    mode: 'standalone',
    list: () => TOOLS.map((t) => ({ name: t.name, description: t.description, parameters: t.parameters })),
    get: (name) => TOOLS.find((t) => t.name === name) ?? null,
    async call(name, args, exec = {}) {
      return callTool(name, args, { client, signal: exec.signal, log: exec.log })
    },
  }
  const dispose = ctx.reflect.provide('sifiTools', registry)
  ctx.effect(() => dispose)

  const reason = !probe.available
    ? `dsh no disponible: ${probe.reason}`
    : 'el contexto no expone el servicio `tools` de dsh'
  return { mode: 'standalone', count: TOOLS.length, reason }
}

export { TOOLS, callTool, ToolInputError, Context }
