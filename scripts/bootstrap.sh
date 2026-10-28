#!/usr/bin/env bash
# Deja el entorno listo sin root: binarios en build/, python deps verificadas.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== python deps"
python3 - <<'PY'
import sys
missing = []
for mod in ("numpy", "Bio"):
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)
if missing:
    print("Faltan:", ", ".join(missing), "- instalá con: pip install --user numpy biopython")
    sys.exit(1)
import numpy, Bio
print("numpy", numpy.__version__, "biopython", Bio.__version__)
PY
echo "== binarios"
python3 core/cli.py doctor || echo "⚠ faltan binarios: ver scripts/fetch_binaries.sh"
echo "== listo"
