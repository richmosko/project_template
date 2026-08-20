---
name: export-doc
description: Renders an HTML doc (PRD / ARCH / SECURITY / DESIGN) to a standalone, portable PDF via scripts/export-pdf.sh — Mermaid diagrams included. Use when the user wants a shareable, server-free copy of a doc, a version GitHub can display inline (GitHub renders PDF but not the raw HTML), or a PDF to annotate. Optional argument: which doc(s) to export; defaults to all four.
---

# export-doc

Wrapper around `scripts/export-pdf.sh`. Produces a standalone PDF of a doc that:

- reads with **no local server** (double-click, email, drop in Drive),
- **renders inline on github.com** (GitHub shows PDFs but not the raw `index.html`),
- can be **annotated** in any PDF reader (Preview / Acrobat) for external-stakeholder review.

The in-repo review loop (the comment widget + `comments.md` + `/refine-doc`) stays the source of truth; PDF is an **export deliverable**, not an editable artifact.

## Usage

```
/export-doc              # export all four docs → docs/<DOC>/<DOC>.pdf
/export-doc PRD          # just the PRD
/export-doc PRD ARCH     # PRD + ARCH
```

## How it works (background)

`scripts/export-pdf.sh` briefly starts `scripts/serve-docs.py`, then delegates rendering to `scripts/print-pdf.mjs`, which drives Chrome over the DevTools Protocol. Two things make it reliable:

- **Requires Node ≥ 22** (built-in `WebSocket`, no npm deps) to speak CDP and wait for the page to be ready before capturing.
- **Diagrams** are re-rendered with **mermaid-cli** (`mmdc`, auto-fetched via `npx` on first run — its own bundled Chromium) and injected as PNGs. This is necessary because Chrome's `printToPDF` won't paint inline `<svg>` (diagrams would come out blank). The PNGs use the page's own computed theme, so they match on-screen. Prefers the conflict-free `chrome-headless-shell` binary when present.

The resulting PDF is fully standalone (text, tables, tokens, and themed diagrams).

## Steps

### 1. Parse the argument

`$ARGUMENTS` is zero or more doc names from `{PRD, ARCH, SECURITY, DESIGN}` (case-insensitive; normalize to upper). Empty → all four. Anything else → bail with the usage block above.

### 2. Run the exporter

```bash
./scripts/export-pdf.sh [DOC ...]
```

It auto-detects Chrome/Chromium/Edge/Brave, spins the server up and down itself, and writes `docs/<DOC>/<DOC>.pdf`. Needs network (Mermaid CDN) the first time diagrams render.

### 3. Report

List each generated PDF with its path and size. Offer to open one with `/open-doc docs/<DOC>/<DOC>.pdf` or to commit the PDFs (so they render on GitHub).

## Notes

- **Committing PDFs is optional and a judgment call.** They're binary and re-generate on demand, so many projects gitignore them and attach to PRs instead. Commit them only when in-repo GitHub-inline viewing is the goal. Ask the user before `git add`-ing them.
- If Chrome isn't found, tell the user to install Google Chrome or pass `CHROME=/path/to/chrome`.
- Override the temp server port with `DOCS_PORT=8080 ./scripts/export-pdf.sh`.
