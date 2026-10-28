# watch — vigilante de novedades (frente M7)

Busca por su cuenta papers nuevos sobre RNAi/dsRNA/siRNA en insectos y fitopatógenos, y
versiones nuevas del siFi upstream. El agente no "recuerda" buscar: corre el comando, lee
el JSON y cuenta lo que apareció **desde la última vez**.

```
cd core
python3 -m watch.cli run --since 7d --out novedades.json
python3 -m watch.cli run --since 7d --offline --out novedades.json   # sólo caché
python3 -m watch.cli sources                                        # qué se vigila y por qué
```

## Qué hace una corrida

1. Lee `config/watch.yaml` (queries por tema, ventana, límites).
2. Consulta **Crossref**, **PubMed**, **bioRxiv** y (opcional) **releases de GitHub** por cada
   query, con `User-Agent: sifi-desk/0.1 (mailto:…)`, timeout, backoff exponencial ante
   429/5xx y caché en disco (24 h por defecto).
3. Filtra por relevancia: `topic_any` **AND** `context_any` (ver la cabecera del YAML).
   Crossref no siempre trae abstract, así que ahí alcanza con el tema.
4. Descarta lo que tenga fecha fuera de la ventana (guarda final, aunque la API se equivoque).
5. Deduplica (DOI, PMID y título normalizado) y resta el `inventory.json`: sólo queda lo nuevo.
6. Escribe el digest, imprime el resumen y **marca** lo nuevo como visto.

## Salida

`--out novedades.json` → `schema: sifi.watch.digest/1`:

```json
{
  "since": "2026-10-21", "until": "2026-10-28",
  "counts": {"fetched": 40, "in_window": 40, "dropped_old": 0, "new": 12, "inventory_entries": 130},
  "items": [{
    "id": "doi:10.1021/acs.jafc.6c11603",
    "title": "Fusion dsRNA Enhances RNAi Efficiency …",
    "source": "crossref", "date": "2026-10-28",
    "doi": "10.1021/acs.jafc.6c11603", "pmid": "",
    "query": "RNAi dsRNA insect pest control", "why": "RNAi en insectos plaga: …",
    "matched_terms": ["RNAi","dsRNA","pest"],
    "matched_by": [{"query_id": "...", "why": "..."}],
    "resumen": "…", "url": "https://doi.org/…"
  }],
  "warnings": []
}
```

`resumen` es la línea corta que el agente puede repetir tal cual. `warnings` dice qué fuente
falló (una fuente caída no tumba la corrida). Código de salida 1 sólo si **todas** fallaron.

`core/watch/ejemplo_novedades.json` es una corrida real (ver `fixtures/README.md` para la fecha).

## Estado e inventario

* Caché HTTP y `inventory.json` viven en `~/.cache/sifi-desk/watch` (o `--cache-dir`).
  La caché se puede borrar sin consecuencias; el inventario **no**: si se borra, la próxima
  corrida vuelve a mostrar todo lo de la ventana.
* `--dry-run` no toca el inventario (sirve para mirar sin gastar novedades).
* `--offline` no hace ni un request; lo que no esté en caché se avisa y se saltea.

## Fuentes y límites reales

| fuente | cómo busca | límite práctico |
|---|---|---|
| Crossref | `query.bibliographic` + filtro de fechas, orden por relevancia | sin abstract, se filtra sólo por título |
| PubMed | `esearch`/`esummary` con término `[tiab]` explícito | 3 req/s sin API key (el cliente espacia 0,4 s) |
| bioRxiv | no tiene búsqueda: baja la ventana (30 por página) y filtra local | `biorxiv_max_pages` (60 ≈ 1–2 min la 1ª vez) |
| GitHub | `/releases` del repo del siFi upstream | 60 req/h sin token |

PubMed hace **AND** de las palabras: por eso cada query trae `pubmed_term` con la sintaxis
explícita. Si agregás una query, agregale `pubmed_term` o PubMed va a devolver cero.

## Tests

`python3 -m pytest -q tests` — los de `tests/unit/test_watch_*.py` no tocan la red: usan
`fixtures/*.json`, que son respuestas reales grabadas y recortadas.
