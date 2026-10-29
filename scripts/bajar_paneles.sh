#!/usr/bin/env bash
# bajar_paneles.sh — baja y registra los paneles de referencia (maíz, abeja, humano, Sulcia).
#
#   bash scripts/bajar_paneles.sh            # los cuatro (≈ 170 MB de descarga, ≈ 550 MB en disco)
#   bash scripts/bajar_paneles.sh --solo maiz,polinizador
#
# Usa el endpoint de NCBI Datasets con el accession fijado acá abajo, así que lo que se baja
# es siempre la misma versión del genoma. Después de bajarlo lo registra con `sifi panel add`
# (que arma el índice de bowtie).
#
# El panel de la chicharrita (TSA GITV) NO se baja de acá: no hay accession de genoma.
# Se copia de una instalación que ya lo tenga:
#   rsync -a maquina-vieja:~/.sifidesk/panels/chicharrita/ ~/.sifidesk/panels/chicharrita/
set -euo pipefail
cd "$(dirname "$0")/.."
RAIZ="$PWD"
PANELS_ROOT="${SIFI_PANELS_ROOT:-$HOME/.sifidesk/panels}"

# id | accession | rol | nombre legible | nota
PANELES=(
  "maiz|GCF_902167145.3|no_blanco|Zea mays B73 (RefSeq)|CDS; cultivo que se quiere proteger"
  "polinizador|GCF_003254395.2|no_blanco|Apis mellifera (RefSeq)|CDS; polinizador no blanco"
  "humano|GCF_000001405.40|no_blanco|Homo sapiens GRCh38.p14 (RefSeq)|CDS; consumidor"
  "simbionte|GCF_000147035.1|simbionte|Sulcia muelleri GWSS (RefSeq)|genoma completo; proxy del simbionte"
)

SOLO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --solo) SOLO=",$2,"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "opción desconocida: $1" >&2; exit 2 ;;
  esac
done

command -v curl >/dev/null || { echo "❌ falta curl" >&2; exit 1; }
command -v unzip >/dev/null || { echo "❌ falta unzip" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

for fila in "${PANELES[@]}"; do
  IFS='|' read -r ID ACC ROL NOMBRE NOTA <<<"$fila"
  if [ -n "$SOLO" ] && [[ "$SOLO" != *",$ID,"* ]]; then continue; fi
  # el chequeo es por accession, no por id: versiones demo viejas del mismo id no cuentan
  if python3 core/cli.py panel list 2>/dev/null | grep -q "$ACC"; then
    echo "== $ID ya tiene $ACC registrado, salteo"
    continue
  fi
  echo "== $ID ($ACC)"
  tipo="CDS_FASTA"; [ "$ROL" = "simbionte" ] && tipo="GENOME_FASTA"
  url="https://api.ncbi.nlm.nih.gov/datasets/v2alpha/genome/accession/$ACC/download?include_annotation_type=$tipo"
  echo "   bajando $ACC"
  curl -sSL -o "$TMP/$ID.zip" "$url"
  unzip -q -o "$TMP/$ID.zip" -d "$TMP/$ID"
  # el nombre del FASTA depende del tipo pedido; tomamos el primero que aparezca
  FASTA="$(find "$TMP/$ID" -name '*.fna' | head -1)"
  [ -n "$FASTA" ] || { echo "❌ no encontré FASTA en el zip de $ACC" >&2; exit 1; }
  echo "   registrando ($(grep -c '^>' "$FASTA") secuencias)"
  python3 core/cli.py panel add --panels-root "$PANELS_ROOT" --panel-id "$ID" \
      --fasta "$FASTA" --nombre "$NOMBRE" --rol "$ROL" --fuente "NCBI RefSeq $ACC · $NOTA"
done

echo
echo "Paneles en $PANELS_ROOT:"
python3 core/cli.py panel list --panels-root "$PANELS_ROOT"
