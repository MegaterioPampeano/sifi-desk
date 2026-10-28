// Pantalla de resultados: tabla ordenable, mapa del gen y acceso al detalle.
import { state } from "./state.js";
import { openDetail } from "./detail.js";
import { esc, num, entero, fecha, bandLabel, bandClass, EJES, roleLabel } from "./format.js";

const $ = (sel) => document.querySelector(sel);
const BAND_ORDER = { recomendado: 0, revisar: 1, bajo: 2, descartar: 3 };

export function initResults({ onNewRun }) {
  $("#band-filters").addEventListener("click", (ev) => {
    const chip = ev.target.closest("[data-band]");
    if (!chip) return;
    state.band = chip.dataset.band;
    [...$("#band-filters").children].forEach((c) => c.classList.toggle("is-active", c === chip));
    renderTable();
  });

  $("#q").addEventListener("input", debounce(() => {
    state.q = $("#q").value.trim().toLowerCase();
    renderTable();
  }, 140));

  $("#cand-table").querySelector("thead").addEventListener("click", (ev) => {
    const th = ev.target.closest("th[data-sort]");
    if (!th) return;
    const key = th.dataset.sort;
    if (state.sort.key === key) {
      state.sort.dir = state.sort.dir === "desc" ? "asc" : "desc";
    } else {
      state.sort.key = key;
      state.sort.dir = key === "id" || key === "query" || key === "banda" ? "asc" : "desc";
    }
    renderTable();
  });

  $("#cand-body").addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-id]");
    if (!tr) return;
    const rec = state.results.records.find((r) => r.query_name === tr.dataset.query);
    const cand = rec && rec.candidates.find((c) => c.id === tr.dataset.id && c.pos === Number(tr.dataset.pos));
    if (cand) openCandidate(rec, cand);
  });

  $("#gene-tabs").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-gene]");
    if (!b) return;
    state.geneFilter = b.dataset.gene;
    renderTabs();
    renderMap();
    renderTable();
  });

  $("#gene-map").addEventListener("click", (ev) => {
    const tick = ev.target.closest("[data-id]");
    if (!tick) return;
    const rec = state.results.records.find((r) => r.query_name === tick.dataset.query);
    const cand = rec && rec.candidates.find((c) => c.id === tick.dataset.id);
    if (cand) openCandidate(rec, cand);
  });

  $("#btn-new").addEventListener("click", onNewRun);
  $("#btn-export").addEventListener("click", () => {
    document.dispatchEvent(new CustomEvent("sifi:toast", {
      detail: { msg: "El frente de reportes todavía no expone POST /reports.", err: true },
    }));
  });
}

export function showResults(res) {
  state.results = res;
  state.geneFilter = "all";
  state.band = "all";
  state.q = "";
  $("#q").value = "";
  [...$("#band-filters").children].forEach((c) => c.classList.toggle("is-active", c.dataset.band === "all"));
  state.sort = { key: "total", dir: "desc" };
  renderAll();
}

export function renderAll() {
  const res = state.results;
  if (!res) return;
  const total = res.records.reduce((a, r) => a + r.candidates.length, 0);
  $("#res-title").textContent = `Candidatos (${total})`;
  const genes = res.records.map((r) => r.query_name).join(", ");
  const params = res.params || {};
  $("#res-sub").textContent = `${genes} · ${params.mode || "design"} · ${params.mismatches ?? "—"} mismatch(es) · ${fecha(res.generated_at)}`;
  $("#res-id").textContent = String(res.run_id || "—").slice(0, 12);
  renderTiles();
  renderTabs();
  renderMap();
  renderTable();
  $("#btn-export").title = "El frente de reportes todavía no expone POST /reports";
}

function renderTiles() {
  const res = state.results;
  const cands = flat();
  const rec = cands.filter((c) => c.cand.banda === "recomendado").length;
  const mejor = cands.slice().sort((a, b) => b.cand.total - a.cand.total)[0];
  const conHits = cands.filter((c) => c.cand.n_hits > 0).length;
  const riesgo = cands.filter((c) => c.cand.desglose?.R && c.cand.desglose.R.valor < 0.35).length;
  const paneles = (res.panels || []).length || (res.panel_ids || []).length;
  $("#res-tiles").innerHTML = `
    <div class="tile"><div class="k">Candidatos</div><div class="v">${entero(cands.length)}</div><div class="s">${res.records.length} gen(es) · ${paneles} panel(es)</div></div>
    <div class="tile"><div class="k">Recomendados</div><div class="v">${entero(rec)}</div><div class="s">${cands.length ? num(100 * rec / cands.length, 1) : "0"} % de la tabla</div></div>
    <div class="tile"><div class="k">Mejor score</div><div class="v">${mejor ? num(mejor.cand.total, 1) : "—"}<small> / 100</small></div><div class="s">${mejor ? `${esc(mejor.cand.id)} · ${esc(mejor.query)}` : "—"}</div></div>
    <div class="tile"><div class="k">Con off-target</div><div class="v">${entero(conHits)}</div><div class="s">${riesgo} con R &lt; 0,35 (riesgo alto)</div></div>
    <div class="tile"><div class="k">Scoring</div><div class="v">v${esc(res.scoring?.version ?? "2")}</div><div class="s">E 40 · R 15 · S 15 · T 15 · D 15</div></div>`;
}

function renderTabs() {
  const res = state.results;
  const tabs = [`<button type="button" class="genetab ${state.geneFilter === "all" ? "is-active" : ""}" data-gene="all">Todos</button>`];
  for (const r of res.records) {
    tabs.push(`<button type="button" class="genetab ${state.geneFilter === r.query_name ? "is-active" : ""}" data-gene="${esc(r.query_name)}">${esc(r.query_name)} <span class="muted">${r.candidates.length}</span></button>`);
  }
  $("#gene-tabs").innerHTML = tabs.join("");
}

function recordsVisibles() {
  const res = state.results;
  return state.geneFilter === "all" ? res.records : res.records.filter((r) => r.query_name === state.geneFilter);
}

function renderMap() {
  const recs = recordsVisibles();
  const cont = $("#gene-map");
  if (!recs.length) {
    cont.innerHTML = `<div class="d-empty">Sin gen seleccionado.</div>`;
    return;
  }
  const bloques = recs.map((rec) => {
    const gene = rec.gene || { longitud: 0, regiones: [] };
    const L = gene.longitud || 1;
    const regiones = (gene.regiones || []).map((rg) => {
      const w = 100 * (rg.fin - rg.inicio + 1) / L;
      const left = 100 * (rg.inicio - 1) / L;
      const tipo = /utr/i.test(rg.tipo) ? "utr" : "cds";
      return `<span class="map-region ${tipo}" style="left:${left}%;width:${w}%"><span>${esc(rg.tipo)}</span></span>`;
    }).join("");
    const ticks = rec.candidates.map((c) => {
      const left = 100 * Math.max(0, c.pos - 1) / L;
      const clase = c.banda === "recomendado" ? "ok" : c.banda === "revisar" ? "mid" : "low";
      return `<button type="button" class="map-tick ${clase}" style="left:${left}%" data-id="${esc(c.id)}" data-query="${esc(rec.query_name)}" title="${esc(c.id)} · pos ${c.pos} · ${num(c.total, 1)} · ${bandLabel(c.banda)}" aria-label="${esc(c.id)} en posición ${c.pos}"></button>`;
    }).join("");
    return `<div class="map-gene">
      <div class="map-scale"><span>${esc(rec.query_name)} · ${entero(L)} nt</span><span>${rec.candidates.length} candidato(s)</span></div>
      <div class="map-track">${regiones}${ticks}</div>
    </div>`;
  }).join("");
  cont.innerHTML = bloques;
  $("#map-caption").textContent = state.geneFilter === "all"
    ? "posición de cada candidato sobre el transcrito"
    : `posición de cada candidato sobre ${state.geneFilter}`;
  $("#map-note").textContent = "hacé clic en una marca para abrir el detalle";
}

function flat() {
  const out = [];
  for (const rec of state.results.records) {
    for (const cand of rec.candidates) {
      out.push({ query: rec.query_name, gene: rec.gene, rec, cand });
    }
  }
  return out;
}

function valorEje(cand, eje) {
  return cand.desglose?.[eje]?.valor ?? -1;
}

function renderTable() {
  const res = state.results;
  if (!res) return;
  const todos = flat();
  const ranking = new Map();
  todos.slice()
    .sort((a, b) => b.cand.total - a.cand.total || a.query.localeCompare(b.query) || a.cand.pos - b.cand.pos)
    .forEach((f, i) => ranking.set(`${f.query}|${f.cand.id}|${f.cand.pos}`, i + 1));

  let filas = todos.filter((f) => {
    if (state.geneFilter !== "all" && f.query !== state.geneFilter) return false;
    if (state.band !== "all" && f.cand.banda !== state.band) return false;
    if (!state.q) return true;
    const texto = [
      f.cand.id, f.cand.seq, f.query, f.gene?.nombre, String(f.cand.pos),
      ...(f.cand.hits || []).map((h) => `${h.seq_id} ${h.panel}`),
    ].join(" ").toLowerCase();
    return texto.includes(state.q);
  });

  const { key, dir } = state.sort;
  const signo = dir === "asc" ? 1 : -1;
  filas.sort((a, b) => {
    let va, vb;
    if (key === "rank") { va = ranking.get(`${a.query}|${a.cand.id}|${a.cand.pos}`); vb = ranking.get(`${b.query}|${b.cand.id}|${b.cand.pos}`); }
    else if (key === "id") { va = a.cand.id; vb = b.cand.id; }
    else if (key === "query") { va = a.query; vb = b.query; }
    else if (key === "banda") { va = BAND_ORDER[a.cand.banda] ?? 9; vb = BAND_ORDER[b.cand.banda] ?? 9; }
    else if (["E", "R", "S", "T", "D"].includes(key)) { va = valorEje(a.cand, key); vb = valorEje(b.cand, key); }
    else { va = a.cand[key] ?? -Infinity; vb = b.cand[key] ?? -Infinity; }
    if (typeof va === "string") return signo * va.localeCompare(vb);
    return signo * (va - vb);
  });

  // orden visual de la tabla
  const thead = $("#cand-table thead");
  thead.querySelectorAll("th[data-sort]").forEach((th) => {
    if (th.dataset.sort === key) {
      th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
    } else {
      th.removeAttribute("aria-sort");
    }
  });

  if (!filas.length) {
    $("#cand-body").innerHTML = `<tr><td colspan="13" class="empty-row">No hay candidatos con ese filtro.</td></tr>`;
  } else {
    $("#cand-body").innerHTML = filas.map((f) => filaHtml(f, ranking)).join("");
  }
  $("#table-count").textContent = `${filas.length} de ${todos.length}`;
  const score = res.scoring || {};
  $("#table-foot").textContent = `scoring ${score.schema || "sifi.score/2"} · v${score.version ?? "2"} · pesos ${Object.entries(score.pesos || {}).map(([k, v]) => `${k} ${v}`).join(" · ")} · la tabla ordena, no recalcula`;
}

function filaHtml(f, ranking) {
  const c = f.cand;
  const rank = ranking.get(`${f.query}|${c.id}|${c.pos}`);
  const axes = ["E", "R", "S", "T", "D"].map((e) => {
    const v = valorEje(c, e);
    const porc = Math.max(0, Math.min(100, v * 100));
    return `<td class="axis"><div class="axis-cell"><span class="val">${num(v, 2)}</span><span class="bar"><span style="width:${porc}%"></span></span></div></td>`;
  }).join("");
  return `<tr data-id="${esc(c.id)}" data-pos="${c.pos}" data-query="${esc(f.query)}">
    <td class="num muted">${rank}</td>
    <td>
      <div class="cand"><span class="cid">${esc(c.id)}</span><span class="cseq">${esc(c.seq)}</span></div>
    </td>
    <td><span class="gene-cell" title="${esc(f.gene?.nombre || "")}">${esc(f.query)}</span></td>
    <td class="num">${entero(c.pos)}</td>
    <td class="num">
      <div class="score-cell"><span class="val">${num(c.total, 1)}</span><span class="bar"><span style="width:${Math.max(0, Math.min(100, c.total))}%"></span></span></div>
    </td>
    <td><span class="band ${bandClass(c.banda)}">${bandLabel(c.banda)}</span></td>
    ${axes}
    <td class="num"><span class="hits-badge ${c.n_hits ? "has" : ""}">${c.n_hits ?? 0}</span></td>
    <td class="num muted">${c.dg === null || c.dg === undefined ? "—" : num(c.dg, 1)}</td>
  </tr>`;
}

function openCandidate(rec, cand) {
  state.activeCandidate = { rec, cand };
  document.querySelectorAll("#cand-body tr").forEach((tr) => {
    tr.classList.toggle("is-active", tr.dataset.id === cand.id && tr.dataset.query === rec.query_name && Number(tr.dataset.pos) === cand.pos);
  });
  openDetail(rec, cand);
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}
