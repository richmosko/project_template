# Project Context

> This file is auto-loaded at the start of every Claude Code session. Keep it concise — link out, don't inline.

## What this project is

<!-- REPLACE on first run: one or two sentences on what the product is and who it's for. -->
_TBD — fill in during the Research phase. See [`docs/PRD/index.html`](docs/PRD/index.html)._

This repo was instantiated from the [project_template](https://github.com/richmosko/project_template) starter. The template's workflow, agent roster, and artifact conventions are defined in [`process/WORKFLOW.md`](process/WORKFLOW.md). The current state of the work — phase, session cycle, feature, decisions — lives in [`process/STATE.md`](process/STATE.md). **Read process/STATE.md before doing anything else.**

## Current state at a glance

- **Majors & roadmap:** the tracker's files — `process/cairn/majors/` and `process/cairn/milestones/` — viewed on the board (`/cairn`) or via `scripts/cairn/cairn ls`
- **Phase:** see `## Current Phase` in [`process/STATE.md`](process/STATE.md)
- **Active feature:** see `## Active Feature` in [`process/STATE.md`](process/STATE.md) (a feature = one cairn issue = one PR = one I→V loop)
- **Active session cycle:** see `## Session Cycles` in [`process/STATE.md`](process/STATE.md) — a context-bounded work session (heuristic; no tracker artifact)
- **Tracker binding:** `process/cairn/config.yml` — ID prefix + board port (run `/setup-tracker` if missing); full spec in [`process/TRACKER.md`](process/TRACKER.md)

## Artifacts

| Doc | Location | Owner agent |
|---|---|---|
| Product Requirements | [`docs/PRD/index.html`](docs/PRD/index.html) | product-manager |
| Architecture & Infrastructure | [`docs/ARCH/index.html`](docs/ARCH/index.html) | architect |
| Security & Compliance | [`docs/SECURITY/index.html`](docs/SECURITY/index.html) | seceng |
| Design System & UX | [`docs/DESIGN/index.html`](docs/DESIGN/index.html) | ux-designer |
| Workflow definition | [`process/WORKFLOW.md`](process/WORKFLOW.md) | team-lead (the main session) |
| Tracker spec (cairn) | [`process/TRACKER.md`](process/TRACKER.md) | architect |
| Tracker data — majors, milestones, issues | [`process/cairn/`](process/cairn/) | all agents (issues); team-lead + architect (majors/milestones) |
| Live state ledger | [`process/STATE.md`](process/STATE.md) | team-lead |
| Decision log | [`process/DECISIONS.md`](process/DECISIONS.md) | team-lead (append-only) |

Open any HTML doc with `/open-doc docs/PRD/index.html` (or just double-click it).

## Team agents

**This template requires Claude Code's experimental team-agents feature.** The workflow assumes each specialist Agent runs as a persistent teammate with its own context, mailbox, and access to the shared task list — not as one-shot subagents. The template ships with `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1"` and `teammateMode: "tmux"` already set in [`.claude/settings.json`](.claude/settings.json); do not disable them. If team-agents is off, `SendMessage`, the shared task list, and the anchor-task coordination pattern in [`process/WORKFLOW.md`](process/WORKFLOW.md) all break.

Nine specialist Agents live in [`.claude/agents/`](.claude/agents/), plus one utility agent — `mcp-broker`. The main session acts as **team-lead**; its identity and operating directives live in [`.claude/roles/team-lead.md`](.claude/roles/team-lead.md), injected at session start by a SessionStart hook (the role is not spawnable — teammates take identity from their own `.claude/agents/*.md` file, none of which reference the role file). Teammates are spawned per phase (not all at once) to manage token cost and the "one active team" constraint. See [`process/WORKFLOW.md`](process/WORKFLOW.md) for the phase→roster mapping.

**`mcp-broker`** is a context firewall for chatty remote MCP servers (Google Drive, Gmail, Calendar, Spotify). Those servers return multi-KB JSON that permanently inflates whatever context it lands in — most painfully the team-lead's. Delegate the query to the broker and it absorbs the raw payload in its own isolated context, returning only the distilled fact + IDs. Spawn it into any phase doing heavy MCP querying; it's not phase-bound. See [`process/WORKFLOW.md`](process/WORKFLOW.md) → MCP Broker. (The tracker is not MCP — cairn is local files; read them directly.)

To start a phase team, say: _"Create a team for the Plan phase"_ — the lead will spawn `architect`, `seceng`, `devops-engineer`, and `qa-engineer` as teammates (specific roster depends on project configuration; see [`process/WORKFLOW.md`](process/WORKFLOW.md) for the canonical phase→roster mapping).

## Session management

The conversation context isn't infinite. Use these heuristics so we don't lose continuity at the wrong moment:

- **End of an I→V loop** (feature shipped): run `/compact`, push the branch, update `process/STATE.md`.
- **Session close**: run `/sweep-temp` — every `temp/` hand-off file gets placed into a tracked artifact, discarded, or explicitly held (`hold-until:` frontmatter). `temp/` is gitignored; unplaced findings do not survive cleanup.
- **Phase transition** (R→P, P→I, I→V, V→R): start a fresh session. Phase artifacts (PRD/ARCH/SECURITY) are the hand-off — make sure they're up-to-date before closing.
- **Long async gap** (you stepped away for hours/days): start fresh; let CLAUDE.md + process/STATE.md re-orient the new session. Whether to `/resume` depends on teammate mode:
  - **In-process mode** (`teammateMode: "in-process"`): teammates do **not** survive `/resume`. Start fresh; do not message ghost teammates by name. Re-spawn the phase team if needed.
  - **Split-pane mode** (`teammateMode: "tmux"` or iTerm2 split-pane): teammates often survive `/resume` because each runs in its own pane/process. Verify each teammate is alive (a quick `SendMessage` ping) before trusting their context. If a pane was closed, treat that teammate as lost and re-spawn.
- **Mid-feature, context > 70%**: `/compact` rather than starting fresh; in-flight work needs the working context.

When in doubt about where we left off, **read process/STATE.md first** — it's the ledger.

### Resume runbook (fresh session, "let's continue")

When a session starts cold and the user says any variant of "continue" / "pick up where we left off" / "what's next", the team-lead should run this sequence **before doing tactical work**:

1. **Read the full `process/STATE.md`** (not just the auto-injected head). Note Active Feature, Current Phase, and the most recent Session Cycle rows; the roadmap lives in the tracker (`scripts/cairn/cairn ls`, or `process/cairn/milestones/`).
2. **Inspect git state** in parallel: `git status`, `git rev-parse --abbrev-ref HEAD`, `git log --oneline -10`. The branch name tells you which loop you're in (`feature/*`, `phase/*`, or `main`).
3. **Match branch → context:**
   - On a `feature/*` branch → an Implement→Validate loop was in flight. Read the issue file (`scripts/cairn/cairn show <ID>`), list recently-modified files (`git diff --stat main...HEAD`), and re-derive what's left from the issue's acceptance criteria.
   - On a `phase/*` branch → a doc-update was in flight. Diff against main to see pending edits.
   - On `main` with a clean tree → between loops. Decide the next move from process/STATE.md + `scripts/cairn/cairn ls --status todo` (next feature for this session cycle, or pending phase transition).
4. **Check open PRs** with `gh pr list --state open` in case a previous session opened one that's waiting for `/merge-pr`.
5. **Read `process/WORKFLOW.md` only if needed** — phase gate criteria, roster, or process detail. Don't pre-load it for every resume.
6. **Surface the inferred pickup point** to the user in one or two sentences and **wait for confirmation** before doing heavy work. If state is ambiguous (no active feature, dirty tree on main, mismatched branch/STATE.md), say so and ask.

The auto-injected STATE head gives you the dashboard; this runbook is the rest of the orientation. Skipping it risks acting on stale or partial context.

**Mid-feature gotcha:** the previous session's tactical micro-state (which approach was ruled out, which test was being debugged) is not in any artifact. If you walked away mid-feature without `/compact`, expect to re-derive — or ask the user explicitly: "Mid-feature pickup — anything from last session I should know before I dive in?"

## First run / bootstrap

When this template is freshly cloned for a new project, the team-lead should walk the user through this checklist on the first session:

1. **Confirm the repo is a git repo.** `git rev-parse --git-dir` should succeed. If not, run `git init`.
2. **Confirm `gh` is authenticated** to the GitHub account that will host this project. `gh auth status` — if not, prompt the user to run `gh auth login`.
3. **Set up Claude's SSH deploy key** — run `/setup-claude-deploy-key`. Generates a passphrase-less Ed25519 key scoped to this repo (`~/.ssh/id_ed25519_claude_<repo>`), walks you through adding it to GitHub as a deploy key with **write access**, and pins the repo's git to use it via `core.sshCommand`. Without this step, Claude's `git push` will fail whenever your main SSH key is passphrase-protected (Claude Code's bash has no TTY to unlock it).
4. **Enable GitHub branch protection on `main`** — go to **Settings → Branches → Add rule**. Suggested config for the solo + team-agents workflow:
   - **Branch name pattern:** `main`
   - ✅ **Require a pull request before merging** — this is the key gate; blocks direct `git push origin main`
   - ☐ Require approvals — skip for solo dev; the `/merge-pr` workflow handles QA + lead approval. Re-enable if you have human collaborators.
   - ✅ **Do not allow bypassing the above settings** — even admins go through PRs
   - ✅ Require status checks (only if you have CI configured)
   Without this, the workflow's "no direct pushes" rule is advisory only — branch protection is the hard enforcement layer.
5. **Replace the placeholders** in this file:
   - L7–8: the "TBD" project description block
   - L10: the GitHub URL (points at the template repo by default — change to this project's repo once created)
6. **Run `/setup-tracker`** to bootstrap cairn (the file-based issue tracker) — confirms the issue-ID prefix, scaffolds `process/cairn/` with the founding major (V1) and the M0/M1 process milestones so the board is populated from Day 0, optionally seeds PRD stories as backlog issues, and sets the **delivery-autonomy methodology** for `/drive` (`stop-at-merge` recommended). View the board anytime with `/cairn`.
7. **Verify team-agents is enabled.** `.claude/settings.json` must have `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1"` (shipped with the template — do not turn off; the workflow depends on it). Then pick `teammateMode`: `"tmux"` (default) for split-pane teammates that survive `/resume`, or `"in-process"` if you don't have tmux/iTerm2 with `it2`. Change it before spawning the first team.
8. **Spawn the Research team:** say _"Create an agent team for the Research phase"_ — the lead will spawn `product-manager` (and bring `ux-designer` + `seceng` in later).
9. **Run `/generate-prd`** to start the discovery interview. The PM teammate drives.
10. **Log the bootstrap** as the first entry in [`process/DECISIONS.md`](process/DECISIONS.md) (the template already includes a stub — update the date and approver name). **Record the template version** on the `**Bootstrapped from:**` line — run `git -C <path-to-template-clone> describe --tags --abbrev=0`, or check the [project_template Releases page](https://github.com/richmosko/project_template/releases) for the latest published version.
11. **Delete `process/TEMPLATE_DECISIONS.md`** — that file documents decisions about the template itself; it's not relevant to your project. Your project's decision log is `process/DECISIONS.md` (already in place).

After step 11, the project is in the Research phase and process/STATE.md becomes the source of truth for "where we are".

## Working principles

- **TDD by default**: write the failing test, then the implementation, then confirm green. Validate is not optional.
- **Small commits, frequent PRs**: one PR per completed I→V loop (one feature). Use `/start-feature` + `/finish-feature` for features tied to a cairn issue; use `/start-doc-update` + `/finish-doc-update` for non-feature doc edits. Merge via `/merge-pr` (team-lead) or GitHub UI (human review). **No direct pushes to `main`.**
- **Goal-driven loops**: to run an I→V loop hands-off, use `/drive` — it aims a native `/goal` at the next feature (or milestone) per the project's delivery-autonomy setting, and surfaces the `/goal` line for you to paste. See [`process/WORKFLOW.md`](process/WORKFLOW.md) → Goal-driven loop.
- **Decisions go in the ledger**: any non-trivial call (stack choice, architectural pivot, scope cut) gets an entry in [`process/DECISIONS.md`](process/DECISIONS.md).
- **Skills over repetition**: if a process happens twice, extract it into `.claude/skills/`.
- **Reusable components**: when a substantial component is reused across projects, needs its own release clock, or already lives elsewhere, treat it as its own template instance — spin it off with `/spin-off-component`, or borrow it as a pinned dependency. Don't split for size alone. See [`process/WORKFLOW.md`](process/WORKFLOW.md) → Shared / reusable components.
