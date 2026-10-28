#!/usr/bin/env bash
# fetch_binaries.sh — deja los binarios externos en packaging/vendor/<sys.platform>-<machine>/
#
# Qué copia: bowtie (+ bowtie-align-s / bowtie-build-s / wrappers), RNAplfold y los
# archivos de licencia. Es idempotente: si ya están, no hace nada (usar --force).
#
# Estrategias, en orden:
#   1. SIFI_VENDOR_SRC=<dir>   → copia lo que haya en ese directorio (build de CI, cache).
#   2. build/ del checkout     → bowtie-*/bowtie, vienna/bin/RNAplfold (Linux; en un
#                                worktree busca también el checkout principal).
#   3. PATH                    → which bowtie / RNAplfold / bowtie-build.
#   4. Descarga                → bowtie 1.3.1 desde GitHub Releases; ViennaRNA desde
#                                SIFI_VIENNA_URL (zip/tar con RNAplfold dentro).
#
# Uso:
#   bash packaging/vendor/fetch_binaries.sh              # auto
#   bash packaging/vendor/fetch_binaries.sh --from-build # sólo estrategia 2 (falla si no hay)
#   bash packaging/vendor/fetch_binaries.sh --force      # rehacer aunque exista
#   bash packaging/vendor/fetch_binaries.sh --check      # verifica sha256 (offline)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FORCE=0
MODE=auto

for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --from-build) MODE=from-build ;;
    --check) MODE=check ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

PYTHON=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PYTHON="$cand"; break; fi
done
[ -n "$PYTHON" ] || { echo "no encuentro python" >&2; exit 1; }

# Mismo cálculo que core/sifi/tools.py: f"{sys.platform}-{platform.machine()}"
PLAT="$("$PYTHON" -c 'import sys, platform; print(f"{sys.platform}-{platform.machine()}")')"
DEST="$REPO_ROOT/packaging/vendor/$PLAT"
EXE=""
case "$PLAT" in win32-*) EXE=".exe" ;; esac

echo "== plataforma: $PLAT"
echo "== destino:    ${DEST#$REPO_ROOT/}"

want=("bowtie" "RNAplfold")
[ -n "${SIFI_WANT_BOWTIE_BUILD:-1}" ] && want+=("bowtie-build")

have_all() {
  local missing=()
  for t in "${want[@]}"; do
    [ -f "$DEST/$t$EXE" ] || missing+=("$t")
  done
  if [ ${#missing[@]} -eq 0 ]; then return 0; fi
  echo "faltan: ${missing[*]}"
  return 1
}

# --check: no toca nada; exige los binarios y, si hay MANIFEST.json, verifica sha256.
if [ "$MODE" = "check" ]; then
  if ! have_all; then exit 1; fi
  "$PYTHON" - "$DEST" <<'PYCHK'
import hashlib, json, os, sys
d = sys.argv[1]
man_path = os.path.join(d, "MANIFEST.json")
if not os.path.isfile(man_path):
    print("== OK: binarios completos (sin MANIFEST.json: no verifico sha256)")
    sys.exit(0)
files = json.load(open(man_path)).get("files", {})
bad = []
for name, meta in sorted(files.items()):
    p = os.path.join(d, name)
    if not os.path.isfile(p):
        bad.append(f"{name}: falta"); continue
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    if h != meta["sha256"]:
        bad.append(f"{name}: sha256 {h[:12]}... != {meta['sha256'][:12]}...")
if bad:
    print("== SHA256 NO COINCIDE:")
    for b in bad: print("   " + b)
    sys.exit(1)
print(f"== OK: {len(files)} binarios, sha256 verificado")
PYCHK
  exit $?
fi

if [ "$FORCE" -eq 0 ] && [ -d "$DEST" ] && have_all >/dev/null 2>&1; then
  echo "== ya están (usar --force para rehacer)"
  "$PYTHON" - "$DEST" <<'PY'
import hashlib, json, os, sys
d = sys.argv[1]
man = {}
for name in sorted(os.listdir(d)):
    p = os.path.join(d, name)
    if os.path.isfile(p) and not name.endswith((".json", ".txt", ".md")):
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        man[name] = {"sha256": h, "bytes": os.path.getsize(p)}
print(json.dumps(man, indent=2))
PY
  exit 0
fi

mkdir -p "$DEST"

# --- helpers ---------------------------------------------------------------- #
copy_exec() {  # copy_exec <src> <name-en-destino>
  local src="$1" name="$2"
  [ -f "$src" ] || return 1
  cp -f "$src" "$DEST/$name"
  chmod +x "$DEST/$name" 2>/dev/null || true
  echo "   ← $src"
}

find_in_build() {  # find_in_build <nombre>
  local name="$1" root cand
  for root in "$REPO_ROOT" "$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null | xargs -r dirname)"; do
    [ -n "$root" ] || continue
    for cand in "$root"/build/bowtie-*/"$name" \
                "$root"/build/vienna/bin/"$name" \
                "$root"/build/ViennaRNA-*/src/bin/"$name"; do
      if [ -f "$cand" ] && [ -x "$cand" ]; then echo "$cand"; return 0; fi
    done
  done
  return 1
}

TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

unpack() {  # unpack <archivo> -> $TMP/unpacked
  local archive="$1"
  TMP="$(mktemp -d)"
  mkdir -p "$TMP/unpacked"
  case "$archive" in
    *.zip) unzip -q -o "$archive" -d "$TMP/unpacked" ;;
    *.tar.gz|*.tgz) tar -xzf "$archive" -C "$TMP/unpacked" ;;
    *) echo "formato no soportado: $archive" >&2; return 1 ;;
  esac
}

fetch() {  # fetch <url> <archivo-salida>
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 --connect-timeout 20 -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$2" "$1"
  else
    echo "ni curl ni wget disponibles" >&2; return 1
  fi
}

# --- 1. SIFI_VENDOR_SRC ----------------------------------------------------- #
if [ -n "${SIFI_VENDOR_SRC:-}" ] && [ -d "$SIFI_VENDOR_SRC" ]; then
  echo "== fuente: SIFI_VENDOR_SRC=$SIFI_VENDOR_SRC"
  for f in "$SIFI_VENDOR_SRC"/*; do
    [ -f "$f" ] || continue
    cp -f "$f" "$DEST/"
  done
  chmod +x "$DEST"/* 2>/dev/null || true
fi

# --- 2. build/ del checkout ------------------------------------------------- #
if ! have_all >/dev/null 2>&1; then
  echo "== fuente: build/ del checkout"
  if src="$(find_in_build bowtie)"; then
    dir="$(dirname "$src")"
    copy_exec "$src" "bowtie$EXE" || true
    copy_exec "$dir/bowtie-align-s" "bowtie-align-s$EXE" || true
    copy_exec "$dir/bowtie-build" "bowtie-build$EXE" || true
    copy_exec "$dir/bowtie-build-s" "bowtie-build-s$EXE" || true
    # Variantes "large index" (>4 Gbp: .ebwtl) e inspect: ~40 MB extra que ningún
    # panel de este producto usa. SIFI_VENDOR_FULL=1 las incluye igual.
    if [ -n "${SIFI_VENDOR_FULL:-}" ]; then
      copy_exec "$dir/bowtie-align-l" "bowtie-align-l$EXE" || true
      copy_exec "$dir/bowtie-build-l" "bowtie-build-l$EXE" || true
      copy_exec "$dir/bowtie-inspect" "bowtie-inspect$EXE" || true
      copy_exec "$dir/bowtie-inspect-s" "bowtie-inspect-s$EXE" || true
    fi
    for lic in LICENSE AUTHORS NEWS; do
      [ -f "$dir/$lic" ] && cp -f "$dir/$lic" "$DEST/LICENSE-bowtie.txt" 2>/dev/null || true
      break
    done
  fi
  if src="$(find_in_build RNAplfold)"; then
    copy_exec "$src" "RNAplfold$EXE" || true
  fi
fi

# --- 3. PATH ---------------------------------------------------------------- #
if ! have_all >/dev/null 2>&1; then
  echo "== fuente: PATH"
  for t in "${want[@]}"; do
    [ -f "$DEST/$t$EXE" ] && continue
    if p="$(command -v "$t$EXE" 2>/dev/null || command -v "$t" 2>/dev/null)"; then
      copy_exec "$p" "$t$EXE" || true
    fi
  done
fi

# --- 4. descarga ------------------------------------------------------------ #
if ! have_all >/dev/null 2>&1 && [ "$MODE" != "from-build" ]; then
  echo "== fuente: descarga"
  if [ ! -f "$DEST/bowtie$EXE" ]; then
    case "$PLAT" in
      linux-*)   BT_URL="${SIFI_BOWTIE_URL:-https://github.com/BenLangmead/bowtie/releases/download/v1.3.1/bowtie-1.3.1-linux-x86_64.zip}" ;;
      win32-*)   BT_URL="${SIFI_BOWTIE_URL:-https://github.com/BenLangmead/bowtie/releases/download/v1.3.1/bowtie-1.3.1-win-x86_64.zip}" ;;
      *)         BT_URL="${SIFI_BOWTIE_URL:-}" ;;
    esac
    if [ -n "$BT_URL" ]; then
      echo "   ↓ $BT_URL"
      if fetch "$BT_URL" "$REPO_ROOT/build/bowtie-download.zip" && unpack "$REPO_ROOT/build/bowtie-download.zip"; then
        for f in "$TMP"/unpacked/*/bowtie*; do
          [ -f "$f" ] || continue
          cp -f "$f" "$DEST/$(basename "$f")"
        done
        chmod +x "$DEST"/bowtie* 2>/dev/null || true
        for f in "$TMP"/unpacked/*/LICENSE*; do [ -f "$f" ] && cp -f "$f" "$DEST/LICENSE-bowtie.txt"; done
      fi
    fi
  fi
  if [ ! -f "$DEST/RNAplfold$EXE" ] && [ -n "${SIFI_VIENNA_URL:-}" ]; then
    echo "   ↓ $SIFI_VIENNA_URL"
    ext="${SIFI_VIENNA_URL##*.}"
    if fetch "$SIFI_VIENNA_URL" "$REPO_ROOT/build/vienna-download.$ext" \
       && unpack "$REPO_ROOT/build/vienna-download.$ext"; then
      found="$(find "$TMP/unpacked" -name "RNAplfold$EXE" -type f | head -1)"
      [ -n "$found" ] && copy_exec "$found" "RNAplfold$EXE" || true
      lic="$(find "$TMP/unpacked" -iname "COPYING*" -o -iname "LICENSE*" | head -1)"
      [ -n "$lic" ] && cp -f "$lic" "$DEST/LICENSE-ViennaRNA.txt" || true
    fi
  fi
fi

# --- wrappers de bowtie (Linux/macOS) -------------------------------------- #
# El zip oficial trae `bowtie` como script Python: en una app de escritorio no hay
# `python3` en el PATH del usuario. En Linux lo reemplazamos por un sh mínimo que
# exec-ea el binario real (mismo comportamiento: -s por defecto, -l si el índice
# es grande). En Windows el `bowtie.exe` ya es un ejecutable.
if [ "$EXE" = "" ] && [ -f "$DEST/bowtie-align-s" ]; then
  cat > "$DEST/bowtie" <<'EOF'
#!/bin/sh
# Wrapper mínimo de bowtie para el bundle de siFi-Desk.
# Uso: bowtie [opciones de bowtie] <idx> -f <reads> <out>
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
impl="$here/bowtie-align-s"
for a in "$@"; do
  case "$a" in
    -*) ;;
    *) if [ ! -e "$a.1.ebwt" ] && [ -e "$a.1.ebwtl" ] && [ -x "$here/bowtie-align-l" ]; then
         impl="$here/bowtie-align-l"
       fi ;;
  esac
done
exec "$impl" --wrapper basic-0 "$@"
EOF
  chmod +x "$DEST/bowtie"
  if [ -f "$DEST/bowtie-build-s" ]; then
    cat > "$DEST/bowtie-build" <<'EOF'
#!/bin/sh
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$here/bowtie-build-s" "$@"
EOF
    chmod +x "$DEST/bowtie-build"
  fi
  if [ -f "$DEST/bowtie-inspect-s" ]; then
    cat > "$DEST/bowtie-inspect" <<'EOF'
#!/bin/sh
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$here/bowtie-inspect-s" "$@"
EOF
    chmod +x "$DEST/bowtie-inspect"
  fi
fi

# --- manifiesto + verificación -------------------------------------------- #
"$PYTHON" - "$DEST" "$PLAT" <<'PY'
import hashlib, json, os, sys
d, plat = sys.argv[1], sys.argv[2]
man = {"platform": plat, "files": {}}
for name in sorted(os.listdir(d)):
    p = os.path.join(d, name)
    if not os.path.isfile(p) or name.endswith((".json", ".md", ".txt")):
        continue
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    man["files"][name] = {"sha256": h, "bytes": os.path.getsize(p)}
with open(os.path.join(d, "MANIFEST.json"), "w", encoding="utf-8") as fh:
    json.dump(man, fh, indent=2)
    fh.write("\n")
print(f"   {len(man['files'])} binarios, "
      f"{sum(v['bytes'] for v in man['files'].values()) / 1e6:.1f} MB")
PY

if have_all; then
  echo "== OK: $DEST"
else
  echo "== INCOMPLETO: faltan binarios en $DEST" >&2
  case "$PLAT" in
    win32-*)
      echo "   Windows: usá el zip oficial de bowtie (bowtie-1.3.1-win-x86_64.zip) y" >&2
      echo "   RNAplfold del instalador de ViennaRNA 2.7.2 (o compilá con MSYS2/MinGW):" >&2
      echo "     powershell -File scripts/build_windows.ps1 -FetchOnly" >&2 ;;
    *)
      echo "   Compilá y volvé a correr con SIFI_VENDOR_SRC=<dir>:" >&2
      echo "     bowtie:     make -C bowtie-1.3.1" >&2
      echo "     ViennaRNA:  ./configure --without-perl && make -j && make install" >&2 ;;
  esac
  exit 1
fi
