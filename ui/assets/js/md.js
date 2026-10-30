// Render de markdown mínimo y seguro para las burbujas del agente.
//
// No es un parser completo: alcanza para lo que el agente escribe (listas, negritas,
// código en línea, bloques de código, títulos chicos y links). Todo el texto se escapa
// primero, así que un `<script>` en la respuesta no se ejecuta: se ve como texto.

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

function escapar(texto) {
  return String(texto).replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

function inline(texto) {
  // código primero, para que los * y _ de adentro no se toquen
  const partes = texto.split(/(`[^`]+`)/g).map((trozo) => {
    if (trozo.startsWith("`") && trozo.endsWith("`") && trozo.length > 2) {
      return `<code>${escapar(trozo.slice(1, -1))}</code>`;
    }
    let html = escapar(trozo);
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    html = html.replace(/(https?:\/\/[^\s<)]+)/g,
      '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
    return html;
  });
  return partes.join("");
}

function bloqueCodigo(codigo, lenguaje) {
  const clase = lenguaje ? ` class="lang-${escapar(lenguaje)}"` : "";
  return `<pre><code${clase}>${escapar(codigo.replace(/\n$/, ""))}</code></pre>`;
}

export function renderMd(texto) {
  const fuente = String(texto || "");
  const salida = [];
  const lineas = fuente.split("\n");
  let i = 0;
  let lista = null; // "ul" | "ol"

  const cerrarLista = () => {
    if (lista) { salida.push(`</${lista}>`); lista = null; }
  };

  while (i < lineas.length) {
    const linea = lineas[i];

    // bloque de código ``` o ~~~
    const cerca = linea.match(/^\s*(```+|~~~+)\s*([\w+-]*)\s*$/);
    if (cerca) {
      cerrarLista();
      const marca = cerca[1][0];
      const cuerpo = [];
      i += 1;
      while (i < lineas.length && !new RegExp(`^\\s*${marca}{3,}\\s*$`).test(lineas[i])) {
        cuerpo.push(lineas[i]);
        i += 1;
      }
      i += 1; // saltear el cierre
      salida.push(bloqueCodigo(cuerpo.join("\n"), cerca[2]));
      continue;
    }

    if (!linea.trim()) {
      cerrarLista();
      i += 1;
      continue;
    }

    // títulos ### / ## / #  →  h4 (no queremos competir con la jerarquía de la app)
    const titulo = linea.match(/^\s*#{1,4}\s+(.*)$/);
    if (titulo) {
      cerrarLista();
      salida.push(`<h4>${inline(titulo[1].trim())}</h4>`);
      i += 1;
      continue;
    }

    if (/^\s*(---|\*\*\*|___)\s*$/.test(linea)) {
      cerrarLista();
      salida.push("<hr>");
      i += 1;
      continue;
    }

    // listas
    const vinetas = linea.match(/^\s*[-*•]\s+(.*)$/);
    const numerada = linea.match(/^\s*\d+[.)]\s+(.*)$/);
    if (vinetas || numerada) {
      const tipo = vinetas ? "ul" : "ol";
      if (lista !== tipo) { cerrarLista(); salida.push(`<${tipo}>`); lista = tipo; }
      salida.push(`<li>${inline((vinetas || numerada)[1])}</li>`);
      i += 1;
      continue;
    }

    // párrafo: junta líneas seguidas hasta un blanco
    cerrarLista();
    const parrafo = [linea];
    i += 1;
    while (i < lineas.length && lineas[i].trim()
           && !/^\s*(```|~~~|#{1,4}\s|[-*•]\s|\d+[.)]\s)/.test(lineas[i])) {
      parrafo.push(lineas[i]);
      i += 1;
    }
    salida.push(`<p>${inline(parrafo.join("\n")).replace(/\n/g, "<br>")}</p>`);
  }
  cerrarLista();
  return salida.join("");
}
