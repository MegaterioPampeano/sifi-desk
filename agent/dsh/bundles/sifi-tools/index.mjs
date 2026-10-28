/**
 * sifi-tools — plugin + bundle de dsh para el agente Si-Fi.
 *
 * Se monta como cualquier otro plugin de dsh (fila `sifi-tools` del perfil) y:
 *   1. registra las 7 tools del producto en el registro real (`ctx.tools.register`,
 *      servicio `@deepseek-ai/dsh-tools`) usando `defineTool`;
 *   2. agrega la persona del producto al system prompt (`ctx.systemPrompt.section`)
 *      leyendo `agent/prompts/system.md` — una sola fuente de verdad.
 *
 * No hay adaptador especulativo: si dsh cambia la API, esto deja de montar y se
 * ve en `dsh --profile sifi --dump-config` / el arranque, no en silencio.
 */

import { readFileSync } from 'node:fs'
import z from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { SifidClient } from '../../../src/client.mjs'
import { TOOLS } from '../../../src/tools.mjs'
import { registerDshTools } from '../../../src/dsh-tools.mjs'

export const name = 'sifi-tools'
export const inject = ['tools', 'systemPrompt']

export const Config = z.object({
  baseUrl: z.string().default('http://127.0.0.1:8765').description('URL base de sifid'),
  token: z.string().default('').description('token de sesión (header x-sifi-token)'),
  timeoutMs: z.number().default(30000).description('timeout HTTP por request'),
})

const PROMPT_URL = new URL('../../../prompts/system.md', import.meta.url)

export function apply(ctx, config) {
  const client = new SifidClient({
    baseUrl: config.baseUrl,
    token: config.token || undefined,
    timeoutMs: config.timeoutMs,
  })

  const disposers = registerDshTools(ctx, TOOLS, { defineTool, client })
  ctx.effect(() => () => {
    for (const dispose of disposers.reverse()) dispose()
  })

  const persona = readFileSync(PROMPT_URL, 'utf8')
  // `interpolate: false`: el prompt es literal (no usa variables de dsh).
  ctx.systemPrompt.section({ name: 'sifi-persona', order: 100, text: persona, interpolate: false })
}
