# core/report — informe A4 de corridas siFi

Convierte uno o varios `results.json` (`sifi.results/1`) en un informe imprimible en
español: portada, parámetros y hashes, tabla de candidatos con desglose E/R/S/T/D,
figuras, limitaciones y metodología.

No recalcula termodinámica ni vuelve a correr bowtie/RNAplfold: puntúa el manifest con
el scoring del producto (`sifi.scoring`, `score.yaml`) y presenta lo que hay. Si un dato
no está en el manifest (hashes, `core_version`, panel de cada hit), el informe lo dice en
vez de completarlo.

## Uso

Desde `core/`:

```bash
python3 -m report.cli --results ../out/results.json --out reporte.pdf
```

Varias corridas (se comparan en §1 y se detallan por separado):

```bash
python3 -m report.cli \
  --results out/run_A/results.json \
  --results out/run_B/results.json \
  --out informes/
```

`--out` acepta un archivo (el formato se infiere de `.pdf`/`.html`) o un directorio;
`--fmt pdf|html` fuerza el formato.

## API

```python
from report import render

pdf = render(["out/results.json"], "out/informe", fmt="pdf")
```

`render(results_json_list, out_dir, fmt="pdf", filename=None) -> ruta`

- `results_json_list`: lista de dicts y/o rutas (también acepta uno solo).
- `out_dir`: se crea si no existe; las figuras van a `out_dir/assets/`.
- `fmt`: `pdf` (WeasyPrint) o `html` (para depurar la plantilla).
- devuelve la ruta absoluta del archivo generado.

## Estructura

| Archivo | Rol |
|---|---|
| `model.py` | normaliza manifests, arma `RunView`, agrega hits por panel y metodología |
| `figures.py` | matplotlib con backend `Agg`: histograma del eje E y barras por panel |
| `render.py` | contexto, filtros Jinja2 (coma decimal, plurales), WeasyPrint |
| `templates/report.html.j2` | maquetado de las secciones |
| `templates/report.css` | A4, tipografías, tablas, portada |
| `cli.py` | `python3 -m report.cli` |

## Decisiones

- **Una tabla por corrida**, siempre ordenada por score total. Los aportes E/R/S/T/D se
  imprimen en puntos (peso × valor) y suman el total; la nota al pie lo aclara.
- **Hits por panel**: el manifest del núcleo no atribuye panel a cada hit. Si la fila trae
  `panel`/`db` se usa; si no, todo cae en «sin panel declarado» y se avisa. No se inventa
  la atribución aguas arriba.
- **Apéndice**: muestra los valores canónicos de siFi (21 nt, 22 °C, W=80, L=40) y, al
  lado, lo declarado por cada corrida. Si difieren, hay un aviso: el apéndice no puede
  contradecir en silencio al manifest.
- **Reproducibilidad**: se imprimen los hashes de binarios y el fingerprint del índice si
  existen; si faltan, se declara la limitación.
- **Determinismo**: misma entrada ⇒ mismo contenido; sólo cambia la fecha de generación
  (y los metadatos de creación del PDF).

## Tests

```bash
python3 -m pytest -q tests/unit/test_report_render.py
```

Verifican PDF real > 20 KB, texto extraído con `run_id` y candidatos, orden y suma del
desglose, multi-corrida, HTML y el comando exacto de la CLI.
