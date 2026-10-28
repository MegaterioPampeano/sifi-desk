// Pantalla de progreso: polling real contra GET /runs/{id}.
// Nada de spinner infinito: se muestra etapa, avance y el registro del servicio.
import { api } from "./api.js";
import { state } from "./state.js";
import { esc, elapsed, num, ESTADOS } from "./format.js";

const $ = (sel) => document.querySelector(sel);

let timer = null;
let abort = null;
let onDone = null;
let onFail = null;
let fallos = 0;

export function initProgress({ onDone: done, onFail: fail }) {
  onDone = done;
  onFail = fail;
  $("#btn-cancel").addEventListener("click", cancelar);
}

export async function followRun(run) {
  stop();
  fallos = 0;
  state.runId = run.id || run.run_id;
  state.run = run;
  resetVista(run);
  if (run.status === "done") {
    await terminar();
    return;
  }
  loop();
}

function resetVista(run) {
  $("#prog-title").textContent = titulo(run.status);
  $("#prog-sub").textContent = run.query_path
    ? `Consulta ${run.query_path}`
    : "Consultando el estado del servicio.";
  $("#prog-id").textContent = state.runId ? String(state.runId).slice(0, 12) : "—";
  $("#prog-log").textContent = "";
  $("#prog-elapsed").textContent = "00:00";
  pintar(run);
}

function titulo(status) {
  return {
    queued: "En cola",
    running: "Corriendo",
    done: "Terminada",
    cancelled: "Cancelada",
    error: "Con error",
  }[status] || "Corrida";
}

function pintar(run) {
  const st = run.status || "queued";
  const pill = $("#prog-status");
  pill.textContent = ESTADOS[st] || st;
  pill.className = `status-pill ${st}`;
  const pct = Math.max(0, Math.min(100, Number(run.progress?.pct ?? 0)));
  const bar = $("#prog-bar");
  bar.setAttribute("aria-valuenow", String(pct));
  bar.querySelector("span").style.width = `${pct}%`;
  $("#prog-pct").textContent = `${num(pct, 0)} %`;
  $("#prog-stage").textContent = run.stage || "—";
  const done = run.progress?.done ?? 0;
  const total = run.progress?.total ?? 0;
  $("#prog-count").textContent = `${done} / ${total}`;
  $("#prog-panels").textContent = (run.panels && run.panels.length) ? run.panels.join(", ") : "—";
  $("#prog-elapsed").textContent = elapsed(run.started_at, run.finished_at);
  $("#prog-title").textContent = titulo(st);
  if (Array.isArray(run.log)) {
    const pre = $("#prog-log");
    const pegado = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 24;
    pre.innerHTML = run.log.map((l) => {
      const hora = String(l.t || "").slice(11, 19);
      return `<span class="mono">${esc(hora)}</span>  ${esc(l.linea)}`;
    }).join("\n");
    if (pegado) pre.scrollTop = pre.scrollHeight;
  }
  $("#btn-cancel").disabled = !["queued", "running"].includes(st);
  if (run.error) {
    $("#prog-sub").textContent = run.error;
    $("#prog-sub").style.color = "var(--bad)";
  } else {
    $("#prog-sub").style.color = "";
  }
}

function loop() {
  stop();
  timer = setTimeout(tick, 850);
}

async function tick() {
  if (!state.runId) return;
  abort = new AbortController();
  try {
    const run = await api.run(state.runId, abort.signal);
    fallos = 0;
    state.run = run;
    pintar(run);
    if (run.status === "done") {
      await terminar();
      return;
    }
    if (run.status === "cancelled" || run.status === "error") {
      onFail && onFail(run);
      return;
    }
    loop();
  } catch (err) {
    if (err.name === "AbortError") return;
    fallos += 1;
    if (fallos >= 4) {
      $("#prog-sub").textContent = `No se pudo consultar el estado: ${err.message}`;
      $("#prog-sub").style.color = "var(--bad)";
      return;
    }
    loop();
  }
}

async function terminar() {
  try {
    const res = await api.results(state.runId);
    onDone && onDone(res);
  } catch (err) {
    $("#prog-sub").textContent = `La corrida terminó pero no se pudieron leer los resultados: ${err.message}`;
    $("#prog-sub").style.color = "var(--bad)";
  }
}

async function cancelar() {
  if (!state.runId) return;
  const btn = $("#btn-cancel");
  btn.disabled = true;
  try {
    await api.cancelRun(state.runId);
    $("#prog-stage").textContent = "cancelando…";
    loop();
  } catch (err) {
    btn.disabled = false;
    document.dispatchEvent(new CustomEvent("sifi:toast", { detail: { msg: err.message, err: true } }));
  }
}

export function stop() {
  if (timer) clearTimeout(timer);
  timer = null;
  if (abort) abort.abort();
  abort = null;
}
