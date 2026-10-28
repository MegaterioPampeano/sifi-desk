/**
 * Definiciones portables de las 7 tools del producto.
 *
 * Formato neutral (no depende de dsh): { name, description, parameters, execute, render }.
 * El adaptador (`adapter/index.mjs`) las publica en el harness que haya.
 * `execute(args, ctx)` recibe { client, signal, log } y devuelve JSON canónico.
 */

import { SifidError, waitForRun } from './client.mjs'

export class ToolInputError extends Error {
  constructor(tool, message) {
    super(`Argumentos inválidos para ${tool}: ${message}`)
    this.name = 'ToolInputError'
    this.code = 'bad_input'
    this.tool = tool
  }
}

// ---------------------------------------------------------------- validación

const P = {
  str: (description, extra = {}) => ({ type: 'string', description, ...extra }),
  num: (description, extra = {}) => ({ type: 'number', description, ...extra }),
  bool: (description, extra = {}) => ({ type: 'boolean', description, ...extra }),
  arr: (description, extra = {}) => ({ type: 'array', items: { type: 'string' }, description, ...extra }),
}

function check(tool, parameters, args) {
  if (args === null || typeof args !== 'object' || Array.isArray(args)) {
    throw new ToolInputError(tool, 'se esperaba un objeto JSON')
  }
  for (const key of Object.keys(args)) {
    if (!(key in parameters)) {
      throw new ToolInputError(
        tool,
        `parámetro desconocido "${key}". Aceptados: ${Object.keys(parameters).join(', ')}`,
      )
    }
  }
  for (const [key, spec] of Object.entries(parameters)) {
    const value = args[key]
    if (value === undefined || value === null) {
      if (spec.required) throw new ToolInputError(tool, `falta "${key}" (${spec.type})`)
      continue
    }
    if (spec.type === 'array') {
      if (!Array.isArray(value)) throw new ToolInputError(tool, `"${key}" debe ser un array`)
      value.forEach((v, i) => {
        if (typeof v !== 'string' || !v.trim()) {
          throw new ToolInputError(tool, `"${key}[${i}]" debe ser un string no vacío`)
        }
      })
      if (spec.minItems && value.length < spec.minItems) {
        throw new ToolInputError(tool, `"${key}" necesita al menos ${spec.minItems} elemento(s)`)
      }
    } else if (spec.type === 'number') {
      if (typeof value !== 'number' || !Number.isFinite(value)) {
        throw new ToolInputError(tool, `"${key}" debe ser un número`)
      }
      if (spec.min !== undefined && value < spec.min) {
        throw new ToolInputError(tool, `"${key}" debe ser >= ${spec.min} (recibí ${value})`)
      }
      if (spec.max !== undefined && value > spec.max) {
        throw new ToolInputError(tool, `"${key}" debe ser <= ${spec.max} (recibí ${value})`)
      }
      if (spec.integer && !Number.isInteger(value)) {
        throw new ToolInputError(tool, `"${key}" debe ser entero (recibí ${value})`)
      }
    } else if (typeof value !== spec.type) {
      throw new ToolInputError(tool, `"${key}" debe ser ${spec.type}`)
    } else if (spec.type === 'string' && !value.trim() && spec.minLength !== 0) {
      throw new ToolInputError(tool, `"${key}" no puede estar vacío`)
    }
    if (spec.enum && !spec.enum.includes(value)) {
      throw new ToolInputError(tool, `"${key}" debe ser uno de: ${spec.enum.join(' | ')}`)
    }
  }
  return args
}

// ------------------------------------------------------------ normalización

const DONE = new Set(['done', 'error', 'cancelled', 'cancelling', 'interrupted'])

export function normalizeRun(run) {
  if (!run || typeof run !== 'object') return run
  return {
    run_id: run.run_id ?? run.id,
    status: run.status,
    progress: run.progress ?? null,
    mode: run.mode,
    panel_ids: run.panel_ids ?? [],
    main_target: run.main_target ?? null,
    created_at: run.created_at ?? null,
    started_at: run.started_at ?? null,
    finished_at: run.finished_at ?? null,
    error: run.error ?? null,
  }
}

function candidatesOf(results) {
  if (!results) return []
  if (Array.isArray(results.candidates)) return results.candidates
  if (Array.isArray(results.top)) return results.top
  if (Array.isArray(results.sirnas)) return results.sirnas
  return []
}

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

export function scoreOf(c) {
  return num(c?.score) ?? num(c?.efficiency) ?? num(c?.eff) ?? 0
}

function bestOf(c) {
  return num(c?.efficiency) ?? num(c?.eff) ?? num(c?.score) ?? null
}

export function slimCandidate(c) {
  return {
    id: c?.id ?? c?.name ?? c?.sirna_id ?? null,
    sequence: c?.sequence ?? c?.seq ?? null,
    position: c?.position ?? c?.start ?? null,
    strand: c?.strand ?? null,
    score: scoreOf(c),
    efficiency: bestOf(c),
    // desglose dominio v2 (si el core lo trae)
    breakdown: c?.breakdown ?? { E: c?.E, R: c?.R, T: c?.T, S: c?.S, D: c?.D },
    flags: c?.flags ?? [],
    verdict: c?.verdict ?? null,
  }
}

function runCreated(run, extra = {}) {
  const r = normalizeRun(run)
  return {
    run_id: r.run_id,
    status: r.status,
    mode: r.mode,
    panel_ids: r.panel_ids,
    main_target: r.main_target,
    ...extra,
  }
}

function requireRunId(tool, args) {
  if (!args.run_id || !String(args.run_id).trim()) {
    throw new ToolInputError(tool, 'falta "run_id" (lo devuelve sifi_design/sifi_offtarget)')
  }
  return String(args.run_id).trim()
}

// ------------------------------------------------------------------- tools

export const TOOLS = [
  {
    name: 'sifi_design',
    description:
      'Diseña siRNAs/dsRNA para una secuencia o gen contra las bases ya indexadas. ' +
      'Crea un run en sifid, espera (opcional) y devuelve el run_id y el top de candidatos.',
    parameters: {
      query_path: P.str('Ruta al FASTA de la consulta, o ID de gen ya registrado en el servicio', {
        required: true,
      }),
      panel_ids: P.arr('Paneles de no-blanco a usar (ver sifi_panels). Vacío = paneles activos por defecto', {
        minItems: 0,
      }),
      sirna_size: P.num('Largo del siRNA en nt (default 21)', {
        min: 15, max: 30, integer: true, default: 21,
      }),
      mismatches: P.num('Mismatches permitidos por bowtie -v (default 2)', {
        min: 0, max: 5, integer: true, default: 2,
      }),
      top_n: P.num('Cuántos candidatos devolver en el resumen (default 10)', {
        min: 1, max: 100, integer: true, default: 10,
      }),
      wait: P.bool('Esperar a que la corrida termine (default true)', { default: true }),
      timeout_s: P.num('Timeout de la espera en segundos (default 120)', {
        min: 5, max: 3600, integer: true, default: 120,
      }),
    },
    async execute(args, { client, signal }) {
      const body = {
        query_path: args.query_path,
        panel_ids: args.panel_ids ?? [],
        mode: 'design',
        mismatches: args.mismatches ?? 2,
        main_target: null,
      }
      if (args.sirna_size !== undefined) body.sirna_size = args.sirna_size
      const run = await client.createRun(body, { signal })
      const created = runCreated(run, { sirna_size: args.sirna_size ?? 21, mismatches: body.mismatches })

      if (args.wait === false || DONE.has(created.status)) {
        if (created.status === 'done') return withTop(client, created, args.top_n ?? 10, signal)
        return { ...created, n_sirnas: null, top: [] }
      }

      const finished = normalizeRun(
        await waitForRun(client, created.run_id, { timeoutS: args.timeout_s ?? 120, signal }),
      )
      const base = { ...created, ...finished, run_id: created.run_id }
      if (finished.status === 'error') {
        throw new SifidError(
          `La corrida ${created.run_id} terminó en error: ${finished.error ?? 'sin detalle'}. ` +
            'No hay resultados que reportar (no los invento).',
          { code: 'run_error', detail: finished },
        )
      }
      if (finished.status !== 'done') return { ...base, n_sirnas: null, top: [] }
      return withTop(client, base, args.top_n ?? 10, signal)
    },
    render(r) {
      if (!r.top?.length) {
        return `Run ${r.run_id} (${r.status}). Sin candidatos todavía.${r.n_sirnas != null ? ` n=${r.n_sirnas}.` : ''}`
      }
      const lines = r.top.map(
        (c, i) => `${i + 1}. ${c.id ?? c.sequence} score=${c.score} eff=${c.efficiency ?? '-'} ${c.flags?.length ? `flags=${c.flags.join(',')}` : ''}`,
      )
      return `Run ${r.run_id}: ${r.n_sirnas} candidatos (muestro ${r.top.length}).\n${lines.join('\n')}\nPredicción in silico: requiere validación en laboratorio.`
    },
  },

  {
    name: 'sifi_offtarget',
    description:
      'Lanza una búsqueda de off-targets para la consulta de un run existente contra otros paneles. ' +
      'Devuelve un run_id nuevo (el servicio encola la búsqueda).',
    parameters: {
      run_id: P.str('Run de origen (de sifi_design): de ahí se toma la consulta y el blanco principal', {
        required: true,
      }),
      panel_ids: P.arr('Paneles de no-blanco donde buscar hits (requerido)', { required: true, minItems: 1 }),
      mismatches: P.num('Mismatches permitidos (default: el del run original)', {
        min: 0, max: 5, integer: true,
      }),
      wait: P.bool('Esperar a que termine (default false: es una búsqueda larga)', { default: false }),
      timeout_s: P.num('Timeout de la espera en segundos (default 300)', {
        min: 5, max: 3600, integer: true, default: 300,
      }),
    },
    async execute(args, { client, signal }) {
      const runId = requireRunId('sifi_offtarget', args)
      const origin = await client.getRun(runId, { signal })
      const query = origin?.query_path ?? origin?.params?.query_path ?? null
      if (!query) {
        throw new SifidError(
          `El run ${runId} no expone "query_path"; no puedo relanzar la búsqueda de off-targets. ` +
            'Volvé a correr sifi_design con query_path explícito.',
          { code: 'bad_run', detail: origin },
        )
      }
      const body = {
        query_path: query,
        panel_ids: args.panel_ids,
        mode: 'offtarget',
        mismatches: args.mismatches ?? origin?.mismatches ?? 2,
        main_target: origin?.main_target ?? origin?.params?.main_target ?? null,
      }
      const run = await client.createRun(body, { signal })
      const created = runCreated(run, { origin_run_id: runId, mismatches: body.mismatches })
      if (args.wait) {
        const finished = normalizeRun(
          await waitForRun(client, created.run_id, { timeoutS: args.timeout_s ?? 300, signal }),
        )
        const hits = finished.status === 'done' ? await hitsByPanel(client, created.run_id, signal) : []
        return { ...created, status: finished.status, error: finished.error, hits_by_panel: hits }
      }
      return { ...created, hits_by_panel: [] }
    },
    render(r) {
      const head = `Run ${r.run_id} (off-target de ${r.origin_run_id}, ${r.status}).`
      if (!r.hits_by_panel?.length) return `${head} Encaminado; consultá sifi_score/sifi_status con este run_id.`
      return `${head} ${r.hits_by_panel.map((h) => `${h.panel_id}: ${h.n_hits}`).join(' · ')}`
    },
  },

  {
    name: 'sifi_status',
    description:
      'Estado de un run (o listado de runs si no se pasa run_id): cola, progreso, tiempos y error.',
    parameters: {
      run_id: P.str('ID del run (opcional: sin esto lista todos)'),
      limit: P.num('Máximo de runs a listar (default 20)', { min: 1, max: 200, integer: true, default: 20 }),
    },
    async execute(args, { client, signal }) {
      if (args.run_id) {
        const run = await client.getRun(String(args.run_id).trim(), { signal })
        return normalizeRun(run)
      }
      const payload = await client.listRuns({ signal })
      const list = Array.isArray(payload) ? payload : (payload?.runs ?? [])
      return {
        runs: list.slice(0, args.limit ?? 20).map(normalizeRun),
        total: list.length,
      }
    },
    render(r) {
      if (Array.isArray(r.runs)) {
        if (!r.runs.length) return 'No hay corridas en el servicio.'
        return `${r.total} corrida(s):\n` +
          r.runs.map((x) => `- ${x.run_id} ${x.status} ${x.progress ? `${x.progress.done ?? x.progress.processed}/${x.progress.total ?? '?'}` : ''}`).join('\n')
      }
      const p = r.progress ? ` ${r.progress.done ?? r.progress.processed ?? '?'}/${r.progress.total ?? '?'}` : ''
      return `Run ${r.run_id}: ${r.status}${p}${r.error ? ` — error: ${r.error}` : ''}`
    },
  },

  {
    name: 'sifi_score',
    description:
      'Lee los resultados de un run terminado y devuelve los candidatos ordenados por score con su desglose (E/R/T/S/D).',
    parameters: {
      run_id: P.str('ID del run terminado', { required: true }),
      top_n: P.num('Cuántos candidatos devolver (default 10)', { min: 1, max: 500, integer: true, default: 10 }),
      min_score: P.num('Filtro: descartar candidatos con score menor a este valor', { min: 0, max: 100 }),
    },
    async execute(args, { client, signal }) {
      const runId = requireRunId('sifi_score', args)
      const results = await client.getResults(runId, { signal })
      const all = candidatesOf(results).map(slimCandidate)
      const filtered = args.min_score === undefined ? all : all.filter((c) => c.score >= args.min_score)
      filtered.sort((a, b) => b.score - a.score)
      return {
        run_id: runId,
        schema: results?.schema ?? null,
        n_candidates: all.length,
        n_returned: Math.min(args.top_n ?? 10, filtered.length),
        top: filtered.slice(0, args.top_n ?? 10),
      }
    },
    render(r) {
      const head = `Run ${r.run_id}: ${r.n_candidates} candidatos, devuelvo ${r.n_returned}.`
      if (!r.top.length) return `${head} (nada supera el filtro)`
      return head + '\n' + r.top
        .map((c, i) => `${i + 1}. ${c.id ?? c.sequence} score=${c.score} ${c.verdict ? `veredicto=${c.verdict}` : ''}`)
        .join('\n')
    },
  },

  {
    name: 'sifi_report',
    description:
      'Pide al motor de reportes un PDF/HTML reproducible para un run terminado (POST /reports).',
    parameters: {
      run_id: P.str('ID del run terminado', { required: true }),
      format: P.str('Formato de salida', { enum: ['pdf', 'html'], default: 'pdf' }),
      template: P.str('Plantilla del reporte (default "default")', { default: 'default' }),
    },
    async execute(args, { client, signal }) {
      const runId = requireRunId('sifi_report', args)
      let payload
      try {
        payload = await client.createReport(
          { run_id: runId, template: args.template ?? 'default', format: args.format ?? 'pdf' },
          { signal },
        )
      } catch (err) {
        if (err instanceof SifidError && err.status === 404) {
          throw new SifidError(
            `Este sifid no expone POST /reports (404). El reporte lo arma el frente de reportes (M6); ` +
              'mientras tanto usá sifi_score para leer los resultados y redactá el informe a mano con los datos reales.',
            { code: 'not_implemented', status: 404, detail: err.detail },
          )
        }
        throw err
      }
      return {
        run_id: runId,
        format: payload?.format ?? args.format ?? 'pdf',
        report_path: payload?.report_path ?? payload?.path ?? null,
        bytes: payload?.bytes ?? payload?.size ?? null,
      }
    },
    render(r) {
      return r.report_path
        ? `Reporte del run ${r.run_id}: ${r.report_path} (${r.format}${r.bytes ? `, ${r.bytes} bytes` : ''})`
        : `Reporte del run ${r.run_id} pedido (${r.format}), el servicio no devolvió ruta.`
    },
  },

  {
    name: 'sifi_panels',
    description: 'Lista los paneles de no-blanco disponibles (nombre, id, estado del índice, n de secuencias).',
    parameters: {},
    async execute(_args, { client, signal }) {
      const payload = await client.listPanels({ signal })
      const panels = Array.isArray(payload) ? payload : (payload?.panels ?? [])
      return {
        panels: panels.map((p) => ({
          panel_id: p.panel_id ?? p.id,
          name: p.name ?? p.label ?? null,
          n_seqs: p.n_seqs ?? p.sequences ?? null,
          built: p.built ?? p.indexed ?? null,
          sha256: p.sha256 ?? null,
          organism: p.organism ?? null,
          active: p.active ?? null,
        })),
      }
    },
    render(r) {
      if (!r.panels.length) return 'No hay paneles cargados en sifid.'
      return r.panels.map((p) => `- ${p.panel_id}${p.name ? ` (${p.name})` : ''}${p.n_seqs != null ? ` n=${p.n_seqs}` : ''}${p.built === false ? ' [índice pendiente]' : ''}`).join('\n')
    },
  },

  {
    name: 'sifi_news',
    description:
      'Novedades de literatura/upstream del vigilante (M7): papers y releases nuevos desde una fecha.',
    parameters: {
      since: P.str('Ventana temporal, ej. "7d", "30d" o fecha ISO (default "7d")', { default: '7d' }),
      limit: P.num('Máximo de novedades (default 20)', { min: 1, max: 200, integer: true, default: 20 }),
    },
    async execute(args, { client, signal }) {
      let payload
      try {
        payload = await client.news({ since: args.since ?? '7d' }, { signal })
      } catch (err) {
        if (err instanceof SifidError && err.status === 404) {
          throw new SifidError(
            'Este sifid no expone GET /news (frente de novedades M7). ' +
              'No invento novedades: pedile al usuario que las revise a mano o esperá ese frente.',
            { code: 'not_implemented', status: 404, detail: err.detail },
          )
        }
        throw err
      }
      const items = Array.isArray(payload) ? payload : (payload?.novedades ?? payload?.items ?? [])
      return {
        since: args.since ?? '7d',
        novedades: items.slice(0, args.limit ?? 20).map((n) => ({
          titulo: n.titulo ?? n.title ?? null,
          url: n.url ?? null,
          fecha: n.fecha ?? n.date ?? n.published ?? null,
          fuente: n.fuente ?? n.source ?? null,
          por_que_importa: n.por_que_importa ?? n.why ?? null,
          accion_sugerida: n.accion_sugerida ?? n.action ?? null,
        })),
        total: items.length,
      }
    },
    render(r) {
      if (!r.novedades.length) return `Sin novedades desde ${r.since}.`
      return `${r.novedades.length} novedad(es) desde ${r.since}:\n` +
        r.novedades.map((n) => `- ${n.titulo}${n.fecha ? ` (${n.fecha})` : ''}`).join('\n')
    },
  },
]

// ------------------------------------------------------------------ helpers

async function withTop(client, base, topN, signal) {
  const results = await client.getResults(base.run_id, { signal })
  const all = candidatesOf(results).map(slimCandidate).sort((a, b) => b.score - a.score)
  return { ...base, n_sirnas: all.length, top: all.slice(0, topN) }
}

async function hitsByPanel(client, runId, signal) {
  const results = await client.getResults(runId, { signal })
  const panels = results?.hits_by_panel ?? results?.offtargets ?? results?.panels
  if (Array.isArray(panels)) {
    return panels.map((p) => ({
      panel_id: p.panel_id ?? p.id ?? null,
      n_hits: p.n_hits ?? (Array.isArray(p.hits) ? p.hits.length : 0),
      hits: (p.hits ?? []).slice(0, 20),
    }))
  }
  return []
}

export function findTool(name) {
  const tool = TOOLS.find((t) => t.name === name)
  if (!tool) {
    throw new ToolInputError(
      String(name),
      `no existe esa tool. Disponibles: ${TOOLS.map((t) => t.name).join(', ')}`,
    )
  }
  return tool
}

/** Ejecuta una tool validando argumentos. Es el único camino de entrada. */
export async function callTool(name, args, ctx) {
  const tool = findTool(name)
  const clean = check(tool.name, tool.parameters, args ?? {})
  const filled = { ...clean }
  for (const [k, spec] of Object.entries(tool.parameters)) {
    if (filled[k] === undefined && spec.default !== undefined) filled[k] = spec.default
  }
  return tool.execute(filled, ctx)
}
