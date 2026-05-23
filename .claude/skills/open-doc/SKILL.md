---
name: open-doc
description: Opens an HTML or Markdown doc in the system default viewer. Use whenever the user asks to "show the PRD", "open the architecture doc", "preview SECURITY", or any variant of viewing a doc rendered. Takes a path as argument; defaults to `docs/PRD/index.html` if no argument.
---

# open-doc

Opens a generated doc for human review.

## Usage

```
/open-doc                       # opens docs/PRD/index.html by default
/open-doc docs/ARCH/index.html        # opens the specified doc
/open-doc docs/SECURITY/index.html
/open-doc CLAUDE.md             # opens .md in One Markdown if available
```

## Implementation

### Step 1 — resolve path

If `$ARGUMENTS` is empty, default to `docs/PRD/index.html`.

Resolve to an absolute path. Verify it exists. If not, list available docs:

```bash
find docs -maxdepth 2 -type f \( -name '*.html' -o -name '*.md' \) 2>/dev/null
```

…and ask the user which to open.

### Step 2 — route by extension

- **`.html`** → open in a browser **explicitly** (not via the default `.html` association — that can route through MacVim / VS Code / other text editors if the user has those set as the default for HTML, which is common):
  ```bash
  open -a "Google Chrome" "<absolute-path>" 2>/dev/null \
    || open -a "Safari" "<absolute-path>"
  ```
  Chrome is tried first (common preference); Safari is the universal macOS fallback. Both calls use `open -a` to bypass LaunchServices' default-app preference for `.html`.

  (On Linux: `xdg-open <path>` typically launches the system's preferred browser; on Windows: `start <path>` does. Default template assumes macOS — adjust per project. See README → Customizing doc preview for swapping in a different browser.)

- **`.md`** → if the One Markdown app is installed (the `open-one-markdown` skill detects it), use that. Otherwise fall back to the user's editor (`$EDITOR file` or `open file`).

### Step 3 — confirm

After launching, post a single-line confirmation: `Opened: <relative-path>`.

## Notes

- Don't try to render Markdown to HTML on the fly — the user's chosen format (HTML for docs/, Markdown for ledgers) is intentional.
- HTML docs are self-contained (CSS + Mermaid CDN) so they work offline by double-click as well. This skill is convenience, not a dependency.
