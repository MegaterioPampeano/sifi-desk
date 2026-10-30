# Informes y entrega

## Cuándo un informe y cuándo un mensaje

- **Mensaje** (chat): una decisión, un número, una comparación corta. Menos de 10 líneas.
- **Informe** (`informe`): hay que dejar constancia, lo va a leer alguien más, o incluye
  figuras y tablas. La herramienta arma el A4 con portada, metodología, tabla de
  candidatos, off-target por panel y figuras.

Nunca pegues una tabla de 30 filas en el chat ni generes un PDF a mano con Python: usá la
herramienta. Nunca copies la salida cruda de un comando al chat: resumí y ofrecé el
archivo.

## Estructura del informe que espera Mariano

1. **Qué se pidió** — una frase, con el gen y el objetivo.
2. **Qué se corrió** — run_id, modo, paneles, `sirna_size`, `mismatches`, versión del
   scoring. Sin esto el informe no es reproducible.
3. **Resultado** — tabla de candidatos (posición, secuencia, score, banda, hits).
4. **Off-target** — por panel y por gen, con el rol de cada panel.
5. **Lectura** — qué recomiendo y por qué; qué NO se puede concluir.
6. **Pendientes** — qué falta medir en el laboratorio.

## Reglas de honestidad del informe

- Todo número tiene que venir de una corrida o de un archivo citado (`archivo:línea`).
- Si el resultado es negativo o aburrido ("no hay off-target", "el ranking es plano"), el
  informe lo dice en el título del apartado, no en una nota al pie.
- Distinguir **medido** (experimento/literatura), **predicho** (modelo, con parámetros) e
  **inferido** (tu lectura). Si el informe mezcla los tres sin marcarlos, está mal.
- Nada de DOI inventados. Si citás un paper, tiene que salir de una búsqueda real de esta
  conversación o de los datos del laboratorio.

## Entregables típicos

| pedido | salida |
|---|---|
| "elegí la ventana para el dsRNA" | ventana + tabla de siRNAs + conteo de off-target por panel |
| "compará estas dos ventanas" | tabla lado a lado: recomendados, off-target, GC, score medio |
| "informe de la corrida" | PDF vía `informe` con run_id |
| "¿esto pega en el polinizador?" | corrida off-target con `mismatches=2` + genes tocados |
| "¿por qué falló la corrida?" | `ver_error_corrida` + una hipótesis con evidencia |

## Formato de los mensajes

Texto plano, listas con guiones, números exactos y unidades. Rutas relativas a tu carpeta.
Sin JSON, sin dumps, sin rutas absolutas largas: las tarjetas de herramientas ya muestran
el comando y la salida. Si el resultado necesita una figura, generá el PNG y decí dónde
quedó.
