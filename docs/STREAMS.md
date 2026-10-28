# STREAMS — frentes de trabajo en paralelo

Cada frente corre en su **propio git worktree + rama**, para que varios subagentes trabajen a
la vez sin pisarse. El supervisor (cron `sifi-reporte`) los lanza, verifica y mergea.

| Frente | Rama | Worktree | Dueño de archivos |
|---|---|---|---|
| `servicio` (M3) | `w/servicio` | `/mnt/datos/work/servicio` | `core/service/**`, `tests/unit/test_service_*.py` |
| `reportes` (M6) | `w/reportes` | `/mnt/datos/work/reportes` | `core/report/**`, `tests/unit/test_report_*.py` |
| `novedades` (M7) | `w/novedades` | `/mnt/datos/work/novedades` | `core/watch/**`, `tests/unit/test_watch_*.py` |

## Contrato común (igual para los tres)

1. **Sólo se escriben los archivos propios del frente.** `core/sifi/**`, `vendor/`, `docs/ROADMAP.md`
   y `NEXT.md` son de sólo lectura: si hace falta un cambio ahí, se anota en
   `docs/PREGUNTAS.md` y se sigue por otro lado.
2. Se **importa** el core (`from sifi.run import run_once`, `from sifi.scoring import ...`),
   nunca se copia código.
3. Todo lo nuevo tiene que funcionar **sin red** salvo el frente `novedades`, y sin credenciales
   salvo las que se lean de variables de entorno (nunca hardcodeadas).
4. Tests propios en `tests/unit/`, sin tocar los tests existentes. `python3 -m pytest -q tests` verde.
5. Commits en la rama del frente, mensaje `Mx: <frente>: <qué>`. **No** mergear, **no** tocar master.
6. Si el paso no se puede terminar en la ventana: dejar el código consistente, tests verdes,
   y anotar en `core/<frente>/TODO.md` qué falta exactamente.

## Definición de "listo" por frente

### servicio (M3)
* `core/service/app.py`: FastAPI con `POST /runs`, `GET /runs`, `GET /runs/{id}`,
  `POST /runs/{id}/cancel`, `GET /runs/{id}/results`, `GET /health`.
* Cola persistente en SQLite (`core/service/queue.py`), un worker a la vez (siFi usa
  archivos temporales y binarios externos: no conviene paralelismo dentro de una corrida).
* Estado por corrida: `queued|running|done|error|cancelled`, con `progress` (registros
  procesados / total), `started_at`, `finished_at`, `error`.
* Cancelación real: `terminate()` del subproceso + marca `cancelled` (no dejar huérfanos).
* Los resultados se guardan como el manifest de `run_once` (mismo esquema `sifi.results/1`).
* Test: encolar 2 corridas con el índice de juguete, verificar orden, estados y cancelación.

### reportes (M6)
* `core/report/render.py`: `render(results_json, out_dir, fmt="pdf") -> path` con Jinja2 + WeasyPrint.
* Secciones: portada (quién/qué/cuándo), parámetros y versiones (del manifest), tabla de
  candidatos ordenada por score, desglose E/R/T/S/D, figura de distribución de eficiencia,
  figura de hits por panel, y **avisos de limitaciones** (texto fijo, honesto).
* Funciona con `results.json` de una o varias corridas.
* Test: renderizar desde `tests/data/results_fixture.json` y verificar que el PDF existe,
  pesa > 20 KB y contiene los nombres de los candidatos en el texto extraído.

### novedades (M7)
* `core/watch/sources.py`: Crossref, PubMed (E-utilities), bioRxiv — consultas por tema
  configurable (`config/watch.yaml`), con `User-Agent` identificable y backoff.
* `core/watch/store.py`: `inventory.json` con ids vistos; `diff()` devuelve sólo lo nuevo.
* `core/watch/cli.py`: `python3 -m watch.cli run --since 7d --out novedades.json`.
* Test: con respuestas HTTP grabadas (fixtures), sin red; verificar deduplicación y diff.
