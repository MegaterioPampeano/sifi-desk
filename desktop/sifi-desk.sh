#!/usr/bin/env bash
# Abre siFi Desk: levanta el servicio si no está y abre el navegador.
set -uo pipefail
REPO="/mnt/datos/proyectos/sifi-desk"
PORT="${SIFID_PORT:-8790}"
DATA="${SIFID_DATA_DIR:-$HOME/.sifidesk/sifid}"
PANELS="${SIFI_PANELS_ROOT:-$HOME/.sifidesk/panels}"
TOKF="$HOME/.sifidesk/token"
mkdir -p "$HOME/.sifidesk" "$DATA" "$PANELS"
[ -s "$TOKF" ] || openssl rand -hex 16 > "$TOKF"
chmod 600 "$TOKF"
TOKEN="$(cat "$TOKF")"

if ! curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null; then
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  systemctl --user stop sifid-desk >/dev/null 2>&1 || true
  systemd-run --user --unit=sifid-desk --collect \
    --working-directory="$REPO/core" \
    --setenv=PYTHONPATH="$REPO/core" \
    --setenv=SIFI_EDITION="${SIFI_EDITION:-stable}" \
    --setenv=SIFI_PANELS_ROOT="$PANELS" \
    --setenv=SIFI_BOWTIE="$REPO/build/bowtie-1.3.1-linux-x86_64/bowtie" \
    --setenv=SIFI_RNAPLFOLD="$REPO/build/vienna/bin/RNAplfold" \
    /usr/bin/python3 -m service.app --port "$PORT" --data-dir "$DATA" \
      --panels-root "$PANELS" --ui-dir "$REPO/ui" --token "$TOKEN" >/dev/null 2>&1
  for _ in $(seq 1 40); do
    curl -sf -m 1 "http://127.0.0.1:$PORT/health" >/dev/null && break
    sleep 0.25
  done
fi
if ! curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null; then
  zenity --error --text="No pude levantar el servicio siFi Desk en el puerto $PORT.\n\nRevisá: journalctl --user -u sifid-desk -n 40" 2>/dev/null
  exit 1
fi
URL="http://127.0.0.1:$PORT/?token=$TOKEN"

# Ventana propia (GTK + WebKit) si hay sesión gráfica; si no, navegador.
if [ "${SIFID_WINDOW:-1}" = "1" ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] \
   && python3 -c "import gi; gi.require_version('WebKit2','4.1')" 2>/dev/null; then
  exec "$(dirname "${BASH_SOURCE[0]}")/sifi_desk_window.py" "$URL"
fi

if ! xdg-open "$URL" >/dev/null 2>&1; then
  command -v firefox >/dev/null && { firefox "$URL" >/dev/null 2>&1 & exit 0; }
  echo "$URL"
fi
