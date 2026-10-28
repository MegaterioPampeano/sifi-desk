# PORT_NOTES — qué se cambió al portar si-Fi a Python 3 headless

Regla del port: **la matemática no se toca**. Todo cambio está en esta tabla con su
justificación. Lo que no está acá, es idéntico al original.

## 1. Cambios obligatorios (py2 → py3)

| # | Original | Port | Motivo |
|---|---|---|---|
| 1 | `print x[0], x[1], x[2]` | `log.debug(...)` | sintaxis py2 |
| 2 | `np.float` | `float` | eliminado en numpy ≥ 1.24 |
| 3 | `np.loadtxt(..., dtype='str')` | igual, + `reshape(1,-1)` si es 1D | numpy 2 devuelve escalar en matrices de 1 fila |
| 4 | `SeqIO.parse(..., "fasta")` con `Bio.Alphabet` | sin `Alphabet` | eliminado en Biopython ≥ 1.78 |
| 5 | `Bio.SeqUtils.GC(seq)` | `gc_fraction(seq)*100` | eliminado en Biopython ≥ 1.80. **Verificado: mismo valor** (era un porcentaje float) |
| 6 | `prc.stdin.write(seq)` | `prc.stdin.write(seq.encode())` | stdin binario en py3 |
| 7 | `tempfile.mkstemp()` (fd sin cerrar) | `run_dir` explícito | el original filtraba file descriptors |
| 8 | `os.chdir(bowtie_location)` global | `cwd=` en cada `subprocess` | el chdir global rompía cualquier uso concurrente |
| 9 | `db_location + db_name` (concatenación cruda) | `os.path.join` | el original exigía pasar la ruta **con** barra final |
| 10 | `sifi_l` mutable de instancia | igual (idéntico) | se mantiene el estado por registro, como el original |

## 2. Cambios de arquitectura (el "corte headless")

| # | Original | Port |
|---|---|---|
| 11 | `popup.ListSelection(...).get_seletced(...)` (Qt modal) | `resolve_main_targets()`: lista explícita o modo `auto` |
| 12 | `show_plot.DrawPlot(...).show()` dentro de `run_pipeline` | eliminado: `run()` devuelve `PipelineResult` y **corta antes de la GUI** |
| 13 | JSON se escribe a `%TEMP%` y se pierde | `PipelineResult.dump_json(path)` explícito + `results.json` versionado |
| 14 | `run_pipeline` es una `@property` con efectos | `run()` es un método que devuelve valores |
| 15 | errores → `QMessageBox` | `PipelineResult.error` (string) o excepción |

Ninguno de estos cambios afecta los números: el corte está **después** de `data_to_json`.

## 3. Divergencias de robustez (documentadas a propósito)

| # | Situación | Original | Port |
|---|---|---|---|
| 16 | Una fila de `_lunp` contiene `NA` en *cualquier* columna | `astype(float)` revienta | se convierte sólo la celda usada; `NA` → `nan` → no eficiente |
| 17 | bowtie devuelve rc=1 (sin alineamientos) | sigue de largo, falla más tarde | se acepta rc=1 como "sin hits" |
| 18 | El FASTA de entrada no tiene registros | `IndexError` | `error="El FASTA de entrada no contiene registros."` |

Donde el original *funcionaba*, estos cambios dan exactamente el mismo resultado.

## 4. Constantes que NO se tocaron (críticas para la fidelidad)

```
sirna_size              21
overhang                 2
end_nucleotides          3
winsize (-W)            80
span (-L)               40
temperature (-T)      22.00   ← el original usa 22 °C, no 37
accessibility_window     8    ← columna de _lunp (u=8)
end_stability_thr      1.0
accessibility_thr      0.1
mismatches (bowtie -v)   0    ← default del GUI (index 0 del combo)
bowtie flags    -a -v N -y
```

Defaults del GUI replicados: `design` → strand+end+access+terminal ON;
`offtarget` → strand+terminal ON, end+access OFF (`main.py:set_*_settings`).

## 5. Verificación (test diferencial)

`tests/diff_oracle.py` corre el **fuente original** (con parches mecánicos py3 y la GUI
stubbeada) y el port, con los **mismos binarios**, y compara el JSON fila por fila,
campo por campo (14 campos, floats a 1e-9).

Resultado al 2026-10-28 (gen sintético de 300 nt + decoy con 3 mismatches):

| Config | Filas | Resultado |
|---|---|---|
| design, v=0, main=GeneA | 280 | idéntico |
| design, v=1, main=GeneA | 320 | idéntico |
| design, v=2, main=GeneA | 324 | idéntico |
| design, v=3, main=GeneA | 326 | idéntico |
| off-target, v=2 | 324 | idéntico |
| design, v=0, main=DecoyB | 280 | idéntico |

Pendiente: (a) oráculo con el `.exe` real bajo Wine/Windows para cerrar la duda de
versiones de librería del binario original; (b) genes reales de *Dalbulus maidis*.

## 6. Paridad aleatoria (barrido, no un caso)

El test de §5 prueba **un** transcrito. `tests/fuzz_parity.py` (target `make paridad`,
fuera del ciclo corto) barre {secuencia} × {mismatches 0/1/2} × {design, offtarget} sobre
20 transcritos sintéticos de 300-600 nt con GC planificado (30/45/60/70 %, incluido un
homopolimérico A/T y uno rico en GC con repeticiones), semilla fija `20261028`.

El índice se arma con tres copias por transcrito (`T` exacta, `A` ~1 mutación/45 nt,
`B` ~1/22 nt con prefijo): sin copias mutadas el barrido sería trivial, porque una
secuencia aleatoria no alinea y nunca se ejecutaría el camino de ΔG / off-target.

Resultado al 2026-10-28: **120 corridas pareadas + 1 caso borde, 196.040 filas, 0
diferencias**. `accessibility_value` con desvío máximo 0.0 (abs y rel): los dos lados
parsean la misma `_lunp` y redondean igual. Detalle en `tests/paridad/REPORTE.md`
(+ `resumen.json` para graficar).

Controles para que el verde signifique algo: 11 casos de control negativo del comparador
y `--mutate-float`, que perturba el port 1e-6 dentro del pipeline real y hace fallar el
barrido con 102 diferencias (desvío rel. 1.0e-06).

    python3 tests/fuzz_parity.py --seed 20261028 --jobs 4     # ~35 s, 4 procesos
