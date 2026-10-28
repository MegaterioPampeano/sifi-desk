# NEEDS — lo que el servicio necesita del core (`core/sifi/`)

> Regla del frente M3: no se toca `core/sifi/**`. Todo lo que haría falta del otro lado
> se anota acá, con el impacto concreto. Nada de esto bloquea a M3: hay workarounds.

## 1. Progreso por registro en `run_once` / `SifiPipeline.run`

**Qué falta:** un hook de avance. Hoy `run_once()` procesa todos los registros del FASTA
de una sola vez y devuelve el manifest al final; el servicio no puede saber cuántos van.

**Impacto:** `GET /runs/{id}` sólo puede mostrar `progress: {done: 0, total: N}` mientras
corre y saltar a `N/N` al terminar. Con un FASTA de 10 secuencias y minutos de corrida, la
UI no puede distinguir "trabajando" de "colgado".

**Pedido mínimo:**

```python
run_once(..., progress: Callable[[int, int, str], None] | None = None)
# progress(registros_terminados, registros_total, nombre_query)
```

El runner (`service/runner.py`) ya sabe traducir eso a eventos JSON; es cambiar una línea
allá y una acá.

## 2. Cancelación cooperativa (opcional, complementa al SIGTERM)

El servicio mata el grupo de procesos, que funciona siempre. Pero si el core pudiera
cortar entre registros (chequear un `threading.Event`/callback entre queries) se evitaría
perder el trabajo ya hecho y se podría devolver un manifest parcial.

**Pedido mínimo:** `run_once(..., should_stop: Callable[[], bool] | None = None)`.

## 3. Off-target contra varios paneles en una corrida

`sifi.run.run_once()` recibe **un** `db_dir` + **un** `db_name`. El registro de paneles
(`PanelsRegistry.resolve`) ya devuelve la lista de prefijos en orden, pero el core no tiene
dónde recibirlos.

**Impacto:** hoy `POST /runs` acepta `panel_id` (uno solo) o `db_dir`+`db_name`. Evaluar
contra patógeno + no-blanco + humano en una sola pasada requiere N corridas y mergear a
mano, con fingerprints por panel.

**Pedido mínimo:** aceptar `db_prefixes: list[tuple[db_dir, db_name]]` (o `db_names` con un
`db_dir` común) y registrar en el manifest el fingerprint de cada uno.

## 4. `run_id` determinístico (nice to have)

`run_once` genera el `run_id` a partir del contenido + timestamp, así que la misma corrida
dos veces da ids distintos. Para idempotencia del servicio (reintentar un `POST /runs`
idéntico) vendría bien poder pasar `run_id=` o tener un modo `dedupe=True` que devuelva el
manifest existente si el hash coincide.

## 5. Códigos de salida tipados (nice to have)

`core/cli.py` devuelve 2 cuando algún registro tiene `error` pero el manifest es válido.
El servicio hoy trata `rc != 0` como `error` de la corrida salvo que el runner haya emitido
un manifest (el runner sale 0 igual). Si la CLI pasa a distinguir "corrida con registros
fallidos" de "corrida rota", el servicio puede reflejarlo en `status` (`done` con
`warnings`) en vez de tener que inferirlo del manifest.
