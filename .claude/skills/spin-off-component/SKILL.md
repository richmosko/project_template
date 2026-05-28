---
name: spin-off-component
description: Extracts a substantial, reusable component out of this monorepo into its own repo — as a fresh `project_template` instance — preserving git history, cutting an initial `v0.1.0` release, and recording the parent↔child linkage. Use when a component graduates to its own repo (reused across ≥2 projects, needs its own release cadence, or is becoming a standalone product — see WORKFLOW.md → Shared / reusable components). Mechanizes the error-prone git extraction + repo creation; hands off the child bootstrap and the parent-side dependency refactor to existing flows. Argument: the path to the component to extract (e.g. `src/auth`); if omitted, the skill asks.
---

# spin-off-component

Graduates a component from "directory in this repo" to "its own repo + Linear Initiative + release cadence." The hard part is extracting the code **with its history** and wiring the dependency back without breaking either repo — that's what this skill mechanizes. It deliberately **hands off** the judgment-heavy parts (the child's PRD/ARCH bootstrap, the parent-side refactor) to the normal template flows.

## When NOT to run

If the only driver is size or context management, **don't split** — use monorepo workspaces or worktrees instead. See the graduation rubric in `WORKFLOW.md` → Shared / reusable components. Splitting a component that isn't actually reused buys overhead and no isolation.

## Inputs

- `$ARGUMENTS` — path to the component directory to extract (e.g. `src/auth`, `packages/parser`). If omitted, ask which directory.

## Pre-flight

Run in parallel; **bail** on any failure with a clear message:

- `git rev-parse --show-toplevel` — confirm we're in a repo.
- `git status --porcelain` — working tree must be clean. Never extract on top of uncommitted work.
- `git rev-parse --abbrev-ref HEAD` — should be `main` (or confirm with the user if not).
- `gh auth status` — needed to create the new repo.
- Confirm the component path exists and is self-contained enough to extract (flag obvious cross-imports back into the parent that will break once separated — those become the parent's public-API surface the child must not depend on).

## Decisions to confirm with the user

1. **New repo name** — default a kebab-case name from the component dir (`src/auth` → `auth`); confirm. This is also the GitHub repo name and the basis for the child's Linear Initiative.
2. **History strategy:**
   - **`git subtree split` (default)** — built-in, no extra deps. Captures history **only for the time the files lived at the current path.** Good enough for most components.
   - **`git filter-repo`** — use when the component's files **moved** over time (renames/relocations) and you want their full history. Requires `git-filter-repo` (`brew install git-filter-repo` / `pip install git-filter-repo`).
3. **Target path in the new repo** — default `src/<name>`. For a library that *is* the whole repo, root or an ecosystem-conventional path (e.g. a Go module at root) may be better. Confirm.
4. **Ecosystem** — how the parent will eventually depend on it (Go module / npm / Python / Cargo / container), so the linkage notes and the hand-off use the right pin syntax (see `WORKFLOW.md` table).

## Steps

### 1. Extract the component's history

**Default (`subtree split`)** — run in the parent repo:

```bash
git subtree split --prefix=<component-path> -b spinoff/<name>-export
```

This creates a local branch `spinoff/<name>-export` whose history is just the component, rewritten to the repo root.

**Alternative (`filter-repo`, for moved files)** — operate on a throwaway clone so the parent is never rewritten:

```bash
git clone . /tmp/<name>-extract
cd /tmp/<name>-extract
git filter-repo --path <component-path> [--path <old-path>] --path-rename <component-path>/:
# result: a repo whose entire history is the component at root
```

### 2. Create the new repo from the template and import the history

```bash
gh repo create <name> --template richmosko/project_template --private --clone
cd <name>
```

Bring the extracted history in under the chosen path, preserving it:

```bash
# from subtree split (parent has the spinoff/<name>-export branch):
git subtree add --prefix=<target-path> <absolute-path-to-parent-repo> spinoff/<name>-export

# or from a filter-repo extract:
git remote add export /tmp/<name>-extract && git fetch export
git read-tree --prefix=<target-path>/ -u export/main   # or merge --allow-unrelated-histories then move
git remote remove export
```

Commit if the import left staged changes, then `git push origin main`.

### 3. Cut the initial release

The code already works (it ran in the parent), so tag it now — the parent needs something to pin. Docs are backfilled during bootstrap (next step).

```bash
git tag -a v0.1.0 -m "Release v0.1.0 — initial extraction of <name> from <parent-repo>"
git push origin v0.1.0
gh release create v0.1.0 --generate-notes --draft --title "v0.1.0 — initial extraction"
```

Leave the release as a **draft** for the user to curate + publish (per `WORKFLOW.md` → Release process).

### 4. Record the linkage (both repos)

- **In the child repo:** append a `DECISIONS.md` entry — "Spun off from `<parent-repo>` on `<date>`; this repo owns `<component>` going forward." Note its first consumer.
- **In the parent repo:** append a `DECISIONS.md` entry — "Extracted `<component-path>` into `<name>` (own repo + Initiative); will consume `<name>@v0.1.0` as a dependency." If the parent has an ARCH doc, add an *Integration Points* note. If ARCH doesn't exist yet, flag it for when it's written.

### 5. Hand off the two follow-ups

Print these clearly — the skill does **not** do them:

1. **Bootstrap the child as a full template instance.** `cd` into the new repo and run the [first-run checklist](../../../CLAUDE.md) — at minimum `/setup-linear-team` (creates the child's Initiative in your shared team), then `/generate-prd` + `/generate-archdoc` **scoped to the component** (what it does, its public API surface, who consumes it). Replace the template placeholders in its `CLAUDE.md`.
2. **Swap the parent over to the dependency.** Back in the parent, run [`/start-feature`](../start-feature/SKILL.md) for "consume `<name>@v0.1.0` instead of in-tree `<component-path>`": delete the in-tree directory, add the pinned dependency (ecosystem syntax per `WORKFLOW.md` table), update imports, and let the acceptance tests prove the swap is behavior-preserving. This is a normal tested I→V loop, **not** part of this skill.

## Caveats & failure modes

- **`subtree split` history is path-scoped.** It only captures commits from while the files lived at `<component-path>`. If they were relocated earlier, that history is lost — use `filter-repo` instead.
- **The parent refactor is a separate, tested change.** Don't let the loop delete the in-tree code until the dependency swap is green. Until then the parent still has its working copy; nothing is lost if the swap is deferred.
- **Cross-imports become a public API.** Anything the component imported *from* the parent must be inverted (the parent now depends on the child, not vice versa) — or the extraction will produce a child that can't build alone. Surface these in pre-flight.
- **`gh repo create --template` needs the template to be a GitHub template repo** (or accessible). If it fails, fall back to `gh repo create <name> --private` + manually copying the template skeleton, then importing the history.
- **Don't rewrite the parent's history.** Extraction reads from the parent (subtree split creates a branch; filter-repo runs on a throwaway clone). The parent's `main` is never rewritten — the only parent-side change is the later dependency-swap feature.
- **Monorepo with many small components?** Spinning each into its own repo is usually the wrong call (see the rubric). Prefer workspaces.
