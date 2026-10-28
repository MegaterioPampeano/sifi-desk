// Formato y vocabulario de la interfaz. Nada de lógica científica acá.

export const BANDAS = {
  recomendado: { label: "Recomendado", clase: "band-recomendado" },
  revisar: { label: "Revisar", clase: "band-revisar" },
  bajo: { label: "Bajo", clase: "band-bajo" },
  descartar: { label: "Descartar", clase: "band-descartar" },
};

export const ROLES = {
  blanco: "blanco",
  no_blanco: "no blanco",
  simbionte: "simbionte",
  control: "control",
  universal: "universal",
  patogeno: "patógeno",
  desconocido: "desconocido",
};

export const EJES = {
  E: "Eficiencia",
  R: "Riesgo",
  S: "Especificidad",
  T: "Consenso siFi",
  D: "Diseño",
};

export const ESTADOS = {
  queued: "en cola",
  running: "corriendo",
  done: "terminada",
  error: "con error",
  cancelled: "cancelada",
};

export function bandLabel(b) {
  return (BANDAS[b] || BANDAS.bajo).label;
}

export function bandClass(b) {
  return (BANDAS[b] || BANDAS.bajo).clase;
}

export function roleLabel(r) {
  return ROLES[r] || r || "desconocido";
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

export function num(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return "—";
  return Number(x).toFixed(digits);
}

export function entero(x) {
  if (x === null || x === undefined) return "—";
  return new Intl.NumberFormat("es-AR").format(x);
}

export function fecha(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("es-AR", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(d);
}

export function fechaCorta(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("es-AR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(d);
}

export function elapsed(desde, hasta) {
  if (!desde) return "00:00";
  const a = new Date(desde).getTime();
  const b = hasta ? new Date(hasta).getTime() : Date.now();
  const s = Math.max(0, Math.round((b - a) / 1000));
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

export function gc(seq) {
  if (!seq) return 0;
  let n = 0;
  for (const c of seq.toUpperCase()) if (c === "G" || c === "C") n++;
  return (100 * n) / seq.length;
}

export function truncSeq(seq, n = 26) {
  if (!seq) return "";
  return seq.length > n ? seq.slice(0, n) + "…" : seq;
}

// Detalle del scoring: diccionario de claves técnicas → texto legible.
const DETALLE = {
  acceso: "accesibilidad",
  hebra: "selección de hebra",
  extremo: "estabilidad de extremo",
  acceso_fuente: "fuente de accesibilidad",
  riesgo: "riesgo acumulado",
  peor_mismatch: "peor mismatch",
  paneles: "paneles",
  hits: "hits distintos",
  unidades: "unidades de castigo",
  is_efficient: "eficiente (siFi)",
  base: "base siFi",
  score_sifi: "score siFi",
  gc: "GC %",
  gc_valor: "valor GC",
  homopolimero: "homopolímero máx.",
  extremo_5p: "base en posición 2",
  gc_nota: "nota GC",
};

export function detalleTexto(clave, valor) {
  const k = DETALLE[clave] || clave;
  let v;
  if (valor === true) v = "sí";
  else if (valor === false) v = "no";
  else if (valor === null || valor === undefined) v = "—";
  else if (Array.isArray(valor)) v = valor.length ? valor.join(", ") : "—";
  else if (typeof valor === "object") v = JSON.stringify(valor);
  else v = String(valor);
  return `${k}: ${v}`;
}
