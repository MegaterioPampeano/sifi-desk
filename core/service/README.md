# sifid — servicio local de siFi-Desk (M3)

API HTTP local (FastAPI) sobre el core headless. Encola corridas en SQLite y las ejecuta
en un **subproceso** (`python3 -m service.runner`), una por vez. El proceso web nunca
importa el pipeline: así se puede cancelar de verdad, no se cuelga el servidor si el core
explota y no hay estado en memoria que se pierda al reiniciar.

## Arranque

Desde `core/` (ahí vive el paquete `service`):

```bash
cd core
python3 -m service.app --port 8765 --data-dir /tmp/sifid
```

Opciones: `--host` (default `127.0.0.1`), `--panels-root` (default `~/.sifidesk/panels`),
`--log-level`, `--no-worker` (sólo API, para depurar la cola).
También sirve `PYTHONPATH=core python3 -m service.app ...` desde la raíz del repo.

Los binarios se descubren como en la CLI: `SIFI_BOWTIE`, `SIFI_RNAPLFOLD`, `build/` del
checkout o `PATH`. `SIFI_PANELS_ROOT` / `SIFID_DATA_DIR` también se leen del entorno.

## API

| método | ruta | qué hace |
|---|---|---|
| GET | `/health` | estado, cola por estado, worker (vivo / corrida actual) |
| GET | `/panels` | paneles ingerados (id, versión, rol, n_seqs, fingerprint, `index_ok`) |
| POST | `/runs` | encola una corrida → 201 con el run |
| GET | `/runs?status=&limit=&offset=` | lista (más nuevas primero) |
| GET | `/runs/{id}` | detalle: estado, fase, progreso, timestamps, error, request |
| POST | `/runs/{id}/cancel` | cancela (ver abajo) |
| GET | `/runs/{id}/results` | manifest `sifi.results/1` (sólo si `done`) |

`POST /runs` — cuerpo (todos los campos están en `service/models.py`):

```json
{
  "mode": "design",                  // design | offtarget
  "query_path": "/ruta/query.fa",    // o "query_fasta": ">id\nACGT..."
  "db_dir": "/tmp/toydb",            // o "panel_id": "toy" (+ "panel_version" opcional)
  "db_name": "toyidx",
  "sirna_size": 21,
  "mismatches": 0,
  "main_target_mode": "auto",        // auto | explicit (+ "main_targets": ["GeneA"])
  "bowtie": null, "rnaplfold": null, // override de binarios
  "extra_meta": {}
}
```

Validaciones (400/422 con mensaje en castellano): exactamente una fuente de query, el
FASTA tiene que tener registros, la base/panel tiene que existir y tener índice `.1.ebwt`,
`panel_id` y `db_dir` son excluyentes, `main_target_mode=explicit` exige `main_targets`,
parámetros dentro de rango y sin campos desconocidos (`extra="forbid"`).

En modo `offtarget` se aplican los mismos defaults que `sifi offtarget` de la CLI:
`end_check=False`, `accessibility_check=False` (sólo hebra + terminales).

La query **se copia** al run dir al encolar: la corrida queda reproducible aunque el
archivo original cambie o desaparezca.

## Estados

```
queued ──claim──> running ──rc=0 + manifest──> done
   │                 ├───────── rc!=0 / excepción ──> error
   └── cancel ──> cancelled <── cancel (mata el grupo de procesos) ──┘
```

* `queued` → `running`: lo hace el worker al reclamarla (atómico en SQLite).
* `error` guarda `error` (texto) y `exit_code` del runner.
* `cancelled` es una decisión del usuario; `error` con prefijo `interrupted:` es una
  corrida que quedó a medias porque se cayó/detuvo el servicio.
* `progress` = `{done, total, percent}`. `total` es la cantidad de registros del FASTA
  de entrada. Hoy el core no reporta avance por registro, así que `done` pasa de 0 a
  `total` (ver `NEEDS.md` #1).

## Cancelación

* `queued`: pasa a `cancelled` en el acto, sin arrancar nada.
* `running`: se marca `cancel_requested`, el worker manda `SIGTERM` al **grupo de
  procesos** del runner (que corre en su propia sesión, `start_new_session=True`), espera
  3 s y manda `SIGKILL`. Los binarios nietos (bowtie, RNAplfold) mueren con el grupo:
  no quedan huérfanos (test e2e con un runner que lanza un nieto).
* `done`/`error`/`cancelled`: 409.

Al arrancar, el servicio revisa las corridas que quedaron `running` de una vida anterior:
si el PID sigue siendo el runner de esa corrida (se valida contra `/proc/<pid>/cmdline`,
para no matar por PID reciclado) mata el grupo y marca `error: interrupted: ...`. Las
`queued` se retoman solas.

## Layout en disco

```
<data-dir>/
  sifid.sqlite3                  cola (WAL) — única fuente de verdad
  runs/<run_id>/
    spec.json                    todo lo necesario para reproducir la corrida
    input.fa                     copia de la query
    stderr.log                   stderr del runner (trazas del core)
    out/results.json             manifest sifi.results/1
    out/sirnas.tsv
```

## Tests

```bash
python3 -m pytest -q tests/unit/test_service_queue.py tests/unit/test_service_api.py \
                    tests/unit/test_service_e2e.py
```

* `test_service_queue.py` — orden FIFO, estados, progreso, cancelación, persistencia y
  recuperación tras reinicio (sin binarios).
* `test_service_api.py` — validaciones, 404/409, paneles, sin worker.
* `test_service_e2e.py` — pipeline real con el índice de juguete (`toyidx` armado en un
  temporal a partir de `tests/data/toy.fa`), corrida completa + manifest, dos corridas en
  orden, y cancelación de una corrida en curso verificando que muere el árbol de procesos.

Los tests que necesitan binarios se saltean si no encuentran `bowtie`/`RNAplfold`
(buscan en `SIFI_*`, `PATH` y `build/`, también en el checkout principal cuando se corre
desde un worktree).

## Decisiones

* **Un worker, un subproceso.** Menos concurrencia, pero cancelación limpia, aislamiento
  de fallas y ningún estado del core en el proceso web.
* **SQLite como cola.** Sin broker ni dependencias: la cola sobrevive reinicios y se puede
  inspeccionar con `sqlite3`.
* **Rutas del lado servidor.** sifid es local (loopback, sin auth en v1); la UI/agente
  nunca tocan el filesystem. Ver `TODO.md` para el endurecimiento pendiente.
