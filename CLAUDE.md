# Project Context

> This file is auto-loaded at the start of every Claude Code session. Keep it concise — link out, don't inline.

## What this project is

<!-- REPLACE on first run: one or two sentences on what the product is and who it's for. -->
_TBD — fill in during the Research phase. See [`docs/PRD.html`](docs/PRD.html)._

This repo was instantiated from the [project_template](https://github.com/richmosko/project_template) starter. The template's workflow, agent roster, and artifact conventions are defined in [`WORKFLOW.md`](WORKFLOW.md). The current state of the work — phase, sprint, feature, decisions — lives in [`MILESTONES.md`](MILESTONES.md). **Read MILESTONES.md before doing anything else.**

## Current state at a glance

- **Project (Linear Initiative):** see `## Project / Initiative` in [`MILESTONES.md`](MILESTONES.md)
- **Phase:** see `## Current Phase` in [`MILESTONES.md`](MILESTONES.md)
- **Active feature:** see `## Active Feature` in [`MILESTONES.md`](MILESTONES.md) (a feature = one Linear issue = one PR = one I→V loop)
- **Active sprint (Linear cycle):** see `## Sprints (Linear cycles)` in [`MILESTONES.md`](MILESTONES.md)
- **Linear binding:** see `.claude/linear-team.json` for the shared team ID + this project's Initiative ID (run `/setup-linear-team` if missing)

## Artifacts

| Doc | Location | Owner agent |
|---|---|---|
| Product Requirements | [`docs/PRD.html`](docs/PRD.html) | product-manager |
| Architecture & Infrastructure | [`docs/ARCH.html`](docs/ARCH.html) | architect |
| Security & Compliance | [`docs/SECURITY.html`](docs/SECURITY.html) | seceng |
| Workflow definition | [`WORKFLOW.md`](WORKFLOW.md) | team-lead (the main session) |
| Live state ledger | [`MILESTONES.md`](MILESTONES.md) | team-lead |
| Decision log | [`DECISIONS.md`](DECISIONS.md) | team-lead (append-only) |
| Backlog overflow queue | [`BACKLOG.md`](BACKLOG.md) | team-lead + `/sync-backlog` |

Open any HTML doc with `/open-doc docs/PRD.html` (or just double-click it).

## Team agents

Nine specialist Agents live in [`.claude/agents/`](.claude/agents/). The main session acts as **team-lead**; teammates are spawned per phase (not all at once) to manage token cost and the "one active team" constraint. See [`WORKFLOW.md`](WORKFLOW.md) for the phase→roster mapping.

To start a phase team, say: _"Create a team for the Plan phase"_ — the lead will spawn `architect`, `seceng`, `devops-engineer`, and `qa-engineer` as teammates (specific roster depends on project configuration; see [`WORKFLOW.md`](WORKFLOW.md) for the canonical phase→roster mapping).

## Session management

The conversation context isn't infinite. Use these heuristics so we don't lose continuity at the wrong moment:

- **End of an I→V loop** (feature shipped): run `/compact`, push the branch, update `MILESTONES.md`.
- **Phase transition** (R→P, P→I, I→V, V→R): start a fresh session. Phase artifacts (PRD/ARCH/SECURITY) are the hand-off — make sure they're up-to-date before closing.
- **Long async gap** (you stepped away for hours/days): start fresh; let CLAUDE.md + MILESTONES.md re-orient the new session. Whether to `/resume` depends on teammate mode:
  - **In-process mode** (`teammateMode: "in-process"`): teammates do **not** survive `/resume`. Start fresh; do not message ghost teammates by name. Re-spawn the phase team if needed.
  - **Split-pane mode** (`teammateMode: "tmux"` or iTerm2 split-pane): teammates often survive `/resume` because each runs in its own pane/process. Verify each teammate is alive (a quick `SendMessage` ping) before trusting their context. If a pane was closed, treat that teammate as lost and re-spawn.
- **Mid-feature, context > 70%**: `/compact` rather than starting fresh; in-flight work needs the working context.

When in doubt about where we left off, **read MILESTONES.md first** — it's the ledger.

## First run / bootstrap

When this template is freshly cloned for a new project, the team-lead should walk the user through this checklist on the first session:

1. **Confirm the repo is a git repo.** `git rev-parse --git-dir` should succeed. If not, run `git init`.
2. **Confirm `gh` is authenticated** to the GitHub account that will host this project. `gh auth status` — if not, prompt the user to run `gh auth login`.
3. **Set up Claude's SSH deploy key** — run `/setup-claude-deploy-key`. Generates a passphrase-less Ed25519 key scoped to this repo (`~/.ssh/id_ed25519_claude_<repo>`), walks you through adding it to GitHub as a deploy key with **write access**, and pins the repo's git to use it via `core.sshCommand`. Without this step, Claude's `git push` will fail whenever your main SSH key is passphrase-protected (Claude Code's bash has no TTY to unlock it).
4. **Replace the placeholders** in this file:
   - L7–8: the "TBD" project description block
   - L10: the GitHub URL (points at the template repo by default — change to this project's repo once created)
5. **Run `/setup-linear-team`** to wire Linear into this project — link to your shared Linear team, create this project's Initiative, and seed the nine `agent:<role>` labels. Caches IDs in `.claude/linear-team.json`.
6. **Verify teammate mode** in `.claude/settings.json` (default: `tmux` for split-pane). If you prefer in-process, change it before spawning the first team.
7. **Spawn the Research team:** say _"Create an agent team for the Research phase"_ — the lead will spawn `product-manager` (and bring `ux-designer` + `seceng` in later).
8. **Run `/generate-prd`** to start the discovery interview. The PM teammate drives.
9. **Log the bootstrap** as the first entry in [`DECISIONS.md`](DECISIONS.md) (the template already includes a stub — update the date and approver name).

After step 9, the project is in the Research phase and MILESTONES.md becomes the source of truth for "where we are".

## Working principles

- **TDD by default**: write the failing test, then the implementation, then confirm green. Validate is not optional.
- **Small commits, frequent PRs**: one PR per completed I→V loop (one feature). Use `/start-feature` and `/finish-feature` to automate the branch+Linear+PR plumbing.
- **Decisions go in the ledger**: any non-trivial call (stack choice, architectural pivot, scope cut) gets an entry in [`DECISIONS.md`](DECISIONS.md).
- **Skills over repetition**: if a process happens twice, extract it into `.claude/skills/`.
