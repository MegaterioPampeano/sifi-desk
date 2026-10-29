// Cliente HTTP del servicio local (sifid). Sin dependencias.
//
// De dónde sale la URL (D4):
//   1. query string `?api=http://127.0.0.1:PORT&token=...` (desarrollo)
//   2. `window.__SIFI_CONFIG__ = { url, token }` (la ventana nativa lo inyecta
//      a partir de las líneas SIFID_URL/SIFID_TOKEN del sidecar)
//   3. mismo origen: si `sifid` sirve la UI, no hace falta nada; si la sirve
//      `ui/mock/server.py`, también es el mismo origen (maqueta).
// La elección del query string se recuerda en sessionStorage para no perderla
// al navegar entre vistas.

import { normalizeHealth, normalizePanels, normalizeRuns, normalizeRun,
         normalizeResults, normalizeNews } from "./adapt.js";

const STORE_KEY = "sifi.api.config";
const EN_TAURI = typeof window !== "undefined" && (
  Boolean(window.__TAURI_INTERNALS__) ||
  window.location.protocol === "tauri:" ||
  window.location.hostname.endsWith("tauri.localhost")
);

function readStored() {
  try {
    return JSON.parse(window.sessionStorage.getItem(STORE_KEY) || "null") || {};
  } catch {
    return {};
  }
}

function resolveConfig() {
  const params = new URLSearchParams(window.location.search || "");
  const stored = readStored();
  const injected = window.__SIFI_CONFIG__ || window.SIFI_CONFIG || {};
  const url = params.get("api") || stored.url || injected.url || "";
  const token = params.get("token") || stored.token || injected.token || "";
  if (params.has("api") || params.has("token")) {
    try {
      window.sessionStorage.setItem(STORE_KEY, JSON.stringify({ url, token }));
    } catch { /* modo privado: seguimos sin persistir */ }
  }
  // El token no queda en la barra de direcciones ni en el Referer de los links
  // externos (novedades): ya vive en sessionStorage.
  if (params.has("token")) {
    try {
      const clean = new URL(window.location.href);
      clean.searchParams.delete("token");
      window.history.replaceState(null, "", clean.toString());
    } catch { /* sin history: no es fatal */ }
  }
  return { url, token };
}

const inicial = resolveConfig();

// Fallback: en Tauri el sidecar escucha en 8791 si nadie inyectó config.
export let API_BASE = (inicial.url || (EN_TAURI ? "http://127.0.0.1:8791" : ""))
  .replace(/\/$/, "");
export let API_TOKEN = inicial.token;

let kind = "unknown"; // "service" | "mock"
export function getKind() { return kind; }
export function setKind(value) { kind = value; }

export function setApiBase(base, token = API_TOKEN) {
  API_BASE = (base || "").replace(/\/$/, "");
  API_TOKEN = token || "";
}

export class ApiError extends Error {
  constructor(status, mensaje, payload) {
    super(mensaje);
    this.status = status;
    this.payload = payload;
  }
}

function headers(extra = {}) {
  const h = { Accept: "application/json", ...extra };
  if (API_TOKEN) h["x-sifi-token"] = API_TOKEN;
  return h;
}

function mensajeDeError(status, payload) {
  if (status === 0) {
    return "No se pudo hablar con el servicio local. Abrí siFi Desk desde sifid " +
      "o pasá ?api=http://127.0.0.1:PUERTO&token=… en desarrollo.";
  }
  if (status === 401) {
    return "El servicio rechazó el token (401). Cerrá y volvé a abrir la ventana " +
      "desde sifid para tomar el SIFID_TOKEN nuevo.";
  }
  const det = payload && (payload.detail || payload.error || payload.message);
  return det || `El servicio respondió ${status}`;
}

async function request(method, path, body, signal) {
  const opts = { method, signal, headers: headers() };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(API_BASE + path, opts);
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(0, mensajeDeError(0, null));
  }
  const tipo = res.headers.get("Content-Type") || "";
  let payload = null;
  if (tipo.includes("application/json")) {
    payload = await res.json().catch(() => null);
  } else {
    payload = await res.text().catch(() => null);
  }
  if (!res.ok) throw new ApiError(res.status, mensajeDeError(res.status, payload), payload);
  return payload;
}

async function requestBlob(path, signal) {
  let res;
  try {
    res = await fetch(API_BASE + path, { signal, headers: headers() });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(0, mensajeDeError(0, null));
  }
  if (!res.ok) {
    let payload = null;
    try { payload = await res.json(); } catch { /* puede ser HTML/texto */ }
    throw new ApiError(res.status, mensajeDeError(res.status, payload), payload);
  }
  const disp = res.headers.get("Content-Disposition") || "";
  const m = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(disp);
  const filename = m ? decodeURIComponent(m[1].replace(/"/g, "")) : "informe.pdf";
  return { blob: await res.blob(), filename };
}

// El servicio real sólo acepta query_fasta o query_path, y main_targets[].
// La maqueta habla el dialecto viejo (query_text, main_target): se traduce
// según el servicio detectado en /health.
function payloadForService(p) {
  if (kind !== "service") return p;
  const out = {
    panel_ids: p.panel_ids || [],
    mode: p.mode || "design",
    mismatches: Number(p.mismatches || 0),
    sirna_size: Number(p.sirna_size || 21),
  };
  if (p.query_text) {
    const text = String(p.query_text);
    out.query_fasta = text.trimStart().startsWith(">") ? text : `>seq_1\n${text}`;
  } else if (p.query_path) {
    out.query_path = p.query_path;
  }
  if (p.main_target) {
    out.main_target_mode = "explicit";
    out.main_targets = [p.main_target];
  }
  return out;
}

// La maqueta vieja no tiene /view; el servicio real expone /view (adaptado).
// Si /view no existe, se cae a /results, que en la maqueta ya viene listo.
async function resultados(id, signal) {
  try {
    return await request("GET", `/runs/${encodeURIComponent(id)}/view`, undefined, signal);
  } catch (err) {
    if (err.status === 404 || err.status === 405) {
      return request("GET", `/runs/${encodeURIComponent(id)}/results`, undefined, signal);
    }
    throw err;
  }
}

export const api = {
  health: async (signal) => {
    const h = await request("GET", "/health", undefined, signal);
    const norm = normalizeHealth(h);
    kind = norm.real ? "service" : "mock";
    return norm;
  },
  panels: async (signal) =>
    normalizePanels(await request("GET", "/panels", undefined, signal)),
  cambiarRolPanel: (id, rol, signal) =>
    request("PATCH", `/panels/${id}`, { rol }, signal),
  runs: async (signal) =>
    normalizeRuns(await request("GET", "/runs", undefined, signal)),
  run: async (id, signal) =>
    normalizeRun(await request("GET", `/runs/${encodeURIComponent(id)}`, undefined, signal)),
  results: async (id, signal) => {
    const res = normalizeResults(await resultados(id, signal));
    if (kind === "mock") res.source = "mock";
    return res;
  },
  createRun: async (payload, signal) =>
    normalizeRun(await request("POST", "/runs", payloadForService(payload), signal)),
  cancelRun: (id, signal) => request("POST", `/runs/${encodeURIComponent(id)}/cancel`, {}, signal),
  report: (id, fmt = "pdf", signal) =>
    requestBlob(`/runs/${encodeURIComponent(id)}/report?fmt=${fmt}`, signal),
  news: (params = {}, signal) => {
    const q = new URLSearchParams();
    q.set("since", params.since || "7d");
    if (params.offline) q.set("offline", "1");
    if (params.refresh) q.set("refresh", "1");
    return request("GET", `/news?${q.toString()}`, undefined, signal)
      .then(normalizeNews);
  },
  chat: (mensaje, runId, signal, historial, sesionId) =>
    request("POST", "/agent/chat", { mensaje, run_id: runId || null, historial: historial || [], sesion_id: sesionId || null }, signal),
  sesiones: (signal) => request("GET", "/agent/sesiones", undefined, signal),
  sesion: (id, signal) => request("GET", `/agent/sesiones/${id}`, undefined, signal),
  nuevaSesion: (signal) => request("POST", "/agent/sesiones", {}, signal),
  borrarSesion: (id, signal) => request("DELETE", `/agent/sesiones/${id}`, undefined, signal),
  ajustes: (signal) => request("GET", "/settings/llm", undefined, signal),
  guardarAjustes: (body, signal) => request("PUT", "/settings/llm", body, signal),
  borrarAjustes: (signal) => request("DELETE", "/settings/llm", undefined, signal),
  probarAjustes: (signal) => request("POST", "/settings/llm/test", {}, signal),
};
