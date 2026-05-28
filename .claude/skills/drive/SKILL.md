---
name: drive
description: Prepares a goal-driven development loop. Reads the project's delivery-autonomy methodology, resolves the next unit of work (a feature for stop-at-merge, a milestone for self-merge), runs pre-flight checks, constructs the matching `/goal` condition, and surfaces the exact `/goal …` line for you to paste. Use when you want to hand the next chunk of work to a `/goal` loop instead of driving it turn-by-turn. Optional argument: a Linear issue ID (stop-at-merge) or milestone ID (self-merge); if omitted, the skill infers the next unit from MILESTONES.md + Linear.
---

# drive

Aims a [`/goal`](https://code.claude.com/docs/en/goal.md) loop at the next unit of work. `/goal` is a **native Claude Code command** (v2.1.139+) that keeps the session working across turns until a completion condition is met. `/drive` does the preparation: it reads project state, picks the right scope, builds the condition string, and surfaces it.

## The one hard constraint

**A skill cannot set a `/goal` itself.** There is no model-callable goal tool and no `SlashCommand` tool — `/goal` is user-typed only. So `/drive` ends by printing the exact `/goal …` line for **you to paste**. This is by design, not a workaround: pasting the line is the human checkpoint at goal-set time, consistent with the template's "gates are human decisions" principle (`WORKFLOW.md`). You see and approve the condition before the loop runs.

Do **not** try to fake self-issuing a goal: don't write a Stop hook into settings (no mid-session hot-reload), and don't spawn a nested `claude -p "/goal …"` subprocess (sessions fight over state). Both are unsupported. Construct-and-surface is the supported pattern.

## When to run

- At the start of an Implement→Validate loop, when you'd rather let `/goal` drive a whole feature (or milestone) to completion than prompt each turn.
- After a feature merges, to aim the loop at the next one.

## Steps

### 1. Resolve the delivery-autonomy methodology

Read the **Delivery autonomy** config line in `WORKFLOW.md` (under *Project configuration*). It is one of:

- **`stop-at-merge`** (default, recommended) — the loop builds **one feature** up to an open, mergeable PR and **stops before merging**. You review and run `/merge-pr`.
- **`self-merge-within-milestone`** — the loop builds **every feature in a milestone**, merging each itself, and stops at the milestone boundary.

If the config line is still the unfilled placeholder, **default to `stop-at-merge`** and tell the user: *"No delivery-autonomy methodology set — defaulting to stop-at-merge. Run `/setup-linear-team` or edit the Delivery autonomy line in WORKFLOW.md to change it."*

A skill argument can override for this one invocation: if the user passed `self-merge` / `stop-at-merge` explicitly, honor it but don't rewrite the config.

### 2. Resolve the unit of work

**For `stop-at-merge` → one feature:**
- If an issue ID was passed as the argument, use it.
- Otherwise infer the next feature: check `MILESTONES.md` → Features → *In Flight* first (resume it); if none, take the top of *Backlog* / the next Linear issue in the current sprint. If the requested feature is only queued in `BACKLOG.md`, note that `/start-feature` will promote it.
- You need the feature's **Linear issue ID, title, and acceptance criteria** to build a good condition. Pull them from Linear if not already in context.

**For `self-merge-within-milestone` → one milestone:**
- If a milestone ID was passed, use it.
- Otherwise take the active milestone from `MILESTONES.md` → Roadmap (status *In Progress*), or the next *Planned* one.

### 3. Pre-flight

- **Git state:** working tree should be clean and on `main` (or already on the in-flight feature branch when resuming). If the tree is dirty on an unrelated branch, stop and surface that — don't start a loop on top of uncommitted work.
- **Linear wired:** `.claude/linear-team.json` must exist. If missing, tell the user to run `/setup-linear-team` first.
- **Auto mode (self-merge only):** the loop runs many tool calls unattended. Remind the user: *"self-merge needs auto mode on, or every tool call will prompt — enable it before pasting the goal."* `/goal` removes per-turn prompts; auto mode removes per-tool prompts. You need both for an unattended run.

### 4. Construct the `/goal` condition

Fill the matching template. Keep it under 4,000 characters. The whole feature/milestone lifecycle runs **inside** the goal — `/drive` does not call `/start-feature` itself.

**`stop-at-merge` template:**

```
/goal Feature <LINEAR-ID> (<title>) is ready for human merge. Run /start-feature <LINEAR-ID> if not already started, then with the Implement team: write failing acceptance tests first (TDD) covering <one-line acceptance criteria>, implement until the full test suite is green, get peer-review approval via SendMessage, and run /finish-feature to open a PR linked to the issue. Done when: tests are green in the transcript, peer review is approved, and the PR is open and mergeable. Do NOT merge — stop at the open PR. Or stop after 30 turns and report what's blocking.
```

**`self-merge-within-milestone` template:**

```
/goal Every issue in milestone <M — name> is Done and merged to main. Work issues in Linear/BACKLOG order; for each: /start-feature, write failing acceptance tests first (TDD), implement until green, get peer-review approval, /finish-feature, then /merge-pr. Run /compact between features to keep context lean. Done when the milestone's issue queue is empty. Stop early if any single feature fails peer review twice, or after 80 turns — and report what's blocking.
```

Adjust the turn bounds to the scope if you have a better estimate; always include a bound so the loop can't run unbounded.

### 5. Surface it

Print the constructed `/goal …` line in a fenced block, then a one-line next step:

- **stop-at-merge:** *"Paste this to start the loop. When the goal clears, review the PR and run `/merge-pr`."*
- **self-merge-within-milestone:** *"Enable auto mode, then paste this. It'll build and merge the whole milestone, stopping at the boundary for your phase-gate decision."*

Then **stop.** The user pastes the line; the loop takes over from there.

## Notes

- **One goal per session.** Setting a new goal replaces any active one. `/goal clear` cancels; `/clear` (new conversation) also clears it. A goal active at session end is restored on `--resume`/`--continue` (counters reset).
- **The evaluator can't run tools.** A fast model (Haiku by default) judges the condition only against what the session surfaced in the transcript. Write conditions whose proof lands in the transcript — "tests green" works because the loop runs the tests and the output is visible. `/finish-feature` and `/merge-pr` already echo PR/issue state, so those conditions are checkable.
- **Methodology is per-project, not per-feature.** It's set once at `/setup-linear-team` and stored in `WORKFLOW.md`. Change it by editing that line and logging a `DECISIONS.md` entry. The skill argument is the per-invocation escape hatch.
- **Record the live condition** in `MILESTONES.md` → Active Feature → *Goal* once `/start-feature` has claimed the feature, so a fresh session can see what the loop is chasing.
