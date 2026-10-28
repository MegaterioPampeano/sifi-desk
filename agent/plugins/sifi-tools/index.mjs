/**
 * Plugin de Cordis `sifi-tools`: publica las 7 tools del producto contra `sifid`.
 *
 * Uso:
 *   await ctx.plugin(sifiTools, { baseUrl: 'http://127.0.0.1:8765' })
 *
 * No importa el core de Python: sólo HTTP. Si `sifid` no está, las tools
 * devuelven un error accionable con el comando para arrancarlo.
 */

import { SifidClient, DEFAULT_BASE_URL } from '../../src/client.mjs'
import { registerTools } from '../../adapter/index.mjs'

export const name = 'sifi-tools'
// El servicio `tools` de dsh es opcional: en modo standalone no existe.
export const inject = []

const DEFAULTS = { baseUrl: DEFAULT_BASE_URL, token: null, timeoutMs: 30_000 }

/**
 * Config en formato Standard Schema v1 (lo que pide cordis para validar).
 * No usamos zod a propósito: una dependencia menos en el producto.
 */
export const Config = {
  '~standard': {
    version: 1,
    vendor: 'sifi-agent',
    validate(value = {}) {
      if (value === null || typeof value !== 'object') {
        return { issues: [{ message: 'la config debe ser un objeto', path: [] }] }
      }
      const merged = { ...DEFAULTS, ...value }
      const issues = []
      if (typeof merged.baseUrl !== 'string' || !/^https?:\/\//.test(merged.baseUrl)) {
        issues.push({ message: 'baseUrl debe ser una URL http(s)', path: ['baseUrl'] })
      }
      if (typeof merged.timeoutMs !== 'number' || merged.timeoutMs <= 0) {
        issues.push({ message: 'timeoutMs debe ser un número positivo', path: ['timeoutMs'] })
      }
      return issues.length ? { issues } : { value: merged }
    },
  },
}

export async function apply(ctx, config = {}) {
  const client = new SifidClient({
    baseUrl: config.baseUrl ?? process.env.SIFID_URL ?? DEFAULT_BASE_URL,
    token: config.token ?? process.env.SIFID_TOKEN ?? null,
    timeoutMs: config.timeoutMs ?? 30_000,
  })

  // Se expone para que otros plugins/tools del agente puedan reusar el cliente.
  ctx.effect(() => ctx.reflect.provide('sifiClient', client))

  // Registro de tools: en dsh (`ctx.tools`) si está, si no servicio `sifiTools`.
  const info = await registerTools(ctx, client)
  ctx.logger?.info?.(
    'sifi-tools: %s tools (%s)%s',
    info.count,
    info.mode,
    info.reason ? ` — ${info.reason}` : '',
  )

  // Ojo: NO devolver objetos desde apply() — cordis los interpreta como
  // disposable/servicio y falla con "Invalid effect". El resultado se loguea y ya.
  ctx.logger?.debug?.('sifi-tools: baseUrl=%s', client.baseUrl)
}
