---
name: start-doc-update
description: Kicks off a doc-only update on a `phase/<phase>-<slug>` branch — for changes to PRD, ARCH, SECURITY (in docs/), MILESTONES.md, DECISIONS.md, WORKFLOW.md, etc. that aren't tied to a Linear feature. Mirrors /start-feature but lighter: no Linear issue, no implementation team, no anchor task. Use during Research/Plan phases when an agent (PM, architect, seceng) needs to revise docs without a feature ticket, or for cross-cutting workflow/meta updates anytime.
---

# start-doc-update

Bootstraps a phase-scoped doc-update branch. Use when you need to revise PRD/ARCH/SECURITY/MILESTONES/DECISIONS/WORKFLOW/CLAUDE and the change isn't tied to a Linear feature.

## When to use vs `/start-feature`

| Situation | Use |
|---|---|
| Implementing a user story tied to a Linear issue | `/start-feature` |
| Updating PRD/ARCH/SECURITY during Research/Plan | **`/start-doc-update`** |
| Adding a Decision Log entry that requires PR review | **`/start-doc-update`** |
| Fixing a typo in WORKFLOW.md or CLAUDE.md | **`/start-doc-update`** |
| Bumping a dependency in package.json | `/start-feature` (it has acceptance tests) |

The simple rule: **if it has acceptance criteria and lives in Linear, use `/start-feature`. If it's purely docs/process and doesn't, use `/start-doc-update`.**

## Inputs

- `$ARGUMENTS` — short kebab-slug describing the change (e.g. `prd-add-non-goals`, `arch-clarify-data-flow`, `workflow-fix-mermaid`). Required. The skill will offer to refine if the slug is overly generic.

## Steps

### 1. Pre-flight

Run in parallel:
- `git rev-parse --show-toplevel` — confirm we're in a repo. Bail if not.
- `git status --porcelain` — if uncommitted changes exist on the current branch, **stop** and ask the user to commit or stash first. Never auto-stash.
- `git rev-parse --abbrev-ref HEAD` — note current branch. If already on a `phase/*` or `feature/*` branch, ask user whether to (a) finish that branch first via `/finish-doc-update` or `/finish-feature`, or (b) stash + checkout main + start fresh.

### 2. Determine the phase prefix

Match the doc being edited to the phase:

| Doc | Phase prefix |
|---|---|
| `docs/PRD/index.html` | `phase/research-<slug>` |
| `docs/ARCH/index.html`, `docs/SECURITY/index.html` | `phase/plan-<slug>` |
| `docs/DESIGN/*` (index.html, tokens.css, screen.css, spec, wireframes/flows/styled-screens) | `phase/research-<slug>` — UX starts late-Research. **Cross-phase**: if the design-system edit is happening during Plan/Implement, use `phase/plan-<slug>` or fold it into the relevant feature instead. |
| `MILESTONES.md`, `DECISIONS.md`, `BACKLOG.md` | `phase/state-<slug>` |
| `WORKFLOW.md`, `CLAUDE.md`, `README.md` | `phase/meta-<slug>` |
| Other (e.g. `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`) | `phase/meta-<slug>` |
| Ambiguous / multi-doc | ask the user which phase the change belongs to |

### 3. Create the branch

```bash
git checkout main
git pull --ff-only
git checkout -b phase/<phase>-<slug>
```

Branch length cap: max 60 chars total. Truncate the slug if needed.

### 4. Confirm and hand off

Tell the user:

```
Branch created: phase/<phase>-<slug>

Make your doc edits. When done:
  /finish-doc-update  →  commit + push + open PR
  /merge-pr           →  team-lead merges the PR (or merge via GitHub UI)
```

If the user is working with an active agent team (e.g. PM agent during Research), `SendMessage` the relevant agent to let them know the branch is ready for their doc edits.

## Failure modes

- **Branch already exists**: ask the user if they want to switch to it (resume an in-progress doc update) or pick a different slug.
- **Uncommitted changes on current branch**: stop; ask user to commit or stash.
- **Not in a git repo**: stop with a clear error.
- **Slug is overly generic** (e.g. `update`, `fix`, `change`): offer the user a more specific alternative before creating the branch.
