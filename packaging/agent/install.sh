#!/usr/bin/env bash
# install.sh — deja el agente de siFi-Desk listo para correr, sin sudo.
#
#   bash /opt/sifi-desk/agent/install.sh              # copia a ~/.sifi/agent + npm ci
#   bash /opt/sifi-desk/agent/install.sh --dir ~/x    # otro destino
#   bash /opt/sifi-desk/agent/install.sh --light      # sin el CLI de dsh (usa el del PATH)
#
# Por qué copia: el bundle vive en /opt (root) y `npm ci` necesita escribir. Este
# script NO instala nada del sistema: Node 22+ y (en --light) el CLI `dsh` son
# prerrequisito y se verifican acá con un mensaje accionable.
#
# Resultado: $DEST/dsh es un DSH_HOME completo. Uso:
#   DSH_HOME=~/.sifi/agent/dsh dsh --profile sifi headless "Llamá a sifi_panels"
# `sifi doctor` verifica lo mismo (y si el perfil monta) sin instalar nada.
set -euo pipefail

DSH_PIN="0.2.1-rc.2"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # <bundle>/agent
DEST="${SIFI_AGENT_HOME:-$HOME/.sifi/agent}"
LIGHT=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DEST="$2"; shift 2 ;;
    --light) LIGHT=1; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "opción desconocida: $1" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

# --- 0. prerrequisitos ------------------------------------------------------ #
NODE="${SIFI_NODE:-$(command -v node || command -v nodejs || true)}"
[ -n "$NODE" ] || die "falta Node.js 22+ (runtime de dsh: no va embebido en el instalable).
  Debian/Ubuntu:  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
  o bajá un build oficial: https://nodejs.org/dist/v22.22.0/"
NODE_VER="$("$NODE" -v 2>/dev/null || echo v0)"; NODE_MAJ="${NODE_VER#v}"; NODE_MAJ="${NODE_MAJ%%.*}"
[ "${NODE_MAJ:-0}" -ge 22 ] || die "Node $NODE_VER es viejo: dsh necesita >= 22."
say "✓ node $NODE_VER ($NODE)"

NPM="$(command -v npm || true)"
[ -n "$NPM" ] || die "falta npm (viene con Node)."

if [ "$LIGHT" = 1 ]; then
  DSH="$(command -v dsh || true)"
  [ -n "$DSH" ] || die "--light necesita el CLI de dsh en el PATH:
  npm i -g @deepseek-ai/dsh@$DSH_PIN"
  DV="$("$DSH" --version 2>/dev/null | head -1)"
  [ "$DV" = "$DSH_PIN" ] || say "! dsh $DV != pin $DSH_PIN: el bundle sifi-tools puede saltearse"
else
  say "· instalación completa: dsh $DSH_PIN queda en $DEST/dsh/node_modules/.bin/dsh"
fi

# --- 1. copiar el agente ---------------------------------------------------- #
[ -f "$HERE/dsh/package.json" ] || die "$HERE no parece ser el agent/ del bundle"
if [ "$DEST" != "$HERE" ]; then
  say "· copiando agente → $DEST"
  mkdir -p "$DEST"
  for item in package.json package-lock.json src prompts bin dsh; do
    [ -e "$HERE/$item" ] || continue
    rm -rf "$DEST/$item"
    cp -a "$HERE/$item" "$DEST/$item"
  done
  cp -a "$HERE/install.sh" "$DEST/install.sh" 2>/dev/null || true
fi

# --- 2. npm ci (árbol del harness, verificado por package-lock) ------------- #
cd "$DEST/dsh"
STAMP="node_modules/.sifi-lock-sha256"
WANT="$(sha256sum package-lock.json | awk '{print $1}')"
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$WANT" ]; then
  say "✓ harness ya instalado (package-lock sin cambios)"
else
  say "· npm ci en $DEST/dsh (621 paquetes, ~884 MB; tarda ~1-3 min)"
  if [ "$LIGHT" = 1 ]; then
    "$NPM" ci --omit=dev --no-audit --no-fund
  else
    "$NPM" ci --no-audit --no-fund
  fi
  echo "$WANT" > "$STAMP"
fi

# --- 3. cómo se usa --------------------------------------------------------- #
say ""
say "listo. DSH_HOME=$DEST/dsh"
say "  DSH_HOME=$DEST/dsh dsh --profile sifi --dump-config"
say "  SIFID_URL=http://127.0.0.1:8765 DSH_HOME=$DEST/dsh \\"
say "    dsh --profile sifi headless \"Llamá a sifi_panels y resumí los paneles\""
say "  DEEPSEEK_API_KEY=... es necesario para el LLM; SIFID_TOKEN si el servicio usa auth."
say "verificación:  sifi doctor"
