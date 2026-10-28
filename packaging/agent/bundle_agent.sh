#!/usr/bin/env bash
# bundle_agent.sh — copia `agent/` al instalable one-dir (M10).
#
#   bash packaging/agent/bundle_agent.sh dist/sifi-desk-linux/agent
#
# Qué entra: el perfil de dsh (`dsh/`), el bundle `sifi-tools`, la persona
# (`prompts/system.md`), las 7 tools (`src/`), el banco de pruebas (`bin/`) y los
# tests (`test/`, 40 KB: sirven para diagnosticar en la máquina del usuario).
#
# Qué NO entra: `node_modules/` (884 MB de harness: prerrequisito, ver
# packaging/agent/README.md), `.env` (credenciales), estado de runtime
# (`sessions/`, `storages/`) ni logs.
#
# Además deja `install.sh` (bootstrap sin sudo a ~/.sifi/agent) y un
# `INFO.json` con el pin del harness y el inventario de lo copiado.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SRC="$REPO/agent"
DEST="${1:?uso: bundle_agent.sh <destino>/agent}"
DSH_PIN="$(sed -n 's/.*"@deepseek-ai\/dsh": *"\([^"]*\)".*/\1/p' "$SRC/dsh/package.json" | head -1)"

[ -f "$SRC/dsh/package.json" ] || { echo "no existe $SRC/dsh/package.json" >&2; exit 1; }
if [ ! -f "$SRC/dsh/package-lock.json" ]; then
  echo "falta $SRC/dsh/package-lock.json: sin lock no hay instalación verificable" >&2
  exit 1
fi

mkdir -p "$DEST"
tar -C "$SRC" -cf - \
  --exclude=node_modules \
  --exclude=.env \
  --exclude=sessions \
  --exclude=storages \
  --exclude=.anonymous-user-id \
  --exclude='*.log' \
  . | tar -C "$DEST" -xf -

cp -f "$HERE/install.sh" "$DEST/install.sh"
cp -f "$HERE/agent_doctor.py" "$DEST/agent_doctor.py"
chmod +x "$DEST/install.sh"

python3 - "$DEST" "$DSH_PIN" <<'PY'
import hashlib, json, os, sys
dest, pin = sys.argv[1], sys.argv[2] or "desconocido"
files = {}
for root, dirs, names in os.walk(dest):
    dirs[:] = [d for d in dirs if d != "node_modules"]
    for n in names:
        p = os.path.join(root, n)
        rel = os.path.relpath(p, dest)
        if rel in ("INFO.json",):
            continue
        files[rel] = {"bytes": os.path.getsize(p),
                      "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()}
info = {
    "agent": "sifi",
    "dsh_home": "dsh",
    "profile": "sifi",
    "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless", "sifi-tools"],
    "dsh_pin": pin,
    "node_min": "22",
    "runtime": "prerrequisito (no embebido): Node 22+ y el árbol de dsh; "
               "install.sh lo instala en ~/.sifi/agent, sifi doctor lo verifica",
    "files": len(files),
    "bytes": sum(v["bytes"] for v in files.values()),
}
json.dump(info, open(os.path.join(dest, "INFO.json"), "w"), indent=2, sort_keys=True)
print(f"   agente: {info['files']} archivos, {info['bytes']/1e3:.0f} kB · dsh {pin}")
PY

echo "agent → ${DEST}"
