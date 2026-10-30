# Agente v2 — reestructuración profunda del agente de siFi Desk

Objetivo: que el agente de la app piense y trabaje con el mismo nivel de detalle que
Multivac (el agente de OpenClaw), pero encerrado en su carpeta, con el harness propio
(deepseek directo + tools propias) y un chat a pantalla completa.

Estado: F1.a terminada (2026-10-30). Suite completa: 196 passed, 8 skipped.
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

### F1.b Aislamiento real con bwrap (requiere 1 comando con sudo de Mariano)
- [ ] Perfil bwrap: `/usr`, `/lib`, `/bin`, `/etc` RO mínimos; tmpfs `/tmp`; `/proc`,
  `/dev`; RW sólo la carpeta del agente; RO programa y datos; sin red propia del host
  más allá de lo necesario (más adelante, allowlist de dominios por proxy).
- [ ] Auto-detección: si `bwrap` no funciona, cae a F1.a sin romper nada.
- Bloqueante: `kernel.apparmor_restrict_unprivileged_userns=1` en Ubuntu 24.04.
  Comando único: `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`
  (+ `/etc/sysctl.d/99-bwrap.conf` para que persista).
- Criterio: dentro del sandbox, `ls /home/mariano` no muestra nada y `cat ~/.ssh/id_rsa`
  da "No such file"; `python`, `bowtie`, `curl` siguen andando.

---

## F2 — Contexto grande con memoria y compactación

- [ ] System prompt modular (~35-45k caracteres): identidad y método (los actuales),
  + guía de herramientas, + dominio (BicC, scoring E/R/S/T/D, paneles), + protocolo de
  reporte, + política de memoria. Armado por secciones desde archivos, no un string.
- [ ] Resultados de herramientas **al contexto** (hoy se pierden): cada `tool` message
  lleva salida completa con tope por resultado y poda de los más viejos.
- [ ] Historial por presupuesto de tokens (no 8 turnos fijos): sumar turnos hasta ~60%
  del contexto, con cola de "resumen" de lo viejo.
- [ ] Compactación: cuando el historial supera el umbral, resumir los turnos viejos con
  el propio modelo y guardar el resumen en la sesión (`resumen` persistido).
- [ ] Memoria por archivos: `~/.sifidesk/agente/memoria/{MEMORY.md,hot,warm,daily}` con
  tools `memoria_leer` / `memoria_escribir` y búsqueda por grep+BM25 (sin embeddings
  primero; embeddings si hace falta).
- [ ] Presupuesto y modelos: `CTX_TOKENS` real del modelo (131k), `max_tokens` 16k,
  temperatura 0.2, reintentos con backoff y corte por costo.
- Criterio: una charla de 40 turnos con corridas mantiene el hilo sin repetir comandos;
  el agente cita datos de un turno 15 atrás.

---

## F3 — Paridad de herramientas

Ya hay 17. Faltan / hay que mejorar:

- [ ] `leer` con offset/limit y números de línea (como el mío).
- [ ] `editar` (reemplazo exacto) y `escribir` con verificación de tamaño/diff.
- [ ] `ejecutar` con pty opcional y ejecución en background + `proceso` (poll/kill/log).
- [ ] `buscar_web` con snippets y `abrir_url` con markdown limpio (hoy texto plano).
- [ ] `memoria_*` (F2) y `plan` (todo list visible en la UI).
- [ ] `informe` mejorado: figuras + metodología + versión del scoring.
- [ ] `sifi` unificado: una tool con subcomandos en vez de 8 sueltas.
- Criterio: ninguna tarea que yo resuelva con mis tools queda sin equivalente.

---

## F4 — Chat a pantalla completa, nivel Multivac

- [ ] Vista `#/chat` full-screen (no panel lateral): historial a ancho completo,
  burbujas por rol, bloques de código con copiar, tablas markdown, colapsables para
  salidas largas de tools.
- [ ] Streaming token por token (SSE) con indicador de pasos ("pensando", "ejecutando
  comando", "leyendo archivo").
- [ ] Barra de contexto: tokens usados / presupuesto, modelo activo, botón de compactar.
- [ ] Lista de conversaciones con búsqueda y renombrado; scroll infinito.
- [ ] Atajos: Enter envía, Shift+Enter nueva línea, Ctrl+K comandos, Esc corta.
- [ ] Adjuntar archivos al chat (drag & drop) que caen en `descargas/` del agente.
- [ ] Estado de aprobaciones inline (aprobar/rechazar sin salir del chat).
- Criterio: se puede tener una conversación técnica larga sin abrir otra pestaña, y
  desde la tele/monitor se lee cómodo a 1920x1080.

---

## F5 — Verificación y puesta en marcha

- [ ] Suite de seguridad (F1) en CI local: `pytest tests/test_politica.py -q`.
- [ ] Benchmark de contexto: 3 guiones largos (diseño de dsRNA, off-target, informe) con
  métrica de "¿recordó lo que hizo?" y tokens gastados.
- [ ] E2E Playwright del chat full-screen.
- [ ] Documento `docs/AGENTE_V2.md` con arquitectura y cómo cambiar el prompt.
- Criterio: todo verde y el agente respondiendo por la app real.

---

## Orden de ejecución

1. F1.a (hoy) → 2. F2 (contexto/memoria) → 3. F3 (tools) → 4. F1.b (bwrap, cuando
Mariano corra el sudo) → 5. F4 (UI) → 6. F5 (verificación).

Nota: F4 se puede adelantar si Mariano quiere ver el chat grande ya, pero sin F2 el chat
grande se queda sin memoria y decepciona. Orden recomendado: F1.a → F2 → F4 → F3 → F1.b.
