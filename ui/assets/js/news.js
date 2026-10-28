// Novedades: GET /news del servicio (watch real, cacheado).
// Si no hay red el servicio contesta 200 con `warnings`; acá se muestran como
// aviso y, si no hay ítems, "Sin novedades ahora". Nunca un volcado de consola.
import { api } from "./api.js";
import { esc, fechaCorta } from "./format.js";

const $ = (sel) => document.querySelector(sel);
let since = "7d";
let cargando = false;

export function initNews() {
  $("#news-since").addEventListener("change", (ev) => {
    since = ev.target.value;
    cargarNews(true);
  });
  $("#btn-news-refresh").addEventListener("click", () => cargarNews(true));
}

export async function cargarNews(refresh = false) {
  if (cargando) return;
  cargando = true;
  const lista = $("#news-list");
  const estado = $("#news-status");
  lista.innerHTML = `<div class="readout-empty">Consultando novedades…</div>`;
  estado.textContent = "";
  estado.className = "muted small";

  try {
    const d = await api.news({ since, refresh });
    const items = d.items || [];
    const avisos = d.warnings || [];
    const c = d.counts || {};
    const cuando = d.generated_at ? fechaCorta(d.generated_at) : "—";
    estado.textContent = `${c.new ?? items.length} nueva(s) · ventana ${d.since_arg || since} · ` +
      `${d.cached ? "caché" : "consultado"} ${cuando}`;
    if (avisos.length) {
      estado.textContent += ` · ${avisos.length} aviso(s) de red`;
      estado.className = "small warn-text";
    }

    const bloqueAvisos = avisos.length
      ? `<div class="notice warn">${avisos.map((w) => `<div>${esc(w)}</div>`).join("")}</div>`
      : "";

    if (!items.length) {
      lista.innerHTML = bloqueAvisos +
        `<div class="readout-empty">Sin novedades ahora. Probá otra ventana o actualizá más tarde.</div>`;
      return;
    }
    lista.innerHTML = bloqueAvisos + items.map((it) => tarjeta(it)).join("");
  } catch (err) {
    estado.textContent = "no se pudieron traer las novedades";
    estado.className = "small warn-text";
    lista.innerHTML = `<div class="notice err"><strong>Sin novedades ahora.</strong>` +
      ` No se pudo consultar el servicio: ${esc(err.message)}</div>`;
  } finally {
    cargando = false;
  }
}

function tarjeta(it) {
  const meta = [it.fuente, it.fecha ? fechaCorta(it.fecha) : "", it.query]
    .filter(Boolean).map(esc).join(" · ");
  const link = it.url
    ? `<a class="btn ghost sm" href="${esc(it.url)}" target="_blank" rel="noopener">Abrir</a>`
    : it.doi ? `<span class="mono small">${esc(it.doi)}</span>` : "";
  return `<article class="news-card">
    <div class="news-head">
      <h3>${esc(it.titulo)}</h3>
      <span class="muted small">${meta}</span>
    </div>
    ${it.resumen ? `<p>${esc(it.resumen)}</p>` : ""}
    ${link ? `<div class="news-foot">${link}</div>` : ""}
  </article>`;
}
