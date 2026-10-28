#!/usr/bin/env bash
# build_vendor_windows.sh — arma packaging/vendor/win32-AMD64/ compilando
# bowtie y RNAplfold con MSYS2/MinGW64, desde las fuentes pineadas.
#
#   bash packaging/vendor/build_vendor_windows.sh
#
# Se corre con el bash de MSYS2 (GitHub Actions windows-latest lo trae en
# C:\msys64). En PowerShell:
#   & C:\msys64\usr\bin\bash.exe -lc "export MSYSTEM=MINGW64; cd /d/a/ruta/repo &&
#       bash packaging/vendor/build_vendor_windows.sh"
#
# Por qué compilar: el release de bowtie 1.3.1 no publica binarios para Windows y
# ViennaRNA no tiene binario estático oficial; bajar un .exe suelto de un tercero
# no es verificable. Los hashes de las fuentes están en pins.sh y se verifican acá.
#
# ⚠️ Estado: escrito y revisado, **no corrido en un Windows real** (M10). Si algo
# falla, el script sale != 0 con el log del paso; el build de Windows no publica
# nada sin binarios (salvo SIFI_VENDOR_OPTIONAL=1 explícito).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
# shellcheck source=pins.sh
. "$HERE/pins.sh"

MSYS="${MSYS2_ROOT:-/c/msys64}"
MINGW="$MSYS/mingw64/bin"
[ -d "$MINGW" ] || { echo "✗ no encuentro MSYS2/MinGW64 en $MINGW (definí MSYS2_ROOT)" >&2; exit 1; }
export PATH="$MINGW:$MSYS/usr/bin:$PATH"

for t in gcc g++ make objdump; do
  command -v "$t" >/dev/null || { echo "✗ falta $t en $MINGW (pacman -S mingw-w64-x86_64-toolchain)" >&2; exit 1; }
done

OUT="$REPO/build/vendor/win32-AMD64"
DL="$REPO/build/dl"
JOBS="${NUMBER_OF_PROCESSORS:-4}"
mkdir -p "$OUT" "$DL"
say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

fetch_pinned() {  # <url> <destino> <sha256>
  local url="$1" out="$2" want="$3" got
  if [ ! -f "$out" ]; then
    say "↓ $url"
    curl -fsSL --retry 3 -o "$out.part" "$url" || die "no pude bajar $url"
    mv "$out.part" "$out"
  fi
  got="$(sha256sum "$out" | awk '{print $1}')"
  [ "$got" = "$want" ] || die "sha256 de $(basename "$out") no coincide ($got != $want)"
  say "  sha256 ok (${want:0:16}…)"
}

# DLLs de MinGW que el .exe necesita además de las del sistema.
collect_dlls() {  # collect_dlls <exe>
  local exe="$1" dll
  for dll in $(objdump -p "$exe" | awk '/DLL Name:/ {print $3}'); do
    case "$dll" in
      KERNEL32.dll|USER32.dll|ADVAPI32.dll|msvcrt.dll|api-ms-*|WS2_32.dll|\
      SHELL32.dll|ole32.dll|OLEAUT32.dll|GDI32.dll|COMDLG32.dll|PSAPI.DLL|\
      VERSION.dll|bcrypt.dll|ucrtbase.dll|ntdll.dll|CRYPT32.dll|WINMM.dll) continue ;;
    esac
    if [ -f "$MINGW/$dll" ] && [ ! -f "$OUT/$dll" ]; then
      cp -f "$MINGW/$dll" "$OUT/$dll"; say "   dll ← $dll"
    fi
  done
}

# --- 1. bowtie -------------------------------------------------------------- #
say "== bowtie $BOWTIE_VERSION (fuente, MinGW64)"
if [ -x "$OUT/bowtie.exe" ]; then
  say "· ya está $OUT/bowtie.exe"
else
  tarball="$DL/bowtie-$BOWTIE_VERSION-src.tar.gz"
  fetch_pinned "$BOWTIE_SRC_URL" "$tarball" "$BOWTIE_SRC_SHA"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  tar -xzf "$tarball" -C "$tmp"
  src="$tmp/bowtie-$BOWTIE_VERSION"
  [ -d "$src" ] || die "no se descomprimió bowtie"
  ( cd "$src" && make -j"$JOBS" BITS=64 >"$tmp/make.log" 2>&1 ) \
    || { tail -40 "$tmp/make.log" >&2; die "make de bowtie falló (¿toolchain MinGW posix threads?)"; }
  for f in bowtie.exe bowtie-align-s.exe bowtie-build.exe bowtie-build-s.exe; do
    [ -f "$src/$f" ] || die "bowtie no generó $f"
    cp -f "$src/$f" "$OUT/$f"
  done
  [ -f "$src/LICENSE" ] && cp -f "$src/LICENSE" "$OUT/LICENSE-bowtie.txt"
  rm -rf "$tmp"; trap - EXIT
  say "✓ $OUT/bowtie.exe"
fi

# --- 2. RNAplfold ----------------------------------------------------------- #
say "== RNAplfold (ViennaRNA $VIENNA_VERSION, fuente, MinGW64)"
if [ -x "$OUT/RNAplfold.exe" ]; then
  say "· ya está $OUT/RNAplfold.exe"
else
  tgz="$DL/ViennaRNA-$VIENNA_VERSION.tar.gz"
  fetch_pinned "$VIENNA_SRC_URL" "$tgz" "$VIENNA_SRC_SHA"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  tar -xzf "$tgz" -C "$tmp"
  src="$tmp/ViennaRNA-$VIENNA_VERSION"
  ( cd "$src" && ./configure --without-perl --without-python --without-doc \
      --disable-openmp >"$tmp/configure.log" 2>&1 ) \
    || { tail -30 "$tmp/configure.log" >&2; die "configure de ViennaRNA falló"; }
  ( cd "$src" && make -j"$JOBS" >"$tmp/make.log" 2>&1 ) \
    || { tail -40 "$tmp/make.log" >&2; die "make de ViennaRNA falló"; }
  bin="$(find "$src" -path '*/src/bin/RNAplfold.exe' -type f | head -1)"
  [ -n "$bin" ] || die "ViennaRNA no generó RNAplfold.exe"
  cp -f "$bin" "$OUT/RNAplfold.exe"
  lic="$(find "$src" -maxdepth 1 -iname 'COPYING*' | head -1)"
  [ -n "$lic" ] && cp -f "$lic" "$OUT/LICENSE-ViennaRNA.txt"
  rm -rf "$tmp"; trap - EXIT
  say "✓ $OUT/RNAplfold.exe"
fi

# --- 3. DLLs + publicación -------------------------------------------------- #
say "== dependencias de runtime (DLLs MinGW)"
collect_dlls "$OUT/bowtie.exe"
collect_dlls "$OUT/bowtie-align-s.exe"
collect_dlls "$OUT/bowtie-build.exe"
collect_dlls "$OUT/bowtie-build-s.exe"
collect_dlls "$OUT/RNAplfold.exe"

PY="$(command -v python || command -v python3 || true)"
[ -n "$PY" ] || die "falta python para generar MANIFEST.json"
say "== publicando en packaging/vendor/win32-AMD64"
SIFI_VENDOR_SRC="$OUT" bash "$REPO/packaging/vendor/fetch_binaries.sh" --force
bash "$REPO/packaging/vendor/fetch_binaries.sh" --check
say "== OK: $OUT"
