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

unpkg serves the same bytes npm publishes, but it's still a third-party
CDN sitting between you and the registry — verify against the npm
registry's own published checksum (its `dist.shasum`/`dist.integrity`),
not just "the download succeeded" (PT-20, seceng finding: an unauthenticated
curl-by-eye isn't a supply-chain verification step). Verify the tarball,
not the individual unpkg file — the registry only publishes a checksum for
the whole package tarball, not per-file.

```
# 1. Fetch the registry's published tarball + shasum for the target version.
curl -s "https://registry.npmjs.org/marked/<version>" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['dist']['tarball']); print(d['dist']['shasum'])"

# 2. Download the tarball and verify its sha1 matches dist.shasum exactly.
curl -fsSL -o marked.tgz "<tarball url from step 1>"
shasum -a 1 marked.tgz   # must equal the shasum printed in step 1

# 3. Extract and copy the file out -- do not re-download from unpkg once
#    the tarball itself is verified.
tar xzf marked.tgz
cp package/lib/marked.umd.js scripts/cairn/board/vendor/marked.js

# Repeat all three steps for dompurify (tarball path: package/dist/purify.min.js).
```

Then strip any trailing `//# sourceMappingURL=...` line from both files
before committing, re-check the versions against known CVEs (seceng did
this at PT-4's implementation time for 18.0.10 / 3.4.14 — clean), and
update the sha256 checksums below to match the newly committed files.

## Checksums of the committed files (post sourceMappingURL-strip)

These are `shasum -a 256` of the files as they sit in this directory today
— re-run and update after any re-vendor, so a future audit can confirm
what's on disk hasn't drifted from what NOTICE.md documents:

```
f649aa15858f991f0407930b427905ce06f47949a768e1d491e986fc41407a80  marked.js
1a83c283c3229acad7ad9f8f874572bcb031df0f79e114318a2957dc2ffcc117  purify.min.js
```
