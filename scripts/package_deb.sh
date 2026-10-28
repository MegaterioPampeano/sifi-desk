#!/usr/bin/env bash
# Arma dist/sifi-desk_<ver>_amd64.deb a partir del bundle one-dir.
#   bash scripts/package_deb.sh dist/sifi-desk-linux
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUNDLE="${1:-$REPO/dist/sifi-desk-linux}"
VER="$("$BUNDLE/sifi" version 2>/dev/null | awk '{print $NF}' | head -1)"
ver_ok() { printf '%s' "$1" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+'; }
ver_ok "${VER:-}" || VER="0.0.0"
OUT="$REPO/dist/sifi-desk_${VER}_amd64.deb"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

[ -d "$BUNDLE" ] || { echo "no existe $BUNDLE" >&2; exit 1; }

mkdir -p "$WORK/DEBIAN" "$WORK/opt" "$WORK/usr/bin" "$WORK/usr/share/applications"
cp -a "$BUNDLE" "$WORK/opt/sifi-desk"
ln -s /opt/sifi-desk/sifi  "$WORK/usr/bin/sifi"
ln -s /opt/sifi-desk/sifid "$WORK/usr/bin/sifid"

cat > "$WORK/DEBIAN/control" <<EOF
Package: sifi-desk
Version: ${VER}
Section: science
Priority: optional
Architecture: amd64
Maintainer: siFi-Desk <sifi-desk@localhost>
Installed-Size: $(du -sk "$WORK/opt/sifi-desk" | awk '{print $1}')
Depends: libc6
Description: siFi-Desk - diseno de siRNAs con verificacion de off-targets
 Nucleo headless (bowtie + RNAplfold) con API local y CLI.
EOF

cat > "$WORK/usr/share/applications/sifi-desk.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=siFi-Desk
Comment=Diseno de siRNAs y verificacion de off-targets
Exec=/opt/sifi-desk/sifi
Terminal=true
Categories=Science;Biology;
EOF

dpkg-deb --root-owner-group -Zxz --build "$WORK" "$OUT" >/dev/null
echo "deb: ${OUT#$REPO/}"
