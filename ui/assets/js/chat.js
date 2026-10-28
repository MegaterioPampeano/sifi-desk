// Panel lateral del agente. En la maqueta habla con POST /agent/chat; en el
// producto, este mismo panel hospeda el adapter dsh del frente M4.
import { api } from "./api.js";
import { state } from "./state.js";
import { esc } from "./format.js";
import { abrir as abrirAjustes } from "./ajustes.js";

const $ = (sel) => document.querySelector(sel);

const INICIAL = [
  "¿Cómo empiezo una corrida?",
  "¿Qué paneles elijo?",
  "¿Cómo se lee el desglose E/R/S/T/D?",
];

const CON_RESULTADOS = [
  "¿Cuál es el mejor candidato?",
  "¿Qué candidatos tienen off-target?",
  "¿Qué significa la banda «revisar»?",
];

let ocupado = false;
const conversacion = [];

// Últimos turnos, para que el agente no pierda el hilo entre preguntas.
function historial() {
  return conversacion.slice(-6);
}

export function initChat() {
  $("#chat-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    enviar($("#chat-input").value);
  });
  $("#chat-input").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      enviar($("#chat-input").value);
    }
  });
  $("#chat-suggest").addEventListener("click", (ev) => {
    const chip = ev.target.closest("button[data-q]");
    if (chip) enviar(chip.dataset.q);
  });

  burbuja("agent", "Soy el agente de siFi. Puedo explicar un ranking, revisar off-target o preparar el informe, siempre a partir del manifest de la corrida. Si algo no está en los datos, lo digo.");
  sugerencias(INICIAL);
  actualizarContexto();
}

export function actualizarContexto() {
  const chip = $("#chat-context");
  if (!chip) return;
  if (state.runId && state.results) {
    chip.textContent = `corrida ${String(state.runId).slice(0, 8)} · ${state.results.records.length} gen(es)`;
    sugerencias(CON_RESULTADOS);
  } else if (state.runId) {
    chip.textContent = `corrida ${String(state.runId).slice(0, 8)} · en curso`;
  } else {
    chip.textContent = "sin corrida activa";
  }
  const st = $("#chat-status");
  st.textContent = "local";
}

async function enviar(texto) {
  const msg = String(texto || "").trim();
  if (!msg || ocupado) return;
  $("#chat-input").value = "";
  burbuja("user", msg);
  conversacion.push({ role: "user", content: msg });
  ocupado = true;
  $("#chat-send").disabled = true;
  const espera = burbuja("agent", "…", true);
  try {
    const res = await api.chat(msg, state.runId, undefined, historial());
    espera.remove();
    const b = burbuja("agent", res.respuesta || "(sin respuesta)");
    conversacion.push({ role: "assistant", content: res.respuesta || "" });
    if (res.configurar) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn ghost";
      btn.textContent = "Abrir Ajustes";
      btn.addEventListener("click", abrirAjustes);
      b.lastElementChild.appendChild(btn);
    }
    if (Array.isArray(res.tools) && res.tools.length) {
      const ultima = $("#chat-log").lastElementChild;
      for (const t of res.tools) ultima.appendChild(tarjetaTool(t));
      $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
    }
    if (Array.isArray(res.sugerencias) && res.sugerencias.length) sugerencias(res.sugerencias);
    $("#chat-status").textContent = "local";
  } catch (err) {
    espera.remove();
    burbuja("agent", `No pude consultar al agente: ${err.message}`);
  } finally {
    ocupado = false;
    $("#chat-send").disabled = false;
    $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  }
}

function burbuja(quien, texto, escribiendo = false) {
  const div = document.createElement("div");
  div.className = `msg ${quien}`;
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = quien === "user" ? "vos" : "agente siFi";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (escribiendo) {
    bubble.innerHTML = `<span class="typing"><i></i><i></i><i></i></span>`;
    bubble.setAttribute("aria-label", "escribiendo");
  } else {
    bubble.textContent = texto;
  }
  div.append(who, bubble);
  const log = $("#chat-log");
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function tarjetaTool(t) {
  const div = document.createElement("div");
  div.className = "tool";
  div.innerHTML = `<div class="tool-head"><span class="tname">${esc(t.nombre)}</span><span>${esc(JSON.stringify(t.args || {}))}</span></div>
    <div class="tool-body">${esc(t.resultado || "")}</div>`;
  return div;
}

function sugerencias(lista) {
  const cont = $("#chat-suggest");
  cont.innerHTML = "";
  for (const q of lista) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.dataset.q = q;
    b.textContent = q;
    cont.appendChild(b);
  }
}
