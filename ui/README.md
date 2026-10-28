# siFi Desk — interfaz (`ui/`)

Frontend **estático**: HTML + CSS + módulos ES, sin bundler, sin `npm install`,
sin paso de compilación. Se abre tal cual y se habla con el servicio local por
HTTP (`fetch`). No hay lógica científica acá: la UI muestra lo que devuelve
`sifid` (o la maqueta).

```
ui/
├── index.html            # shell único (asistente, progreso, resultados, corridas)
├── assets/
│   ├── styles.css
│   └── js/               # api · wizard · progress · results · detail · chat · state · format · main · demo
├── mock/
│   ├── server.py         # servicio de maqueta (sólo stdlib)
│   ├── gen_data.py       # regenera mock_data.json desde el fixture + scoring del core
│   └── data/mock_data.json
├── tauri/                # envoltorio de escritorio (config + src-tauri)
└── docs/screens/         # capturas de verificación
```

## Correr la maqueta (así se revisa acá)

Sin dependencias, sin red, sin credenciales:

```bash
python3 ui/mock/server.py --port 8765
# y abrir http://127.0.0.1:8765
```

La maqueta sirve la UI **y** el mismo contrato HTTP que va a exponer `sifid`:

| Método | Ruta | Uso |
|---|---|---|
| GET | `/health` | estado del servicio |
| GET | `/panels` | paneles de referencia |
| GET | `/runs` | corridas (histórico) |
| POST | `/runs` | crear corrida |
| GET | `/runs/{id}` | estado + progreso (la UI hace *polling*) |
| POST | `/runs/{id}/cancel` | cancelar |
| GET | `/runs/{id}/results` | candidatos, scores y desglose |
| POST | `/agent/chat` | **extensión de la maqueta**: chat simulado |

Opcional: `GET /meta` devuelve los resultados de ejemplo completos.

La corrida simulada tarda unos segundos: alcanza para ver la pantalla de
progreso con sus etapas reales (validando → ventanas → RNAplfold → bowtie →
scoring → cierre) y el log en vivo.

Verificación hecha en este host: las 10 capturas de `docs/screens/` (asistente paso a paso, progreso,
resultados, detalle, chat, tema oscuro y corridas) salen de
levantar la maqueta y recorrer el asistente con un navegador headless:

```bash
agent-browser open http://127.0.0.1:8765   # o Playwright
```

## Escritorio (Tauri 2)

`ui/tauri/tauri.conf.json` + `ui/tauri/src-tauri/` arman la ventana nativa y
lanzan el sidecar `sifid` (empaquetado como `externalBin` en `binaries/sifid`).

* `frontendDist` = `../..` → el `ui/` de este repo (sin paso de build).
* El sidecar se busca al lado del ejecutable y se mata al cerrar la app
  (`src-tauri/src/main.rs`). El frontend espera el servicio en
  `http://127.0.0.1:8791` cuando corre dentro de Tauri (`assets/js/api.js`).
* `beforeDevCommand`/`devUrl` apuntan a la maqueta en `8765`, así que
  `tauri dev` también funciona sin `sifid`.

### ⚠️ El binario NO se compila en este host

Este equipo **no tiene `webkit2gtk`** (ni las librerías de desarrollo), que es
dependencia obligatoria del webview en Linux. Por eso:

* acá sólo se **verifica la UI en el navegador** contra la maqueta;
* el binario Tauri se compila en **Windows** (target del producto: `.msi`/`.exe`)
  o en **CI**, corriendo:

```bash
cd ui/tauri
cargo tauri build        # requiere rust + tauri-cli + webkit2gtk-4.1 (Linux)
```

* `bundle.externalBin` espera `src-tauri/binaries/sifid-<target-triple>[.exe]`,
  generado por el frente de empaquetado (M8). Sin ese archivo el `build` falla,
  igual que sin los iconos (ya incluidos en `src-tauri/icons/`).

## Tests

```bash
python3 -m pytest -q tests
```

Los tests de la maqueta viven en `tests/unit/test_ui_mock.py` y levantan el
servidor en un puerto efímero.
