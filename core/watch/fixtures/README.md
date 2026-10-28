# Fixtures — respuestas reales grabadas

Todo lo de esta carpeta son respuestas **reales** de las APIs (no inventadas), grabadas el
**2026-10-28** para que los tests corran sin red. Se recortaron para que el repo no engorde:
se achicó `rows`/`retmax`, se dejó una sola página de bioRxiv y, en bioRxiv, se conservaron
los preprints que matchean las keywords más unos pocos de relleno (los registros son
originales; sólo se redujo la cantidad y se ajustó `messages.total` a la cantidad guardada).

| archivo | endpoint | cómo se grabó |
|---|---|---|
| `crossref_rnai.json` | `api.crossref.org/works` | `query.bibliographic="RNAi dsRNA insect pest control"`, `filter=from-pub-date:2026-10-01,until-pub-date:2026-10-28,type:journal-article`, `rows=8`, orden por relevancia |
| `pubmed_esearch.json` | `eutils…/esearch.fcgi` | término `(RNAi insect pest control) AND ("2026-09-01"[PDAT] : "2026-10-28"[PDAT])`, `retmax=5`, `sort=date` |
| `pubmed_esummary.json` | `eutils…/esummary.fcgi` | los 5 PMIDs del esearch anterior |
| `biorxiv_details.json` | `api.biorxiv.org/details/biorxiv/2026-10-27/2026-10-27/{cursor}` | páginas recorridas hasta juntar 5 preprints con RNAi/dsRNA/insect + 6 de relleno |
| `github_releases.json` | `api.github.com/repos/snowformatics/siFi21-/releases` | `per_page=5` |

Regrabar (una vez, con red):

```bash
cd core
python3 - <<'PY'
import json, requests
UA = {"User-Agent": "sifi-desk/0.1 (mailto:sifi-desk@omnivac.science)"}
r = requests.get("https://api.crossref.org/works", params={
    "query.bibliographic": "RNAi dsRNA insect pest control",
    "filter": "from-pub-date:2026-10-01,until-pub-date:2026-10-28,type:journal-article",
    "rows": 8,
    "select": "DOI,title,issued,published-online,published-print,container-title,author,URL,abstract,type,score",
    "mailto": "sifi-desk@omnivac.science"}, headers=UA, timeout=30)
json.dump(r.json(), open("watch/fixtures/crossref_rnai.json", "w"), ensure_ascii=False, indent=1)
PY
```

Los tests no dependen de las fechas exactas: usan `--since 2026-10-01` para que los fixtures
entren en la ventana aunque se corran dentro de un año.
