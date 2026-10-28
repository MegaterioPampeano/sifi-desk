# Paridad aleatoria — port (`core/sifi`) vs original siFi21

* **Fecha:** 2026-10-28 22:17:25Z
* **Semilla:** `20261028` (generador determinista)
* **Comando:** `python3 tests/fuzz_parity.py --seed 20261028 --jobs 4`
* **Corridas pareadas:** 120 del producto {secuencia} × {mismatches} × {modo} + 1 caso borde = 121 pareadas (242 ejecuciones: original + port en cada una)
* **Filas comparadas:** 196,040 (× 14 campos = 2,744,560 valores)
* **Duración:** 31.1 s (pared, 4 procesos)

Cada corrida usa **los mismos binarios** en los dos lados (bowtie / RNAplfold del `build/`), así que cualquier diferencia es del port. Comparación: mismo orden de claves, misma cantidad de filas, igualdad exacta para str/int/bool y `math.isclose(rel_tol=1e-9, abs_tol=1e-9)` para floats.

## Desvío por campo

| campo | tipo | corridas | valores comparados | desvío máx absoluto | desvío máx relativo | valores con desvío | NaN en ambos |
|---|---|---:|---:|---:|---:|---:|---:|
| `query_name` | str | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `sirna_name` | str | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `sirna_position` | int | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `sirna_sequence` | str | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `is_efficient` | bool | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `strand_selection` | bool | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `end_stability` | bool | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `target_site_accessibility` | bool | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `accessibility_value` | float | 120 | 196,040 | 0 (exacto) | 0 (exacto) | 0 | 0 |
| `is_off_target` | bool|null | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `hit_name` | str|false | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `reference_strand_pos` | int|null | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `strand` | str|null | 120 | 196,040 | — (exacto) | — | 0 | 0 |
| `mismatches` | str|null | 120 | 196,040 | — (exacto) | — | 0 | 0 |

(`—` = campo no flotante: se compara con igualdad exacta, sin tolerancia.)

## Cobertura del barrido

| secuencia | largo | GC objetivo | GC real | tipo | filas (todas las corridas) |
|---|---:|---:|---:|---|---:|
| `synth01` | 585 | 30% | 30.1% | homopolimero A/T | 54,628 |
| `synth02` | 358 | 45% | 45.0% | balanceada | 5,148 |
| `synth03` | 337 | 60% | 59.9% | balanceada | 4,816 |
| `synth04` | 377 | 70% | 70.0% | GC con repeticiones | 27,828 |
| `synth05` | 520 | 30% | 30.0% | balanceada | 7,600 |
| `synth06` | 546 | 45% | 45.1% | balanceada | 7,988 |
| `synth07` | 330 | 60% | 60.0% | balanceada | 4,738 |
| `synth08` | 309 | 70% | 69.9% | balanceada | 4,406 |
| `synth09` | 301 | 30% | 29.9% | balanceada | 4,286 |
| `synth10` | 575 | 45% | 45.0% | balanceada | 8,444 |
| `synth11` | 422 | 60% | 60.0% | balanceada | 6,154 |
| `synth12` | 529 | 70% | 69.9% | balanceada | 7,830 |
| `synth13` | 497 | 30% | 30.0% | balanceada | 7,202 |
| `synth14` | 340 | 45% | 45.0% | balanceada | 4,894 |
| `synth15` | 506 | 60% | 60.1% | balanceada | 7,320 |
| `synth16` | 375 | 70% | 69.9% | balanceada | 5,406 |
| `synth17` | 402 | 30% | 30.1% | balanceada | 5,892 |
| `synth18` | 571 | 45% | 45.0% | balanceada | 8,424 |
| `synth19` | 337 | 60% | 59.9% | balanceada | 4,916 |
| `synth20` | 553 | 70% | 70.0% | balanceada | 8,120 |

* filas totales (lado original): 196,040; máximo de siRNAs distintos en una corrida: 565
* `is_off_target`: 60,106 True / 37,914 False / 98,020 None
* filas eficientes: 55,242
* `target_site_accessibility` (derivado del float): 51,762 True / 144,278 False; valores distintos de `accessibility_value` en una corrida (máx.): 565
* descriptores de mismatches distintos: 3,352 (ej.: 0, 0:A>C, 0:A>C,10:G>T, 0:A>C,11:C>A …)

## Casos borde

La corrida extra `orphan01` usa una secuencia que **no está** en el índice: ejercita el camino "sin hits" de design. Ahí los dos lados abortan con el mismo mensaje (`No targets found. Please make sure that the query and/or database sequences are in correct orientation.`), así que la paridad es del error, no de las filas (0 filas: la rama sin hits nunca entra en `if strand == '+'`).

## Control negativo del comparador

Para que un verde signifique algo, el comparador tiene que saber fallar:

| caso | debía fallar | falló |
|---|---|---|
| identicas | no | no |
| float +1e-12 (dentro de tolerancia) | no | no |
| float x1.000001 (fuera de tolerancia) | sí | sí |
| bool invertido | sí | sí |
| int vs float 7 vs 7.0 | sí | sí |
| string distinta | sí | sí |
| fila de menos | sí | sí |
| fila de mas | sí | sí |
| nan a los dos lados | no | no |
| nan de un solo lado | sí | sí |
| orden de claves distinto | sí | sí |

Todos los casos del control se comportaron como se esperaba: **sí**.

Además hay una prueba de mutación end-to-end: `--mutate-float` multiplica por `1+1e-6` el `accessibility_value` del port dentro del pipeline real. Con `--sequences 1` el barrido reporta 102 diferencias con desvío relativo 1.0e-06 (es decir: el detector ve una deriva de una parte en un millón). Repetir con: `python3 tests/fuzz_parity.py --sequences 1 --mutate-float`.

## Diferencias encontradas

Ninguna. 0 diferencias en 14 campos × todas las filas.

Abortos con paridad (mismo mensaje en original y port): `orphan01/mm0/design`.
Mensaje: `No targets found. Please make sure that the query and/or database sequences are in correct orientation.`

## Veredicto

**PARIDAD MEDIDA: el port reproduce el original en todo el barrido.** 121 corridas pareadas, 196,040 filas, desvío máximo en `accessibility_value` = 0 (exacto); el resto de los campos, igualdad exacta.
