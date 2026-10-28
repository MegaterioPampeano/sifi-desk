#!/usr/bin/env bash
# build_vendor_linux.sh — deja `packaging/vendor/linux-x86_64/` completo en una
# máquina limpia (CI incluido), sin sudo y sin versionar binarios.
#
#   bash scripts/build_vendor_linux.sh              # bowtie + RNAplfold → vendor/
#   bash scripts/build_vendor_linux.sh --no-install  # sólo build/vendor/...
#   bash scripts/build_vendor_linux.sh --force       # rehacer aunque exista
#
# Procedencia (packaging/vendor/pins.sh, con sha256 fijado):
#   · bowtie 1.3.1  → zip oficial de GitHub Releases (binarios estáticos).
#   · RNAplfold     → se COMPILA de ViennaRNA 2.7.2: no hay binario estático
#                     oficial y el producto no acepta binarios de origen dudoso.
#   · Si un sha256 no coincide, aborta (nada de "seguir con lo que haya").
#
# Cache: `build/dl/` (descargas) y `build/vendor/<plat>/` (binarios). Son
# gitignoreados; en CI conviene cachearlos (ver .github/workflows/build.yml).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
# shellcheck source=../packaging/vendor/pins.sh
. "$REPO/packaging/vendor/pins.sh"

PYTHON="$(command -v python3 || command -v python)"
PLAT="$("$PYTHON" -c 'import sys, platform; print(f"{sys.platform}-{platform.machine()}")')"
case "$PLAT" in linux-*) ;; *) echo "este script es para Linux (plataforma: $PLAT)" >&2; exit 1 ;; esac

OUT="$REPO/build/vendor/$PLAT"
DL="$REPO/build/dl"
JOBS="$(nproc 2>/dev/null || echo 2)"
DO_BOWTIE=1; DO_VIENNA=1; FORCE=0; INSTALL=1
for a in "$@"; do
  case "$a" in
    --only-bowtie) DO_VIENNA=0 ;;
    --only-vienna) DO_BOWTIE=0 ;;
    --force) FORCE=1 ;;
    --no-install) INSTALL=0 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "opción desconocida: $a" >&2; exit 2 ;;
  esac
done

mkdir -p "$OUT" "$DL"
say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

fetch_pinned() {  # fetch_pinned <url> <destino> <sha256>
  local url="$1" out="$2" want="$3" got
  if [ -f "$out" ] && [ "$FORCE" -eq 0 ]; then
    got="$(sha256sum "$out" | awk '{print $1}')"
    [ "$got" = "$want" ] && { say "· cache ok: $(basename "$out")"; return 0; }
    say "· cache con hash distinto, rebajo: $(basename "$out")"
    rm -f "$out"
  fi
  say "↓ $url"
  curl -fsSL --retry 3 --connect-timeout 20 -o "$out.part" "$url" || die "no se pudo bajar $url"
  got="$(sha256sum "$out.part" | awk '{print $1}')"
  if [ "$got" != "$want" ]; then
    rm -f "$out.part"
    die "sha256 de $(basename "$url") no coincide
     esperado: $want
     obtenido: $got
   (si el upstream cambió, actualizá packaging/vendor/pins.sh en un commit aparte)"
  fi
  mv "$out.part" "$out"
  say "  sha256 ok (${want:0:16}…)"
}

# --- 1. bowtie -------------------------------------------------------------- #
if [ "$DO_BOWTIE" -eq 1 ]; then
  say "== bowtie $BOWTIE_VERSION"
  if [ -x "$OUT/bowtie" ] && [ "$FORCE" -eq 0 ]; then
    say "· ya está $OUT/bowtie (--force para rehacer)"
  else
    zip="$DL/bowtie-$BOWTIE_VERSION-linux-x86_64.zip"
    fetch_pinned "$BOWTIE_URL_LINUX" "$zip" "$BOWTIE_SHA_LINUX"
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    unzip -q -o "$zip" -d "$tmp"
    src="$(dirname "$(find "$tmp" -name bowtie -type f | head -1)")"
    [ -n "$src" ] || die "no encontré bowtie dentro del zip"
    # Sólo las variantes "small index" (las que usa el producto): las -l/-inspect
    # son ~40 MB de binarios que ningún panel toca (SIFI_VENDOR_FULL=1 las trae).
    for f in bowtie bowtie-align-s bowtie-build bowtie-build-s; do
      [ -f "$src/$f" ] || die "falta $f en el zip de bowtie"
      cp -f "$src/$f" "$OUT/$f"; chmod +x "$OUT/$f"
    done
    if [ -n "${SIFI_VENDOR_FULL:-}" ]; then
      for f in bowtie-align-l bowtie-build-l bowtie-inspect bowtie-inspect-s; do
        [ -f "$src/$f" ] && cp -f "$src/$f" "$OUT/$f" && chmod +x "$OUT/$f"
      done
    fi
    for lic in LICENSE AUTHORS; do
      [ -f "$src/$lic" ] && cp -f "$src/$lic" "$OUT/LICENSE-bowtie.txt" && break
    done
    rm -rf "$tmp"; trap - EXIT
    say "✓ $OUT/bowtie ($("$OUT/bowtie" --version | head -1))"
  fi
fi

# --- 2. RNAplfold (ViennaRNA desde fuente) ---------------------------------- #
if [ "$DO_VIENNA" -eq 1 ]; then
  say "== RNAplfold (ViennaRNA $VIENNA_VERSION)"
  if [ -x "$OUT/RNAplfold" ] && [ "$FORCE" -eq 0 ]; then
    say "· ya está $OUT/RNAplfold (--force para rehacer)"
  else
    for t in gcc make; do command -v "$t" >/dev/null || die "falta $t (build-essential)"; done
    tgz="$DL/ViennaRNA-$VIENNA_VERSION.tar.gz"
    fetch_pinned "$VIENNA_SRC_URL" "$tgz" "$VIENNA_SRC_SHA"
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    tar -xzf "$tgz" -C "$tmp"
    srcdir="$tmp/ViennaRNA-$VIENNA_VERSION"
    [ -d "$srcdir" ] || die "no se descomprimió ViennaRNA"
    say "· configure (sin perl/python/docs, sin openmp)"
    ( cd "$srcdir" && ./configure --without-perl --without-python --without-doc \
        --disable-openmp >"$tmp/configure.log" 2>&1 ) || { tail -20 "$tmp/configure.log" >&2; die "configure falló"; }
    say "· make -j$JOBS (5-10 min)"
    ( cd "$srcdir" && make -j"$JOBS" >"$tmp/make.log" 2>&1 ) || { tail -30 "$tmp/make.log" >&2; die "make falló"; }
    bin="$(find "$srcdir" -path '*/src/bin/RNAplfold' -type f | head -1)"
    [ -n "$bin" ] || die "make terminó sin src/bin/RNAplfold"
    cp -f "$bin" "$OUT/RNAplfold"; chmod +x "$OUT/RNAplfold"
    lic="$(find "$srcdir" -maxdepth 1 -iname 'COPYING*' | head -1)"
    [ -n "$lic" ] && cp -f "$lic" "$OUT/LICENSE-ViennaRNA.txt"
    rm -rf "$tmp"; trap - EXIT
    say "✓ $OUT/RNAplfold ($("$OUT/RNAplfold" --version 2>&1 | head -1))"
  fi
fi

[ -x "$OUT/bowtie" ] || die "falta bowtie en $OUT"
[ -x "$OUT/RNAplfold" ] || die "falta RNAplfold en $OUT"

# --- 3. publicar a packaging/vendor/<plat> --------------------------------- #
if [ "$INSTALL" -eq 1 ]; then
  say "== instalando en packaging/vendor/$PLAT (con MANIFEST.json)"
  SIFI_VENDOR_SRC="$OUT" bash "$REPO/packaging/vendor/fetch_binaries.sh" --force
  bash "$REPO/packaging/vendor/fetch_binaries.sh" --check
else
  say "== --no-install: binarios en $OUT"
  say "   usalos con: SIFI_VENDOR_SRC=$OUT bash packaging/vendor/fetch_binaries.sh"
fi
