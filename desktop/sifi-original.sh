#!/usr/bin/env bash
# siFi 21 original (2019): corre SU motor y muestra SUS dos gráficos.
#
# La ventana PyQt4 del original no arranca en este equipo (necesita Python 2.7 + PyQt4,
# que no existen para Python 3). El cálculo sí corre: es el mismo código, con los parches
# mínimos que también usa el oráculo de tests.
set -uo pipefail
REPO="/mnt/datos/proyectos/sifi-desk"
OUT="${SIFI_OLD_OUT:-$HOME/.sifidesk/original}"
mkdir -p "$OUT"

FASTA="$(zenity --file-selection --title="siFi original — elegí un FASTA" \
  --filename="$REPO/tests/data/" 2>/dev/null)" || exit 0
[ -n "${FASTA:-}" ] || exit 0

MM="$(zenity --list --title="Mismatches permitidos" --column="valor" 0 1 2 3 2>/dev/null | head -1)"
[ -n "${MM:-}" ] || MM=2
MODO="$(zenity --list --title="Modo" --column="modo" design offtarget 2>/dev/null | head -1)"
[ -n "${MODO:-}" ] || MODO=design

IDX="$(zenity --file-selection --directory --title="Índice bowtie (carpeta con idx.*.ebwt)" \
  --filename="$HOME/.sifidesk/panels/" 2>/dev/null)" || exit 0
[ -n "${IDX:-}" ] || exit 0
DB="$(basename "$(dirname "$IDX")")"; [ "$DB" = "v1" ] && DB="idx"

(
  cd "$REPO" || exit 1
  export SIFI_BOWTIE="$REPO/build/bowtie-1.3.1-linux-x86_64/bowtie"
  export PATH="$(dirname "$SIFI_BOWTIE"):$REPO/build/vienna/bin:$PATH"
  python3 - "$FASTA" "$MM" "$MODO" "$IDX" "$DB" "$OUT" <<'PY'
import json, os, sys
sys.path.insert(0, "tests")
sys.path.insert(0, "tests/oracle")
import diff_oracle as D
fasta, mm, modo, idx, db, out = sys.argv[1:7]
filas = D.run_original(modo, int(mm), "Hit_A", db, fasta, db_location=idx.rstrip("/") + "/")
if not filas:
    print("El original no devolvió filas (sin hits o error)."); raise SystemExit(3)
ruta = os.path.join(out, "original.json")
json.dump(filas, open(ruta, "w"), indent=1)
print("filas:", len(filas), "->", ruta)
PY
) 2>&1 | zenity --text-info --title="siFi original — motor" --width=620 --height=260 2>/dev/null

if [ -f "$OUT/original.json" ]; then
  python3 "$REPO/desktop/old_plots.py" --json "$OUT/original.json" --query "$FASTA" \
    --out-dir "$OUT" 2>&1 | tail -2
  xdg-open "$OUT/sifi-original-diseno.png" >/dev/null 2>&1 &
  sleep 1
  xdg-open "$OUT/sifi-original-offtarget.png" >/dev/null 2>&1 &
fi
