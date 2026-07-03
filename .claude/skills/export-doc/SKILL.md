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

## Why headless Chrome (background)

The docs draw diagrams with **Mermaid**, which renders via JavaScript at load time. Only a browser engine runs that JS, so weasyprint / pandoc / wkhtmltopdf would emit PDFs with the diagrams missing. The script uses headless Chrome and briefly starts `scripts/serve-docs.py` so Mermaid's CDN module + relative assets resolve; the resulting PDF is fully standalone.

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

- **Committing PDFs is optional and a judgment call.** They're binary and re-generate on demand, so many projects gitignore them and attach to Linear/PRs instead. Commit them only when in-repo GitHub-inline viewing is the goal. Ask the user before `git add`-ing them.
- If Chrome isn't found, tell the user to install Google Chrome or pass `CHROME=/path/to/chrome`.
- Override the temp server port with `DOCS_PORT=8080 ./scripts/export-pdf.sh`.
