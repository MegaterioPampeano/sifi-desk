// Avisos efímeros de la interfaz. Vive en su propio módulo porque lo usan wizard.js,
// main.js, chat.js y results.js: antes estaba copiado adentro de wizard.js y en los
// demás archivos la llamada tiraba ReferenceError, que se comía el error real.
export function toast(msg, err = false) {
  document.dispatchEvent(new CustomEvent("sifi:toast", { detail: { msg, err } }));
}
