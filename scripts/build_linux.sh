#!/usr/bin/env bash
# Arma el instalable de Linux de siFi-Desk (M8): dist/sifi-desk-linux/
#
#   bash scripts/build_linux.sh              # tests + PyInstaller + verificación
#   bash scripts/build_linux.sh --no-tests   # sólo empaquetar
#   bash scripts/build_linux.sh --cli-only   # además, dist/sifi-cli/ (CLI standalone)
#   bash scripts/build_linux.sh --deb        # además, .deb (si dpkg-deb está)
#
# Resultado:
#   dist/sifi-desk-linux/sifid          API local (FastAPI) + worker
#   dist/sifi-desk-linux/sifi           CLI headless
#   dist/sifi-desk-linux/packaging/vendor/linux-x86_64/  bowtie, RNAplfold
#   dist/sifi-desk-linux/ui/            UI Tauri, si existe dist/ui o ui/dist
#
# Sin red: si los binarios de vendor ya están no descarga nada (ver
# packaging/vendor/README.md). Sin binarios, compila igual (SIFI_VENDOR_OPTIONAL=1).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PY="${PYTHON:-python3}"
PLAT="$("$PY" -c 'import sys,platform;print(f"{sys.platform}-{platform.machine()}")')"
BUNDLE="$REPO/dist/sifi-desk-linux"

run_tests=1; cli_standalone=0; make_deb=0
for arg in "$@"; do
  case "$arg" in
    --no-tests) run_tests=0 ;;
    --cli-only|--standalone-cli) cli_standalone=1 ;;
    --deb) make_deb=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "arg desconocido: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n== %s\n' "$*"; }

step "0/4 entorno"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), sys.version'
"$PY" -m PyInstaller --version >/dev/null 2>&1 || {
  echo "falta PyInstaller. Instalalo en un venv, no global:" >&2
  echo "  $PY -m venv .venv && .venv/bin/pip install -e '.[dev]' pyinstaller" >&2
  exit 1
}
echo "python: $("$PY" -V 2>&1)  ·  pyinstaller: $("$PY" -m PyInstaller --version)  ·  plat: $PLAT"

if [ "$run_tests" = 1 ]; then
  step "1/4 tests"
  "$PY" -m pytest -q "$REPO/tests"
else
  step "1/4 tests (omitidos)"
fi

step "2/4 vendor"
if [ -x "$REPO/packaging/vendor/fetch_binaries.sh" ]; then
  bash "$REPO/packaging/vendor/fetch_binaries.sh" --check || {
    echo "aviso: binarios incompletos → bundle sin bowtie/RNAplfold" >&2
    export SIFI_VENDOR_OPTIONAL=1
  }
fi

step "3/4 sidecars (PyInstaller, one-dir)"
cd "$REPO"
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$REPO/dist" --workpath "$REPO/build/pyinstaller" \
  packaging/pyinstaller/sifid.spec

if [ "$cli_standalone" = 1 ]; then
  "$PY" -m PyInstaller --noconfirm --clean \
    --distpath "$REPO/dist" --workpath "$REPO/build/pyinstaller-cli" \
    packaging/pyinstaller/sifi.spec
fi

step "4/4 ensamblado + verificación"
[ -d "$BUNDLE" ] || { echo "no se generó $BUNDLE" >&2; exit 1; }

# UI (Tauri): se copia si ya está compilada; el instalable funciona sin ella (API-only).
for cand in "$REPO/dist/ui" "$REPO/ui/dist" "$REPO/agent/dist"; do
  if [ -d "$cand" ] && [ ! -e "$BUNDLE/ui" ]; then
    cp -a "$cand" "$BUNDLE/ui"
    echo "ui ← ${cand#$REPO/}"
    break
  fi
done

# Los binarios de vendor ya vienen copiados por el .spec (misma ruta relativa),
# pero si el build se hizo con SIFI_VENDOR_OPTIONAL=1 y ahora están, se completan.
venv_src="$REPO/packaging/vendor/$PLAT"
if [ -d "$venv_src" ]; then
  mkdir -p "$BUNDLE/packaging/vendor/$PLAT"
  for f in "$venv_src"/*; do
    [ -f "$f" ] || continue
    case "$f" in *.md|*.gitkeep|*SHA256SUMS*) continue ;; esac
    cp -f "$f" "$BUNDLE/packaging/vendor/$PLAT/"
  done
fi

echo "-- contenido"
ls -1 "$BUNDLE" | sed 's/^/   /'
echo "-- humo"
"$BUNDLE/sifid" --help >/dev/null && echo "   sifid --help ok"
"$BUNDLE/sifi" version >/dev/null && echo "   sifi version ok"
"$BUNDLE/sifid" --version >/dev/null 2>&1 || true

if [ "$make_deb" = 1 ]; then
  command -v dpkg-deb >/dev/null 2>&1 || { echo "sin dpkg-deb: no armo .deb" >&2; exit 0; }
  bash "$HERE/package_deb.sh" "$BUNDLE"
fi

echo
echo "listo: ${BUNDLE#$REPO/}/"
