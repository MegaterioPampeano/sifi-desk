# Agente v2 — arquitectura

Cómo está armado el agente de siFi Desk después de la reestructuración (F1-F4 del
`AGENTE_V2_ROADMAP.md`). La idea: la misma inteligencia y el mismo nivel de contexto que
Multivac, pero encerrado en su carpeta y comunicándose por la app.

## Mapa de piezas

| archivo | qué hace |
|---|---|
| `core/service/agent.py` | system prompt base, tools, loop de herramientas, cliente LLM |
| `core/service/politica.py` | permisos deny-by-default (qué rutas puede *nombrar*) |
| `core/service/jaula.py` | aislamiento de kernel con bwrap (qué rutas *existen*) |
| `core/service/guardia.py` | audit hook para el tool `python` |
| `core/service/sandbox.py` | shell, archivos, descargas, trabajos en segundo plano |
| `core/service/contexto.py` | ventana de contexto por tokens, tarjetas, compactación |
| `core/service/memoria.py` | memoria persistente en archivos |
| `core/service/charlas.py` | sesiones en JSON: mensajes, herramientas, resumen, plan |
| `core/service/prompt/*.md` | referencia técnica del laboratorio (se recarga sola) |
| `ui/assets/js/md.js` | render de markdown seguro para las respuestas |
| `ui/assets/js/chat.js` | chat: envío, sesiones, full-screen, barra, plan |

## El turno, de punta a punta

1. `POST /agent/chat` con `{mensaje, sesion_id?, run_id?}`.
2. `charlas.asegurar` abre o crea la sesión y guarda el mensaje del usuario.
3. `charlas.historial_para_llm` arma la ventana: resumen (si hay) + turnos con sus tarjetas
   de herramientas, recortados por presupuesto de tokens.
4. `agent.chat` compone el system prompt: `SYSTEM` + `prompt/*.md` + memoria viva (HOT,
   WARM, cola de MEMORY) + fecha y carpeta.
5. Loop de hasta `MAX_RONDAS`: el modelo pide tools, `_ejecutar` las corre, cada resultado
   vuelve como mensaje `tool` y como tarjeta para la UI.
6. Al terminar: se guardan respuesta + tarjetas en la sesión. Si la sesión superó el 75%
   del presupuesto, `charlas.compactar` resume los turnos viejos con el mismo modelo.
7. La respuesta incluye `plan` (si el agente lo fijó) y `compactado` (si hubo).

## Streaming

El turno se pide con `stream: true` y se entrega por `POST /agent/chat/stream` como NDJSON:
una línea por evento (`delta`, `tool`, `fin`). La UI escribe sobre la burbuja a medida que
llega el texto y muestra un cursor; las tarjetas de herramientas aparecen en vivo.

La lógica es una sola: `agent.chat_eventos()` es un generador y `agent.chat()` lo consume
para devolver el JSON clásico. El endpoint sin streaming sigue existiendo (clientes viejos,
pruebas, `curl`). `SIFI_STREAM=0` apaga el streaming y todo vuelve al modo bloqueante.

## Presupuesto de contexto

| constante | valor | dónde |
|---|---|---|
| `PRESUPUESTO_TOKENS` | 90.000 | `contexto.py` (`SIFI_AGENT_HIST_TOKENS`) |
| umbral de compactación | 75% | `SIFI_AGENT_COMPACT_AT` |
| turnos vivos tras compactar | 10 | `SIFI_AGENT_TURNOS_VIVOS` |
| tope por salida de tool en contexto | 4.000 chars | `contexto.TOPE_TOOL_CTX` |
| tope por turno | 12.000 chars | `contexto.TOPE_TURNO` |

Los tokens se estiman con `caracteres / 3,4`. Es una estimación: sirve para ver la
tendencia y para decidir cuándo compactar, no para auditar facturación.

## Permisos: dos capas

1. **Política** (`politica.py`): deny-by-default. RW = carpeta del agente + `/tmp/sifi_agent`;
   RO = programa, datos del laboratorio, site-packages, sistema. Todo lo demás se rechaza
   con un mensaje legible antes de ejecutar nada.
2. **Jaula** (`jaula.py`): el comando corre en un namespace de montaje donde sólo están
   esas raíces. `ls /home/mariano` no da "permiso denegado": el home no está montado.
   Si bwrap no está disponible, se sigue con la política sola (`jaula: false`).

`SIFI_BWRAP=0` desactiva la jaula; `SIFI_BWRAP=1` la fuerza.

## Memoria

```
~/.sifidesk/agente/memoria/
  MEMORY.md            largo plazo (curado)
  hot/HOT_MEMORY.md    en qué está trabajando ahora
  warm/WARM_MEMORY.md  preferencias y configuración estable
  2026-10-30.md        bitácora del día
```

HOT + WARM + la cola de MEMORY entran en cada system prompt. El agente escribe con
`memoria_escribir` cuando aprende algo que va a hacer falta después. La memoria sobrevive
a la compactación y a las sesiones nuevas.

## Herramientas (18)

`ejecutar` (con `fondo`), `proceso`, `plan`, `python`, `descargar`, `leer`, `editar`,
`escribir`, `listar_archivos`, `memoria_leer`, `memoria_escribir`, `memoria_buscar`,
`sifi`, `buscar_gen`, `transcrito`, `buscar_web`, `abrir_url`, `corrida`.

`corrida` unifica las seis anteriores de corridas con `accion`: `paneles`, `lanzar`,
`estado`, `resultados`, `error`, `informe`. Menos esquema, menos nombres inventados.

## Cómo cambiar el comportamiento

- **Conocimiento del dominio**: editar `core/service/prompt/*.md`. Se recargan solas
  cuando cambia el mtime; no hace falta reiniciar.
- **Personalidad y reglas de respuesta**: `SYSTEM` en `agent.py` (es el bloque corto:
  quién es, cómo contesta, qué no hace).
- **Memoria**: `~/.sifidesk/agente/memoria/`. El agente también escribe ahí.
- **Permisos**: `politica.RW` / `politica.RO` / `politica.DENEGADO`.
- **Presupuesto y compactación**: variables de entorno `SIFI_AGENT_*` o las constantes.

## Pruebas

```bash
python3 -m pytest tests/ -q          # 213 casos: política, jaula, contexto, pipeline
node tests/e2e/chat_full.mjs         # E2E de la UI (requiere servicio arriba)
```

Las pruebas de política simulan intentos de escape reales (home, traversal, symlink a
`/etc/shadow`, escritura fuera, guardia). Las de jaula verifican el aislamiento de kernel
y se saltean si el host no permite namespaces sin privilegios.

## Lo que falta (F5 y deuda conocida)

- Adjuntar archivos al chat y renombrar conversaciones.
- Renombrar conversaciones y scroll infinito en la lista.
- `informe` con figuras propias y versión del scoring en portada.
- Benchmark de contexto con guiones largos (diseño, off-target, informe).
