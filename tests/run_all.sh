#!/usr/bin/env bash
# Suite completa: backend + E2E de la UI. Uso: tests/run_all.sh [url]
set -u
cd "$(dirname "$0")/.."
echo "== backend =="
python3 -m pytest tests/ -q || exit 1
echo
echo "== E2E UI =="
TOKEN="${SIFID_TOKEN:-$(grep -rho '"[0-9a-f]\{32\}"' ~/.sifidesk/*.json 2>/dev/null | head -1 | tr -d '"')}"
SIFID_URL="${1:-${SIFID_URL:-http://127.0.0.1:8790}}" SIFID_TOKEN="$TOKEN" \
  node tests/e2e/chat_full.mjs
