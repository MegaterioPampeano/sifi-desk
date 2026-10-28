// Cliente HTTP del servicio local (sifid). Sin dependencias.
// En la maqueta el mismo origen sirve la UI y la API; en Tauri el sidecar
// escucha en 127.0.0.1:<puerto efímero> y main.js fija API_BASE.

// En el navegador la maqueta sirve UI y API en el mismo origen. En la ventana
// Tauri el frontend se carga desde el asset protocol y el sidecar escucha en un
// puerto fijo (ver ui/tauri/src-tauri/src/main.rs).
const EN_TAURI = typeof window !== "undefined" && (
  Boolean(window.__TAURI_INTERNALS__) ||
  window.location.protocol === "tauri:" ||
  window.location.hostname.endsWith("tauri.localhost")
);

export let API_BASE = EN_TAURI ? "http://127.0.0.1:8791" : "";

export function setApiBase(base) {
  API_BASE = (base || "").replace(/\/$/, "");
}

export class ApiError extends Error {
  constructor(status, mensaje, payload) {
    super(mensaje);
    this.status = status;
    this.payload = payload;
  }
}

async function request(method, path, body, signal) {
  const opts = { method, signal, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(API_BASE + path, opts);
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(0, "No se pudo hablar con el servicio local (¿está corriendo sifid?)");
  }
  const tipo = res.headers.get("Content-Type") || "";
  let payload = null;
  if (tipo.includes("application/json")) {
    payload = await res.json().catch(() => null);
  } else {
    payload = await res.text().catch(() => null);
  }
  if (!res.ok) {
    const msg = (payload && payload.error) || `El servicio respondió ${res.status}`;
    throw new ApiError(res.status, msg, payload);
  }
  return payload;
}

export const api = {
  health: (signal) => request("GET", "/health", undefined, signal),
  panels: (signal) => request("GET", "/panels", undefined, signal),
  runs: (signal) => request("GET", "/runs", undefined, signal),
  run: (id, signal) => request("GET", `/runs/${encodeURIComponent(id)}`, undefined, signal),
  results: (id, signal) => request("GET", `/runs/${encodeURIComponent(id)}/results`, undefined, signal),
  createRun: (payload, signal) => request("POST", "/runs", payload, signal),
  cancelRun: (id, signal) => request("POST", `/runs/${encodeURIComponent(id)}/cancel`, {}, signal),
  chat: (mensaje, runId, signal) => request("POST", "/agent/chat", { mensaje, run_id: runId || null }, signal),
};
