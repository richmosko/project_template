#!/usr/bin/env bash
#
# vendor-mermaid.sh — download Mermaid locally so HTML docs render without
# CDN access. Use when the default CDN-backed loader is undesired (regulated
# environments, offline workflows, air-gapped deployments, etc.).
#
# Run from the repo root:
#     ./scripts/vendor-mermaid.sh
#
# Pin a specific Mermaid version:
#     MERMAID_VERSION=11.4.0 ./scripts/vendor-mermaid.sh
#
# Revert to CDN:
#     git checkout docs/_assets/mermaid-init.js
#     rm -rf docs/_assets/vendor/
#
# See README.md → External integrations → Mermaid loading: CDN vs vendored.

set -euo pipefail

MERMAID_VERSION="${MERMAID_VERSION:-11}"
VENDOR_DIR="docs/_assets/vendor"
INIT_JS="docs/_assets/mermaid-init.js"
BUNDLE_URL="https://cdn.jsdelivr.net/npm/mermaid@${MERMAID_VERSION}/dist/mermaid.min.js"

if [ ! -d "docs/_assets" ]; then
  echo "Error: docs/_assets/ not found. Run this script from the repo root." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "Error: curl is required but not found in PATH." >&2
  exit 1
fi

mkdir -p "$VENDOR_DIR"

echo "→ Downloading Mermaid @ $MERMAID_VERSION (UMD bundle) from jsdelivr…"
curl -fsSL "$BUNDLE_URL" -o "$VENDOR_DIR/mermaid.min.js"

BUNDLE_SIZE=$(wc -c < "$VENDOR_DIR/mermaid.min.js" | tr -d ' ')
echo "  saved → $VENDOR_DIR/mermaid.min.js ($BUNDLE_SIZE bytes)"

echo "→ Rewriting $INIT_JS to load from vendor/ instead of CDN…"
cat > "$INIT_JS" <<'EOF'
// Loads Mermaid from a local vendored bundle and initializes it.
// Vendored variant — created by scripts/vendor-mermaid.sh for projects
// that can't rely on a CDN at doc-view time (regulated, offline, etc.).
// To revert to the CDN variant: `git checkout docs/_assets/mermaid-init.js`.

(function () {
  var bundle = document.createElement("script");
  bundle.src = "_assets/vendor/mermaid.min.js";
  bundle.onload = function () {
    var darkMode = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    window.mermaid.initialize({
      startOnLoad: true,
      theme: darkMode ? "dark" : "default",
      securityLevel: "loose",
      flowchart: { curve: "basis" },
      themeVariables: {
        fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Inter, system-ui, sans-serif"
      }
    });
    window.mermaid.run();
    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
        document.querySelectorAll(".mermaid").forEach(function (el) {
          el.removeAttribute("data-processed");
          el.innerHTML = el.dataset.source || el.textContent;
        });
        location.reload();
      });
    }
  };
  document.head.appendChild(bundle);

  // Cache raw mermaid source before mermaid mutates it (used on theme switch).
  window.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".mermaid").forEach(function (el) {
      if (!el.dataset.source) el.dataset.source = el.textContent;
    });
  });
})();
EOF

cat <<MSG

✓ Done. Mermaid now loads from $VENDOR_DIR/ instead of the CDN.

Verify:
  - Open docs/PRD.html (or ARCH.html / SECURITY.html) in a browser
  - Disconnect from the internet — diagrams should still render

Notes:
  - $VENDOR_DIR/ is gitignored by default (template-level). If your
    project should commit the bundle, edit your project's .gitignore
    to un-ignore it. Re-running this script regenerates the bundle.
  - The UMD build (mermaid.min.js) is used instead of ESM so file://
    URLs work — you can double-click the HTML docs from Finder.
  - Pin a specific version via MERMAID_VERSION=11.4.0 (or similar).

Revert to CDN:
  git checkout $INIT_JS
  rm -rf $VENDOR_DIR

MSG
