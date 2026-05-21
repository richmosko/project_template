---
name: open-doc
description: Opens an HTML or Markdown doc in the system default viewer. Use whenever the user asks to "show the PRD", "open the architecture doc", "preview SECURITY.html", or any variant of viewing a doc rendered. Takes a path as argument; defaults to `docs/PRD.html` if no argument.
---

# open-doc

Opens a generated doc for human review.

## Usage

```
/open-doc                       # opens docs/PRD.html by default
/open-doc docs/ARCH.html        # opens the specified doc
/open-doc docs/SECURITY.html
/open-doc CLAUDE.md             # opens .md in One Markdown if available
```

## Implementation

### Step 1 — resolve path

If `$ARGUMENTS` is empty, default to `docs/PRD.html`.

Resolve to an absolute path. Verify it exists. If not, list available docs:

```bash
find docs -maxdepth 2 -type f \( -name '*.html' -o -name '*.md' \) 2>/dev/null
```

…and ask the user which to open.

### Step 2 — route by extension

- **`.html`** → open in default browser:
  ```bash
  open "<absolute-path>"   # macOS
  ```
  (On Linux this would be `xdg-open`; on Windows `start`. Default template assumes macOS — adjust per project.)

- **`.md`** → if the One Markdown app is installed (the `open-one-markdown` skill detects it), use that. Otherwise fall back to the user's editor (`$EDITOR file` or `open file`).

### Step 3 — confirm

After launching, post a single-line confirmation: `Opened: <relative-path>`.

## Notes

- Don't try to render Markdown to HTML on the fly — the user's chosen format (HTML for docs/, Markdown for ledgers) is intentional.
- HTML docs are self-contained (CSS + Mermaid CDN) so they work offline by double-click as well. This skill is convenience, not a dependency.
