# Vendored third-party assets

Checked into git (not gitignored, not fetched at runtime) — the board renders
markdown fully offline; a fresh clone works with zero extra steps. PT-4.

| File | Library | Version | License | Source |
|---|---|---|---|---|
| `marked.js` | [marked](https://github.com/markedjs/marked) | 18.0.10 | MIT | `https://unpkg.com/marked@18.0.10/lib/marked.umd.js` |
| `purify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.14 | Apache-2.0 OR MPL-2.0 | `https://unpkg.com/dompurify@3.4.14/dist/purify.min.js` |
| `fonts/merriweather-latin-wght-normal.woff2` | [Fontsource: Merriweather Variable](https://fontsource.org/fonts/merriweather) | 5.3.0 | SIL OFL 1.1 | `https://unpkg.com/@fontsource-variable/merriweather@5.3.0/files/merriweather-latin-wght-normal.woff2` |
| `fonts/merriweather-latin-ext-wght-normal.woff2` | [Fontsource: Merriweather Variable](https://fontsource.org/fonts/merriweather) | 5.3.0 | SIL OFL 1.1 | `https://unpkg.com/@fontsource-variable/merriweather@5.3.0/files/merriweather-latin-ext-wght-normal.woff2` |
| `fonts/space-grotesk-latin-wght-normal.woff2` | [Fontsource: Space Grotesk Variable](https://fontsource.org/fonts/space-grotesk) | 5.3.0 | SIL OFL 1.1 | `https://unpkg.com/@fontsource-variable/space-grotesk@5.3.0/files/space-grotesk-latin-wght-normal.woff2` |
| `fonts/space-grotesk-latin-ext-wght-normal.woff2` | [Fontsource: Space Grotesk Variable](https://fontsource.org/fonts/space-grotesk) | 5.3.0 | SIL OFL 1.1 | `https://unpkg.com/@fontsource-variable/space-grotesk@5.3.0/files/space-grotesk-latin-ext-wght-normal.woff2` |
| `fonts/geist-mono-latin-wght-normal.woff2` | [Fontsource: Geist Mono Variable](https://fontsource.org/fonts/geist-mono) | 5.3.0 | SIL OFL 1.1 | `https://unpkg.com/@fontsource-variable/geist-mono@5.3.0/files/geist-mono-latin-wght-normal.woff2` |
| `fonts/geist-mono-latin-ext-wght-normal.woff2` | [Fontsource: Geist Mono Variable](https://fontsource.org/fonts/geist-mono) | 5.3.0 | SIL OFL 1.1 | `https://unpkg.com/@fontsource-variable/geist-mono@5.3.0/files/geist-mono-latin-ext-wght-normal.woff2` |

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

## Fonts (PT-63)

Pre-decided by the PT-57 token-delivery ruling's addendum: the board self-hosts
the three preset faces (Merriweather body/UI, Space Grotesk headings, Geist
Mono ids/mono) the same way `marked.js`/`purify.min.js` are vendored — checked
in, zero CDN, zero build. **Explicitly rejected: pointing `board/tokens.css`'s
`@font-face` at the dashboard's `/dashboard/assets/*.woff2`.** It costs no
extra bytes, which is the trap — it would make the board's own rendering
depend on the dashboard's build artifact, the exact dependency direction the
spin-off constraint forbids (an unbuilt dashboard `dist/` would then degrade
the board too, not just the dashboard).

**Subsets: latin + latin-ext only**, matching the dashboard's own scope
decision — six `.woff2` files, ~250KB total (measured: 256KB on disk). The
dashboard's Vite build pulls the FULL `@fontsource-variable` package (every
subset: cyrillic, cyrillic-ext, vietnamese too) because Vite tree-shakes
nothing here and the extra weight is amortized across a SPA that's already
paying for a JS bundle; the vanilla board has no such amortization and no
build step to trim at, so the subset cut happens here, once, by hand.

**Sourced by copying the dashboard's own installed packages, not re-downloaded
from unpkg.** `scripts/cairn/dashboard/node_modules/@fontsource-variable/
{merriweather,space-grotesk,geist-mono}@5.3.0` — the exact version the PT-57
ruling measured — already arrived through npm's own registry-integrity
verification at `npm install` time (unlike `marked.js`/`purify.min.js`, which
predate this project's own npm usage and were vendored by hand from unpkg
before any local install existed to copy from). The `unpkg` URLs in the table
above are cited for provenance/reproducibility, not as the actual source of
the bytes committed here.

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

**Re-vendoring the fonts** is simpler, since the dashboard's own npm install
already did the registry-integrity check: bump the version in
`scripts/cairn/dashboard/package.json`, `npm install` there, then re-copy the
same six files from that package's freshly-installed `files/` directory --
```
cp scripts/cairn/dashboard/node_modules/@fontsource-variable/merriweather/files/merriweather-latin{,-ext}-wght-normal.woff2 scripts/cairn/board/vendor/fonts/
# repeat for space-grotesk, geist-mono
```
-- then update this table's `Version` column and the checksums below. Don't
add opsz/wdth/italic entries or any subset beyond latin/latin-ext without a
deliberate re-ruling of the budget this issue set (~250KB, six files).

## Checksums of the committed files (post sourceMappingURL-strip)

These are `shasum -a 256` of the files as they sit in this directory today
— re-run and update after any re-vendor, so a future audit can confirm
what's on disk hasn't drifted from what NOTICE.md documents:

```
f649aa15858f991f0407930b427905ce06f47949a768e1d491e986fc41407a80  marked.js
1a83c283c3229acad7ad9f8f874572bcb031df0f79e114318a2957dc2ffcc117  purify.min.js
1a189eb997c3e2ece68373e387afaec9e8617424186c4b1ab3cff7c54ba6223b  fonts/geist-mono-latin-ext-wght-normal.woff2
684ad5b531f81d43c1e8c7038262d5db7cdc1f68006e04d6c7769efa8d33c8cc  fonts/geist-mono-latin-wght-normal.woff2
8ca0880997847953a13964d6769b6712c57aa2dc2f881f4e6e805719791daed8  fonts/merriweather-latin-ext-wght-normal.woff2
4fbe8dd9c23b1fd62a988bb8a69b8e692d810f773d9ef6ebca2ba2760c7b11ee  fonts/merriweather-latin-wght-normal.woff2
952dddb45d2f96f71cbf3b7f510b24379afc3c89ea02fcf89d377b45d62c0166  fonts/space-grotesk-latin-ext-wght-normal.woff2
0640890476fc1198ab4de571fb658de443c4d85b66466ec09534a8737ab1ce9d  fonts/space-grotesk-latin-wght-normal.woff2
```
