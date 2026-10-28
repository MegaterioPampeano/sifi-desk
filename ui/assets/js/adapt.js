// Traducciones entre el contrato de `sifid` y la forma que ya usa la vista.
// La UI no calcula ciencia: sólo renombra campos y completa huecos de
// presentación. Lo que falta se muestra como "—", nunca se inventa.

const ROLES_OK = new Set(["blanco", "no_blanco", "control", "relacionado", "desconocido"]);

function n(v, def = null) {
  const x = Number(v);
  return Number.isFinite(x) ? x : def;
}

export function normalizeHealth(h) {
  const real = h && (h.service === "sifid" || (h.servicio === undefined && h.queue));
  return {
    real: Boolean(real),
    servicio: h?.service || h?.servicio || "desconocido",
    version: h?.version || "",
    modo: h?.modo || (real ? "local" : "mock"),
    n_paneles: h?.n_paneles ?? null,
    corridas: h?.corridas ?? h?.queue?.total ?? h?.queue?.done ?? null,
    worker: h?.worker || null,
  };
}

export function normalizePanel(p) {
  const rol = ROLES_OK.has(p?.rol) ? p.rol : "desconocido";
  return {
    id: p.id,
    nombre: p.nombre || p.id,
    rol,
    version: p.version || "—",
    titulo: p.titulo || p.nombre || p.id,
    descripcion: p.descripcion || (p.fingerprint ? `fingerprint ${p.fingerprint.slice(0, 12)}` : ""),
    n_seqs: n(p.n_seqs, 0),
    tamano: p.tamano || (p.n_seqs != null ? `${p.n_seqs} seqs` : "—"),
    sha256: p.sha256 || p.fingerprint || "",
    index_ok: p.index_ok !== false,
  };
}

export function normalizePanels(body) {
  return (body?.panels || []).map(normalizePanel);
}

export function normalizeRun(r) {
  if (!r) return r;
  const prog = r.progress || {};
  const pct = prog.percent ?? prog.pct ?? (r.status === "done" ? 100 : 0);
  const publicReq = r.request || {};
  const panels = publicReq.panels || [];
  return {
    ...r,
    id: r.run_id || r.id,
    status: r.status,
    progress: {
      ...prog,
      pct: Math.round(n(pct, 0)),
      hechos: prog.done ?? prog.hechos ?? 0,
      total: prog.total ?? 0,
    },
    panels: (panels.length ? panels : (r.panels || [])).map((p) =>
      typeof p === "string" ? { id: p, nombre: p, rol: "desconocido" } : normalizePanel(p)),
    mode: publicReq.mode || r.mode || "design",
    mismatches: n(publicReq.params?.mismatches ?? r.mismatches, null),
    query_path: publicReq.query?.name || r.query_path || "—",
    main_targets: publicReq.main_targets || r.main_targets || [],
    started_at: r.started_at || r.created_at,
    finished_at: r.finished_at,
    cost_seconds: r.cost_seconds ?? r.elapsed_s ?? null,
  };
}

export function normalizeRuns(body) {
  const list = Array.isArray(body) ? body : (body?.runs || []);
  return list.map(normalizeRun);
}

// El servicio real devuelve `records[].candidates[]` ya puntuados y con hits
// por panel; acá se completa lo que la tabla pinta y el manifest no guarda
// (ΔG no se persiste: se muestra "—"). La maqueta devuelve esta forma directa.
export function normalizeResults(payload) {
  if (!payload || !Array.isArray(payload.records)) return payload;
  const records = payload.records.map((rec) => ({
    ...rec,
    query_name: rec.query_name || rec.gene?.id || "—",
    gene: {
      id: rec.gene?.id || rec.query_name,
      nombre: rec.gene?.nombre || rec.query_name,
      longitud: rec.gene?.longitud ?? null,
      secuencia: rec.gene?.secuencia || null,
      regiones: rec.gene?.regiones || [],
    },
    candidates: (rec.candidates || []).map((c) => ({
      ...c,
      id: c.id || c.sirna_name || "—",
      pos: n(c.pos, null),
      seq: c.seq || "",
      total: n(c.total, 0),
      banda: c.banda || "bajo",
      dg: c.dg ?? null,
      acc: c.acc ?? null,
      gc: c.gc ?? null,
      n_hits: n(c.n_hits, (c.hits || []).length),
      hits: c.hits || [],
      notas: c.notas || [],
    })),
  }));
  return { ...payload, records, source: payload.source || "service" };
}

export function normalizeNews(d) {
  const items = d?.items || [];
  return {
    ...d,
    items: items.map((it) => ({
      titulo: it.title || it.titulo || "(sin título)",
      fecha: it.date || it.fecha || "",
      fuente: it.source || it.fuente || it.journal || "",
      doi: it.doi || "",
      url: it.url || "",
      resumen: it.resumen || it.abstract || "",
      query: it.query || it.query_id || "",
    })),
    warnings: d?.warnings || [],
    cached: Boolean(d?.service?.cached),
  };
}
