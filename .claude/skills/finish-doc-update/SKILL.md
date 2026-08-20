---
name: finish-doc-update
description: Closes a doc-only update — commits the doc edits, regenerates the affected docs' PDF artifacts, pushes the `phase/*` branch, and opens a PR. Mirrors /finish-feature but lighter: no tracker issue update, no QA handshake. After this, run /merge-pr (or merge via GitHub UI) to land the changes on main.
---

# finish-doc-update

Wraps a doc-update branch into a PR. Does not auto-merge — that's `/merge-pr`'s job.

## Pre-flight

Run in parallel:
- `git rev-parse --abbrev-ref HEAD` — confirm we're on a `phase/*` branch. **Bail** if on `main` or a `feature/*` branch.
- `git diff --quiet HEAD` + `git status --porcelain` — confirm there are uncommitted changes to wrap. If clean and nothing to commit since branch creation, **bail** with a clear message ("nothing to commit on this branch — abandon it via `git checkout main && git branch -D <branch>` or make edits first").

## Steps

### 1. Stage and commit

- Run `git status` and `git diff` to see what's changing.
- Group changes into logical commits if there are multiple. One commit per logical change (e.g. "PRD: add Non-Goals" and "PRD: refine success metrics" are separate commits, not one).
- **Commit message format:** `docs(<phase>): <subject>` — e.g.:
  - `docs(research): add Non-Goals section to PRD`
  - `docs(plan): clarify data-flow diagram in ARCH`
  - `docs(meta): fix Mermaid arrow in WORKFLOW`
- HEREDOC body for non-trivial changes; one-liner subject is fine for simple edits.

Add the standard Claude trailer per global git instructions:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### 2. Regenerate PDF artifacts

Doc PDFs live at `docs/<DOC>/<DOC>.pdf` and are committed to the repo so they render **inline on GitHub** (which won't render the raw `index.html`) and travel with the PR. Regenerate the ones this branch affects — no more, no less.

1. **Determine affected docs** from the branch diff:
   ```bash
   git diff --name-only main...HEAD
   ```
   - Any `docs/_assets/**` or `docs/DESIGN/tokens.css` changed → **all four** docs (`PRD ARCH SECURITY DESIGN`): shared styling/tokens/fonts affect every doc's rendering.
   - Otherwise → only the docs whose own `docs/<DOC>/index.html` changed.
   - If neither a doc `index.html` nor a shared asset changed (e.g. only `process/*` or `CLAUDE.md`), **skip this step** — there's nothing to render. Note that in the PR body.

2. **Generate** (headless Chrome + a temp docs server — same engine as `/export-doc`):
   ```bash
   ./scripts/export-pdf.sh <DOC ...>
   ```
   - **If it fails**, don't silently drop it. The usual cause is that Chrome is already running and the headless instance conflicts (the script says so). Surface the error and either (a) ask the user to quit Chrome and re-run `./scripts/export-pdf.sh <DOC ...>`, or (b) proceed with the PR and clearly note the PDFs weren't regenerated. **Never fabricate a successful render.**

3. **Commit the PDFs** as their own commit (keeps the binary churn separate from the source diff):
   ```bash
   git add docs/*/*.pdf
   git commit -m "docs(<phase>): regenerate PDF artifacts"
   ```
   Skip the commit if `git status` shows no PDF changes.

### 3. Push and open PR

```bash
git push -u origin HEAD
```

Then `gh pr create` with:
- **Title:** matches the most recent *source* commit's subject (or summarize if multiple commits)
- **Body:** include
  - A `## Summary` section (2–3 bullets — what changed and why)
  - A line: `**Type:** doc-only update (no tracker issue, no QA validation required)`
  - A line noting the PDF artifacts: which docs were regenerated (or that PDF regen was skipped/failed, per Step 2)
  - The standard Claude footer

Use a HEREDOC for the body.

### 4. Hand off

`SendMessage` to the team-lead (you): "Doc update opened as PR <url>. Ready for review and `/merge-pr` (or human merge via GitHub UI)."

The team-lead reviews the diff, confirms it reads correctly, and either:
- Runs `/merge-pr` to merge on the user's behalf
- Tells the user to review and merge via the GitHub UI

**There's no QA / Validate phase for doc-only PRs.** The lead's read of the diff is the only gate beyond GitHub's own branch-protection rules.

## After-merge follow-up

If the merged change was tied to a phase transition (e.g. "PRD v1 approved → move to Plan"), the lead should still:
- Update `process/MILESTONES.md` → Current Phase
- Add an entry to `process/DECISIONS.md` for the phase-gate approval

These updates may need their own subsequent `/start-doc-update` cycle since the merge of *this* PR doesn't automatically trigger them.

## Failure modes

- **Not on a `phase/*` branch**: bail; suggest `/start-doc-update` first to create the branch.
- **No uncommitted changes**: bail; nothing to commit. Either make edits or abandon the branch.
- **`gh pr create` fails**: surface the error verbatim (auth, branch-protection mismatch, etc.). Don't pretend success.
- **Branch protection rejects the push** (rare on the initial push, common if main was force-changed): surface the error and advise the user to rebase or pull.
