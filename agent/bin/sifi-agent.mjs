#!/usr/bin/env node
/**
 * Entry de desarrollo del agente Si-Fi.
 *
 * - `node bin/sifi-agent.mjs --list-tools`        lista las tools disponibles
 * - `node bin/sifi-agent.mjs --health`            chequea sifid
 * - `node bin/sifi-agent.mjs --tool sifi_panels`  llama una tool (args: --args '<json>')
 * - `node bin/sifi-agent.mjs --prompt`            imprime el system prompt (para pegar en el harness)
 *
 * Sin harness (dsh) instalado, corre en modo standalone: el plugin publica
 * `ctx.sifiTools` y este bin lo usa. No inventa una API de dsh que no existe.
 */

import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { Context } from 'cordis'
import * as sifiTools from '../plugins/sifi-tools/index.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')

function parseArgs(argv) {
  const out = { _: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--list-tools' || a === '--health' || a === '--prompt' || a === '--json') out[a.slice(2)] = true
    else if (a === '--tool') out.tool = argv[++i]
    else if (a === '--args') out.args = argv[++i]
    else if (a === '--url') out.url = argv[++i]
    else out._.push(a)
  }
  return out
}

const args = parseArgs(process.argv.slice(2))
const ctx = new Context()

await ctx.plugin(sifiTools, {
  baseUrl: args.url ?? process.env.SIFID_URL ?? 'http://127.0.0.1:8765',
})

const registry = ctx.sifiTools
if (!registry) {
  console.error('sifi-tools no se registró. Revisá el log de cordis.')
  process.exit(1)
}

if (args['list-tools']) {
  for (const t of registry.list()) {
    console.log(`${t.name}  —  ${t.description}`)
    for (const [k, spec] of Object.entries(t.parameters)) {
      console.log(`    ${k}: ${spec.type}${spec.required ? ' (requerido)' : ''} — ${spec.description}`)
    }
  }
  process.exit(0)
}

if (args.prompt) {
  console.log(await readFile(join(root, 'prompts/system.md'), 'utf8'))
  process.exit(0)
}

if (args.health) {
  try {
    const h = await ctx.sifiClient.health()
    console.log('sifid OK:', JSON.stringify(h))
    process.exit(0)
  } catch (err) {
    console.error(err.message)
    process.exit(1)
  }
}

if (args.tool) {
  let toolArgs = {}
  if (args.args) {
    try {
      toolArgs = JSON.parse(args.args)
    } catch (err) {
      console.error(`--args no es JSON válido: ${err.message}`)
      process.exit(2)
    }
  }
  try {
    const result = await registry.call(args.tool, toolArgs)
    const tool = registry.get(args.tool)
    console.log(args.json ? JSON.stringify(result, null, 2) : tool.render(result))
  } catch (err) {
    console.error(`${err.name ?? 'Error'}: ${err.message}`)
    process.exit(1)
  }
  process.exit(0)
}

console.log('sifi-agent (dev, standalone)')
console.log(`sifid: ${ctx.sifiClient.baseUrl}`)
console.log(`tools: ${registry.list().map((t) => t.name).join(', ')}`)
console.log('')
console.log('Ejemplos:')
console.log('  node bin/sifi-agent.mjs --health')
console.log('  node bin/sifi-agent.mjs --tool sifi_panels')
console.log('  node bin/sifi-agent.mjs --tool sifi_design --args \'{"query_path":"tests/data/query.fa","panel_ids":["maiz"]}\'')
process.exit(0)
