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
Recommends: nodejs (>= 22.0.0), npm
Description: siFi-Desk - diseno de siRNAs con verificacion de off-targets
 Nucleo headless (bowtie + RNAplfold) con API local y CLI, mas el agente
 (perfil de dsh + tools del producto) en /opt/sifi-desk/agent. El agente
 necesita Node 22+ y dsh: se instalan aparte (ver /opt/sifi-desk/agent/install.sh)
 y \`sifi doctor\` lo verifica.
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

# Mensaje de instalación: el núcleo queda andando solo; el agente necesita su
# runtime (Node 22+ y dsh, ~1 GB) que a propósito no viaja en el .deb.
cat > "$WORK/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if ! command -v node >/dev/null 2>&1; then
  cat <<'MSG'
siFi-Desk quedó instalado: `sifid` y `sifi` funcionan ya (probá `sifi doctor`).
El agente incluido en /opt/sifi-desk/agent necesita su runtime, que no viaja en
el paquete (Node 22+ y el harness dsh, ~1 GB):
  1) instalá Node 22+ (nodesource o el tarball oficial de nodejs.org)
  2) bash /opt/sifi-desk/agent/install.sh      # deja el harness en ~/.sifi/agent
  3) sifi doctor                               # verifica node, dsh y el perfil
MSG
fi
exit 0
POST
chmod 755 "$WORK/DEBIAN/postinst"

dpkg-deb --root-owner-group -Zxz --build "$WORK" "$OUT" >/dev/null
echo "deb: ${OUT#$REPO/}  ($(du -h "$OUT" | awk '{print $1}'))"
