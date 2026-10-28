#!/usr/bin/env bash
# Instala la GUI del siFi 21 ORIGINAL (2019) en este equipo, sin root.
#
# El original es Python 2.7 + PyQt4 + matplotlib con backend qt4agg. Nada de eso existe
# para Python 3, así que armamos un entorno conda aparte (~/sifi21-env) y corremos su
# código tal cual, con tres parches mínimos:
#   1. `import FileDialog` (módulo de pywin32) → shim vacío, el original no lo usa.
#   2. la ruta de datos sale de QDesktopServices.DataLocation con lógica de Windows
#      (`split('Local')[0]`) → la fijamos en ~/.sifidesk/sifi21.
#   3. los binarios que trae en ToCopy/ son .exe de Windows →symlinks a bowtie 1.3.1 y
#      RNAplfold compilados en build/.
#
# Uso:  bash desktop/build_sifi21_gui.sh            (instala/actualiza y prueba)
#       bash desktop/build_sifi21_gui.sh --no-test
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${SIFI21_PREFIX:-$HOME/sifi21}"
ENV="${SIFI21_ENV:-$HOME/sifi21-env}"
ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/.mamba-root}"
APP="$PREFIX/app"
DATA="$HOME/.sifidesk/sifi21"
BOWTIE_SRC="$REPO/build/bowtie-1.3.1-linux-x86_64"
VIENNA_SRC="$REPO/build/vienna/bin"
run_test=1
[ "${1:-}" = "--no-test" ] && run_test=0

echo "== 1/6 micromamba"
if [ ! -x "$HOME/bin/micromamba" ]; then
  mkdir -p "$HOME/bin"
  curl -sL https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C "$HOME" bin/micromamba
fi

echo "== 2/6 entorno Python 2.7 + PyQt4 ($ENV)"
if [ ! -x "$ENV/bin/python" ]; then
  export MAMBA_ROOT_PREFIX="$ROOT_PREFIX"
  "$HOME/bin/micromamba" create -y -p "$ENV" -c conda-forge \
    "python=2.7" "pyqt=4.11.4" "numpy=1.16" "biopython=1.76" "pillow" "scipy=1.2" pip >/dev/null
  # matplotlib va por pip: el de conda arrastra pyqt5 y choca con qt4 (freetype/icu).
  "$ENV/bin/pip" -q install --no-cache-dir "matplotlib==2.2.5" "seaborn==0.9.0" "pandas==0.24.2"
fi

echo "== 3/6 copia del código original en $APP"
rm -rf "$APP"; mkdir -p "$PREFIX"
cp -r "$REPO/vendor/siFi21" "$APP"
rm -rf "$APP/__pycache__"

echo "== 4/6 parches"
cat > "$APP/FileDialog.py" <<'PY'
"""Shim: el original hace `import FileDialog` (pywin32) y no lo usa."""
PY
"$ENV/bin/python" - "$APP/main.py" <<'PY'
# -*- coding: utf-8 -*-
# en bytes: el original mezcla utf-8 y latin-1, no vale la pena normalizar el archivo
import sys
ruta = sys.argv[1]
s = open(ruta, "rb").read()
viejo = (b"        self.data_location = str(QtGui.QDesktopServices.storageLocation("
         b"QtGui.QDesktopServices.DataLocation))\n"
         b"        self.data_location = self.data_location.split('Local')[0] + '/Local/'\n"
         b"        self.app_location = self.data_location + '/siFi2015/'")
nuevo = (b"        # PATCH (Linux): la logica de Windows (split('Local')) arma rutas invalidas.\n"
         b"        self.data_location = os.path.expanduser('~/.sifidesk/')\n"
         b"        self.app_location = os.path.expanduser('~/.sifidesk/sifi21/')")
if viejo not in s:
    raise SystemExit("no encontre el bloque de rutas: cambio main.py?")
open(ruta, "wb").write(s.replace(viejo, nuevo))
print("main.py parcheado")
PY

# binarios Linux con los nombres que el original invoca (bowtie / RNAplfold a secas)
mkdir -p "$DATA/Bowtie" "$DATA/RNAplfold" "$DATA/Images" "$DATA/Databases"
for b in bowtie bowtie-align-s bowtie-align-l bowtie-build bowtie-build-s bowtie-build-l \
         bowtie-inspect bowtie-inspect-s bowtie-inspect-l; do
  [ -e "$BOWTIE_SRC/$b" ] && ln -sf "$BOWTIE_SRC/$b" "$DATA/Bowtie/$b"
done
ln -sf "$VIENNA_SRC/RNAplfold" "$DATA/RNAplfold/RNAplfold"

echo "== 5/6 lanzador $PREFIX/sifi21-gui.sh"
cat > "$PREFIX/sifi21-gui.sh" <<SH
#!/usr/bin/env bash
# Abre la GUI del siFi 21 original.
set -uo pipefail
APP="$APP"; DATA="$DATA"; PY="$ENV/bin/python"
cd "\$APP" || exit 1
export PATH="\$DATA/Bowtie:\$DATA/RNAplfold:\$PATH"
exec "\$PY" main.py "\$@"
SH
chmod +x "$PREFIX/sifi21-gui.sh"

echo "== 6/6 verificación"
if [ "$run_test" = 1 ]; then
  "$ENV/bin/python" - <<'PY'
from PyQt4 import QtGui, QtCore
import matplotlib
matplotlib.use("Agg")
print("PyQt4", QtCore.QT_VERSION_STR, "| matplotlib", matplotlib.__version__)
PY
fi
echo "LISTO → $PREFIX/sifi21-gui.sh   (datos en $DATA)"
