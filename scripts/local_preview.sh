#!/usr/bin/env bash
# Thin wrapper around scripts/local_preview.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/local_preview.py" "$@"
