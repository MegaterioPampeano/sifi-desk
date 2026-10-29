#!/usr/bin/env bash
# Arma dist/sifi-desk-x86_64.AppImage a partir del bundle one-dir.
#
#   bash scripts/package_appimage.sh dist/sifi-desk-linux
#
# Sin sudo ni FUSE: `appimagetool` se baja (versión y sha256 fijados) a
# packaging/.tools/ y se corre con `--appimage-extract-and-run`. Si algo falta,
# el script **falla con el motivo** (antes salía 0 sin artefacto y el CI no se
# enteraba).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUNDLE="${1:-$REPO/dist/sifi-desk-linux}"
OUT="$REPO/dist/sifi-desk-x86_64.AppImage"
APPIDIR="$REPO/build/sifi-desk.AppDir"
TOOLS="$REPO/packaging/.tools"

# appimagetool 1.9.1 — sin tag "continuous" (mutable) a propósito.
AT_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
AT_SHA="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"

die() { printf '✗ AppImage: %s\n' "$*" >&2; exit 1; }
[ -d "$BUNDLE" ] || die "no existe $BUNDLE"
[ -x "$BUNDLE/sifid" ] || die "el bundle no tiene sifid"

# --- appimagetool ----------------------------------------------------------- #
TOOL="${APPIMAGETOOL:-}"
if [ -z "$TOOL" ] && command -v appimagetool >/dev/null 2>&1; then
  TOOL="$(command -v appimagetool)"
fi
if [ -z "$TOOL" ]; then
  TOOL="$TOOLS/appimagetool-x86_64.AppImage"
  mkdir -p "$TOOLS"
  if [ ! -x "$TOOL" ] || [ "$(sha256sum "$TOOL" | awk '{print $1}')" != "$AT_SHA" ]; then
    echo "-- bajando appimagetool 1.9.1 → ${TOOL#$REPO/}"
    curl -fsSL --retry 3 --connect-timeout 20 -o "$TOOL.part" "$AT_URL" \
      || die "no pude bajar $AT_URL"
    got="$(sha256sum "$TOOL.part" | awk '{print $1}')"
    [ "$got" = "$AT_SHA" ] || { rm -f "$TOOL.part"; die "sha256 de appimagetool no coincide ($got)"; }
    mv "$TOOL.part" "$TOOL"; chmod +x "$TOOL"
  fi
fi
[ -x "$TOOL" ] || die "appimagetool no ejecutable: $TOOL"

# --- AppDir ----------------------------------------------------------------- #
rm -rf "$APPIDIR"
mkdir -p "$APPIDIR/usr/bin" "$APPIDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$BUNDLE" "$APPIDIR/usr/bin/sifi-desk"
ln -sf sifi-desk/sifid "$APPIDIR/usr/bin/sifid"
ln -sf sifi-desk/sifi  "$APPIDIR/usr/bin/sifi"

cat > "$APPIDIR/AppRun" <<'EOF'
#!/bin/sh
# AppRun: por defecto el servicio (sifid). `sifi …` o `--cli …` → CLI headless.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$(basename -- "$0")" in
  sifi) exec "$here/usr/bin/sifi-desk/sifi" "$@" ;;
esac
case "${1:-}" in
  sifi)  shift; exec "$here/usr/bin/sifi-desk/sifi" "$@" ;;
  --cli) shift; exec "$here/usr/bin/sifi-desk/sifi" "$@" ;;
  --server) shift; exec "$here/usr/bin/sifi-desk/sifid" "$@" ;;
esac
# Sin argumentos: modo ventana. Servicio en localhost con la UI estática y el navegador
# apuntando ahí. --no-auth sólo porque el socket bindea 127.0.0.1 (nadie más lo alcanza).
BUNDLE="$here/usr/bin/sifi-desk"
PORT="${SIFI_PORT:-8790}"
"$BUNDLE/sifid" --port "$PORT" --host 127.0.0.1 --no-auth \
    --ui-dir "$BUNDLE/ui" \
    --data-dir "${SIFI_DATA:-$HOME/.sifidesk/sifid}" \
    --panels-root "${SIFI_PANELS:-$HOME/.sifidesk/panels}" >"${SIFI_LOG:-/tmp/sifid-app.log}" 2>&1 &
srv=$!
trap 'kill $srv 2>/dev/null' INT TERM EXIT
for i in $(seq 1 60); do
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/" && break
  sleep 0.5
done
URL="http://127.0.0.1:$PORT/"
# Ventana propia sin barra de direcciones ni pestañas si hay un navegador que lo permita.
abrir() {
  for b in chromium chromium-browser google-chrome brave-browser microsoft-edge; do
    command -v "$b" >/dev/null && { "$b" --app="$URL" --window-size=1280,880 >/dev/null 2>&1 & return 0; }
  done
  command -v firefox >/dev/null && { firefox --new-window "$URL" >/dev/null 2>&1 & return 0; }
  command -v xdg-open >/dev/null && { xdg-open "$URL" >/dev/null 2>&1 & return 0; }
  echo "abrí a mano: $URL"
}
abrir
echo "siFi-Desk: $URL   (log: ${SIFI_LOG:-/tmp/sifid-app.log}; Ctrl-C para cerrar)"
wait $srv
EOF
chmod +x "$APPIDIR/AppRun"

cat > "$APPIDIR/sifi-desk.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=siFi-Desk
Comment=Diseno de siRNAs y verificacion de off-targets
Exec=sifi-desk
Icon=sifi-desk
Terminal=true
Categories=Science;Biology;
EOF

# Ícono: el de la UI si existe; si no, un PNG 1x1 (AppImage exige uno).
ICON=""
for cand in "$REPO/ui/tauri/src-tauri/icons/128x128.png" "$REPO/ui/src-tauri/icons/128x128.png" \
            "$REPO/ui/icons/128x128.png" "$REPO/ui/tauri/icons/128x128.png"; do
  [ -f "$cand" ] && { ICON="$cand"; break; }
done
if [ -n "$ICON" ]; then
  cp "$ICON" "$APPIDIR/sifi-desk.png"
else
  printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82' > "$APPIDIR/sifi-desk.png"
fi
cp -f "$APPIDIR/sifi-desk.png" "$APPIDIR/usr/share/icons/hicolor/256x256/apps/sifi-desk.png"
ln -sf sifi-desk.png "$APPIDIR/.DirIcon"

# --- empaquetar ------------------------------------------------------------- #
rm -f "$OUT"
LOG="$REPO/build/appimagetool.log"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPIDIR" "$OUT" \
  >"$LOG" 2>&1 || {
    echo "-- appimagetool falló; log (${LOG#$REPO/}):" >&2
    sed -n '1,40p' "$LOG" >&2
    die "no se generó el AppImage"
  }
[ -s "$OUT" ] || die "appimagetool salió 0 pero no hay $OUT"
chmod +x "$OUT"
echo "AppImage: ${OUT#$REPO/}  ($(du -h "$OUT" | awk '{print $1}'))"
