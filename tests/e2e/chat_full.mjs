// E2E del chat a pantalla completa (F4) y de la barra de contexto.
//
// Necesita el servicio arriba (por defecto 8790) y playwright disponible:
//   SIFID_URL=http://127.0.0.1:8790 SIFID_TOKEN=... node tests/e2e/chat_full.mjs
// Sale con código 1 si algo de lo esperado no se cumple.
import { createRequire } from "node:module";

// Playwright puede no estar en el node_modules de este repo: se busca en los lugares
// habituales y se puede forzar con SIFID_PLAYWRIGHT=/ruta/a/playwright.
async function cargarPlaywright() {
  const candidatos = [
    process.env.SIFID_PLAYWRIGHT,
    "playwright",
    "/home/mariano/.openclaw/workspace/node_modules/playwright/index.js",
    `${process.env.HOME}/.npm-global/lib/node_modules/playwright/index.js`,
  ].filter(Boolean);
  for (const c of candidatos) {
    try {
      const req = createRequire(import.meta.url);
      const mod = c.startsWith("/") ? req(c) : req(c);
      if (mod && mod.chromium) return mod;
    } catch { /* siguiente */ }
  }
  throw new Error("no encontré playwright (probá SIFID_PLAYWRIGHT=/ruta/index.js)");
}
const { chromium } = await cargarPlaywright();

const BASE = process.env.SIFID_URL || "http://127.0.0.1:8790";
const TOKEN = process.env.SIFID_TOKEN || "";
const url = `${BASE}/${TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : ""}`;

const fallos = [];
const check = (cond, texto) => {
  if (cond) console.log(`  ok  ${texto}`);
  else { fallos.push(texto); console.log(`  MAL ${texto}`); }
};

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 950 } });
const errores = [];
p.on("pageerror", (e) => errores.push(e.message));
p.on("console", (m) => { if (m.type() === "error") errores.push(m.text()); });

await p.goto(url, { waitUntil: "networkidle" });

check(await p.isVisible(".app"), "la app carga");
const anchoPanel = await p.evaluate(() =>
  Math.round(document.querySelector(".chat").getBoundingClientRect().width));

await p.click("#chat-expandir");
await p.waitForTimeout(500);
const full = await p.evaluate(() => ({
  main: getComputedStyle(document.querySelector(".main")).display,
  anchoChat: Math.round(document.querySelector("#chat-log").getBoundingClientRect().width),
  barra: document.querySelector("#chat-barra").getBoundingClientRect().height,
  fuente: getComputedStyle(document.querySelector(".msg") || document.body).fontSize,
}));
check(full.main === "none", "el panel principal se oculta en pantalla completa");
check(full.anchoChat > anchoPanel, `el chat crece (${anchoPanel}px → ${full.anchoChat}px)`);
check(full.barra > 20, "la barra de contexto se muestra");
check(full.fuente !== "12.5px", `la tipografía crece (${full.fuente})`);

const md = await p.evaluate(async () => {
  const m = await import("/assets/js/md.js");
  return m.renderMd("**b** `<x>`\n\n```js\nalert(1)\n```\n\n<script>alert(2)</script>");
});
check(md.includes("<strong>b</strong>"), "markdown: negritas");
check(md.includes("&lt;x&gt;"), "markdown: código en línea escapado");
check(md.includes("<pre><code"), "markdown: bloque de código");
check(!md.includes("<script>"), "markdown: HTML crudo no se ejecuta");

await p.keyboard.press("Escape");
await p.waitForTimeout(300);
check(await p.evaluate(() => !document.querySelector(".app").classList.contains("modo-chat")),
  "Esc vuelve al panel");

// Streaming: el endpoint tiene que mandar varios deltas y cerrar con "fin".
const stream = await p.evaluate(async () => {
  // Se usa el cliente de la app: ya sabe la URL y el token.
  const { api } = await import("/assets/js/api.js");
  let deltas = 0;
  let primeros = "";
  const fin = await api.chatStream("Contestá sólo: ok, streaming andando.", null, [], null, {
    onEvento: (e) => { if (e.tipo === "delta") { deltas += 1; primeros += e.texto; } },
  });
  return { deltas, primeros, respuesta: fin.respuesta || "", sesion: fin.sesion_id || "" };
});
check(stream.deltas >= 3, `streaming: ${stream.deltas} deltas en vivo`);
check(stream.respuesta.length > 0, `streaming: cierra con respuesta ("${stream.respuesta.slice(0, 40)}")`);
check(Boolean(stream.sesion), "streaming: guarda la sesión");

check(errores.length === 0, `sin errores de consola${errores.length ? ": " + errores.join(" | ") : ""}`);

await b.close();
if (fallos.length) {
  console.error(`\n${fallos.length} fallo(s)`);
  process.exit(1);
}
console.log("\nE2E OK");
