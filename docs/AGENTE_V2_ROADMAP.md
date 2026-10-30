# Agente v2 — reestructuración profunda del agente de siFi Desk

Objetivo: que el agente de la app piense y trabaje con el mismo nivel de detalle que
Multivac (el agente de OpenClaw), pero encerrado en su carpeta, con el harness propio
(deepseek directo + tools propias) y un chat a pantalla completa.

Estado: F1-F5 completas el 2026-10-30. Suite: 223 passed, 8 skipped + E2E 11/11.
Cada fase tiene criterio de aceptación verificable.

---

## F0 — Diagnóstico (hecho 2026-10-30)

Lo que hay hoy, medido:

| Aspecto | Agente siFi (actual) | Multivac (referencia) |
|---|---|---|
| System prompt | 8.049 caracteres | 44.166 caracteres |
| Tools | 17 | 17 + skills |
| Historial al modelo | últimos 8 turnos, sólo texto | todo lo vivo + compaction |
| Resultados de tools en contexto | **no** (sólo tarjetas en la UI) | **sí**, completos |
| Memoria persistente | archivos en la carpeta | MEMORY.md + memory/*.md + búsqueda semántica |
| Compactación | no existe | automática (19 en esta sesión) |
| Presupuesto de contexto | CTX_TOKENS (chico) | 200.000 configurado |
| Aislamiento | política de rutas en Python (deny-list) | no aplica (host completo) |
| UI | panel lateral 380px | chat full-screen |

Brechas principales: (1) permisos deny-list, no deny-by-default ni kernel-level;
(2) contexto chico y sin memoria ni compactación; (3) los resultados de herramientas no
vuelven al modelo, así que "no se acuerda" de lo que corrió; (4) UI de panel, no de chat.

---

## F1 — Permisos: de "no toques esto" a "no podés ver esto"

### F1.a Política deny-by-default (sin sudo) — HECHO 2026-10-30
- [x] `core/service/politica.py`: raíces explícitas RW / RO, todo lo demás denegado.
  - RW: `~/.sifidesk/agente`
  - RO: programa (`/mnt/datos/proyectos/sifi-desk`), datos (`/mnt/datos/biotech`,
    `/mnt/datos/sifidesk`), site-packages de usuario, binarios del sistema.
  - DENY: resto de `$HOME` (incluye `~/.ssh`, `~/.openclaw`, `~/.config`), `/etc`
    sensible, `/root`, `/var`, otros usuarios, discos montados fuera de la lista.
- [x] Aplicada en los 3 caminos: shell (`correr`), python (`python`) y archivos
  (`leer`/`escribir`/`listar_archivos`).
- [x] `guardia.py`: launcher con `sys.addaudithook` que bloquea `open`/`exec` fuera de
  las raíces permitidas aun cuando el agente escriba Python a mano.
- [x] Tests de escape (27 casos, verdes): `tests/test_politica.py` (≥15 casos: `cat ~/.ssh/id_rsa`,
  `ls ~/.openclaw`, `python -c open(...)`, symlinks, `..`, `/proc/self/environ`, etc.).
- Criterio: los 15 casos fallan con mensaje claro y el agente sigue funcionando normal.

### F1.b Aislamiento real con bwrap — HECHO 2026-10-30 (Mariano corrió el sysctl)
- [x] Perfil bwrap (`core/service/jaula.py`): `/usr`, `/lib`, `/bin`, `/etc` RO mínimos; tmpfs `/tmp`; `/proc`,
  `/dev`; RW sólo la carpeta del agente; RO programa y datos; sin red propia del host
  más allá de lo necesario (más adelante, allowlist de dominios por proxy).
- [x] Auto-detección (probe cacheado + `SIFI_BWRAP=0/1`): si `bwrap` no funciona, cae a F1.a sin romper nada.
- Requirió: `kernel.apparmor_restrict_unprivileged_userns=0` (Ubuntu 24.04). Mariano
  lo aplicó el 2026-10-30 00:50. Persistencia: `/etc/sysctl.d/99-bwrap.conf`.
- Hecho: dentro de la jaula `/` son 12 carpetas, `/home/mariano` sólo tiene la cáscara
  `.local/lib` (padre de site-packages), `cat /etc/shadow` da Permission denied por uid,
  `/root` no existe; `python`, `biopython`, `curl` con HTTPS y escritura en su carpeta andan.
  Tests: `tests/test_jaula.py` (6 casos). Suite: 202 passed, 8 skipped.

---

## F2 — Contexto grande con memoria y compactación — HECHO 2026-10-30

- [x] System prompt modular (~35-45k caracteres): identidad y método (los actuales),
  + guía de herramientas, + dominio (BicC, scoring E/R/S/T/D, paneles), + protocolo de
  reporte, + política de memoria. Armado por secciones desde archivos, no un string.
- [x] Resultados de herramientas **al contexto** (hoy se pierden): cada `tool` message
  lleva salida completa con tope por resultado y poda de los más viejos.
- [x] Historial por presupuesto de tokens (no 8 turnos fijos): sumar turnos hasta ~60%
  del contexto, con cola de "resumen" de lo viejo.
- [x] Compactación: cuando el historial supera el umbral, resumir los turnos viejos con
  el propio modelo y guardar el resumen en la sesión (`resumen` persistido).
- [x] Memoria por archivos: `~/.sifidesk/agente/memoria/{MEMORY.md,hot,warm,daily}` con
  tools `memoria_leer` / `memoria_escribir` y búsqueda por grep+BM25 (sin embeddings
  primero; embeddings si hace falta).
- [x] Presupuesto y modelos: `CTX_TOKENS` real del modelo (131k), `max_tokens` 16k,
  temperatura 0.2, reintentos con backoff y corte por costo.
- Hecho: system 8.049 → 24.812 caracteres (base + `service/prompt/{metodo,dominio,scoring,offtarget,informes}.md`).
  Memoria en `~/.sifidesk/agente/memoria/{MEMORY.md,hot,warm,YYYY-MM-DD.md}` con
  `memoria_leer/escribir/buscar`; HOT+WARM+cola de MEMORY entran en el system prompt.
  Ventana por presupuesto (90k tokens, tope 12k por turno, 4k por salida de tool),
  compactación al 75% con resumen persistido en `sesion["resumen"]` y 10 turnos vivos.
  Verificado E2E: turno 2 recordó el `ls` del turno 1 y la línea de memoria, sin tools.
  Tests: `tests/test_contexto.py` (11 casos).

---

## F3 — Paridad de herramientas — HECHO 2026-10-30

Ya hay 17. Faltan / hay que mejorar:

- [x] `leer` con offset/limit y números de línea.
- [x] `editar` (reemplazo exacto, con chequeo de unicidad) y `escribir`.
- [x] `ejecutar(fondo=true)` + `proceso` (listar/estado/log/matar). pty no hace falta: los comandos del agente no son interactivos.
- [x] `abrir_url` con markdown limpio (article/main, listas, links, PDF vía pdftotext).
- [x] `memoria_*` (F2). Falta `plan` (todo list visible en la UI).
- [ ] `informe` mejorado: figuras + metodología + versión del scoring.
- [x] `corrida` unifica las 6 tools de corridas (paneles/lanzar/estado/resultados/error/informe). 23 → 18 tools.
- Hecho: trabajos en segundo plano con registro en `.procesos.json`, cosecha de zombis y
  kill por grupo; `plan` persistido en la sesión y renderizado arriba del chat; `corrida`
  con subcomandos. Verificado E2E por API: plan 3/3, paneles (6, todos con index_ok),
  trabajo lanzado y log leído.
- Sin streaming SSE: queda como deuda de F4/F5 (el cronómetro cubre la espera).
- Tests: `tests/test_tools_v2.py` (7 casos). Suite: 220 passed, 8 skipped.

---

## F4 — Chat a pantalla completa, nivel Multivac — HECHO 2026-10-30

- [x] Vista full-screen (`.app.modo-chat`, Ctrl+Mayús+F, Esc, preferencia en localStorage) (no panel lateral): historial a ancho completo,
  burbujas por rol, bloques de código con copiar, tablas markdown, colapsables para
  salidas largas de tools.
- [ ] Streaming token por token (SSE) con indicador de pasos ("pensando", "ejecutando
  comando", "leyendo archivo").
- [x] Barra de contexto (modelo, tokens usados/presupuesto, memoria, botón compactar): tokens usados / presupuesto, modelo activo, botón de compactar.
- [x] Lista de conversaciones con búsqueda (filtro por título). Falta renombrar y scroll infinito.
- [x] Atajos: Enter envía, Shift+Enter nueva línea, Ctrl+K chat full, Esc vuelve al panel.
- [ ] Adjuntar archivos al chat (drag & drop) — falta endpoint de subida.
- [x] Estado de aprobaciones inline (ya estaba; se mantiene en full-screen).
- Hecho: columna centrada de 1040px, tipografía 14,5px/1,65, markdown propio y seguro
  (`ui/assets/js/md.js`: listas, negritas, código en línea y en bloque, títulos, links,
  todo escapado), tarjetas de herramientas plegables, cronómetro de espera, resumen de
  compactación visible al abrir la sesión. Verificado con Playwright: `.main` oculto,
  1440px → 200px de margen, barra de contexto con tokens en vivo, cero errores de consola.

---

## F5 — Verificación y puesta en marcha — HECHO 2026-10-30

- [x] Suite de seguridad: `run_all.sh` corre todo (política, jaula, contexto, tools, pipeline).
- [x] Benchmark de contexto: `tests/test_bench_contexto.py` (120 turnos con tarjetas de 9k
  → 65 mensajes, 90.188 tokens, armado en 0,8 ms; turno gigante se recorta).
- [x] E2E Playwright del chat full-screen: `tests/e2e/chat_full.mjs` (11 chequeos, todos ok).
- [x] `docs/AGENTE_V2.md`: arquitectura, mapa de archivos, presupuesto, permisos, memoria, tools.
- Hecho: `tests/run_all.sh` (backend 223 casos + E2E 11 chequeos). Deuda declarada:
  streaming SSE, adjuntar archivos, renombrar charlas y figuras propias en `informe`.

---

## Orden de ejecución

1. ~~F1.a~~ → 2. F2 (contexto/memoria) → 3. F3 (tools) → 4. ~~F1.b~~ → 5. F4 (UI) → 6. F5 (verificación).

Nota: F4 se puede adelantar si Mariano quiere ver el chat grande ya, pero sin F2 el chat
grande se queda sin memoria y decepciona. Orden ejecutado: F1 → F2 → F4. Sigue F3 (tools/streaming) → F5.
