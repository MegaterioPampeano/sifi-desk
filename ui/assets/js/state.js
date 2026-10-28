// Estado de la ventana. Todo lo que el usuario eligió vive acá y, lo que tiene
// sentido entre sesiones, se guarda en localStorage.

const KEY = "sifi.desk.draft.v1";

export const state = {
  panels: [],
  selected: new Set(),
  origin: "paste",
  fastaText: "",
  fileName: "",
  parsed: [],
  params: { size: "21", mismatches: "2", mode: "design", main: "" },
  view: "wizard",
  step: 1,
  runId: null,
  run: null,
  results: null,
  geneFilter: "all",
  band: "all",
  q: "",
  sort: { key: "total", dir: "desc" },
  activeCandidate: null,
};

export function saveDraft() {
  try {
    localStorage.setItem(KEY, JSON.stringify({
      selected: [...state.selected],
      origin: state.origin,
      fastaText: state.fastaText.slice(0, 200000),
      fileName: state.fileName,
      params: state.params,
      step: state.step,
    }));
  } catch {
    /* cuota llena o modo privado: la ventana funciona igual */
  }
}

export function loadDraft() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return;
    const d = JSON.parse(raw);
    if (Array.isArray(d.selected)) state.selected = new Set(d.selected);
    if (d.origin) state.origin = d.origin;
    if (typeof d.fastaText === "string") state.fastaText = d.fastaText;
    if (typeof d.fileName === "string") state.fileName = d.fileName;
    if (d.params && typeof d.params === "object") {
      state.params = { ...state.params, ...d.params };
    }
  } catch {
    /* borrador corrupto: se ignora */
  }
}

export function clearDraft() {
  try { localStorage.removeItem(KEY); } catch { /* nada */ }
}

export function panelById(id) {
  return state.panels.find((p) => p.id === id) || null;
}

export function selectedPanels() {
  return state.panels.filter((p) => state.selected.has(p.id));
}

// --- parser de FASTA del lado del navegador ---------------------------------

const VALID = /^[ACGTUNRYKMSWBDHV]+$/i;

export function parseFasta(texto) {
  const lineas = String(texto || "").split(/\r?\n/);
  const registros = [];
  let actual = null;
  let errores = [];

  const push = () => {
    if (!actual) return;
    const seq = actual.seq.join("").toUpperCase().replace(/U/g, "T").replace(/\s+/g, "");
    if (!seq) {
      errores.push(`${actual.id}: sin secuencia`);
      actual = null;
      return;
    }
    if (!VALID.test(seq)) {
      errores.push(`${actual.id}: caracteres fuera del alfabeto IUPAC`);
    }
    registros.push({ id: actual.id, desc: actual.desc, seq, length: seq.length, gc: 0 });
    actual = null;
  };

  for (const cruda of lineas) {
    const linea = cruda.trim();
    if (!linea) continue;
    if (linea.startsWith(">")) {
      push();
      const cab = linea.slice(1).trim();
      const [id, ...resto] = cab.split(/\s+/);
      actual = { id: (id || `seq${registros.length + 1}`).replace(/[^\w.\-|:]/g, "_"), desc: resto.join(" "), seq: [] };
    } else {
      if (!actual) actual = { id: "consulta", desc: "secuencia sin cabecera", seq: [] };
      actual.seq.push(linea.replace(/\s+/g, ""));
    }
  }
  push();

  for (const r of registros) {
    let n = 0;
    for (const c of r.seq) if (c === "G" || c === "C") n++;
    r.gc = r.seq.length ? (100 * n) / r.seq.length : 0;
  }
  return { registros, errores };
}

export function queryPath() {
  // El servicio real recibe una ruta a un FASTA. La maqueta usa el nombre como
  // pista para elegir el conjunto de datos. Si hay varios registros con nombres
  // de gen, no se manda un id suelto: así el servicio procesa todos.
  if (state.fileName) return state.fileName;
  if (state.parsed.length === 1) {
    const id = state.parsed[0].id.replace(/[^\w.\-]/g, "_");
    return `${id}.fa`;
  }
  return "consulta.fa";
}
