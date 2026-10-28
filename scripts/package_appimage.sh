#!/usr/bin/env bash
# Arma un .AppImage "casero" (AppDir + appimagetool si está) a partir del bundle.
#   bash scripts/package_appimage.sh dist/sifi-desk-linux
# Sin appimagetool (o sin red) sale con 0 y no genera nada: el CI lo tolera.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUNDLE="${1:-$REPO/dist/sifi-desk-linux}"
OUT="$REPO/dist/sifi-desk-x86_64.AppImage"
APPIDIR="$REPO/build/sifi-desk.AppDir"

[ -d "$BUNDLE" ] || { echo "no existe $BUNDLE" >&2; exit 1; }

TOOL="${APPIMAGETOOL:-}"
if [ -z "$TOOL" ]; then
  if command -v appimagetool >/dev/null 2>&1; then
    TOOL="$(command -v appimagetool)"
  elif [ -x "$REPO/build/appimagetool" ]; then
    TOOL="$REPO/build/appimagetool"
  else
    curl -fsSL --retry 2 -o "$REPO/build/appimagetool" \
      https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage \
      2>/dev/null && chmod +x "$REPO/build/appimagetool" && TOOL="$REPO/build/appimagetool" \
      || { echo "sin appimagetool: no armo AppImage"; exit 0; }
  fi
fi

rm -rf "$APPIDIR"
mkdir -p "$APPIDIR/usr/bin" "$APPIDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$BUNDLE" "$APPIDIR/usr/bin/sifi-desk"
ln -sf sifi-desk/sifid "$APPIDIR/usr/bin/sifid"
ln -sf sifi-desk/sifi  "$APPIDIR/usr/bin/sifi"

cat > "$APPIDIR/AppRun" <<'EOF'
#!/bin/sh
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$here/usr/bin/sifi-desk/sifid" "$@"
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

# Ícono mínimo (PNG 1x1 si no hay assets): AppImage exige uno.
if [ -f "$REPO/ui/src-tauri/icons/128x128.png" ]; then
  cp "$REPO/ui/src-tauri/icons/128x128.png" "$APPIDIR/sifi-desk.png"
else
  printf '\x89PNG\r\n\x1a\n' > "$APPIDIR/sifi-desk.png"
fi
cp "$APPIDIR/sifi-desk.png" "$APPIDIR/usr/share/icons/hicolor/256x256/apps/sifi-desk.png"

ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPIDIR" "$OUT" >/dev/null 2>&1 \
  || ARCH=x86_64 "$TOOL" --no-appstream "$APPIDIR" "$OUT" >/dev/null 2>&1 \
  || { echo "appimagetool falló"; exit 0; }
echo "AppImage: ${OUT#$REPO/}"
