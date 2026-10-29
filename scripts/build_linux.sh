#!/usr/bin/env bash
# Arma el instalable de Linux de siFi-Desk: dist/sifi-desk-linux/
#
#   bash scripts/build_linux.sh              # tests + vendor + PyInstaller + smoke
#   bash scripts/build_linux.sh --no-tests   # sólo empaquetar
#   bash scripts/build_linux.sh --no-smoke   # sin la corrida real de tests/data
#   bash scripts/build_linux.sh --cli-only   # además, dist/sifi-cli/ (CLI standalone)
#   bash scripts/build_linux.sh --deb        # además, .deb  (y .AppImage si se puede)
#   bash scripts/build_linux.sh --appimage   # además, .AppImage
#
# Resultado:
#   dist/sifi-desk-linux/sifid          API local (FastAPI) + worker
#   dist/sifi-desk-linux/sifi           CLI headless
#   dist/sifi-desk-linux/sifid-x86_64-unknown-linux-gnu   sidecar con nombre Tauri (D6)
#   dist/sifi-desk-linux/agent/         agente: perfil dsh + sifi-tools + persona + tools
#   dist/sifi-desk-linux/packaging/vendor/linux-x86_64/  bowtie, RNAplfold
#
# Binarios externos: si faltan, este script los compila/baja con
# `scripts/build_vendor_linux.sh` (hashes fijados en packaging/vendor/pins.sh) y
# si aun así no aparecen **falla**. El único modo de saltearlos es pedirlo:
#   SIFI_VENDOR_OPTIONAL=1 bash scripts/build_linux.sh     # bundle incompleto, para desarrollo
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PY="${PYTHON:-python3}"
PLAT="$("$PY" -c 'import sys,platform;print(f"{sys.platform}-{platform.machine()}")')"
BUNDLE="$REPO/dist/sifi-desk-linux"
TRIPLE="${SIFI_TARGET_TRIPLE:-}"
VENDOR_OPTIONAL="${SIFI_VENDOR_OPTIONAL:-}"

run_tests=1; cli_standalone=0; make_deb=0; make_appimage=0; run_smoke=1
for arg in "$@"; do
  case "$arg" in
    --no-tests) run_tests=0 ;;
    --no-smoke) run_smoke=0 ;;
    --cli-only|--standalone-cli) cli_standalone=1 ;;
    --deb) make_deb=1 ;;
    --appimage) make_appimage=1 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "arg desconocido: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n== %s\n' "$*"; }
warn() { printf '! %s\n' "$*" >&2; }
die()  { printf '✗ %s\n' "$*" >&2; exit 1; }

# Triples de Rust para el nombre del sidecar que espera Tauri (D6).
if [ -z "$TRIPLE" ]; then
  case "$PLAT" in
    linux-x86_64)  TRIPLE="x86_64-unknown-linux-gnu" ;;
    linux-aarch64|linux-arm64) TRIPLE="aarch64-unknown-linux-gnu" ;;
    linux-armv7l)  TRIPLE="armv7-unknown-linux-gnueabihf" ;;
    *) TRIPLE="$(uname -m)-unknown-linux-gnu" ;;
  esac
fi

step "0/6 entorno"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), sys.version'
"$PY" -m PyInstaller --version >/dev/null 2>&1 || {
  echo "falta PyInstaller. Instalalo en un venv, no global:" >&2
  echo "  $PY -m venv .venv && .venv/bin/pip install -r packaging/requirements-build.txt" >&2
  exit 1
}
echo "python: $("$PY" -V 2>&1)  ·  pyinstaller: $("$PY" -m PyInstaller --version)  ·  plat: $PLAT  ·  triple: $TRIPLE"

if [ "$run_tests" = 1 ]; then
  step "1/6 tests"
  "$PY" -m pytest -q "$REPO/tests"
else
  step "1/6 tests (omitidos)"
fi

# --- binarios externos ------------------------------------------------------- #
step "2/6 binarios externos (bowtie + RNAplfold)"
bash "$REPO/packaging/vendor/fetch_binaries.sh" --check >/dev/null 2>&1 || {
  echo "-- faltan: los compilo/bajo con hashes fijados (scripts/build_vendor_linux.sh)"
  bash "$REPO/scripts/build_vendor_linux.sh" --no-install \
    || die "no pude preparar bowtie/RNAplfold (ver arriba)"
  SIFI_VENDOR_SRC="$REPO/build/vendor/$PLAT" bash "$REPO/packaging/vendor/fetch_binaries.sh" --force
}
if bash "$REPO/packaging/vendor/fetch_binaries.sh" --check; then
  echo "-- binarios ok"
elif [ "$VENDOR_OPTIONAL" = "1" ]; then
  warn "SIFI_VENDOR_OPTIONAL=1: sigo con un bundle SIN bowtie/RNAplfold (sólo desarrollo)"
  run_smoke=0
else
  die "faltan binarios y no hay SIFI_VENDOR_OPTIONAL=1: un instalable sin bowtie/RNAplfold
   no puede correr nada. Arreglá el build (scripts/build_vendor_linux.sh) o pedí
   explícitamente un bundle incompleto:  SIFI_VENDOR_OPTIONAL=1 bash scripts/build_linux.sh"
fi

step "3/6 sidecars (PyInstaller, one-dir)"
cd "$REPO"
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$REPO/dist" --workpath "$REPO/build/pyinstaller" \
  packaging/pyinstaller/sifid.spec

if [ "$cli_standalone" = 1 ]; then
  "$PY" -m PyInstaller --noconfirm --clean \
    --distpath "$REPO/dist" --workpath "$REPO/build/pyinstaller-cli" \
    packaging/pyinstaller/sifi.spec
fi

step "4/6 ensamblado (UI, vendor, agente, sidecar Tauri)"
[ -d "$BUNDLE" ] || { echo "no se generó $BUNDLE" >&2; exit 1; }

# UI (Tauri): se copia si ya está compilada; el instalable funciona sin ella (API-only).
for cand in "$REPO/dist/ui" "$REPO/ui/dist" "$REPO/agent/dist"; do
  if [ -d "$cand" ] && [ ! -e "$BUNDLE/ui" ]; then
    cp -a "$cand" "$BUNDLE/ui"
    echo "ui ← ${cand#$REPO/}"
    break
  fi
done

# UI estática (ui/index.html + assets): es la misma que sirve --ui-dir; el build de Tauri
# produce lo mismo pero compilado. Sin esto el bundle queda API-only y no hay ventana.
if [ ! -e "$BUNDLE/ui" ] && [ -f "$REPO/ui/index.html" ]; then
  mkdir -p "$BUNDLE/ui"
  tar -C "$REPO/ui" --exclude=tauri -cf - . | tar -C "$BUNDLE/ui" -xf -
  echo "ui ← ui/ (estática, sin tauri)"
fi

# Los binarios de vendor ya vienen copiados por el .spec (misma ruta relativa);
# esto completa el caso "no estaban cuando corrió PyInstaller".
venv_src="$REPO/packaging/vendor/$PLAT"
if [ -d "$venv_src" ]; then
  mkdir -p "$BUNDLE/packaging/vendor/$PLAT"
  for f in "$venv_src"/*; do
    [ -f "$f" ] || continue
    case "$f" in *.md|*.gitkeep|*SHA256SUMS*) continue ;; esac
    cp -f "$f" "$BUNDLE/packaging/vendor/$PLAT/"
  done
fi

# Agente (M10): código + perfil de dsh. Su runtime (Node + árbol de dsh) NO se
# embebe: es prerrequisito y `sifi doctor` lo verifica (packaging/agent/README.md).
bash "$REPO/packaging/agent/bundle_agent.sh" "$BUNDLE/agent"

# D6: Tauri busca el sidecar con el nombre `<name>-<target-triple>`. Hardlink
# (mismo binario, 13 MB): tar/squashfs lo deduplican; si no se puede, copia.
if ln -f "$BUNDLE/sifid" "$BUNDLE/sifid-$TRIPLE" 2>/dev/null; then
  :
else
  cp -f "$BUNDLE/sifid" "$BUNDLE/sifid-$TRIPLE"
fi
chmod +x "$BUNDLE/sifid-$TRIPLE"
if [ -d "$REPO/ui/tauri/src-tauri" ]; then
  mkdir -p "$REPO/ui/tauri/src-tauri/binaries"
  if ln -f "$BUNDLE/sifid" "$REPO/ui/tauri/src-tauri/binaries/sifid-$TRIPLE" 2>/dev/null; then
    :
  else
    cp -f "$BUNDLE/sifid" "$REPO/ui/tauri/src-tauri/binaries/sifid-$TRIPLE"
  fi
  echo "sidecar Tauri ← ui/tauri/src-tauri/binaries/sifid-$TRIPLE"
fi

echo "-- contenido"
ls -1 "$BUNDLE" | sed 's/^/   /'
echo "-- tamaño: $(du -sh "$BUNDLE" | awk '{print $1}')  (agente: $(du -sh "$BUNDLE/agent" | awk '{print $1}'))"

step "5/6 verificación del bundle"
"$BUNDLE/sifid" --help >/dev/null && echo "   sifid --help ok"
"$BUNDLE/sifi" version >/dev/null && echo "   sifi version ok"
"$BUNDLE/sifid-$TRIPLE" --help >/dev/null && echo "   sidecar sifid-$TRIPLE ok"
"$BUNDLE/sifi" doctor || \
  echo "   (normal en una máquina sin el harness: el runtime del agente se instala con agent/install.sh)"
"$BUNDLE/sifid" --version >/dev/null 2>&1 || true

# --- smoke real del pipeline ------------------------------------------------- #
# `--help` no prueba nada del bundle: no verifica score.yaml, los binarios, el
# runner congelado (`sifid --runner`) ni la cola. Este bloque corre una corrida
# de verdad con el índice de juguete, primero por CLI y después por la API.
if [ "$run_smoke" = 1 ]; then
  step "6/6 smoke (corrida real con tests/data)"
  [ -x "$BUNDLE/packaging/vendor/$PLAT/bowtie-build" ] || {
    die "sin bowtie-build en el bundle: no puedo probar el pipeline.
   Un instalable que no pasó el smoke no se publica (usá --no-smoke para
   empaquetar sin probar, o SIFI_VENDOR_OPTIONAL=1 para un bundle vacío de dev)."
  }
  [ -x "$BUNDLE/packaging/vendor/$PLAT/RNAplfold" ] || die "sin RNAplfold en el bundle"
  SMOKE="$(mktemp -d)"
  export SIFI_SMOKE="$SMOKE"
  (
    set -e
    cd "$SMOKE"                       # fuera del repo: nada de rutas relativas
    "$BUNDLE/packaging/vendor/$PLAT/bowtie-build" -q \
      "$REPO/tests/data/toy.fa" "$SMOKE/toyidx" >/dev/null
    echo "-- CLI: sifi design"
    "$BUNDLE/sifi" design -q "$REPO/tests/data/query.fa" -d "$SMOKE" \
      --db-name toyidx -o "$SMOKE/out-cli" --quiet
    "$PY" - "$SMOKE/out-cli/results.json" <<'PY'
import json, sys
rec = json.load(open(sys.argv[1]))["records"][0]
assert rec["error"] is None, rec["error"]
assert rec["summary"]["n_sirnas"] > 0, rec["summary"]
print(f"   CLI OK · {rec['query_name']} · {rec['summary']['n_sirnas']} siRNAs · "
      f"{rec['summary'].get('n_hits')} hits")
PY
    echo "-- API: sifid + runner congelado"
    "$BUNDLE/sifid" --port 8791 --data-dir "$SMOKE/sifid" >"$SMOKE/sifid.log" 2>&1 &
    SRV=$!
    trap 'kill $SRV 2>/dev/null || true' EXIT
    "$PY" - "$SMOKE" "$REPO/tests/data/query.fa" <<'PY'
import json, sys, time, urllib.error, urllib.request
tmp, query = sys.argv[1], sys.argv[2]
base = "http://127.0.0.1:8791"

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

for _ in range(100):
    try:
        call("GET", "/health")
        break
    except (urllib.error.URLError, ConnectionError):
        time.sleep(0.2)
else:
    raise SystemExit("sifid no arrancó")

run = call("POST", "/runs", {"mode": "design", "query_path": query,
                             "db_dir": tmp, "db_name": "toyidx"})
rid = run["run_id"]
for _ in range(300):
    st = call("GET", f"/runs/{rid}")
    if st["status"] in ("done", "error", "cancelled"):
        break
    time.sleep(0.3)
else:
    raise SystemExit("la corrida por API no terminó")
assert st["status"] == "done", (st["status"], st.get("error"))
rec = call("GET", f"/runs/{rid}/results")["records"][0]
assert rec["error"] is None, rec["error"]
print(f"   API OK · {rid} · {st['status']} · {rec['summary']['n_sirnas']} siRNAs")
PY
    kill $SRV 2>/dev/null || true
    wait $SRV 2>/dev/null || true
    trap - EXIT
  )
  rm -rf "$SMOKE"
  echo "-- smoke OK"
else
  step "6/6 smoke (omitido)"
  warn "--no-smoke: el bundle NO está probado de punta a punta"
fi

if [ "$make_deb" = 1 ]; then
  command -v dpkg-deb >/dev/null 2>&1 || die "sin dpkg-deb: no puedo armar el .deb"
  bash "$HERE/package_deb.sh" "$BUNDLE"
fi
if [ "$make_appimage" = 1 ]; then
  bash "$HERE/package_appimage.sh" "$BUNDLE" || warn "sin .AppImage (ver packaging/TODO.md)"
fi

echo
echo "listo: ${BUNDLE#$REPO/}/"
