# Dominio: dsRNA contra Dalbulus maidis

## El sistema

*Dalbulus maidis* (chicharrita del maíz) transmite Spiroplasma kunkelii, Maize bushy stunt
phytoplasma y Maize rayado fino virus. En Argentina su expansión acompañó los inviernos
suaves y el maíz tardío; el daño no es la picadura sino la enfermedad que vectoriza. Por
eso el blanco de un dsRNA no es matar al insecto de inmediato: es bajar la población o
cortar la transmisión.

**BicC (Bicaudal C)** es el blanco de referencia del laboratorio. RNA-binding, ovogénesis.
En *D. maidis* está descrito por Dalaisón-Fuentes et al. 2022 (Pest Manag Sci 78:3108,
doi 10.1002/ps.6937): el dsRNA baja el transcrito hasta 170× y reduce la oviposición. Todo
diseño nuevo se compara contra ese trabajo, no contra la intuición.

## Qué hace bueno a un siRNA dentro de un dsRNA

Un dsRNA de 200-400 nt se procesa en el insecto en siRNAs de ~21 nt. Eso cambia el
criterio respecto de un siRNA sintético:

- **Todos los siRNAs del dsRNA están presentes.** No se elige uno: se elige una región
  donde la mayoría de las ventanas sea buena. Un dsRNA de 300 nt son ~280 ventanas.
- **La especificidad pesa más que la eficiencia.** Una ventana con 3 off-targets en el
  polinizador es preferible a una con 18 aunque la eficiencia predicha sea 2 puntos mayor.
  El daño ecológico y regulatorio no se compensa con 2 puntos de score.
- **La región tiene que ser exclusiva del blanco.** Si la ventana cae en un dominio
  conservado (quinasa, WD40, RRM), va a pegar en parientes. Los dominios conservados se
  evitan incluso si el score global sube.
- **El largo importa por costo, no por eficacia.** 200-400 nt es el rango práctico de
  síntesis y de estabilidad. Menos de 150 nt deja pocas ventanas; más de 500 encarece sin
  agregar especificidad.
- **La hebra guía manda.** Vale la asimetría clásica: A/U en el 5' de la antisentido, G/C
  en el 5' del pasajero, 13-19 de la guía con más A/U que el pasajero, y ausencia de
  tramos largos de GC en la guía.

## Reglas duras de diseño (se chequean siempre)

- GC de la ventana entre 35% y 55%. Fuera de 30-60% es descarte.
- Sin homopolímeros de 5 o más (AAAAA, GGGGG, TTTTT, CCCCC).
- Sin motivos inmunoestimulantes conocidos en la hebra larga.
- Evitar extremos 5' ricos en GC en la guía.
- Evitar repeticiones invertidas que plieguen el dsRNA sobre sí mismo.
- Descartar ventanas que solapen el poly-A, el adaptador o los extremos del transcrito:
  ahí la accesibilidad es artefactual.

## Números que ya están medidos en el laboratorio

- Off-target humano, polinizador (*Apis mellifera*) y lombriz (*Eisenia fetida*) se buscan
  contra paneles propios, no contra NCBI completo: el panel es el índice y el criterio.
- Un hit con 0 mismatches en el blanco es lo esperado; el riesgo está en `no_blanco`,
  `control` y `relacionado`.
- La termodinámica (ΔG de apertura del sitio) correlaciona con eficacia mejor que el
  contenido de GC. Si hay que elegir entre dos ventanas parecidas, gana la de mejor ΔG.

## Cómo se interpreta un resultado

1. **Score alto no es eficacia medida.** Es una predicción in silico con pesos elegidos.
   Decilo cada vez que recomiendes algo.
2. **Un solo siRNA perfecto no justifica un dsRNA.** Mirá la distribución de la ventana:
   si 30 de 300 ventanas son buenas, el dsRNA va a producir mayormente siRNAs mediocres.
3. **Los off-target en el panel blanco son esperables** (es el mismo gen). El número que
   importa es el de los otros paneles.
4. **Si todos los candidatos dan parecido, sospechá del panel o del índice**, no del
   diseño. Un ranking plano suele ser un panel mal armado o un FASTA con una sola isoforma.
