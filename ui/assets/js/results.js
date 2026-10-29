// Pantalla de resultados: tabla ordenable, mapa del gen y acceso al detalle.
import { state } from "./state.js";
import { api } from "./api.js";
import { openDetail } from "./detail.js";
import { esc, num, entero, fecha, bandLabel, bandClass, EJES, roleLabel } from "./format.js";

const $ = (sel) => document.querySelector(sel);
const BAND_ORDER = { recomendado: 0, revisar: 1, bajo: 2, descartar: 3 };

export function initResults({ onNewRun }) {
  const zin = $("#perfil-in"), zout = $("#perfil-out"), ztodo = $("#perfil-todo");
  if (zin) zin.addEventListener("click", () => perfilZoom(0.6));
  if (zout) zout.addEventListener("click", () => perfilZoom(1.6));
  if (ztodo) ztodo.addEventListener("click", perfilReset);

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
    renderPerfil();
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
  $("#btn-export").addEventListener("click", exportarPdf);
}

async function exportarPdf() {
  const btn = $("#btn-export");
  const id = state.results?.run_id || state.runId;
  if (!id) return;
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Generando…";
  try {
    const { blob, filename } = await api.report(id, "pdf");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || `informe-${id}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    document.dispatchEvent(new CustomEvent("sifi:toast", {
      detail: { msg: `Informe descargado: ${a.download}` },
    }));
  } catch (err) {
    document.dispatchEvent(new CustomEvent("sifi:toast", {
      detail: { msg: `No se pudo generar el informe: ${err.message}`, err: true },
    }));
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
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
  renderPerfil();
  renderTable();
  $("#btn-export").title = "Descargar el informe PDF generado por el servicio";
  $("#btn-export").disabled = !(res.run_id && res.source !== "mock");
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


// Perfil por posición: score de cada candidato contra su posición en el transcrito, con
// una media móvil para ver dónde conviene cortar. Tiene zoom (rueda o botones), arrastre
// para moverse y doble clic para volver a ver todo. El mapa de arriba dice *dónde* están;
// esto dice *qué tan buenos* son en cada zona, que es lo que decide la ventana.

const PERFIL_ANCHO = 720;
const PERFIL_ALTO = 220;
const PERFIL_M = { top: 12, right: 12, bottom: 26, left: 34 };

// dominio visible por gen: {x0, x1, y0, y1}. Vive en memoria, no se guarda en disco.
const perfilVista = new Map();

function perfilDominio(rec) {
  const L = (rec.gene && rec.gene.longitud) || 1;
  const clave = rec.query_name;
  if (!perfilVista.has(clave)) perfilVista.set(clave, { x0: 1, x1: L, y0: 0, y1: 100 });
  return perfilVista.get(clave);
}

function renderPerfil() {
  const cont = $("#gene-perfil");
  if (!cont) return;
  const recs = recordsVisibles();
  const nota = $("#perfil-note");
  if (!recs.length) {
    cont.innerHTML = `<div class="d-empty">Sin gen seleccionado.</div>`;
    if (nota) nota.textContent = "";
    return;
  }

  const { top, right, bottom, left } = PERFIL_M;
  const iw = PERFIL_ANCHO - left - right;
  const ih = PERFIL_ALTO - top - bottom;

  cont.innerHTML = recs.map((rec, idx) => {
    const cands = rec.candidates.slice().sort((a, b) => a.pos - b.pos);
    if (!cands.length) return `<div class="d-empty">Sin candidatos.</div>`;
    const dom = perfilDominio(rec);
    const x = (pos) => left + iw * (pos - dom.x0) / Math.max(1e-9, dom.x1 - dom.x0);
    const y = (v) => top + ih * (1 - (v - dom.y0) / Math.max(1e-9, dom.y1 - dom.y0));
    const dentro = (c) => c.pos >= dom.x0 && c.pos <= dom.x1
      && c.total >= dom.y0 && c.total <= dom.y1;

    const visibles = cands.filter(dentro);
    const puntos = visibles.map((c) => {
      const clase = c.banda === "recomendado" ? "ok" : c.banda === "revisar" ? "mid" : "low";
      const r = visibles.length > 1500 ? 1.8 : 2.4;
      return `<circle class="pf ${clase}" cx="${x(c.pos).toFixed(1)}" cy="${y(c.total).toFixed(1)}" `
        + `r="${r}" data-id="${esc(c.id)}" data-query="${esc(rec.query_name)}">`
        + `<title>${esc(c.id)} · pos ${c.pos} · ${num(c.total, 1)} · ${bandLabel(c.banda)}</title></circle>`;
    }).join("");

    // media móvil de 50 candidatos: suaviza el ruido de la secuencia sin esconder la forma
    const VENTANA = 50;
    const puntosMedia = [];
    for (let i = 0; i < cands.length; i += 1) {
      const desde = Math.max(0, i - VENTANA + 1);
      const trozo = cands.slice(desde, i + 1);
      puntosMedia.push([cands[i].pos, trozo.reduce((a, c) => a + c.total, 0) / trozo.length]);
    }
    const linea = puntosMedia.map((pt, i) =>
      `${i ? "L" : "M"}${x(pt[0]).toFixed(1)},${y(pt[1]).toFixed(1)}`).join("");

    const grilla = [0, 25, 50, 75, 100].filter((v) => v >= dom.y0 && v <= dom.y1).map((v) =>
      `<line class="pf-grid" x1="${left}" x2="${left + iw}" y1="${y(v)}" y2="${y(v)}"/>`
      + `<text class="pf-tick" x="${left - 6}" y="${y(v) + 3}" text-anchor="end">${v}</text>`).join("");
    const marcasX = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const pos = Math.round(dom.x0 + f * (dom.x1 - dom.x0));
      return `<text class="pf-tick" x="${x(pos)}" y="${PERFIL_ALTO - 8}" text-anchor="middle">${entero(pos)}</text>`;
    }).join("");

    const mejor = cands.slice().sort((a, b) => b.total - a.total)[0];
    const mostrarMejor = mejor.pos >= dom.x0 && mejor.pos <= dom.x1;
    return `<figure class="perfil-fig" data-query="${esc(rec.query_name)}" data-idx="${idx}">
      <svg viewBox="0 0 ${PERFIL_ANCHO} ${PERFIL_ALTO}" role="img" tabindex="0"
           aria-label="Perfil de score por posición en ${esc(rec.query_name)}. Rueda para acercar, arrastrar para moverse, doble clic para ver todo.">
        ${grilla}${marcasX}
        <path class="pf-media" d="${linea}"/>
        ${puntos}
        ${mostrarMejor ? `<line class="pf-mejor" x1="${x(mejor.pos)}" x2="${x(mejor.pos)}"
              y1="${top}" y2="${top + ih}"/>
        <text class="pf-tag" x="${Math.min(Math.max(x(mejor.pos) + 4, left), PERFIL_ANCHO - 90)}" y="${top + 10}">
          mejor ${num(mejor.total, 1)}
        </text>` : ""}
      </svg>
      <figcaption>${esc(rec.query_name)} · ${entero(cands.length)} candidatos en
        ${entero(rec.gene?.longitud || 1)} nt · ventana ${entero(Math.round(dom.x0))}–${entero(Math.round(dom.x1))} nt
        (${visibles.length} a la vista) · mejor en ${entero(mejor.pos)} (${esc(mejor.id)})</figcaption>
    </figure>`;
  }).join("");

  cont.querySelectorAll("circle.pf").forEach((c) => {
    c.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const rec = state.results.records.find((r) => r.query_name === c.dataset.query);
      const cand = rec && rec.candidates.find((x) => x.id === c.dataset.id);
      if (cand) openCandidate(rec, cand);
    });
  });
  cont.querySelectorAll("figure.perfil-fig").forEach((fig) => {
    engancharZoom(fig);
  });
  const cap = $("#perfil-caption");
  if (cap) cap.textContent = "score de cada candidato a lo largo del transcrito";
  if (nota) nota.textContent = "rueda para acercar · arrastrá para moverte · doble clic para ver todo";
}

// Zoom y arrastre sobre el SVG. Se cambia el dominio visible y se redibuja: son ~5.000
// puntos, entra de sobra en un frame.
function engancharZoom(fig) {
  const svg = fig.querySelector("svg");
  const rec = state.results.records.find((r) => r.query_name === fig.dataset.query);
  if (!svg || !rec) return;
  const { left, right, top, bottom } = PERFIL_M;
  const ancho = PERFIL_ANCHO - left - right;
  const alto = PERFIL_ALTO - top - bottom;

  const aDominioX = (clientX) => {
    const caja = svg.getBoundingClientRect();
    const f = (clientX - caja.left) / caja.width;
    const dom = perfilDominio(rec);
    return dom.x0 + Math.max(0, Math.min(1, (f * PERFIL_ANCHO - left) / ancho)) * (dom.x1 - dom.x0);
  };

  svg.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const dom = perfilDominio(rec);
    const L = rec.gene?.longitud || 1;
    const factor = ev.deltaY > 0 ? 1.25 : 0.8;
    const centro = aDominioX(ev.clientX);
    let anchoNuevo = (dom.x1 - dom.x0) * factor;
    anchoNuevo = Math.max(20, Math.min(L, anchoNuevo));   // ni 20 nt ni más que el gen
    const prop = (centro - dom.x0) / Math.max(1e-9, dom.x1 - dom.x0);
    let x0 = centro - prop * anchoNuevo;
    x0 = Math.max(1, Math.min(L - anchoNuevo, x0));
    dom.x0 = x0;
    dom.x1 = x0 + anchoNuevo;

    // el eje Y se acompaña: si estás muy cerca, el rango se angosta alrededor del centro
    if (anchoNuevo < 400) {
      const rango = Math.max(15, 100 * anchoNuevo / 400);
      const medio = (dom.y0 + dom.y1) / 2;
      dom.y0 = Math.max(0, Math.max(0, medio - rango / 2));
      dom.y1 = Math.min(100, dom.y0 + rango);
      dom.y0 = Math.max(0, dom.y1 - rango);
    } else {
      dom.y0 = 0;
      dom.y1 = 100;
    }
    renderPerfil();
  }, { passive: false });

  let arrastre = null;
  svg.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    arrastre = { x: ev.clientX, y: ev.clientY, dom: { ...perfilDominio(rec) } };
    svg.setPointerCapture(ev.pointerId);
    svg.classList.add("arrastrando");
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!arrastre) return;
    const caja = svg.getBoundingClientRect();
    const dom = perfilDominio(rec);
    const L = rec.gene?.longitud || 1;
    const dx = (ev.clientX - arrastre.x) / caja.width * PERFIL_ANCHO / ancho * (arrastre.dom.x1 - arrastre.dom.x0);
    const dy = (ev.clientY - arrastre.y) / caja.height * PERFIL_ALTO / alto * (arrastre.dom.y1 - arrastre.dom.y0);
    const anchoDom = arrastre.dom.x1 - arrastre.dom.x0;
    let x0 = arrastre.dom.x0 - dx;
    x0 = Math.max(1, Math.min(L - anchoDom, x0));
    dom.x0 = x0;
    dom.x1 = x0 + anchoDom;
    const altoDom = arrastre.dom.y1 - arrastre.dom.y0;
    let y0 = arrastre.dom.y0 - dy;   // el contenido sigue al puntero
    y0 = Math.max(0, Math.min(100 - altoDom, y0));
    dom.y0 = y0;
    dom.y1 = y0 + altoDom;
    renderPerfil();
  });
  const soltar = () => { arrastre = null; svg.classList.remove("arrastrando"); };
  svg.addEventListener("pointerup", soltar);
  svg.addEventListener("pointercancel", soltar);
  svg.addEventListener("dblclick", () => {
    const L = rec.gene?.longitud || 1;
    perfilVista.set(rec.query_name, { x0: 1, x1: L, y0: 0, y1: 100 });
    renderPerfil();
  });
}

// Botones del encabezado: acercar, alejar y ver todo, sobre el gen visible.
function perfilZoom(factor) {
  const recs = recordsVisibles();
  if (!recs.length) return;
  for (const rec of recs) {
    const dom = perfilDominio(rec);
    const L = rec.gene?.longitud || 1;
    const centro = (dom.x0 + dom.x1) / 2;
    let anchoNuevo = (dom.x1 - dom.x0) * factor;
    anchoNuevo = Math.max(20, Math.min(L, anchoNuevo));
    let x0 = Math.max(1, Math.min(L - anchoNuevo, centro - anchoNuevo / 2));
    dom.x0 = x0;
    dom.x1 = x0 + anchoNuevo;
    dom.y0 = 0;
    dom.y1 = 100;
  }
  renderPerfil();
}

function perfilReset() {
  for (const rec of recordsVisibles()) {
    perfilVista.delete(rec.query_name);
  }
  renderPerfil();
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
