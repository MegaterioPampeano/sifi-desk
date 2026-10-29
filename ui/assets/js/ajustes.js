// Ajustes de la aplicación. Hoy sólo el proveedor del modelo (clave, modelo, endpoint),
// pero el diálogo está pensado para crecer: cada bloque es independiente y guarda solo.
import { api } from "./api.js";
import { esc } from "./format.js";

const $ = (sel) => document.querySelector(sel);
let cargado = false;

export function initAjustes() {
  $("#settings-toggle").addEventListener("click", abrir);
  $("#settings-close").addEventListener("click", cerrar);
  $("#settings-modal").addEventListener("click", (ev) => {
    if (ev.target.id === "settings-modal") cerrar();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !$("#settings-modal").classList.contains("hidden")) cerrar();
  });
  $("#llm-save").addEventListener("click", guardar);
  $("#llm-test").addEventListener("click", probar);
  $("#llm-clear").addEventListener("click", borrar);
  $("#llm-key").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); guardar(); }
  });
  // enlace directo: ?ajustes=1 abre el diálogo al cargar (lo usa también el agente
  // cuando contesta "configurá la clave")
  if (new URLSearchParams(location.search).has("ajustes")) abrir();
}

export function abrir() {
  $("#settings-modal").classList.remove("hidden");
  if (!cargado) refrescar();
  setTimeout(() => $("#llm-key").focus(), 30);
}

function cerrar() {
  $("#settings-modal").classList.add("hidden");
}

function estado(msg = "", err = false) {
  const el = $("#llm-estado");
  el.textContent = msg;
  el.classList.toggle("err", !!err);
}

async function refrescar() {
  try {
    const st = await api.ajustes();
    cargado = true;
    pintar(st);
  } catch (err) {
    estado(`No pude leer los ajustes: ${err.message}`, true);
  }
}

function pintar(st) {
  $("#llm-key").value = "";
  $("#llm-modelo").value = st.modelo || "deepseek-flash";
  $("#llm-base").value = st.base_url || "";
  const chip = $("#llm-chip");
  if (st.configurada) {
    chip.textContent = `clave cargada ${st.pista || ""} · ${st.largo} caracteres · origen: ${st.origen}`;
    chip.classList.remove("off");
  } else {
    chip.textContent = "sin clave: el agente del panel lateral no puede responder";
    chip.classList.add("off");
  }
  $("#llm-key").placeholder = st.configurada ? "pegá una nueva para reemplazarla" : "sk-…";
  estado(st.editable === false
    ? `Hay una clave puesta por variable de entorno: no se edita desde acá. Archivo: ${st.archivo}`
    : `Se guarda en ${st.archivo} con permisos 600.`, st.editable === false);
}

async function guardar() {
  const api_key = $("#llm-key").value.trim();
  if (!api_key) { estado("Pegá la clave primero.", true); return; }
  const body = { api_key, modelo: $("#llm-modelo").value.trim() || "deepseek-flash" };
  const base = $("#llm-base").value.trim();
  if (base) body.base_url = base;
  estado("Guardando…");
  try {
    const st = await api.guardarAjustes(body);
    pintar(st);
    estado("Guardada. Probando contra el proveedor…");
    const t = await api.probarAjustes();
    estado(t.ok
      ? `Listo: el proveedor respondió en ${t.ms} ms (${t.modelo}).`
      : `Guardada, pero la prueba falló: ${t.detalle}`, !t.ok);
  } catch (err) {
    estado(err.message, true);
  }
}

async function probar() {
  estado("Probando…");
  try {
    const t = await api.probarAjustes();
    estado(t.ok ? `Responde bien (${t.ms} ms, ${t.modelo}).` : `Falló: ${t.detalle}`, !t.ok);
  } catch (err) {
    estado(err.message, true);
  }
}

async function borrar() {
  if (!confirm("¿Borrar la clave guardada? El agente deja de responder hasta que pongas otra.")) return;
  try {
    pintar(await api.borrarAjustes());
    estado("Clave borrada.");
  } catch (err) {
    estado(err.message, true);
  }
}
