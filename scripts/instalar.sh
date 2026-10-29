#!/usr/bin/env bash
# instalar.sh — deja siFi-Desk andando en una máquina nueva, sin root y sin Docker.
#
#   bash scripts/instalar.sh                 # venv + deps + binarios + doctor
#   bash scripts/instalar.sh --paneles       # además baja los paneles (maíz/abeja/humano/Sulcia)
#   bash scripts/instalar.sh --paneles --todo # paneles + transcriptoma de la chicharrita (95 MB)
#
# Qué hace, en orden, y es idempotente (volver a correrlo no rompe nada):
#   1. crea .venv/ y verifica python >= 3.10
#   2. pip install -r requirements.txt
#   3. packaging/vendor/fetch_binaries.sh  (bowtie 1.3.1 con sha256 fijado; RNAplfold
#      se toma del PATH si existe, si no hay que compilarlo: ver el mensaje final)
#   4. blastn: si está en el PATH se usa; si no, avisa (sólo lo necesita el dossier A-D)
#   5. opcional: paneles, con scripts/bajar_paneles.sh
#   6. core/cli.py doctor
set -euo pipefail
cd "$(dirname "$0")/.."
RAIZ="$PWD"

PANELES=0
TODO=0
for a in "$@"; do
  case "$a" in
    --paneles) PANELES=1 ;;
    --todo) TODO=1; PANELES=1 ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "opción desconocida: $a" >&2; exit 2 ;;
  esac
done

echo "== 1/6 python"
PY=""
for c in python3.12 python3.11 python3.10 python3; do
  command -v "$c" >/dev/null 2>&1 || continue
  "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null || continue
  PY="$c"; break
done
[ -n "$PY" ] || { echo "❌ necesito python >= 3.10 (probé python3.12/3.11/3.10/python3)" >&2; exit 1; }
echo "   $PY → $("$PY" -V 2>&1)"

[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install -q --upgrade pip

echo "== 2/6 dependencias de python"
python -m pip install -q -r requirements.txt
python - <<'PY'
import numpy, Bio, fastapi, matplotlib
print(f"   numpy {numpy.__version__} · biopython {Bio.__version__} · fastapi {fastapi.__version__}")
PY

echo "== 3/6 binarios (bowtie, RNAplfold)"
if ! bash packaging/vendor/fetch_binaries.sh; then
  echo "⚠  faltan binarios. Camino corto en Debian/Ubuntu:"
  echo "     sudo apt-get install -y bowtie vienna-rna"
  echo "     export SIFI_BOWTIE=\$(command -v bowtie) SIFI_RNAPLFOLD=\$(command -v RNAplfold)"
  echo "   (o compilá ViennaRNA: bash scripts/build_vendor_linux.sh)"
fi

echo "== 4/6 blastn"
if command -v blastn >/dev/null 2>&1; then
  echo "   $(command -v blastn)"
else
  echo "⚠  blastn no está en el PATH (sólo lo usa el dossier A-D, no el diseño de siRNAs)."
  echo "   Ubuntu: sudo apt-get install -y ncbi-blast+   ·   o bajalo de ftp.ncbi.nlm.nih.gov/blast/executables/blast+/LATEST/"
fi

echo "== 5/6 paneles"
if [ "$PANELES" = 1 ]; then
  bash scripts/bajar_paneles.sh $([ "$TODO" = 1 ] && echo --todo)
else
  echo "   salteado (usá --paneles). Sin paneles el diseño corre igual, pero el off-target es ciego:"
  echo "   los paneles demo de 1-2 secuencias NO alcanzan para decidir nada."
fi

echo "== 6/6 doctor"
PYTHONPATH="$RAIZ/core" python core/cli.py doctor || true

cat <<EOF

Listo. Para levantarlo:

  . .venv/bin/activate
  python -m service.app --port 8790 \\
      --data-dir ~/.sifidesk/sifid --panels-root ~/.sifidesk/paneles \\
      --ui-dir ui/$( [ -d ui ] && echo "" ) --token CAMBIAME

y abrí http://127.0.0.1:8790 (el token va en el encabezado X-Sifi-Token; la UI lo pide una vez).

Dossier A-D de las 12 ventanas:
  SIFI_BLASTN=\$(command -v blastn) python core/cli.py dossier \\
      docs/dossier_ventanas.json out/dossier --hilos 8
EOF
