// Panel de detalle de un candidato: secuencia en contexto, desglose E/R/S/T/D y hits.
import { esc, num, entero, bandLabel, bandClass, EJES, roleLabel, detalleTexto } from "./format.js";

const $ = (sel) => document.querySelector(sel);
let actual = null;

export function initDetail() {
  $("#d-close").addEventListener("click", closeDetail);
  $("#drawer-scrim").addEventListener("click", closeDetail);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !$("#detail").classList.contains("hidden")) closeDetail();
  });
  $("#d-copy").addEventListener("click", copiar);
  $("#d-focus").addEventListener("click", () => {
    if (!actual) return;
    const { cand, rec } = actual;
    closeDetail();
    const tick = document.querySelector(`#gene-map .map-tick[data-id="${cssEscape(cand.id)}"][data-query="${cssEscape(rec.query_name)}"]`);
    if (tick) {
      tick.scrollIntoView({ behavior: "smooth", block: "center" });
      tick.classList.add("is-active");
      setTimeout(() => tick.classList.remove("is-active"), 1800);
    }
  });
}

export function openDetail(rec, cand) {
  actual = { rec, cand };
  $("#d-title").textContent = cand.id;
  $("#d-body").innerHTML = cuerpo(rec, cand);
  $("#detail").classList.remove("hidden");
  $("#drawer-scrim").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  $("#d-close").focus({ preventScroll: true });
}

export function closeDetail() {
  $("#detail").classList.add("hidden");
  $("#drawer-scrim").classList.add("hidden");
  document.body.style.overflow = "";
  actual = null;
  document.querySelectorAll("#cand-body tr.is-active").forEach((tr) => tr.classList.remove("is-active"));
}

function cuerpo(rec, cand) {
  const gene = rec.gene || {};
  const seq = gene.secuencia || "";
  const pos = Number(cand.pos) || 1;
  const ctx = seq ? {
    antes: seq.slice(Math.max(0, pos - 13), pos - 1),
    foco: seq.slice(pos - 1, pos - 1 + (cand.seq || "").length),
    despues: seq.slice(pos - 1 + (cand.seq || "").length, pos - 1 + (cand.seq || "").length + 12),
  } : null;

  const items = [
    ["Gen", `<span class="mono">${esc(rec.query_name)}</span>`],
    ["Posición", entero(cand.pos)],
    ["Hebra", `<span class="mono">${esc(cand.strand || "+")}</span>`],
    ["ΔG", cand.dg === null || cand.dg === undefined ? "—" : `${num(cand.dg, 2)} <span>kcal/mol</span>`],
    ["Accesibilidad", cand.acc === null || cand.acc === undefined ? "—" : num(cand.acc, 2)],
    ["GC", cand.gc === null || cand.gc === undefined ? "—" : `${num(cand.gc, 1)} <span>%</span>`],
    ["Eficiente (siFi)", cand.efficient === null || cand.efficient === undefined ? "—" : (cand.efficient ? "sí" : "no")],
    ["Score siFi", cand.sifi_score === null || cand.sifi_score === undefined ? "—" : num(cand.sifi_score, 2)],
    ["Estabilidad de extremo", cand.end_stability === null || cand.end_stability === undefined ? "—" : (cand.end_stability ? "sí" : "no")],
    ["Selección de hebra", cand.strand_selection === null || cand.strand_selection === undefined ? "—" : (cand.strand_selection ? "sí" : "no")],
    ["Hits", entero(cand.n_hits ?? 0)],
    ["Banda", `<span class="band ${bandClass(cand.banda)}">${bandLabel(cand.banda)}</span>`],
  ];

  const ejes = ["E", "R", "S", "T", "D"].map((e) => {
    const d = cand.desglose?.[e];
    if (!d) return `<tr><td class="eje">${e}</td><td colspan="4" class="d-empty">sin dato</td></tr>`;
    const detalle = Object.entries(d.detalle || {}).map(([k, v]) => detalleTexto(k, v)).join(" · ");
    return `<tr>
      <td class="eje" title="${EJES[e]}">${e}</td>
      <td class="num">${num(d.valor, 3)}</td>
      <td class="num">${num(d.peso, 0)}</td>
      <td class="num">${num(d.aporte, 2)}</td>
      <td class="det">${esc(detalle)}</td>
    </tr>`;
  }).join("");

  const hits = (cand.hits || []).slice().sort((a, b) => (a.mismatch ?? 9) - (b.mismatch ?? 9) || String(a.panel).localeCompare(String(b.panel)));
  const hitsHtml = hits.length ? `
    <table class="hits">
      <thead><tr><th>Panel</th><th>Rol</th><th>Hit</th><th class="num">Mismatch</th><th class="num">Pos.</th><th>Hebra</th></tr></thead>
      <tbody>${hits.map((h) => `<tr class="${h.mismatch === 0 ? "mm0" : h.mismatch === 1 ? "mm1" : ""}">
        <td>${esc(h.panel_nombre || h.panel)}</td>
        <td><span class="role role-${esc(h.rol || "desconocido")}">${roleLabel(h.rol)}</span></td>
        <td class="mono">${esc(h.seq_id)}</td>
        <td class="num">${h.mismatch ?? "—"}</td>
        <td class="num">${entero(h.pos)}</td>
        <td class="mono">${esc(h.strand || "")}</td>
      </tr>`).join("")}</tbody>
    </table>` : `<p class="d-empty">Sin hits fuera del panel blanco. R = 1,00 y S = 1,00: no hay evidencia de off-target en los paneles elegidos.</p>`;

  const notas = (cand.notas || []).length
    ? `<div class="notas">${cand.notas.map((n) => `<span class="nota ${n.includes("riesgo") || n.includes("hit_perfecto") ? "warn" : ""}">${esc(n)}</span>`).join("")}</div>`
    : `<span class="d-empty">Sin observaciones del scoring.</span>`;

  return `
    <div class="d-top">
      <div class="d-total">${num(cand.total, 1)}<small> / 100</small></div>
      <span class="band ${bandClass(cand.banda)}">${bandLabel(cand.banda)}</span>
      <span class="muted small">${esc(gene.nombre || "")}</span>
    </div>

    <div class="d-seq">
      <div class="ctx">${ctx ? `${esc(ctx.antes)}<mark>${esc(ctx.foco || cand.seq)}</mark>${esc(ctx.despues)}` : `<mark>${esc(cand.seq || "")}</mark>`}</div>
      <div class="legend">ventana de ${(cand.seq || "").length} nt en la posición ${entero(cand.pos)}${ctx ? " · 12 nt de contexto a cada lado" : ""}</div>
    </div>

    <div class="d-grid">
      ${items.map(([k, v]) => `<div class="item"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("")}
    </div>

    <div class="d-sec">
      <h3>Desglose del score <small>total = Σ peso × valor</small></h3>
      <table class="axis">
        <thead><tr><th></th><th class="num">Valor</th><th class="num">Peso</th><th class="num">Aporte</th><th>Detalle</th></tr></thead>
        <tbody>
          ${ejes}
          <tr class="total"><td class="eje">Σ</td><td></td><td class="num">100</td><td class="num">${num(cand.total, 2)}</td><td class="det">total redondeado a dos decimales</td></tr>
        </tbody>
      </table>
    </div>

    <div class="d-sec">
      <h3>Hits por panel <small>${hits.length} registro(s)</small></h3>
      ${hitsHtml}
    </div>

    <div class="d-sec">
      <h3>Observaciones</h3>
      ${notas}
    </div>`;
}

async function copiar() {
  if (!actual) return;
  const texto = actual.cand.seq || "";
  try {
    await navigator.clipboard.writeText(texto);
    aviso("Secuencia copiada.");
  } catch {
    const ta = document.createElement("textarea");
    ta.value = texto;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); aviso("Secuencia copiada."); }
    catch { aviso("No se pudo copiar al portapapeles.", true); }
    ta.remove();
  }
}

function aviso(msg, err = false) {
  document.dispatchEvent(new CustomEvent("sifi:toast", { detail: { msg, err } }));
}

function cssEscape(s) {
  return window.CSS && CSS.escape ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, "\\$&");
}
