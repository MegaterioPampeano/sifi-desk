# fixtures

Respuestas **reales** de las APIs de resolución, recortadas a los campos que usa
`library.fetch` (grabadas el 2026-10-28). Sirven para que los tests corran sin red.

| archivo | origen |
|---|---|
| `crossref_10.3390_plants15203237.json` | `api.crossref.org/works/10.3390/plants15203237` |
| `unpaywall_10.3390_plants15203237.json` | `api.unpaywall.org/v2/10.3390/plants15203237` |
| `idconv_10.3390_plants15203237.json` | `pmc.ncbi.nlm.nih.gov/tools/idconv/...` |
| `epmc_fulltext_PMC13709202.xml` | `ebi.ac.uk/europepmc/webservices/rest/PMC13709202/fullTextXML` (sólo `<front>`, cerrado para que parsee) |
| `crossref_10.1242_jeb251768.json` | paper **cerrado** (licencia `user-licence`, `oa_status=closed`) |
| `unpaywall_10.1242_jeb251768.json` | idem |

Notas de la grabación:

* Europe PMC `search` devolvía **503** ese día: los tests lo simulan a propósito para
  probar que la resolución sigue funcionando sin ese paso.
* `mdpi.com` devolvía **403** (Cloudflare) y `pmc.ncbi.nlm.nih.gov` servía un captcha; por
  eso el PDF real de MDPI se resuelve por `mdpi-res.com` usando el nombre de archivo del
  JATS (`plants-15-03237.pdf`).
* No hay fixtures de PDFs: el PDF de prueba lo genera WeasyPrint en el momento, y el fake
  transport devuelve esos bytes.
