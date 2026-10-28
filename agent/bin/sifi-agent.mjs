#!/usr/bin/env node
/**
 * Entry de desarrollo del agente Si-Fi, SIN harness.
 *
 * Es un banco de pruebas de las tools, no un agente: no hay LLM ni loop. Para
 * el agente real se usa el perfil de dsh (`agent/dsh`, ver README).
 *
 * - `node bin/sifi-agent.mjs --list-tools`        lista las tools disponibles
 * - `node bin/sifi-agent.mjs --health`            chequea sifid
 * - `node bin/sifi-agent.mjs --tool sifi_panels`  llama una tool (args: --args '<json>')
 * - `node bin/sifi-agent.mjs --prompt`            imprime el system prompt
 */

import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { SifidClient } from '../src/client.mjs'
import { TOOLS, callTool } from '../src/tools.mjs'

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
const baseUrl = args.url ?? process.env.SIFID_URL ?? 'http://127.0.0.1:8765'
const client = new SifidClient({ baseUrl, token: process.env.SIFID_TOKEN })

const registry = {
  list: () => TOOLS,
  get: (name) => TOOLS.find((t) => t.name === name),
  call: (name, toolArgs) => callTool(name, toolArgs, { client }),
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
    console.log('sifid OK:', JSON.stringify(await client.health()))
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
    console.log(args.json ? JSON.stringify(result, null, 2) : registry.get(args.tool).render(result))
  } catch (err) {
    console.error(`${err.name ?? 'Error'}: ${err.message}`)
    process.exit(1)
  }
  process.exit(0)
}

console.log('sifi-agent (dev, sin harness)')
console.log(`sifid: ${client.baseUrl}`)
console.log(`tools: ${registry.list().map((t) => t.name).join(', ')}`)
console.log('')
console.log('Para el agente real con LLM: cd dsh && npm run headless -- "<tarea>"')
console.log('')
console.log('Ejemplos:')
console.log('  node bin/sifi-agent.mjs --health')
console.log('  node bin/sifi-agent.mjs --tool sifi_panels')
console.log('  node bin/sifi-agent.mjs --tool sifi_design --args \'{"query_path":"tests/data/query.fa","panel_ids":["maiz"]}\'')
process.exit(0)
