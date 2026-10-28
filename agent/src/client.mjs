/**
 * Cliente HTTP del agente contra `sifid` (el servicio local del producto).
 *
 * Regla dura: este módulo NO importa el core de Python ni shell-out a nada.
 * Todo pasa por HTTP en 127.0.0.1. Si `sifid` no está, el error dice cómo
 * arrancarlo.
 */

export const DEFAULT_BASE_URL = 'http://127.0.0.1:8765'

const START_HINT = [
  'El servicio local `sifid` no está respondiendo.',
  'Arrancalo con:  python3 -m service.app --port 8765   (o el sidecar:  sifid --port 8765)',
  'Y verificá con:  curl -s http://127.0.0.1:8765/health',
  'Si corre en otro puerto, exportá SIFID_URL=http://127.0.0.1:<puerto>.',
].join('\n')

export class SifidError extends Error {
  constructor(message, { code = 'sifid_error', status, url, detail, cause } = {}) {
    super(message, { cause })
    this.name = 'SifidError'
    this.code = code
    this.status = status
    this.url = url
    this.detail = detail
  }
}

function extractDetail(payload) {
  if (!payload) return undefined
  if (typeof payload === 'string') return payload.slice(0, 500)
  return payload.detail ?? payload.error ?? payload.message ?? JSON.stringify(payload).slice(0, 500)
}

export class SifidClient {
  constructor({ baseUrl, token, timeoutMs = 30_000 } = {}) {
    this.baseUrl = (baseUrl || process.env.SIFID_URL || DEFAULT_BASE_URL).replace(/\/+$/, '')
    this.token = token ?? process.env.SIFID_TOKEN ?? null
    this.timeoutMs = timeoutMs
  }

  url(path, query) {
    const u = new URL(this.baseUrl + path)
    for (const [k, v] of Object.entries(query || {})) {
      if (v !== undefined && v !== null && v !== '') u.searchParams.set(k, String(v))
    }
    return u
  }

  async request(method, path, { query, body, signal, timeoutMs } = {}) {
    const url = this.url(path, query)
    const headers = { accept: 'application/json' }
    if (body !== undefined) headers['content-type'] = 'application/json'
    if (this.token) headers['x-sifi-token'] = this.token

    const timeout = AbortSignal.timeout(timeoutMs ?? this.timeoutMs)
    const combined = signal ? AbortSignal.any([signal, timeout]) : timeout

    let res
    try {
      res = await fetch(url, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: combined,
      })
    } catch (err) {
      if (err?.name === 'AbortError' || err?.name === 'TimeoutError') {
        const cancelled = signal?.aborted
        throw new SifidError(
          cancelled
            ? `Pedido cancelado: ${method} ${path}.`
            : `Timeout (${timeoutMs ?? this.timeoutMs} ms) esperando ${method} ${path} en ${this.baseUrl}. ` +
                'La corrida puede seguir en el servicio: consultá sifi_status con el run_id.',
          { code: cancelled ? 'cancelled' : 'timeout', url: String(url), cause: err },
        )
      }
      throw new SifidError(
        `No puedo hablar con sifid en ${this.baseUrl} (${method} ${path}): ${err?.message ?? err}.\n${START_HINT}`,
        { code: 'service_down', url: String(url), cause: err },
      )
    }

    const text = await res.text()
    let payload
    try {
      payload = text ? JSON.parse(text) : null
    } catch {
      payload = text
    }

    if (!res.ok) {
      const detail = extractDetail(payload)
      const extra =
        res.status === 404
          ? '\n(404: el servicio no expone ese endpoint todavía, o el id no existe.)'
          : res.status >= 500
            ? '\n(500: el servicio falló. Mirá el log de sifid; el run puede haber quedado en error.)'
            : ''
      throw new SifidError(
        `sifid respondió ${res.status} a ${method} ${path}: ${detail ?? 'sin detalle'}${extra}`,
        { code: 'http_error', status: res.status, url: String(url), detail, cause: payload },
      )
    }
    return payload
  }

  // --- endpoints del contrato ---
  health(opts) {
    return this.request('GET', '/health', opts)
  }

  createRun(body, opts) {
    return this.request('POST', '/runs', { ...opts, body })
  }

  listRuns(opts) {
    return this.request('GET', '/runs', opts)
  }

  getRun(runId, opts) {
    return this.request('GET', `/runs/${encodeURIComponent(runId)}`, opts)
  }

  cancelRun(runId, opts) {
    return this.request('POST', `/runs/${encodeURIComponent(runId)}/cancel`, opts)
  }

  getResults(runId, opts) {
    return this.request('GET', `/runs/${encodeURIComponent(runId)}/results`, {
      ...opts,
      // el manifest puede ser grande y el worker puede tardar
      timeoutMs: opts?.timeoutMs ?? 60_000,
    })
  }

  listPanels(opts) {
    return this.request('GET', '/panels', opts)
  }

  /** Reporte: POST /reports (ROADMAP §5.3). Puede no estar en un servicio viejo. */
  createReport(body, opts) {
    return this.request('POST', '/reports', opts ? { ...opts, body } : { body })
  }

  /** Novedades (M7): GET /news?since=... */
  news(query, opts) {
    return this.request('GET', '/news', { ...opts, query })
  }
}

export async function waitForRun(client, runId, { timeoutS = 120, intervalMs = 1000, signal } = {}) {
  const deadline = Date.now() + timeoutS * 1000
  let last
  while (Date.now() < deadline) {
    last = await client.getRun(runId, { signal })
    const status = last?.status
    if (status && status !== 'queued' && status !== 'running') return last
    await sleep(intervalMs, signal)
  }
  throw new SifidError(
    `La corrida ${runId} sigue en estado "${last?.status ?? 'desconocido'}" después de ${timeoutS}s. ` +
      `No la doy por terminada: consultá sifi_status con run_id="${runId}" o subí el timeout.`,
    { code: 'timeout', detail: last },
  )
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason ?? new Error('aborted'))
    const t = setTimeout(() => {
      signal?.removeEventListener?.('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(t)
      reject(new SifidError('Pedido cancelado mientras esperaba la corrida.', { code: 'cancelled' }))
    }
    signal?.addEventListener?.('abort', onAbort, { once: true })
  })
}
