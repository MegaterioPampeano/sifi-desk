# Preguntas y decisiones

> Si una tarea depende de una respuesta de acá, el agente NO la implementa: busca la
> siguiente tarea que no dependa y la hace.
> Las decisiones del arquitecto (`D#`) son vinculantes: no hace falta preguntarlas de nuevo.

## Decisiones (arquitecto, 2026-10-28 19:35 UTC)

**D1 — `Worker` recibe `cwd` y `env` explícitos.** El layout de PyInstaller no se adivina
desde dentro del servicio. `create_app(...)` pasa `cwd=CORE_DIR`, `env=` con las rutas de
binarios. El entry point congelado (`sifid --runner`) sigue siendo el argv, pero nunca más
se depende de en qué directorio cayó el bundle.

**D2 — Un solo bundle one-dir (191 MB) para v1.** Es el precio de llevar numpy, biopython y
FastAPI. Se acepta: instalador de 62 MB comprimido es razonable para software científico.
Se revisa si aparece un pedido concreto de tamaño.

**D3 — La raíz de Tauri es `ui/tauri/`.** `tauri.conf.json`, `src-tauri/` y `capabilities/`
viven ahí. El CI y `scripts/build_windows.ps1` **deben** apuntar a esa ruta (si no existe,
se saltea el `.msi` con warning, no falla el build).

**D4 — Anuncio de puerto y token (contrato con la UI).** `sifid` imprime al arrancar, en
stdout y en una sola línea por dato:
```
SIFID_URL=http://127.0.0.1:<puerto>
SIFID_TOKEN=<token efímero>
```
La UI (o `main.rs`, que lanza el sidecar) lee esas dos líneas. Toda petición a la API lleva
el header `x-sifi-token`. Sin token válido: `401`. El token se genera por proceso y muere
con él. `--no-auth` existe sólo para tests y queda documentado como inseguro.

**D5 — El chat NO pasa por `sifid`.** `sifid` es un servicio científico: cálculo, estado,
resultados. Cero LLM. El chat habla con el **harness de agente** (dsh), que a su vez usa las
tools HTTP contra `sifid`. La maqueta puede simular `POST /agent/chat`, pero el producto
final lo rutea al agente, no al servicio.

**D6 — Nombre del sidecar.** PyInstaller produce `sifid` (o `sifid.exe`); el script de build
lo renombra a `sifid-<target-triple>` (convención de Tauri `externalBin`). Ambos builds
(Linux/Windows) usan el mismo nombre base.

**D7 — Una corrida, varios paneles.** El core va a aceptar N índices y etiquetar cada hit con
su panel (`panel` en la fila). Mientras eso no esté, la UI muestra «sin panel declarado» y el
informe lo advierte. No se simula la atribución.

**D8 — Progreso por registro.** El core va a emitir una línea de evento por registro
procesado (JSON a stdout, prefijo `EVENT`) para que el servicio actualice `progress`. Hasta
entonces el progreso salta de 0 a 100.

---

## Abiertas para Mariano

_(ninguna por ahora)_

## Historial de preguntas (resueltas o derivadas a decisión)

### M8 · empaquetado
1. `cwd` del runner congelado → **D1**.
2. Tamaño del bundle / split de `sifi` → **D2**.
3. Ubicación de la UI Tauri → **D3**.

### M5 · ventana
1. Puerto y token → **D4**.
2. Chat del agente → **D5**.
3. Nombre del sidecar → **D6**.

### M3 · servicio
1. Progreso por registro → **D8**.
2. Multi-panel en una corrida → **D7**.
3. Atribución de panel en los hits → **D7**.
