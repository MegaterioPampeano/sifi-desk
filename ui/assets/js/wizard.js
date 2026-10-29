// Asistente de 4 pasos: paneles → secuencia → parámetros → correr.
import { state, saveDraft, selectedPanels, parseFasta, queryPath } from "./state.js";
import { DEMO_FASTA } from "./demo.js";
import { esc, num, roleLabel, gc } from "./format.js";
import { api } from "./api.js";
import { toast } from "./toast.js";

let onRun = null;
let maxStep = 1;

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function initWizard({ onRun: cb }) {
  onRun = cb;

  $("#panel-grid").addEventListener("click", (ev) => {
    if (ev.target.closest(".panel-rol")) return;   // el select no marca el panel
    const card = ev.target.closest(".panel-card");
    if (!card) return;
    togglePanel(card.dataset.id);
  });
  $("#panel-grid").addEventListener("change", async (ev) => {
    const sel = ev.target.closest(".panel-rol");
    if (!sel) return;
    ev.preventDefault();
    try {
      await api.cambiarRolPanel(sel.dataset.id, sel.value);
      toast(`Rol de ${sel.dataset.id}: ${roleLabel(sel.value)}`);
      await cargarPaneles();
    } catch (err) {
      toast(err.message, true);
    }
  });
  $("#panel-grid").addEventListener("change", (ev) => {
    const card = ev.target.closest(".panel-card");
    if (!card) return;
    togglePanel(card.dataset.id, ev.target.checked);
  });

  $("#panels-min").addEventListener("click", () => {
    state.selected = new Set(["dalbulus_maidis", "maiz"]);
    afterPanels();
  });
  $("#panels-all").addEventListener("click", () => {
    state.selected = new Set(state.panels.map((p) => p.id));
    afterPanels();
  });
  $("#panels-none").addEventListener("click", () => {
    state.selected = new Set();
    afterPanels();
  });

  $("#steps").addEventListener("click", (ev) => {
    const li = ev.target.closest(".step");
    if (!li) return;
    const n = Number(li.dataset.step);
    if (n <= maxStep) goStep(n);
  });

  $$("[data-go]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const n = Number(btn.dataset.go);
      if (n > state.step && !validateStep(state.step)) return;
      goStep(n);
    });
  });

  // secuencia
  $("#seq-input").addEventListener("input", debounce(() => {
    state.fastaText = $("#seq-input").value;
    state.origin = "paste";
    state.fileName = "";
    reparse();
  }, 180));

  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      setOrigin(tab.dataset.origin);
    });
  });

  const file = $("#seq-file");
  file.addEventListener("change", () => {
    const f = file.files && file.files[0];
    if (f) leerArchivo(f);
  });
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((evt) => dz.addEventListener(evt, (e) => {
    e.preventDefault();
    dz.classList.add("is-over");
  }));
  ["dragleave", "drop"].forEach((evt) => dz.addEventListener(evt, (e) => {
    e.preventDefault();
    dz.classList.remove("is-over");
  }));
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) leerArchivo(f);
  });

  $("#load-demo").addEventListener("click", () => {
    state.fastaText = DEMO_FASTA;
    state.fileName = "";
    $("#seq-input").value = DEMO_FASTA;
    setOrigin("paste");
    reparse();
  });
  $("#clear-seq").addEventListener("click", () => {
    state.fastaText = "";
    state.fileName = "";
    $("#seq-input").value = "";
    $("#file-name").textContent = "";
    $("#seq-file").value = "";
    reparse();
  });

  // parámetros
  bindField("#p-size", "size");
  bindField("#p-mismatches", "mismatches");
  bindField("#p-mode", "mode");
  $("#p-main").addEventListener("input", () => {
    state.params.main = $("#p-main").value.trim();
    renderReview();
    saveDraft();
  });

  $("#btn-run").addEventListener("click", () => {
    if (!validateStep(1) || !validateStep(2)) return;
    const payload = {
      query_path: queryPath(),
      panel_ids: [...state.selected],
      mode: state.params.mode,
      mismatches: Number(state.params.mismatches),
      main_target: state.params.main || null,
      // extensiones documentadas de la maqueta (el servicio real sólo usa query_path)
      query_text: state.fastaText,
      genes: state.parsed.map((r) => r.id),
      sirna_size: Number(state.params.size),
    };
    onRun(payload);
  });

  restoreFields();
}

function restoreFields() {
  $("#p-size").value = state.params.size;
  $("#p-mismatches").value = state.params.mismatches;
  $("#p-mode").value = state.params.mode;
  $("#p-main").value = state.params.main || "";
  $("#seq-input").value = state.fastaText || "";
  setOrigin(state.origin, false);
  reparse();
}

function bindField(sel, key) {
  const el = $(sel);
  el.addEventListener("change", () => {
    state.params[key] = el.value;
    renderParamsPanels();
    renderReview();
    saveDraft();
  });
}

export function setPanels(panels) {
  state.panels = panels;
  // por defecto, el mínimo recomendado
  if (state.selected.size === 0 && panels.length) {
    state.selected = new Set(["dalbulus_maidis", "maiz"].filter((id) => panels.some((p) => p.id === id)));
  }
  renderPanels();
  renderParamsPanels();
  renderReview();
}

function togglePanel(id, forzar) {
  const on = forzar === undefined ? !state.selected.has(id) : forzar;
  if (on) state.selected.add(id);
  else state.selected.delete(id);
  afterPanels();
}

function afterPanels() {
  renderPanels();
  renderParamsPanels();
  renderReview();
  saveDraft();
  updateFoot();
}

function renderPanels() {
  const grid = $("#panel-grid");
  if (!state.panels.length) {
    grid.innerHTML = `<div class="readout-empty">No hay paneles cargados. Revisá GET /panels del servicio.</div>`;
    return;
  }
  grid.innerHTML = state.panels.map((p) => {
    const on = state.selected.has(p.id);
    return `
      <label class="panel-card ${on ? "is-on" : ""}" data-id="${esc(p.id)}">
        <input type="checkbox" ${on ? "checked" : ""} aria-label="Panel ${esc(p.nombre)}">
        <span class="panel-check" aria-hidden="true">
          <svg viewBox="0 0 16 16" width="11" height="11"><path d="m3 8.5 3 3 7-7" fill="none" stroke="currentColor" stroke-width="2"/></svg>
        </span>
        <span class="panel-main">
          <span class="panel-title">
            <strong>${esc(p.nombre)}</strong>
            <span class="role role-${esc(p.rol)}">${roleLabel(p.rol)}</span>
            <span class="ver">v${esc(p.version)}</span>
          </span>
          <span class="panel-sub">${esc(p.titulo)}</span>
          <span class="panel-desc">${esc(p.descripcion)}</span>
          <span class="panel-rol-row">
            <label>rol
              <select class="panel-rol" data-id="${esc(p.id)}" aria-label="Rol de ${esc(p.nombre)}">
                ${["blanco", "no_blanco", "patogeno", "simbionte", "control", "universal"].map((r) =>
                  `<option value="${r}" ${r === p.rol ? "selected" : ""}>${roleLabel(r)}</option>`).join("")}
              </select>
            </label>
          </span>
          <span class="panel-meta"><span>${Number(p.n_seqs).toLocaleString("es-AR")} secuencias</span><span>${esc(p.tamano)}</span><span>${esc(p.sha256.slice(0, 10))}</span></span>
        </span>
      </label>`;
  }).join("");
  updateFoot();
}

function updateFoot() {
  const n = state.selected.size;
  const roles = selectedPanels().map((p) => roleLabel(p.rol));
  const rolesset = [...new Set(roles)];
  $("#panels-note").textContent = n
    ? `${n} panel(es): ${rolesset.join(", ")}`
    : "Elegí al menos un panel para continuar";
  $("#btn-step1").disabled = n === 0;
}

function renderParamsPanels() {
  const cont = $("#params-panels");
  const sel = selectedPanels();
  cont.innerHTML = sel.length
    ? sel.map((p) => `<span class="chip tag">${esc(p.nombre)} <span class="role role-${esc(p.rol)}">${roleLabel(p.rol)}</span></span>`).join("")
    : `<span class="readout-empty">sin paneles</span>`;
  const genes = state.parsed.length;
  const nt = state.parsed.reduce((a, r) => a + r.length, 0);
  $("#params-note").textContent = genes
    ? `${genes} registro(s) · ${nt.toLocaleString("es-AR")} nt · ${sel.length} panel(es)`
    : "Falta la secuencia";
}

// --- secuencia --------------------------------------------------------------

function setOrigin(origin, conFoco = true) {
  state.origin = origin;
  $$(".tab").forEach((t) => {
    const on = t.dataset.origin === origin;
    t.classList.toggle("is-active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  $$("[data-origin-pane]").forEach((p) => {
    p.classList.toggle("hidden", p.dataset.originPane !== origin);
  });
  if (conFoco) {
    if (origin === "paste") $("#seq-input").focus();
    else $("#dropzone").focus();
  }
  saveDraft();
}

function leerArchivo(f) {
  const reader = new FileReader();
  reader.onload = () => {
    const texto = String(reader.result || "");
    state.fastaText = texto;
    state.fileName = f.name;
    $("#seq-input").value = "";
    $("#file-name").textContent = `${f.name} · ${(f.size / 1024).toFixed(1)} KB`;
    reparse();
  };
  reader.onerror = () => {
    $("#file-name").textContent = `No se pudo leer ${f.name}`;
  };
  reader.readAsText(f, "utf-8");
}

function reparse() {
  const { registros, errores } = parseFasta(state.fastaText);
  state.parsed = registros;
  renderReadout(errores);
  renderParamsPanels();
  renderReview();
  updateFoot();
  saveDraft();
}

function renderReadout(errores) {
  const box = $("#seq-readout");
  if (!state.parsed.length) {
    box.innerHTML = `<div class="readout-empty">${state.fastaText.trim() ? "No se pudo interpretar la secuencia." : "Todavía no hay secuencia."}</div>`;
    $("#btn-step2").disabled = true;
    return;
  }
  const filas = state.parsed.map((r) => {
    const aviso = r.length < 100
      ? `<span class="warn">· corta (pocas ventanas de 21 nt)</span>`
      : `<span class="ok">· ok</span>`;
    const raro = /[^ACGT]/.test(r.seq) ? `<span class="warn">· bases ambiguas</span>` : "";
    return `<div class="readout-row">
      <span class="rid">${esc(r.id)}</span>
      <span class="metrics">${r.length.toLocaleString("es-AR")} nt · GC ${num(r.gc, 1)} %</span>
      <span class="metrics">${aviso} ${raro}</span>
    </div>`;
  }).join("");
  const total = state.parsed.reduce((a, r) => a + r.length, 0);
  const media = gc(state.parsed.map((r) => r.seq).join(""));
  const problemas = errores.length
    ? `<div class="readout-sum" style="color:var(--bad)">${errores.map(esc).join(" · ")}</div>`
    : "";
  box.innerHTML = `<div class="readout-list">${filas}</div>
    <div class="readout-sum">${state.parsed.length} registro(s) · ${total.toLocaleString("es-AR")} nt en total · GC medio ${num(media, 1)} %</div>${problemas}`;
  const valido = state.parsed.length > 0 && state.parsed.every((r) => r.length >= 21) && errores.length === 0;
  $("#btn-step2").disabled = !valido;
}

// --- revisión ---------------------------------------------------------------

function renderReview() {
  const sel = selectedPanels();
  const total = state.parsed.reduce((a, r) => a + r.length, 0);
  const rows = [
    ["Consulta", state.fileName
      ? `<span class="mono">${esc(state.fileName)}</span>`
      : `${state.parsed.length} registro(s) · ${total.toLocaleString("es-AR")} nt ${state.parsed.length ? `<span class="mono">(${esc(state.parsed.map((r) => r.id).join(", "))})</span>` : ""}`],
    ["Paneles", sel.length ? sel.map((p) => `${esc(p.nombre)} <span class="role role-${esc(p.rol)}">${roleLabel(p.rol)}</span>`).join(" · ") : "<span style='color:var(--bad)'>ninguno</span>"],
    ["Largo del siRNA", `${esc(state.params.size)} nt`],
    ["Mismatches", `${esc(state.params.mismatches)} (bowtie -v)`],
    ["Modo", `<span class="mono">${esc(state.params.mode)}</span>`],
    ["Main target", state.params.main ? `<span class="mono">${esc(state.params.main)}</span>` : "<span class='muted'>automático (primer registro)</span>"],
    ["Scoring", `v2 · E 40 · R 15 · S 15 · T 15 · D 15`],
  ];
  $("#review").innerHTML = rows.map(([k, v]) => `
    <div class="review-row"><span class="k">${k}</span><span class="v">${v}</span></div>`).join("");
  const ok = sel.length > 0 && state.parsed.length > 0;
  $("#btn-run").disabled = !ok;
}

// --- pasos ------------------------------------------------------------------

export function goStep(n) {
  state.step = n;
  maxStep = Math.max(maxStep, n);
  $$(".panel-step").forEach((p) => p.classList.toggle("hidden", Number(p.dataset.pane) !== n));
  $$("#steps .step").forEach((li) => {
    const s = Number(li.dataset.step);
    li.classList.toggle("is-active", s === n);
    li.classList.toggle("is-done", s < n);
  });
  if (n === 3) renderParamsPanels();
  if (n === 4) renderReview();
  saveDraft();
  document.getElementById("main").scrollTo({ top: 0, behavior: "smooth" });
}

function validateStep(n) {
  if (n === 1 && state.selected.size === 0) {
    toast("Elegí al menos un panel.", true);
    return false;
  }
  if (n === 2) {
    if (!state.parsed.length) {
      toast("Falta la secuencia de entrada.", true);
      return false;
    }
    if (state.parsed.some((r) => r.length < 21)) {
      toast("Hay secuencias más cortas que un siRNA.", true);
      return false;
    }
  }
  return true;
}

// --------------------------------------------------------------------------

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

