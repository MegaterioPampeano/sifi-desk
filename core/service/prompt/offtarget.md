# Paneles, off-target y los dos modos de corrida

## Los dos modos no son intercambiables

- **`design`**: entra un gen (o un transcrito), sale un ranking de siRNAs contra ese gen.
  El campo `database` de la corrida **no** es el gen atacado: es el **índice de
  off-targets** (los paneles). Confundirlos es el error más común: si ponés el gen blanco
  como database, cada candidato va a "pegar" en sí mismo y el ranking se llena de ruido.
- **`offtarget`**: no diseña nada. Toma siRNAs ya elegidos y los cruza contra los paneles
  para ver qué tocan. Se usa para auditar una ventana antes de sintetizarla.

### Cero hits en modo off-target es un resultado, no un error

Si en modo off-target no aparece ningún hit, la corrida es **válida** y el resultado es el
buscado: la secuencia no toca nada del índice. El pipeline devuelve `sirnas: []`, el
summary en cero y un warning que lo explica. No es "No targets found" (ese error es sólo
para modo design, y significa que el query y la base están en orientaciones distintas o
que el query no tiene nada que ver). Si querés más sensibilidad, subí `mismatches` a 3 y
volvé a correr.

## Los paneles

Cada panel tiene un rol, y el rol define cuánto pesa un hit:

| rol | qué es | cómo se lee un hit |
|---|---|---|
| `blanco` | el gen atacado | esperable; no cuenta como riesgo |
| `no_blanco` | especie que no querés dañar (polinizador, enemigo natural) | riesgo alto |
| `control` | gen de referencia del ensayo | riesgo crítico: invalida la medición |
| `relacionado` | pariente cercano del blanco | riesgo medio; mirar conservación |

Un panel se registra con `sifi panel add <fasta> --id <id> --rol <rol>` y queda indexado
para búsquedas. `listar_paneles` muestra id, rol, cantidad de secuencias y si el índice
está ok: **si `index_ok` es false, los resultados de ese panel no valen** y hay que
reindexar antes de sacar conclusiones.

## Mismatches

- `mismatches=0`: sólo hits idénticos. Sirve para descartar por lo seguro, y suele dar
  falsos negativos en especies con genomas incompletos.
- `mismatches=1`: el estándar para decidir.
- `mismatches=2`: lo que se usa para el screen fino de una ventana candidata: muestra los
  Off-targets plausibles sin llenar la tabla de ruido.
- `mismatches=3`: auditoría de sensibilidad. Sube mucho el número de hits y baja la
  señal; se usa para saber si una ventana "limpia" lo es por suerte o por secuencia.

## Cómo leer la tabla de resultados

1. **Mirá primero `genes_por_panel`, no el conteo.** Un hit en un gen conservado vale más
   que veinte hits en regiones no codificantes.
2. **Un hit en el polinizador con 0 mismatches descalifica la ventana**, aunque el score
   sea 98. No hay score que compense eso.
3. **Los off-target en el blanco son el diseño funcionando**, no un defecto.
4. **Si el panel de control tiene hits, el ensayo no sirve**: cambiá la ventana o el
   control, no el criterio.
5. **Chequeá la orientación del FASTA**: un gen en antisentido da cero hits y parece
   "limpísimo". Si una ventana no tiene ningún hit ni en el blanco, sospechá orientación.

## Auditar una ventana (receta)

1. Extraer la ventana del transcrito (`transcrito` + coordenadas, o Python sobre el FASTA).
2. Correr `design` sobre la ventana con el índice de paneles, `sirna_size=21`,
   `mismatches=2`.
3. Contar cuántos siRNAs de la ventana quedan "recomendados" y cuántos tienen off-target
   en `no_blanco`/`control`.
4. Comparar contra la ventana alternativa por especificidad, no por score medio.
5. Recién ahí elegir la ventana; el dsRNA se pide sobre la región, no sobre un siRNA.
