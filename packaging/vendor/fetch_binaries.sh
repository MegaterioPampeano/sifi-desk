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
#   4. Descarga                → bowtie 1.3.1 del release de GitHub, **con sha256
#                                fijado acá abajo** (un hash distinto aborta).
#                                RNAplfold NO se baja de internet: se compila del
#                                fuente con scripts/build_vendor_linux.sh (Linux) o
#                                packaging/vendor/build_vendor_windows.sh (MSYS2), o
#                                se toma de una release propia con SIFI_VIENNA_URL +
#                                SIFI_VIENNA_SHA256.
#
# Este script **falla** si al final falta algún binario (exit 1). Para compilar un
# bundle de desarrollo sin binarios, el que lo pide lo dice explícitamente:
# SIFI_VENDOR_OPTIONAL=1 al compilar (ver scripts/build_linux.sh).
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

# Fuentes versionadas (M10): URL + sha256 fijados en packaging/vendor/pins.sh.
# Si cambia el contenido del release, el build falla en vez de empaquetar otra cosa.
# shellcheck source=pins.sh
. "$REPO_ROOT/packaging/vendor/pins.sh"

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

# --- 4. descarga (sólo fuentes versionadas, con sha256 fijado) -------------- #
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else "$PYTHON" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
  fi
}

fetch_verified() {  # fetch_verified <url> <archivo> <sha256 esperado | "">
  local url="$1" out="$2" want="$3" got
  echo "   ↓ $url"
  fetch "$url" "$out" || { echo "   ✗ no se pudo bajar" >&2; return 1; }
  got="$(sha256_of "$out")"
  if [ -z "$want" ]; then
    echo "   ! sin sha256 fijado para esta URL (origen no verificado): $got" >&2
    return 0
  fi
  if [ "$got" != "$want" ]; then
    echo "   ✗ sha256 NO coincide" >&2
    echo "     esperado: $want" >&2
    echo "     obtenido: $got" >&2
    rm -f "$out"
    return 1
  fi
  echo "   sha256 ok (${want:0:16}…)"
  return 0
}

if ! have_all >/dev/null 2>&1 && [ "$MODE" != "from-build" ]; then
  echo "== fuente: descarga (verificada)"
  if [ ! -f "$DEST/bowtie$EXE" ]; then
    case "$PLAT" in
      linux-*) BT_URL="$BOWTIE_URL_LINUX"; BT_SHA="$BOWTIE_SHA_LINUX" ;;
      win32-*) BT_URL=""; BT_SHA="" ;;   # no hay zip win en el release 1.3.1: se compila
      *)       BT_URL=""; BT_SHA="" ;;
    esac
    # Mirror propio (release corporativa): exige el hash explícito.
    if [ -n "${SIFI_BOWTIE_URL:-}" ]; then
      BT_URL="$SIFI_BOWTIE_URL"
      BT_SHA="${SIFI_BOWTIE_SHA256:-}"
    fi
    if [ -n "$BT_URL" ] && fetch_verified "$BT_URL" "$REPO_ROOT/build/bowtie-download.zip" "$BT_SHA"; then
      unpack "$REPO_ROOT/build/bowtie-download.zip" || true
      # Sólo las variantes "small index" (las únicas que usa el producto):
      # -l/-inspect son ~40 MB de binarios que ningún panel toca.
      keep="bowtie bowtie-align-s bowtie-build bowtie-build-s"
      [ -n "${SIFI_VENDOR_FULL:-}" ] && keep="$keep bowtie-align-l bowtie-build-l bowtie-inspect bowtie-inspect-s"
      for f in "$TMP"/unpacked/*/bowtie*; do
        [ -f "$f" ] || continue
        case " $keep " in
          *" $(basename "$f" | sed 's/\.exe$//') "*) cp -f "$f" "$DEST/$(basename "$f")" ;;
        esac
      done
      chmod +x "$DEST"/bowtie* 2>/dev/null || true
      for f in "$TMP"/unpacked/*/LICENSE*; do [ -f "$f" ] && cp -f "$f" "$DEST/LICENSE-bowtie.txt"; done
      TMP=""
    fi
  fi

  # RNAplfold: no hay binario estático oficial de ViennaRNA. Se compila del
  # fuente pinneado (`scripts/build_vendor_linux.sh`) o se toma de una release
  # propia, y en ese caso hay que dar URL **y** sha256.
  if [ ! -f "$DEST/RNAplfold$EXE" ] && [ -n "${SIFI_VIENNA_URL:-}" ]; then
    if [ -z "${SIFI_VIENNA_SHA256:-}" ]; then
      echo "   ! SIFI_VIENNA_URL sin SIFI_VIENNA_SHA256: no la uso (origen no verificable)" >&2
    else
      ext="tar.gz"
      case "$SIFI_VIENNA_URL" in
        *.zip) ext="zip" ;;
        *.tgz) ext="tar.gz" ;;
        *.tar.xz) ext="tar.xz" ;;
      esac
      out="$REPO_ROOT/build/vienna-vendor.$ext"
      if fetch_verified "$SIFI_VIENNA_URL" "$out" "$SIFI_VIENNA_SHA256" && unpack "$out"; then
        found="$(find "$TMP/unpacked" -name "RNAplfold$EXE" -type f | head -1)"
        [ -n "$found" ] && copy_exec "$found" "RNAplfold$EXE" || true
        lic="$(find "$TMP/unpacked" \( -iname "COPYING*" -o -iname "LICENSE*" \) | head -1)"
        [ -n "$lic" ] && cp -f "$lic" "$DEST/LICENSE-ViennaRNA.txt" || true
        TMP=""
      fi
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
      echo "   Compilá los dos desde el fuente pineado (MSYS2/MinGW64):" >&2
      echo "     bash packaging/vendor/build_vendor_windows.sh" >&2 ;;
    *)
      echo "   Compilá los dos desde el fuente pineado (no hay binario estático de" >&2
      echo "   RNAplfold, y el que hay que usar lo fija packaging/vendor/pins.sh):" >&2
      echo "     bash scripts/build_vendor_linux.sh" >&2
      echo "   o reutilizá un build existente:" >&2
      echo "     SIFI_VENDOR_SRC=<dir con bowtie y RNAplfold> bash packaging/vendor/fetch_binaries.sh" >&2 ;;
  esac
  exit 1
fi
