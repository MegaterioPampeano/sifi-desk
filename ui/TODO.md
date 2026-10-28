# ui/ — pendientes (frente ventana, M5)

Estado: **UI completa y verificada contra la maqueta**. Falta conectar el
servicio real y el empaquetado, que no dependen de este frente.

## Lo que falta (ordenado por dependencia)

1. **Contrato real con `sifid` (M3).**
   * Hoy el frontend asume `http://127.0.0.1:8791` dentro de Tauri y un puerto
     fijo. El roadmap pide **puerto efímero + token de sesión** en cada request:
     cuando M3 lo defina, `main.rs` tiene que leer el puerto/token del sidecar y
     pasarlo a la UI (`setApiBase()` ya existe en `assets/js/api.js`), y `api.js`
     tiene que mandar el header del token.
   * `POST /agent/chat` es una **extensión de la maqueta**: no está en el
     contrato HTTP de §5.3 del roadmap. Falta decidir si el agente real expone
     ese endpoint o si el chat va por el harness (`agent/adapter/`).

2. **Progreso en vivo.** Se usa *polling* a `GET /runs/{id}` (simple y suficiente
   para la maqueta). SSE queda como mejora si el servicio lo ofrece.

3. **Empaquetado (M8).**
   * `frontendDist` apunta a `ui/` completo, así que el bundle copiaría también
     `mock/`, `docs/` y `tauri/` (incluido `src-tauri/target/` si existe). En CI
     conviene stagear un `dist/ui/` con sólo `index.html` + `assets/` y apuntar
     `frontendDist` ahí.
   * `externalBin` necesita `src-tauri/binaries/sifid-<triple>` (PyInstaller).
   * Firmas/updater y los `.msi` se resuelven en M8.

4. **Compilación Tauri.** No verificable acá: este host no tiene `webkit2gtk`.
   El primer `cargo tauri build` real (Windows/CI) puede pedir ajustes menores de
   versión de `tauri`/`tauri-build`.

## Hecho

* Asistente de 4 pasos (paneles → secuencia → parámetros → correr) con validación
  entre pasos y borrador persistido.
* Progreso con etapas, log, cancelación y polling.
* Tabla de candidatos con score, desglose E/R/S/T/D, detalle por candidato y
  mapa del gen.
* Chat lateral con el agente (simulado en la maqueta).
* Corridas históricas y reapertura de resultados.
* Maqueta con datos derivados del fixture y del scoring real del core.
* Capturas en `docs/screens/` (10 PNG, 1440×1000).
