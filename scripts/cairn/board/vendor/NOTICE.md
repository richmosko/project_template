# Vendored third-party assets

Checked into git (not gitignored, not fetched at runtime) — the board renders
markdown fully offline; a fresh clone works with zero extra steps. PT-4.

| File | Library | Version | License | Source |
|---|---|---|---|---|
| `marked.js` | [marked](https://github.com/markedjs/marked) | 18.0.10 | MIT | `https://unpkg.com/marked@18.0.10/lib/marked.umd.js` |
| `purify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.14 | Apache-2.0 OR MPL-2.0 | `https://unpkg.com/dompurify@3.4.14/dist/purify.min.js` |

`marked.js` is the UMD build, deliberately left unminified for auditability
(43 KB). `purify.min.js` is the upstream minified build (29 KB). Both had
their trailing `//# sourceMappingURL=...` comment stripped on vendoring so
nothing ever attempts even a devtools-triggered network fetch for a source
map that isn't checked in.

## Why this pairing

`marked` parses markdown to HTML but deliberately does not sanitize its
output (upstream's own recommendation is to pair it with a dedicated
sanitizer). `DOMPurify` is the de facto browser HTML sanitizer. board.js
calls them in that order — `DOMPurify.sanitize(marked.parse(text))` — never
the reverse; sanitizing pre-parse is the classic mistake markdown
reconstruction can bypass. See board.js's `renderMarkdown` for the call site
and its `USE_PROFILES: { html: true }` config (seceng's PT-4 pre-clear:
restricts DOMPurify's parser to the HTML grammar only — markdown issue
bodies have no legitimate use for inline SVG/MathML, and SVG has been the
source of most historical DOMPurify mXSS bypass classes).

## Re-vendoring / updating

```
curl -fsSL -o scripts/cairn/board/vendor/marked.js \
  "https://unpkg.com/marked@<version>/lib/marked.umd.js"
curl -fsSL -o scripts/cairn/board/vendor/purify.min.js \
  "https://unpkg.com/dompurify@<version>/dist/purify.min.js"
```

Then strip any trailing `//# sourceMappingURL=...` line from both files
before committing, and re-check the versions against known CVEs (seceng did
this at PT-4's implementation time for 18.0.10 / 3.4.14 — clean).
