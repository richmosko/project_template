#!/usr/bin/env bash
#
# export-pdf.sh — render docs/<DOC>/index.html to a standalone, portable PDF.
#
# Why headless Chrome (and not weasyprint / pandoc / wkhtmltopdf): the docs use
# Mermaid diagrams that are rendered by JavaScript at load time. Only a real
# browser engine executes that JS, so only Chrome/Chromium produces a PDF with
# the diagrams actually drawn.
#
# The script briefly starts the local docs server (scripts/serve-docs.py) so
# Mermaid's CDN module and relative assets resolve, prints each doc to PDF, then
# stops the server. The resulting PDF is fully standalone:
#   - readable with no server (double-click, email, drop in Drive)
#   - GitHub renders it inline in its web UI (unlike the raw HTML)
#   - annotatable in any PDF reader (Preview / Acrobat)
#
# Comment-widget chrome and TBD stubs are hidden via @media print in doc.css;
# <details> sections are force-opened by toc.js's beforeprint handler, so no
# collapsed content is dropped.
#
# Usage:
#   ./scripts/export-pdf.sh                 # all four docs
#   ./scripts/export-pdf.sh PRD ARCH        # only the named docs
#
# Env overrides:
#   DOCS_PORT=8080   port for the temporary docs server (default 8765)
#   CHROME=/path     explicit browser binary (skips auto-detection)
#
# Output: docs/<DOC>/<DOC>.pdf

set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${DOCS_PORT:-8765}"
BASE="http://127.0.0.1:${PORT}"

DOCS=("$@")
if [ ${#DOCS[@]} -eq 0 ]; then
  DOCS=(PRD ARCH SECURITY DESIGN)
fi

# ── Locate a Chromium-family browser ────────────────────────────────────────
# Prefer chrome-headless-shell / "Chrome for Testing": dedicated headless
# binaries that DON'T conflict with an already-running Chrome. Plain Google
# Chrome works too, but if you have Chrome open, a headless print can hang or
# silently produce nothing (a single-instance conflict) — the bounded render
# below turns that into a clear error instead of an infinite hang.
CHROME="${CHROME:-}"
if [ -z "$CHROME" ]; then
  for c in \
    "$(command -v chrome-headless-shell 2>/dev/null || true)" \
    "$HOME/.cache/puppeteer/chrome-headless-shell"/*/chrome-headless-shell* \
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
    "$(command -v google-chrome 2>/dev/null || true)" \
    "$(command -v google-chrome-stable 2>/dev/null || true)" \
    "$(command -v chromium 2>/dev/null || true)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then CHROME="$c"; break; fi
  done
fi
if [ -z "$CHROME" ] || [ ! -x "$CHROME" ]; then
  echo "Error: no Chromium-family browser found (needed to render Mermaid diagrams)." >&2
  echo "Install Google Chrome, or run with CHROME=/path/to/chrome ./scripts/export-pdf.sh" >&2
  exit 1
fi

# Warn if we're about to drive a full Chrome that's already running.
case "$CHROME" in
  *chrome-headless-shell*|*"for Testing"*) ;;  # conflict-free binaries
  *)
    if pgrep -x "Google Chrome" >/dev/null 2>&1; then
      echo "Note: Google Chrome is already running. Headless export may conflict with it." >&2
      echo "      If a render hangs or yields no PDF, quit Chrome and retry, or install" >&2
      echo "      chrome-headless-shell (npx @puppeteer/browsers install chrome-headless-shell)." >&2
    fi
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required (to serve docs/ during rendering)." >&2
  exit 1
fi

# ── Temp state + cleanup ────────────────────────────────────────────────────
SERVER_PID=""
TMP_PROFILE="$(mktemp -d)"
cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$TMP_PROFILE"
}
trap cleanup EXIT

# ── Ensure a docs server is up (reuse if one already answers) ────────────────
if curl -sf -o /dev/null "${BASE}/"; then
  echo "Reusing docs server already on :${PORT}"
else
  DOCS_PORT="$PORT" python3 scripts/serve-docs.py >/dev/null 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 50); do
    if curl -sf -o /dev/null "${BASE}/"; then break; fi
    sleep 0.2
  done
  if ! curl -sf -o /dev/null "${BASE}/"; then
    echo "Error: docs server did not come up on :${PORT}." >&2
    exit 1
  fi
fi

# ── Render each doc ─────────────────────────────────────────────────────────
status=0
for DOC in "${DOCS[@]}"; do
  SRC="docs/${DOC}/index.html"
  if [ ! -f "$SRC" ]; then
    echo "skip ${DOC} — ${SRC} not found"
    continue
  fi
  OUT="docs/${DOC}/${DOC}.pdf"
  echo "Rendering ${DOC} → ${OUT}"
  rm -f "$OUT"
  # --virtual-time-budget lets Mermaid's async render finish before the PDF is
  # captured. Run in the background and bound the wait, so a single-instance
  # conflict (Chrome already running) surfaces as an error, not an infinite hang.
  "$CHROME" \
      --headless=new \
      --disable-gpu \
      --no-sandbox \
      --no-first-run \
      --no-default-browser-check \
      --disable-background-networking \
      --user-data-dir="$TMP_PROFILE" \
      --virtual-time-budget=15000 \
      --print-to-pdf="$OUT" \
      "${BASE}/${DOC}/index.html" >/dev/null 2>&1 &
  CH=$!
  ok=0
  for _ in $(seq 1 60); do            # up to ~30s
    if ! kill -0 "$CH" 2>/dev/null; then ok=1; break; fi
    sleep 0.5
  done
  if [ "$ok" -eq 0 ]; then kill "$CH" 2>/dev/null || true; fi
  wait "$CH" 2>/dev/null || true
  if [ -s "$OUT" ]; then
    echo "  ✓ $(du -h "$OUT" | cut -f1)  ${OUT}"
  else
    echo "  ✗ failed to render ${DOC} (no PDF produced)." >&2
    echo "    Most likely Chrome is already running — quit it and retry, or install" >&2
    echo "    chrome-headless-shell (npx @puppeteer/browsers install chrome-headless-shell)." >&2
    status=1
  fi
done

exit $status
