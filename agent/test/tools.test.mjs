/**
 * Tests de las 7 tools contra un `sifid` FALSO (node:http).
 * No requiere el servicio real ni el core de Python: `npm test`.
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import { Context } from 'cordis'

import { SifidClient } from '../src/client.mjs'
import { TOOLS, callTool } from '../src/tools.mjs'
import * as sifiTools from '../plugins/sifi-tools/index.mjs'

// ------------------------------------------------------------- sifid falso

const RUN_ID = 'run_abc123'
const PANELS = [
  { panel_id: 'maiz', name: 'Zea mays (B73)', n_seqs: 12, built: true, organism: 'Zea mays' },
  { panel_id: 'simbionte', name: 'Simbionte de Dalbulus maidis', n_seqs: 3, built: false, organism: 'Sulcia muelleri' },
]

const CANDIDATES = [
  { id: 'sirna_07', sequence: 'GCUAGCUAGCUAGCUAGCUAG', position: 120, score: 61.2, efficiency: 88.1, verdict: 'prometedor', flags: [] },
  { id: 'sirna_02', sequence: 'AUGCUAGCUAGCUAGCUAGCU', position: 40, score: 88.4, efficiency: 95.0, verdict: 'prometedor', flags: ['offtarget:maiz'] },
  { id: 'sirna_11', sequence: 'UUUUGCUAGCUAGCUAGCUAG', position: 220, score: 44.0, efficiency: 51.3, verdict: 'descartar', flags: [] },
]

const state = { runs: new Map(), requests: [], cancelled: [] }

function json(res, code, payload) {
  const body = JSON.stringify(payload)
  res.writeHead(code, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) })
  res.end(body)
}

async function readBody(req) {
  const chunks = []
  for await (const c of req) chunks.push(c)
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : null
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x')
  const p = url.pathname
  state.requests.push(`${req.method} ${p}${url.search}`)

  if (req.method === 'GET' && p === '/health') return json(res, 200, { ok: true, version: '0.0.0-test' })

  if (req.method === 'GET' && p === '/panels') return json(res, 200, { panels: PANELS })

  if (req.method === 'POST' && p === '/runs') {
    const body = await readBody(req)
    if (!body?.query_path) return json(res, 422, { detail: 'query_path requerido' })
    const id = `run_${state.runs.size + 1}`
    const run = {
      run_id: id,
      status: 'queued',
      progress: { done: 0, total: 100 },
      mode: body.mode,
      panel_ids: body.panel_ids,
      main_target: body.main_target ?? null,
      mismatches: body.mismatches,
      query_path: body.query_path,
      created_at: '2026-10-28T19:00:00Z',
    }
    state.runs.set(id, run)
    return json(res, 202, run)
  }

  if (req.method === 'GET' && p === '/runs') {
    return json(res, 200, { runs: [...state.runs.values()] })
  }

  const m = p.match(/^\/runs\/([^/]+)(\/cancel|\/results)?$/)
  if (m) {
    const run = state.runs.get(decodeURIComponent(m[1]))
    if (!run) return json(res, 404, { detail: 'run no existe' })
    if (req.method === 'GET' && !m[2]) {
      // la segunda consulta lo termina (imita al worker)
      if (run.status === 'queued') {
        run.status = 'running'
        run.progress = { done: 40, total: 100 }
      } else if (run.status === 'running') {
        run.status = 'done'
        run.progress = { done: 100, total: 100 }
        run.finished_at = '2026-10-28T19:01:00Z'
      }
      return json(res, 200, run)
    }
    if (m[2] === '/cancel' && req.method === 'POST') {
      run.status = 'cancelled'
      state.cancelled.push(run.run_id)
      return json(res, 200, { run_id: run.run_id, status: 'cancelled' })
    }
    if (m[2] === '/results' && req.method === 'GET') {
      if (run.status !== 'done') return json(res, 409, { detail: `run en estado ${run.status}` })
      if (run.mode === 'offtarget') {
        return json(res, 200, {
          schema: 'sifi.results/1',
          run_id: run.run_id,
          hits_by_panel: [{ panel_id: 'maiz', n_hits: 2, hits: [{ id: 'h1' }, { id: 'h2' }] }],
        })
      }
      return json(res, 200, { schema: 'sifi.results/1', run_id: run.run_id, candidates: CANDIDATES })
    }
  }

  if (req.method === 'POST' && p === '/reports') {
    const body = await readBody(req)
    if (!body?.run_id) return json(res, 422, { detail: 'run_id requerido' })
    return json(res, 202, { run_id: body.run_id, format: body.format ?? 'pdf', report_path: `/tmp/out/${body.run_id}/report.pdf`, bytes: 48211 })
  }

  if (req.method === 'GET' && p === '/news') {
    const since = url.searchParams.get('since') ?? '7d'
    return json(res, 200, {
      since,
      novedades: [
        { titulo: 'dsRNA contra Dalbulus maidis', url: 'https://example.org/a', fecha: '2026-10-20', fuente: 'PubMed', por_que_importa: 'nueva diana', accion_sugerida: 'leer' },
      ],
    })
  }

  return json(res, 404, { detail: `ruta desconocida ${p}` })
})

let client
let baseUrl

test.before(async () => {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  baseUrl = `http://127.0.0.1:${server.address().port}`
  process.env.SIFID_URL = baseUrl
  client = new SifidClient({ baseUrl })
})

test.after(() => {
  server.closeAllConnections?.()
  server.close()
})

const ctx = () => ({ client })

// ------------------------------------------------------------------- tests

test('el catálogo tiene exactamente las 7 tools del contrato', () => {
  assert.deepEqual(
    TOOLS.map((t) => t.name).sort(),
    ['sifi_design', 'sifi_news', 'sifi_offtarget', 'sifi_panels', 'sifi_report', 'sifi_score', 'sifi_status'],
  )
  for (const t of TOOLS) {
    assert.ok(t.description?.length > 20, `${t.name} sin descripción útil`)
    assert.equal(typeof t.execute, 'function')
    assert.equal(typeof t.render, 'function')
  }
})

test('sifi_panels devuelve los paneles normalizados', async () => {
  const r = await callTool('sifi_panels', {}, ctx())
  assert.equal(r.panels.length, 2)
  assert.equal(r.panels[0].panel_id, 'maiz')
  assert.equal(r.panels[1].built, false)
  assert.match(TOOLS.find((t) => t.name === 'sifi_panels').render(r), /maiz/)
})

test('sifi_design crea el run, espera y devuelve top ordenado por score', async () => {
  const r = await callTool(
    'sifi_design',
    { query_path: 'tests/data/query.fa', panel_ids: ['maiz'], sirna_size: 21 },
    ctx(),
  )
  assert.ok(r.run_id, 'falta run_id')
  assert.equal(r.status, 'done')
  assert.equal(r.n_sirnas, 3)
  assert.equal(r.top[0].id, 'sirna_02', 'debe ordenar por score descendente')
  assert.equal(r.top[0].score, 88.4)
  assert.ok(r.top.length <= 10)
  assert.match(TOOLS.find((t) => t.name === 'sifi_design').render(r), /run_/)

  // el POST respetó el contrato
  const post = state.runs.get(r.run_id)
  assert.equal(post.mode, 'design')
  assert.equal(post.mismatches, 2)
  assert.deepEqual(post.panel_ids, ['maiz'])
})

test('sifi_design con wait:false devuelve el run encolado sin bloquear', async () => {
  const r = await callTool('sifi_design', { query_path: 'q.fa', wait: false }, ctx())
  assert.equal(r.status, 'queued')
  assert.deepEqual(r.top, [])
  assert.equal(r.n_sirnas, null)
})

test('sifi_status lee un run y lista sin run_id', async () => {
  const created = await callTool('sifi_design', { query_path: 'q2.fa', wait: false }, ctx())
  const one = await callTool('sifi_status', { run_id: created.run_id }, ctx())
  assert.equal(one.run_id, created.run_id)
  assert.ok(one.progress.total > 0)

  const all = await callTool('sifi_status', {}, ctx())
  assert.ok(all.total >= 1)
  assert.ok(Array.isArray(all.runs))
  assert.ok(all.runs.every((x) => x.run_id))
})

test('sifi_offtarget reusa la consulta del run y devuelve hits por panel', async () => {
  const base = await callTool('sifi_design', { query_path: 'trigger.fa', panel_ids: ['maiz'] }, ctx())
  const r = await callTool(
    'sifi_offtarget',
    { run_id: base.run_id, panel_ids: ['simbionte'], wait: true },
    ctx(),
  )
  assert.ok(r.run_id)
  assert.notEqual(r.run_id, base.run_id, 'offtarget crea un run nuevo')
  assert.equal(r.origin_run_id, base.run_id)
  assert.equal(r.status, 'done')
  assert.equal(r.hits_by_panel[0].panel_id, 'maiz')
  assert.equal(r.hits_by_panel[0].n_hits, 2)

  // se relanzó con la query del run original
  const created = state.runs.get(r.run_id)
  assert.equal(created.query_path, 'trigger.fa')
  assert.equal(created.mode, 'offtarget')
})

test('sifi_score ordena, filtra por min_score y expone desglose', async () => {
  const run = await callTool('sifi_design', { query_path: 'q3.fa' }, ctx())
  const r = await callTool('sifi_score', { run_id: run.run_id, top_n: 2 }, ctx())
  assert.equal(r.n_candidates, 3)
  assert.equal(r.n_returned, 2)
  assert.deepEqual(r.top.map((c) => c.id), ['sirna_02', 'sirna_07'])
  assert.ok('breakdown' in r.top[0])
  assert.ok(Array.isArray(r.top[0].flags))

  const filtered = await callTool('sifi_score', { run_id: run.run_id, min_score: 50 }, ctx())
  assert.deepEqual(filtered.top.map((c) => c.id), ['sirna_02', 'sirna_07'])
})

test('sifi_report pide el PDF y devuelve la ruta', async () => {
  const run = await callTool('sifi_design', { query_path: 'q4.fa' }, ctx())
  const r = await callTool('sifi_report', { run_id: run.run_id, format: 'pdf' }, ctx())
  assert.equal(r.run_id, run.run_id)
  assert.equal(r.format, 'pdf')
  assert.match(r.report_path, /report\.pdf$/)
  assert.ok(r.bytes > 0)
})

test('sifi_news devuelve novedades normalizadas', async () => {
  const r = await callTool('sifi_news', { since: '30d' }, ctx())
  assert.equal(r.since, '30d')
  assert.equal(r.novedades.length, 1)
  assert.equal(r.novedades[0].titulo, 'dsRNA contra Dalbulus maidis')
  assert.equal(r.novedades[0].accion_sugerida, 'leer')
})

test('validación: parámetros faltantes, desconocidos y fuera de rango', async () => {
  await assert.rejects(() => callTool('sifi_design', {}, ctx()), /falta "query_path"/)
  await assert.rejects(() => callTool('sifi_design', { query_path: 'q', nope: 1 }, ctx()), /parámetro desconocido "nope"/)
  await assert.rejects(() => callTool('sifi_design', { query_path: 'q', sirna_size: 500 }, ctx()), /sirna_size.*<= 30/)
  await assert.rejects(() => callTool('sifi_report', { run_id: 'r', format: 'docx' }, ctx()), /pdf \| html/)
  await assert.rejects(() => callTool('sifi_inventada', {}, ctx()), /no existe esa tool/)
  await assert.rejects(() => callTool('sifi_offtarget', { run_id: 'r', panel_ids: 3 }, ctx()), /debe ser un array/)
})

test('error accionable cuando sifid no está corriendo', async () => {
  const dead = new SifidClient({ baseUrl: 'http://127.0.0.1:8799' })
  await assert.rejects(
    () => callTool('sifi_panels', {}, { client: dead }),
    (err) => {
      assert.equal(err.code, 'service_down')
      assert.match(err.message, /no está respondiendo/)
      assert.match(err.message, /python3 -m service\.app --port 8765/)
      assert.match(err.message, /SIFID_URL/)
      return true
    },
  )
})

test('el plugin de cordis registra las 7 tools y publica ctx.sifiTools', async () => {
  const app = new Context()
  await app.plugin(sifiTools, { baseUrl })
  const registry = app.sifiTools
  assert.ok(registry, 'no publicó ctx.sifiTools')
  const names = registry.list().map((t) => t.name).sort()
  assert.equal(names.length, 7)
  const panels = await registry.call('sifi_panels', {})
  assert.equal(panels.panels.length, 2)
  assert.equal(typeof registry.get('sifi_design').render, 'function')
  assert.equal(app.sifiClient.baseUrl, baseUrl)
  await app.registry.delete(sifiTools)
})
