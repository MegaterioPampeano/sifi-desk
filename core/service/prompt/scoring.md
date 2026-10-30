# El score: qué mide y cuánto pesa

El score va de 0 a 100 y es la suma ponderada de cinco ejes. Está implementado en
`score.yaml` v2 del servicio; si el número que ves no cierra con la fórmula, primero
revisá la versión del scoring de la corrida antes de discutir el resultado.

    score = 40·E + 15·R + 15·S + 15·T + 15·D

## E — eficacia predicha (peso 40)

    E = 0,50·accesibilidad + 0,25·asimetría de hebra + 0,25·estabilidad de extremos

- **Accesibilidad**: cuánto se abre la estructura secundaria del transcrito en esa ventana
  (RNAplfold). Es el componente que más manda dentro de E.
- **Asimetría**: la hebra guía tiene que entrar al RISC. A/U en el 5' de la antisentido,
  G/C en el 5' del pasajero, y 13-19 de la guía más rico en A/U.
- **Extremos**: penaliza ventanas pegadas a los bordes del transcrito, donde la
  accesibilidad calculada suele ser artefactual.

## R — riesgo de off-target (peso 15)

    R = 1 − riesgo

    riesgo = Σ sobre cada hit (severidad(mismatches) × peso_del_rol) + 0,15·(paneles extra)

| mismatches | severidad |
|---|---|
| 0 | 1,00 |
| 1 | 0,70 |
| 2 | 0,40 |
| 3 | 0,15 |

Los pesos por rol salen del panel: `blanco` pesa 0 (es el gen atacado, pegar ahí es el
objetivo), `relacionado` pesa menos que `no_blanco`, y `control` es el que más pesa porque
un hit en el control invalida el ensayo.

## S — especificidad (peso 15)

    S = 1 / (1 + Σ 1/(1 + mismatches))

Cuenta cuántos hits hay y cuán cerca están. Muchos hits con 3 mismatches bajan menos que
uno solo con 0. Es complementario a R: R mira gravedad, S mira cantidad.

## T — termodinámica (peso 15)

    T = 1,00 si el siRNA está marcado como eficiente por el modelo termodinámico
    T = 0,15 si no

Es deliberadamente binario: el delta de ΔG entre dos siRNAs "eficientes" no es
distinguible con los datos que tenemos, y fingir precisión ahí sería inventar.

## D — diseño intrínseco (peso 15)

    D = 0,50·GC + 0,25·homopolímero + 0,25·extremo 5'

- **GC**: 35-55% = 1,00; 25-35% y 55-65% rampa de 0,4 a 1,0; fuera de 25-65% = 0,15.
- **Homopolímero**: 1,00 sin tramos de 5+; castiga proporcional al largo del tramo.
- **Extremo 5'**: 1,00 si el 5' de la guía no es rico en GC; decae si lo es.

## Bandas de decisión

| score | banda | qué significa |
|---|---|---|
| ≥ 70 | recomendado | candidato para pedir el dsRNA |
| 50-69 | revisar | sirve, pero mirá por qué perdió puntos |
| 25-49 | bajo | sólo como respaldo |
| < 25 | descartar | no vale el costo de síntesis |

## Malentendidos frecuentes

- **"El GC mueve el score"**: mueve como máximo 7,5 puntos (mitad de D, que pesa 15). Lo
  que manda es accesibilidad (20 puntos dentro de E) más R+S+T (45 puntos).
- **"Subir el peso de R mejora la selección"**: sólo si el panel de off-target está bien
  armado. Con un panel incompleto, R premia la falta de datos, no la especificidad.
- **"Todos los recomendados son iguales"**: no. Ordená por score y mirá el segundo
  decimal: las diferencias chicas sí separan cuando el resto del ranking es plano.
- **"Si el score es 96, la eficacia es 96%"**: no existe esa conversión. El score es
  ordinal, no probabilístico.
