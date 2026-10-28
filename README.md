# Si-Fi Agent Integration

Programa de escritorio (Windows primero, luego Linux) que **incorpora si-Fi** para diseño de
dsRNA/siRNA y predicción de off-targets, con un **agente de IA** enganchado que lo controla,
lo actualiza y busca novedades, y con **reportes reproducibles**.

Organización: **Omnivac Science** · Documento de diseño: [`docs/ROADMAP.md`](docs/ROADMAP.md)

> **Licencia:** obra derivada de si-Fi / siFi21, por lo tanto **CC BY-NC-SA 2.0**
> (no comercial, share-alike). Ver [`LICENSE-siFi.md`](LICENSE-siFi.md) y [`VENDOR.md`](VENDOR.md).

## Estado

| Hito | Estado |
|---|---|
| M0 Fundaciones | ✅ repo, vendor, licencias, notas de port |
| M1 Core headless | ✅ port verificado 1:1 contra el original en 6 configuraciones |
| M2 Dominio (paneles/scoring) | ⏳ |
| M3 Servicio local (`sifid`) | ⏳ |
| M4 Agente (dsh + plugins) | ⏳ |
| M5 Ventana nativa | ⏳ |
| M6 Reportes | ⏳ |
| M7 Novedades/actualizaciones | ⏳ |
| M8 Distribución | ⏳ |

## Uso rápido (desarrollo)

```bash
make bootstrap          # venv + dependencias + binarios (bowtie1, RNAplfold)
make doctor             # verifica binarios y versiones
make test               # tests unitarios + test diferencial contra el original

./core/cli.py design -q tests/data/query.fa -d tests/data --db-name toyidx -o out/ --mismatches 1
./core/cli.py offtarget -q trigger.fa -d /ruta/db --db-name maiz -o out/
```

Salida: `out/results.json` (esquema `sifi.results/1`, con hashes de binarios y de la base)
+ `out/sirnas.tsv`.

## Estructura

```
core/       núcleo Python 3 headless (port de siFi + dominio + servicio)
agent/      DeepSeek Harness + plugins (tools, skills, watch)
ui/         ventana nativa (Tauri) — Windows/Linux
packaging/  sidecars, binarios por plataforma, instaladores
tests/      golden, unitarios, diferencial contra el original
vendor/     código upstream verbatim (no se edita)
docs/       roadmap, ADRs, manual
```

## Verificación de fidelidad

`tests/diff_oracle.py` corre el **fuente original** de siFi (parcheado sólo sintácticamente)
y el port, con los mismos binarios, y compara el JSON campo por campo. Ver `PORT_NOTES.md`.
