#!/usr/bin/env bash
# Compatibilidad: el script vive en packaging/vendor/fetch_binaries.sh (frente M8).
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/packaging/vendor/fetch_binaries.sh" "$@"
