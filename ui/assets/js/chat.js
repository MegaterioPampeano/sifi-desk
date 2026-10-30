// Panel lateral del agente. En la maqueta habla con POST /agent/chat; en el
// producto, este mismo panel hospeda el adapter dsh del frente M4.
import { api } from "./api.js";
import { state } from "./state.js";
import { esc } from "./format.js";
import { renderMd } from "./md.js";
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
// La charla vive en el servidor: al cerrar la ventana no se pierde nada y se pueden
// tener varias conversaciones en paralelo (una por tema o por corrida).
let sesionActual = localStorage.getItem("sifi.sesion") || null;

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
  $("#chat-suggest-toggle").addEventListener("click", () => alternarSugerencias());
  $("#chat-expandir").addEventListener("click", () => alternarModoChat());
  $("#chat-buscar").addEventListener("input", (ev) => filtrarSesiones(ev.target.value));
  $("#cb-compactar").addEventListener("click", () => compactarSesion());
  $("#chat-plan").addEventListener("click", (ev) => {
    if (ev.target.closest("[data-plan-toggle]")) {
      $("#chat-plan").classList.toggle("plegado");
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && document.querySelector(".app.modo-chat")) {
      alternarModoChat(false);
    } else if (ev.key.toLowerCase() === "f" && ev.ctrlKey && ev.shiftKey) {
      ev.preventDefault();
      alternarModoChat();
    } else if (ev.key.toLowerCase() === "k" && ev.ctrlKey && !ev.shiftKey) {
      ev.preventDefault();
      alternarModoChat(true);
      $("#chat-input").focus();
    }
  });
  $("#chat-suggest").addEventListener("click", (ev) => {
    const chip = ev.target.closest("button[data-q]");
    if (chip) enviar(chip.dataset.q);
  });

  $("#chat-sesiones").addEventListener("change", (ev) => {
    const id = ev.target.value;
    if (id) abrirSesion(id);
    else nuevaSesion();
  });
  $("#chat-nueva").addEventListener("click", () => nuevaSesion());
  $("#chat-borrar").addEventListener("click", () => borrarSesion());

  $("#aprob-lista").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-aprob]");
    if (btn) resolverAprobacion(btn.dataset.id, btn.dataset.aprob === "1", btn);
  });
  cargarAprobaciones();
  // El agente puede encolar un pedido en cualquier momento (también desde otra
  // ventana), así que se refresca solo mientras la app está abierta.
  setInterval(() => { if (!document.hidden) cargarAprobaciones(); }, 20000);

  cargarSesiones().then(() => (sesionActual ? abrirSesion(sesionActual) : saludar()));
}

// Pedidos que quedaron esperando permiso: escribir fuera de la carpeta del agente.
// Antes se contestaban "no puedo" y quedaban muertos; ahora se aprueban con un botón.
async function cargarAprobaciones() {
  const caja = $("#aprobaciones");
  if (!caja) return;
  let items = [];
  try {
    const data = await api.aprobaciones();
    items = data.items || [];
  } catch {
    caja.classList.add("hidden");
    return;
  }
  const lista = $("#aprob-lista");
  if (!items.length) {
    caja.classList.add("hidden");
    lista.innerHTML = "";
    return;
  }
  caja.classList.remove("hidden");
  $("#aprob-titulo").textContent = items.length === 1
    ? "El agente pide permiso para 1 cosa"
    : `El agente pide permiso para ${items.length} cosas`;
  lista.innerHTML = items.map((it) => `
    <li class="aprob-item" data-id="${esc(it.id)}">
      <code class="aprob-cmd">${esc(it.cmd)}</code>
      <p class="aprob-motivo">${esc(it.motivo || "")}</p>
      <div class="aprob-botones">
        <button type="button" class="btn small primary" data-aprob="1" data-id="${esc(it.id)}">Aprobar</button>
        <button type="button" class="btn small ghost" data-aprob="0" data-id="${esc(it.id)}">Rechazar</button>
      </div>
    </li>`).join("");
}

async function resolverAprobacion(id, aprobar, btn) {
  if (btn) { btn.disabled = true; btn.textContent = aprobar ? "Ejecutando…" : "Rechazando…"; }
  try {
    const res = await api.resolverAprobacion(id, aprobar);
    const salida = (res.resultado && res.resultado.salida) || "";
    if (aprobar && salida) {
      burbuja("agent", `Ejecutado: ${salida}`);
    }
  } catch (err) {
    burbuja("agent", `No pude resolver el pedido: ${err.message || err}`);
  }
  cargarAprobaciones();
}

function saludar() {
  burbuja("agent", "Soy el agente de siFi. Puedo explicar un ranking, revisar off-target, bajar un transcriptoma, armar un panel o lanzar una corrida. Trabajo en mi carpeta (~/.sifidesk/agente) y cada comando que ejecuto aparece abajo, con su salida. Lo que no hago: tocar el código de la app.");
  sugerencias(INICIAL);
  actualizarContexto();
}

async function cargarSesiones() {
  const sel = $("#chat-sesiones");
  try {
    const data = await api.sesiones();
    const lista = data.sesiones || [];
    sel.innerHTML = `<option value="">Charla nueva</option>`;
    for (const s of lista) {
      const opt = document.createElement("option");
      opt.value = s.id;
      const fecha = s.actualizado ? new Date(s.actualizado * 1000) : null;
      const cuando = fecha && !isNaN(fecha) ? fecha.toLocaleDateString("es-AR", { day: "2-digit", month: "2-digit" }) : "";
      opt.textContent = `${s.titulo || "Charla"}${cuando ? " · " + cuando : ""}`;
      sel.appendChild(opt);
    }
    sel.value = sesionActual || "";
    return lista;
  } catch {
    return [];
  }
}

// Reabre una conversación guardada: se dibuja lo que pasó, sin volver a ejecutar nada.
async function abrirSesion(id) {
  try {
    const s = await api.sesion(id);
    sesionActual = s.id;
    localStorage.setItem("sifi.sesion", s.id);
    conversacion.length = 0;
    const log = $("#chat-log");
    log.innerHTML = "";
    for (const m of s.mensajes || []) {
      burbuja(m.role === "user" ? "user" : "agent", m.texto || "");
      conversacion.push({ role: m.role, content: m.texto || "" });
      if (Array.isArray(m.herramientas) && m.herramientas.length) {
        log.lastElementChild.appendChild(bloqueTools(m.herramientas));
      }
    }
    $("#chat-sesiones").value = s.id;
    log.scrollTop = log.scrollHeight;
    if (s.resumen) {
      const aviso = document.createElement("div");
      aviso.className = "msg agent";
      aviso.innerHTML = '<div class="who">resumen de lo anterior</div>'
        + `<details class="tools"><summary>compactado · ${s.resumen.length} caracteres</summary>`
        + `<div class="tool-body">${esc(s.resumen)}</div></details>`;
      log.insertBefore(aviso, log.firstChild);
    }
    renderPlan(s.plan);
    actualizarBarra();
  } catch {
    sesionActual = null;
    localStorage.removeItem("sifi.sesion");
    $("#chat-log").innerHTML = "";
    saludar();
  }
}

function nuevaSesion() {
  renderPlan(null);
  sesionActual = null;
  localStorage.removeItem("sifi.sesion");
  conversacion.length = 0;
  $("#chat-log").innerHTML = "";
  $("#chat-sesiones").value = "";
  saludar();
  $("#chat-input").focus();
}

async function borrarSesion() {
  if (!sesionActual) return;
  if (!confirm("¿Borrar esta conversación?")) return;
  try {
    await api.borrarSesion(sesionActual);
  } catch { /* si ya no está, da igual */ }
  nuevaSesion();
  cargarSesiones();
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
  if (st) st.textContent = "local";   // el elemento puede no existir en esta vista
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
  // Cronómetro mientras no llega el primer token; después el texto habla solo.
  const t0 = Date.now();
  const cron = setInterval(() => {
    const b = espera.querySelector(".bubble");
    if (!b || b.dataset.streaming) return;
    const seg = Math.round((Date.now() - t0) / 1000);
    b.innerHTML = `<span class="typing"><i></i><i></i><i></i></span>`
      + `<span class="espera-s">${seg}s</span>`;
  }, 1000);
  let vivo = "";
  let tarjetasVivas = 0;
  try {
    const res = await api.chatStream(msg, state.runId, historial(), sesionActual, {
      onEvento: (ev) => {
        const cuerpo = espera.querySelector(".bubble");
        if (ev.tipo === "delta" && cuerpo) {
          vivo += ev.texto;
          cuerpo.dataset.streaming = "1";
          cuerpo.innerHTML = renderMd(vivo) + `<span class="cursor" aria-hidden="true"></span>`;
          $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
        } else if (ev.tipo === "tool" && ev.tarjeta) {
          tarjetasVivas += 1;
          espera.appendChild(bloqueTools([ev.tarjeta]));
          $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
        }
      },
    });
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
    // Si las tarjetas ya se mostraron en vivo no se repiten; si no hubo streaming,
    // van acá como siempre.
    if (!tarjetasVivas && Array.isArray(res.tools) && res.tools.length) {
      const ultima = $("#chat-log").lastElementChild;
      ultima.appendChild(bloqueTools(res.tools));
      $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
    }
    if (res.sesion_id && res.sesion_id !== sesionActual) {
      sesionActual = res.sesion_id;
      localStorage.setItem("sifi.sesion", sesionActual);
      cargarSesiones();
    }
    if (Array.isArray(res.sugerencias) && res.sugerencias.length) sugerencias(res.sugerencias);
    if (res.compactado) {
      const b2 = burbuja("agent", `Contexto compactado: resumí ${res.compactado.turnos_resumidos} `
        + `turnos viejos y quedaron ${res.compactado.turnos_vivos} textuales.`);
      b2.classList.add("aviso");
    }
    renderPlan(res.plan);
    actualizarBarra();
    $("#chat-status").textContent = "local";
  } catch (err) {
    espera.remove();
    burbuja("agent", `No pude consultar al agente: ${err.message}`);
  } finally {
    clearInterval(cron);
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
    bubble.classList.add("md");
    bubble.innerHTML = renderMd(texto);
  }
  div.append(who, bubble);
  const log = $("#chat-log");
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

// Los pasos del agente van plegados: se ve cuántos fueron y se abren si interesan.
// Antes cada llamada se apilaba como tarjeta y tapaba la respuesta.
function bloqueTools(tools) {
  const fallos = tools.filter((t) => t.ok === false).length;
  const det = document.createElement("details");
  det.className = "tools";
  const resumen = document.createElement("summary");
  resumen.textContent = `${tools.length} paso${tools.length === 1 ? "" : "s"}`
    + (fallos ? ` · ${fallos} con error` : "");
  det.appendChild(resumen);
  for (const t of tools) det.appendChild(tarjetaTool(t));
  return det;
}

// Cada herramienta que usa el agente vuelve como tarjeta: se ve el comando exacto
// y su salida. Las salidas largas quedan plegadas para no tapar la conversación.
function tarjetaTool(t) {
  const div = document.createElement("div");
  div.className = `tool${t.ok === false ? " fail" : ""}`;
  const args = t.args && Object.keys(t.args).length ? JSON.stringify(t.args) : "";
  const salida = String(t.resultado || "(sin salida)");
  const ms = t.ms ? ` · ${t.ms} ms` : "";
  const head = document.createElement("div");
  head.className = "tool-head";
  head.innerHTML = `<span class="tname">${esc(t.nombre)}</span><span class="targs">${esc(args)}</span><span class="tms">${esc(ms)}</span>`;
  div.appendChild(head);
  if (salida.length > 420) {
    const det = document.createElement("details");
    det.innerHTML = `<summary>salida (${salida.length} caracteres)</summary><pre></pre>`;
    det.querySelector("pre").textContent = salida;
    det.className = "tool-body";
    div.appendChild(det);
  } else {
    const body = document.createElement("div");
    body.className = "tool-body";
    body.textContent = salida;
    div.appendChild(body);
  }
  return div;
}

// Las sugerencias se pueden apagar: a veces estorban abajo del chat. Queda en
// localStorage para que no vuelvan a aparecer en cada arranque.
const CLAVE_SUGERENCIAS = "sifi.sugerencias";

function sugerenciasVisibles() {
  return localStorage.getItem(CLAVE_SUGERENCIAS) !== "0";
}

function alternarSugerencias(forzar) {
  const cont = $("#chat-suggest");
  const boton = $("#chat-suggest-toggle");
  const visible = typeof forzar === "boolean" ? forzar : !sugerenciasVisibles();
  localStorage.setItem(CLAVE_SUGERENCIAS, visible ? "1" : "0");
  cont.classList.toggle("oculto", !visible);
  if (boton) {
    boton.setAttribute("aria-pressed", String(visible));
    boton.title = visible ? "Ocultar sugerencias" : "Mostrar sugerencias";
  }
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
  alternarSugerencias(sugerenciasVisibles());
}

// ---------------------------------------------------------------------------
// Modo pantalla completa (F4)
//
// El panel lateral queda para "consultar de reojo". Cuando hay que leer un informe,
// comparar ventanas o seguir una corrida larga, se pasa a pantalla completa: una sola
// columna centrada de 1040px, tipografía más grande, bloques de código y barra de
// contexto. La preferencia queda en localStorage.
const CLAVE_MODO = "sifi.chatmodo";

function alternarModoChat(forzar) {
  const app = document.querySelector(".app");
  if (!app) return;
  const activo = typeof forzar === "boolean" ? forzar : !app.classList.contains("modo-chat");
  app.classList.toggle("modo-chat", activo);
  localStorage.setItem(CLAVE_MODO, activo ? "1" : "0");
  const btn = $("#chat-expandir");
  if (btn) {
    btn.setAttribute("aria-pressed", String(activo));
    btn.title = activo ? "Volver al panel (Esc)" : "Pantalla completa (Ctrl+Mayús+F)";
  }
  if (activo) {
    $("#chat-barra").classList.remove("hidden");
    actualizarBarra();
    setTimeout(() => $("#chat-input").focus(), 60);
  } else {
    $("#chat-barra").classList.add("hidden");
  }
}

export function restaurarModoChat() {
  if (localStorage.getItem(CLAVE_MODO) === "1") alternarModoChat(true);
}

// ---------------------------------------------------------------------------
// Barra de contexto: modelo, tokens usados y memoria.
// Los tokens son una estimación (caracteres / 3,4) porque el proveedor no siempre
// devuelve usage en modo herramientas; sirve para ver la tendencia, no para auditar.
function acortar(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}

async function actualizarBarra() {
  const barra = $("#chat-barra");
  if (!barra || barra.classList.contains("hidden")) return;
  let est = null;
  try {
    est = await api.estadoAgente(sesionActual);
  } catch {
    est = null;
  }
  if (!est) {
    $("#cb-modelo").textContent = "sin datos";
    return;
  }
  $("#cb-modelo").textContent = est.modelo || "—";
  const usados = est.tokens_sesion || 0;
  const tope = est.presupuesto_tokens || 1;
  const pct = Math.min(100, Math.round((usados / tope) * 100));
  $("#cb-tokens").textContent = `contexto ${acortar(usados)} / ${acortar(tope)} (${pct}%)`;
  const fill = $("#cb-fill");
  fill.style.width = `${pct}%`;
  fill.classList.toggle("alerta", pct >= 75);
  const partes = [];
  if (est.turnos) partes.push(`${est.turnos} turnos`);
  if (est.resumen_chars) partes.push(`resumen ${acortar(est.resumen_chars)}`);
  const mem = est.memoria || {};
  const bytes = (mem.hot?.bytes || 0) + (mem.warm?.bytes || 0) + (mem.largo?.bytes || 0);
  if (bytes) partes.push(`memoria ${acortar(bytes)}B`);
  $("#cb-memoria").textContent = partes.join(" · ");
}

async function compactarSesion() {
  if (!sesionActual) {
    burbuja("agent", "Todavía no hay historial en esta charla: no hay nada que compactar.");
    return;
  }
  const btn = $("#cb-compactar");
  const previo = btn.textContent;
  btn.disabled = true;
  btn.textContent = "compactando…";
  try {
    const info = await api.compactar(sesionActual);
    if (info.ok) {
      burbuja("agent", `Listo: resumí ${info.turnos_resumidos} turnos y quedaron `
        + `${info.turnos_vivos} textuales (resumen de ${info.resumen_chars} caracteres).`);
      await abrirSesion(sesionActual);
    } else {
      burbuja("agent", info.detalle || "no se pudo compactar");
    }
  } catch (err) {
    burbuja("agent", `No pude compactar: ${err.message || err}`);
  } finally {
    btn.disabled = false;
    btn.textContent = previo;
    actualizarBarra();
  }
}

// ---------------------------------------------------------------------------
// Buscar dentro de las conversaciones guardadas: filtra las opciones del selector
// por título. Barato y suficiente para decenas de charlas.
function filtrarSesiones(termino) {
  const sel = $("#chat-sesiones");
  const t = String(termino || "").toLowerCase().trim();
  for (const opt of sel.options) {
    if (!opt.value) continue;
    opt.hidden = Boolean(t) && !opt.textContent.toLowerCase().includes(t);
  }
  const primera = Array.from(sel.options).find((o) => o.value && !o.hidden);
  if (primera && t) sel.value = primera.value;
}

// ---------------------------------------------------------------------------
// Plan de trabajo: la lista de pasos que el agente fija con la tool `plan`.
// Se ve arriba del log, plegable, con el avance. Es lo que evita que una tarea de
// seis pasos se pierda en el medio de la conversación.
const ICONOS = { hecho: "✓", en_curso: "◐", pendiente: "○", fallo: "✕" };

function renderPlan(plan) {
  const caja = $("#chat-plan");
  if (!caja) return;
  const pasos = (plan && plan.pasos) || [];
  if (!pasos.length) {
    caja.classList.add("hidden");
    caja.innerHTML = "";
    return;
  }
  const hechos = pasos.filter((p) => p.estado === "hecho").length;
  const fallos = pasos.filter((p) => p.estado === "fallo").length;
  caja.classList.remove("hidden");
  caja.innerHTML = `
    <div class="plan-head" data-plan-toggle role="button" tabindex="0"
         aria-label="Mostrar u ocultar el plan">
      <strong>plan</strong>
      <span class="plan-progreso">${hechos}/${pasos.length}${fallos ? ` · ${fallos} con problema` : ""}</span>
      <span class="plan-mas">${caja.classList.contains("plegado") ? "+" : "−"}</span>
    </div>
    ${plan.nota ? `<p class="plan-nota">${esc(plan.nota)}</p>` : ""}
    <ol class="plan-lista">
      ${pasos.map((p) => `<li class="p-${esc(p.estado || "pendiente")}">`
        + `<span class="p-ico" aria-hidden="true">${ICONOS[p.estado] || "○"}</span>`
        + `${esc(p.texto)}</li>`).join("")}
    </ol>`;
}
