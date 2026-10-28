# `library` — biblioteca de papers con PDF real (M11, edición developer)

Un lugar razonable y organizado para entrar a los papers que baja el vigilante: **el PDF
de verdad**, buscador de texto completo, etiquetas y anotaciones tipadas sobre *qué se
puede extraer* de cada paper (para pensar tests nuevos o mejoras de la plataforma).

> **Política de PDFs: no se inventa nada.** El archivo se descarga del repositorio del
> editor o de PMC/Europe PMC y se guarda byte por byte. Nunca se genera un PDF con texto
> escrito por el agente. Si no hay versión de acceso abierto, el paper queda
> `status="sin_pdf"` con el motivo, y no se crea archivo.

Todo el módulo vive detrás de `SIFI_EDITION=dev` (default `stable`). En `stable` el CLI y
la API responden con `función de la edición developer`, sin traceback.

---

## Comandos

Desde `core/`:

```bash
export SIFI_EDITION=dev

# alta de un paper (baja el PDF y lo indexa)
python3 -m library.cli add --doi 10.3390/plants15203237 --tag entrega --tag dsrna
python3 -m library.cli add --pmid 42943189
python3 -m library.cli add --url https://www.biorxiv.org/content/10.1101/2025.08.31.673361v1.full.pdf

# importar en lote el digest del vigilante (M7)
python3 -m library.cli import-watch watch/ejemplo_novedades.json --limit 5 --tag novedades
python3 -m library.cli import-watch watch/ejemplo_novedades.json --tag-from-query

# buscar (texto completo: título + abstract + cuerpo del PDF)
python3 -m library.cli search "dsrna delivery"
python3 -m library.cli search '"systemic RNAi"' --tag entrega --year 2026
python3 -m library.cli search "dsrna OR sirna" --status ok --limit 10

# ver, etiquetar, anotar
python3 -m library.cli show 3
python3 -m library.cli show 3 --text --chars 4000
python3 -m library.cli tag 3 +test -entrega
python3 -m library.cli note 3 --kind idea_test "probar el mismo diseño en Dalbulus"
python3 -m library.cli note 3 --kind mejora_plataforma "falta un score por panel"
python3 -m library.cli note 3 --kind riesgo "el ensayo usó microinyección, no foliar"

# resumen y export
python3 -m library.cli stats
python3 -m library.cli export --tag entrega --out /tmp/biblioteca-entrega
```

Opciones globales: `--db PATH`, `--data-dir DIR` (default `~/.sifidesk/library`),
`--cache-dir DIR` (default `~/.cache/sifi-desk/library`), `--offline`, `--json`.

`--offline` no hace ningún request: usa la caché de resolución. Si no hay caché, el paper
queda `sin_pdf` con el motivo (sirve para tests y para trabajar sin red).

### Búsqueda

* `dsrna delivery` → `dsrna* AND delivery*` (AND por defecto, prefijo automático en
  palabras de 4+ letras);
* `"systemic RNAi"` → frase exacta;
* `dsrna OR sirna` → alternativa;
* `tag:entrega` → filtro por etiqueta (también `--tag`);
* `year:2026`, `status:ok` → filtros;
* ranking `bm25(title=8, abstract=3, body=1)`, menor es mejor;
* snippet alrededor del match (marcado con `[[...]]`; el CLI lo resalta si hay TTY).

---

## Esquema (SQLite + FTS5)

```sql
papers(id, doi, pmid, pmcid, title, authors, journal, year, abstract, body,
       oa_status, license, pdf_path, pdf_sha256, pdf_bytes, pages, text_chars,
       status, motivo, added_at, source)

tags(paper_id, tag)                       -- PK(paper_id, tag), FK papers ON DELETE CASCADE
annotations(id, paper_id, kind, text, author, created_at)

papers_fts USING fts5(title, abstract, body, content='papers', content_rowid='id')
```

* `status`: `ok` (PDF real verificado), `sin_pdf` (no hay versión abierta o falló la
  verificación), `error` (reservado).
* `annotations.kind`: `idea_test`, `mejora_plataforma`, `riesgo`, `nota`.
* `pdf_path` es **relativo** a `--data-dir`, así la biblioteca se puede mover.
* `papers_fts` se mantiene sincronizada con triggers `AFTER INSERT/UPDATE/DELETE`:
  no hay reindexado manual.

Dedupe: por DOI, si no PMID, si no PMCID, si no título normalizado (minúsculas, sin
acentos ni puntuación). Los campos vacíos de una fuente no pisan datos ya guardados.

---

## Cómo se decide qué es "accesible"

`fetch.resolve()` arma candidatos en este orden y baja el primero que pase la verificación:

1. **Europe PMC** — `search` (`fullTextUrlList`, licencia, PMCID) y `fullTextXML` del
   PMCID (nombre exacto del PDF, licencia, journal-id).
2. **Unpaywall** — `api.unpaywall.org/v2/{doi}?email=…`: `oa_status`, licencia y
   `url_for_pdf`.
3. **PMC OA** — `idconv` (DOI/PMID → PMCID), `oa.fcgi` y `/articles/{pmcid}/pdf/`.
4. **Portada del editor** — `https://doi.org/{doi}` y su `<meta name="citation_pdf_url">`.
5. **Patrones del editor** — sólo sin adivinar: MDPI (`mdpi-res.com`, con el nombre de
   archivo que dio el JATS) y bioRxiv/medRxiv.

Se considera **abierto** si:

* hay una licencia Creative Commons (BY, BY-SA, BY-NC, BY-NC-SA, BY-ND, BY-NC-ND, CC0) o
  dominio público; **o**
* no hay licencia declarada **y** `oa_status` es `gold`, `hybrid` o `green`.

Quedan afuera (→ `sin_pdf`): `closed`, `bronze` (gratis para leer pero sin licencia
abierta) y cualquier licencia de uso restringido del editor (p. ej. "user licence"). La
regla es deliberadamente conservadora: **no se baja lo que no es abierto**, ni siquiera si
hay una URL de PDF a mano. La excepción es `add --url`: si el usuario pasa una URL
explícita, se verifica el archivo y se guarda (queda `oa_status` unknown), porque el
usuario afirmó que puede usarlo.

HTTP: `User-Agent: sifi-desk/0.1 (mailto:sifi-desk@omnivac.science)`, timeout 30 s,
reintentos con backoff exponencial respetando `Retry-After` (408/425/429/5xx), y caché en
disco de las respuestas de **resolución** (no de los PDFs) con TTL de 30 días
(`SIFI_LIBRARY_CACHE_TTL`).

### Verificación obligatoria

Después de bajar, antes de guardar:

1. los primeros bytes son `%PDF`;
2. tamaño > 20 KB;
3. `pdfinfo` abre el archivo y reporta ≥ 1 página;
4. se calcula `sha256` y se guarda;
5. se extrae texto con `pdftotext -layout`; si el PDF no tiene texto (escaneado), se
   descarta con motivo.

Si falla cualquiera, el archivo temporal se borra y el paper queda `sin_pdf` con el motivo
(p. ej. `el servidor devolvió HTML, no un PDF (Just a moment...)`). El motivo también
conserva los intentos por fuente (`crossref: HTTP 403 | pmc: HTML | mdpi-cdn: ...`).

`extract.normalize_text()` normaliza **sólo espacios** (`\r\n`, tabs, espacios repetidos,
líneas en blanco, `\f`): no resume, no reescribe, no cambia el contenido.

---

## API (para `core/service`)

`library.api.router` es un `APIRouter` con prefijo `/library`:

| método | ruta | qué hace |
|---|---|---|
| GET | `/library/search?q=&tag=&year=&status=&limit=&offset=` | búsqueda full-text |
| GET | `/library/papers?tag=&status=&limit=` | listado |
| POST | `/library/papers` | alta `{doi,pmid,url,tags,force}` |
| GET | `/library/papers/{id-o-doi}` | detalle + anotaciones |
| GET | `/library/papers/{ref}/text?limit=` | texto extraído |
| GET | `/library/papers/{ref}/pdf` | el PDF real (`application/pdf`) |
| GET | `/library/papers/{ref}/annotations?kind=` | anotaciones |
| POST | `/library/papers/{ref}/annotations` | `{kind,text,author}` |
| DELETE | `/library/annotations/{id}` | borrar anotación |
| POST | `/library/papers/{ref}/tags` | `{add:[],remove:[]}` |
| GET | `/library/tags` | etiquetas con conteo |
| GET | `/library/stats` | resumen |

Las líneas exactas para montarlo están en [`NEEDS.md`](NEEDS.md). En `stable` todos los
endpoints devuelven `403` con `detail="función de la edición developer (activar con
SIFI_EDITION=dev)"`.

---

## Tests

```bash
python3 -m pytest -q tests/unit/test_library_store.py tests/unit/test_library_fetch.py \
                    tests/unit/test_library_cli.py tests/unit/test_library_api.py
```

* Sin red: la resolución se simula con respuestas grabadas en `fixtures/` y el PDF de
  prueba se genera en el momento con WeasyPrint (multi-página, > 20 KB).
* Casos: PDF válido guardado con sha256 y texto indexado; HTML en lugar de PDF rechazado
  con motivo; sin acceso abierto no se crea archivo ni se pide el PDF; búsqueda con
  etiqueta y con frase; anotaciones por tipo; edición `stable` → error claro.
* Test de red real, skippeado por defecto:
  `SIFI_NET_TESTS=1 python3 -m pytest -q tests/unit/test_library_net.py -m net`.

## Variables de entorno

| variable | default | para qué |
|---|---|---|
| `SIFI_EDITION` | `stable` | `dev` habilita la biblioteca |
| `SIFI_LIBRARY_DIR` | `~/.sifidesk/library` | base y PDFs |
| `SIFI_LIBRARY_CACHE` | `~/.cache/sifi-desk/library` | caché de resolución |
| `SIFI_LIBRARY_CACHE_TTL` | `720` (horas) | edad máxima de la caché |
| `SIFI_LIBRARY_CONTACT` | `sifi-desk@omnivac.science` | User-Agent / Unpaywall |
| `SIFI_UNPAYWALL_EMAIL` | igual a contact | email para Unpaywall |
| `SIFI_AUTHOR` | usuario del sistema | autor por defecto de las notas |

## Lo que queda afuera (a propósito)

* No hay OCR: un PDF escaneado sin capa de texto se descarta con motivo.
* No se resuelven proxies/paywalls ni se usan credenciales de biblioteca.
* `bronze` no se considera abierto.
* No hay descarga de material suplementario ni figuras sueltas.
* La búsqueda no usa sinónimos ni stemming: prefijos y frases, nada más.
