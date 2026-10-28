#!/usr/bin/env node
/**
 * sifid falso mínimo para el smoke del harness (no lo usan los tests: ellos
 * tienen su propio doble con más endpoints).
 *
 *   node test/fake-sifid.mjs --port 8765
 *
 * Sirve `/health`, `/panels` y `/runs` con datos fijos, suficiente para que el
 * modelo pueda llamar `sifi_panels` de punta a punta.
 */
import http from 'node:http'

const portArg = process.argv.indexOf('--port')
const port = portArg > -1 ? Number(process.argv[portArg + 1]) : 8765

const PANELS = {
  maize: { id: 'maize', species: 'Zea mays', transcripts: 120345 },
  human: { id: 'human', species: 'Homo sapiens', transcripts: 191000 },
  aphid: { id: 'aphid', species: 'Acyrthosiphon pisum', transcripts: 33000 },
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x')
  const send = (code, body) => {
    const text = JSON.stringify(body)
    res.writeHead(code, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(text) })
    res.end(text)
  }
  if (req.method === 'GET' && url.pathname === '/health') return send(200, { ok: true, version: 'fake' })
  if (req.method === 'GET' && url.pathname === '/panels') return send(200, { panels: Object.values(PANELS) })
  if (req.method === 'GET' && url.pathname === '/runs') return send(200, { runs: [] })
  return send(404, { error: 'not_found', path: url.pathname })
})

server.listen(port, '127.0.0.1', () => {
  console.log(`fake sifid en http://127.0.0.1:${port}`)
})
