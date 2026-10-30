# Método de trabajo y catálogo de errores

## El ciclo, con criterio de corte

1. **Delimitar.** Qué se pregunta, con qué datos alcanza, qué sería "listo". Si el pedido
   es ambiguo elegí la interpretación más útil y decila en una línea.
2. **Buscar lo ya calculado.** Antes de correr nada: `buscar_gen` en los datos del
   laboratorio, `listar_archivos` en tu carpeta (quizás lo bajaste la semana pasada),
   `estado_corrida` si el run_id existe. Repetir un cálculo que ya está hecho es el error
   más caro en tiempo.
3. **Verificar la fuente.** Un hit de BLAST a una proteína predicha no es lo mismo que un
   transcrito con expresión medida. Anotá de dónde sale cada número.
4. **Actuar.** Comando, script, corrida. Si algo tiene que existir, creálo vos.
5. **Comprobar.** Releé la salida: `rc`, bytes, cantidad de filas, warnings. Un `ok: true`
   con salida vacía no es éxito.
6. **Cerrar.** Qué se encontró, qué se hizo, qué quedó pendiente y cuál es el paso
   siguiente concreto.

## Errores que ya vimos y cómo se resuelven

| síntoma | causa habitual | qué hacer |
|---|---|---|
| "No targets found…" en modo design | query y base en orientación distinta, o query sin relación | revisar orientación (revcomp), revisar que el FASTA sea del gen |
| corrida termina sin siRNAs en modo off-target | cero hits = resultado buscado | informarlo como "sin off-target", no como fallo |
| ranking plano, todos ~50 | panel con una sola isoforma o índice incompleto | revisar `index_ok` del panel, revisar el FASTA de entrada |
| `index_ok: false` | panel agregado sin indexar | reindexar antes de correr; los resultados no valen |
| hits sólo en `blanco` | es lo esperado | el riesgo se mide en `no_blanco` y `control` |
| FASTA con CRLF o líneas vacías | archivo de Windows | normalizar con Python antes de correr |
| comando bloqueado por la jaula | ruta fuera de tu carpeta | usar rutas dentro de tu carpeta; si es lectura de datos, usar las tools |
| escritura rechazada | querés escribir en el programa o en los datos | escribir en tu carpeta y avisar qué hay que cambiar |
| `HTTP 4xx` del servicio | pedido mal formado (panel inexistente, modo inválido) | leer el detalle del error, corregir el cuerpo |
| sin salida y rc≠0 | el error fue a stderr | siempre leer stderr antes de reintentar |

## Presupuesto de esfuerzo

- Un problema simple: 1-2 herramientas. Si necesitás 6, probablemente estás atacando mal
  el problema; replantealo antes de seguir.
- Una corrida del servicio puede tardar minutos: lanzala, seguí con otra cosa y consultá
  `estado_corrida`. No bloquees el turno esperando.
- Las descargas grandes se hacen una vez y se guardan. Si ya está el archivo, usalo.

## Cuándo parar y preguntar

- Antes de gastar mucho (corrida sobre genoma completo, descarga > 300 MB).
- Antes de algo irreversible o que salga de la máquina (mail, publicación, borrar datos).
- Cuando el resultado contradice algo que Mariano afirmó: mostrale el dato y la duda, no
  elijas por él.
- Nunca para pedir permiso de leer, buscar, calcular o escribir en tu carpeta.

## Higiene de archivos

- Nombres con fecha y sentido: `bicc_ventana_1513-1812.fa`, no `ventana2_final_final.fa`.
- Un directorio por tema en tu carpeta (`trabajo/bicc/`), y los scripts junto a su salida.
- Si corrés algo que tarda, dejá el comando en un `.sh` para poder repetirlo.
- Borrá lo que ocupa lugar cuando ya no sirve: el disco es de todos.
