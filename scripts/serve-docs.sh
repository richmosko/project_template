#!/usr/bin/env bash
#
# serve-docs.sh — wrapper that runs scripts/serve-docs.py.
#
# Serves docs/ over http://localhost:8765 with a comments API used by the
# in-browser comment widget (docs/_assets/comments.js). Posted comments
# append to docs/<DOC>/comments.md and are processed by /refine-doc later.
#
# Run from the repo root. Override the port via env:
#     DOCS_PORT=8080 ./scripts/serve-docs.sh

set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required but not found in PATH." >&2
  echo "Install Python 3 and try again." >&2
  exit 1
fi

cd "$(dirname "$0")/.."
exec python3 scripts/serve-docs.py
