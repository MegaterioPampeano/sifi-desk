// Arranque de la ventana: tema, navegación, servicio y cableado entre vistas.
import { api, setApiBase, ApiError } from "./api.js";
import { state, loadDraft, clearDraft } from "./state.js";
import { initWizard, setPanels, goStep } from "./wizard.js";
import { initProgress, followRun, stop as stopProgress } from "./progress.js";
import { initResults, showResults } from "./results.js";
import { initDetail } from "./detail.js";
import { initChat, actualizarContexto } from "./chat.js";
import { initNews, cargarNews } from "./news.js";
import { esc, fechaCorta, entero, num, ESTADOS } from "./format.js";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

// ------------------------------------------------------------------ tema
function initTema() {
  const guardado = localStorage.getItem("sifi.theme") || "auto";
  aplicarTema(guardado);
  $$("[data-theme-set]").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.themeSet === guardado);
    b.addEventListener("click", () => {
      const t = b.dataset.themeSet;
      localStorage.setItem("sifi.theme", t);
      aplicarTema(t);
      $$("[data-theme-set]").forEach((x) => x.classList.toggle("is-active", x === b));
    });
  });
}

function aplicarTema(t) {
  document.documentElement.dataset.theme = t;
}

// ------------------------------------------------------------------ navegación
function setView(nombre) {
  state.view = nombre;
  for (const v of ["wizard", "progress", "results", "runs", "news"]) {
    $(`#view-${v}`).classList.toggle("hidden", v !== nombre);
  }
  $$(".navlink").forEach((b) => b.classList.toggle("is-active", b.dataset.nav === nombre));
  $("#nav-results").disabled = !state.results;
  document.getElementById("main").scrollTop = 0;
}

function initNav() {
  $$(".navlink").forEach((b) => {
    b.addEventListener("click", () => {
      const v = b.dataset.nav;
      if (v === "results" && !state.results) return;
      if (v === "runs") cargarCorridas();
      if (v === "news") cargarNews();
      setView(v);
    });
  });
  $("#btn-new2").addEventListener("click", volverAlAsistente);
  $("#btn-refresh-runs").addEventListener("click", cargarCorridas);
  $("#chat-toggle").addEventListener("click", () => {
    const app = $(".app");
    app.classList.toggle("chat-closed");
    localStorage.setItem("sifi.chat", app.classList.contains("chat-closed") ? "closed" : "open");
  });
}

function volverAlAsistente() {
  stopProgress();
  state.runId = null;
  state.run = null;
  state.results = null;
  $("#nav-results").disabled = true;
  actualizarContexto();
  goStep(1);
  setView("wizard");
}

// ------------------------------------------------------------------ servicio
async function cargarSalud() {
  const svc = $("#svc");
  const txt = $("#svc-text");
  const banner = $("#svc-offline");
  try {
    const h = await api.health();
    svc.classList.remove("err");
    svc.classList.add("ok");
    txt.textContent = `${h.servicio || "sifid"} · ${h.modo || "local"}`;
    svc.title = `servicio ok · ${h.n_paneles ?? "—"} paneles · ${h.corridas ?? 0} corridas`;
    if (banner) banner.classList.add("hidden");
  } catch (err) {
    svc.classList.remove("ok");
    svc.classList.add("err");
    txt.textContent = "sin servicio";
    svc.title = err.message;
    if (banner) {
      banner.classList.remove("hidden");
      banner.innerHTML = `<strong>Sin servicio local.</strong> ${esc(err.message)}`;
    }
  }
}

async function cargarPaneles() {
  try {
    const paneles = await api.panels();
    setPanels(paneles || []);
  } catch (err) {
    $("#panel-grid").innerHTML = `<div class="readout-empty">No se pudo cargar la lista de paneles: ${esc(err.message)}</div>`;
    toast(err.message, true);
  }
}

// ------------------------------------------------------------------ corridas
async function lanzar(payload) {
  const btn = $("#btn-run");
  btn.disabled = true;
  try {
    const run = await api.createRun(payload);
    state.runId = run.id || run.run_id;
    state.run = run;
    state.results = null;
    $("#nav-results").disabled = true;
    clearDraft();
    setView("progress");
    actualizarContexto();
    followRun(run);
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function onRunDone(res) {
  const total = res.records.reduce((a, r) => a + r.candidates.length, 0);
  state.results = res;
  showResults(res);
  setView("results");
  actualizarContexto();
  toast(`Corrida terminada: ${entero(total)} candidato(s) en ${res.records.length} gen(es).`);
}

function onRunFail(run) {
  toast(run.status === "cancelled" ? "Corrida cancelada." : `La corrida falló: ${run.error || "sin detalle"}`, true);
  actualizarContexto();
}

async function cargarCorridas() {
  const cont = $("#runs-list");
  cont.innerHTML = `<div class="readout-empty">Consultando GET /runs…</div>`;
  try {
    const runs = (await api.runs()) || [];
    if (!runs.length) {
      cont.innerHTML = `<div class="readout-empty">No hay corridas todavía. Empezá por el asistente.</div>`;
      return;
    }
    cont.innerHTML = runs.map((r) => filaRun(r)).join("");
    cont.querySelectorAll("[data-run]").forEach((btn) => {
      btn.addEventListener("click", () => abrirCorrida(btn.dataset.run));
    });
  } catch (err) {
    cont.innerHTML = `<div class="readout-empty">No se pudo leer el historial: ${esc(err.message)}</div>`;
  }
}

function filaRun(r) {
  const st = r.status || "queued";
  const pct = r.progress?.pct ?? 0;
  const desc = [
    ((r.panels || []).map((p) => (typeof p === "string" ? p : p.nombre || p.id)).join(", ")) || "sin paneles",
    `${r.mode || "design"} · ${r.mismatches ?? "—"} mm`,
    r.query_path ? r.query_path.split(/[\\/]/).pop() : "",
    r.started_at ? fechaCorta(r.started_at) : "",
  ].filter(Boolean).join(" · ");
  const accion = st === "done" ? "Abrir" : st === "running" || st === "queued" ? "Seguir" : "Ver";
  return `<div class="run-row">
    <div><span class="status-pill ${st}">${ESTADOS[st] || st}</span></div>
    <div class="meta">
      <div class="rid">${esc(String(r.id || r.run_id).slice(0, 12))}</div>
      <div class="desc" title="${esc(desc)}">${desc}</div>
    </div>
    <div class="right">
      <span class="pct">${num(pct, 0)} %</span>
      <button type="button" class="btn ghost sm" data-run="${esc(r.id || r.run_id)}">${accion}</button>
    </div>
  </div>`;
}

async function abrirCorrida(id) {
  try {
    const run = await api.run(id);
    state.runId = id;
    state.run = run;
    actualizarContexto();
    if (run.status === "done") {
      const res = await api.results(id);
      state.results = res;
      showResults(res);
      setView("results");
    } else {
      setView("progress");
      followRun(run);
    }
  } catch (err) {
    toast(err.message, true);
  }
}

// ------------------------------------------------------------------ arranque
function initToasts() {
  document.addEventListener("sifi:toast", (ev) => {
    const { msg, err } = ev.detail || {};
    const t = document.createElement("div");
    t.className = `toast ${err ? "err" : ""}`;
    t.textContent = msg;
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), 5200);
  });
}

async function main() {
  initTema();
  initNav();
  initToasts();
  initWizard({ onRun: lanzar });
  initProgress({ onDone: onRunDone, onFail: onRunFail });
  initResults({ onNewRun: volverAlAsistente });
  initDetail();
  initChat();
  initNews();

  const chatPref = localStorage.getItem("sifi.chat");
  if (chatPref === "closed" || (!chatPref && window.innerWidth < 980)) {
    $(".app").classList.add("chat-closed");
  }

  loadDraft();
  await cargarSalud();
  await cargarPaneles();
  setView("wizard");
  goStep(1);
  actualizarContexto();

  setInterval(cargarSalud, 30000);
}

main();
