---
name: finish-feature
description: Closes a feature — commits, pushes, opens a PR linked to the active Linear issue, updates Linear status, and prepares the Validate handoff. Use when the implementation is complete, tests are green, and the feature is ready to merge. No arguments needed; reads feature state from MILESTONES.md and Linear.
---

# finish-feature

Wraps one Implement→Validate loop (one feature) and queues it for merge.

## Pre-flight checks

Run these in parallel; abort with a clear message if any fails:

```bash
# 1. We're on a feature branch
git rev-parse --abbrev-ref HEAD | grep -q '^feature/' || echo "ERROR: not on a feature branch"

# 2. Tests are green (heuristic: project should have a `test` script)
npm test 2>/dev/null || yarn test 2>/dev/null || pytest 2>/dev/null || echo "WARNING: no test runner detected"

# 3. No uncommitted changes
git status --porcelain
```

If tests are red, **do not proceed**. Surface the failure and let the user (or QA agent) fix it.

## Steps

### 1. Stage and commit

- Run `git status` and `git diff` to see what's changing.
- Group changes into logical commits if they aren't already. One commit per logical change.
- Commit message format: `<type>(<linear-id>): <subject>` — e.g. `feat(ABC-123): add login form`.
- Use a HEREDOC for the body if non-trivial.

Add the trailer per global git instructions:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### 2. Push and open PR

```bash
git push -u origin HEAD
```

Then `gh pr create` with:
- Title: matches the Linear issue title
- Body: includes
  - `Closes <linear-issue-url>`
  - `## Summary` (2–4 bullets)
  - `## Test plan` (checklist of what QA validated)
  - The standard footer

Use a HEREDOC for the body.

### 3. Update Linear

- Set issue status to "In Review".
- Post a comment linking the PR URL.

### 4. Update MILESTONES.md

Move the active feature entry from `## Active Feature` to `### In Flight` (under Features), with the PR URL filled in.

### 5. Run validation handshake

`SendMessage` to qa-engineer: "Feature <id> opened as PR <url>. Drive Validate."

The Validate phase begins. QA + DevOps + Architect will review, deploy to staging, and either approve merge (then `/merge-pr`) or send back a fix request.

### 6. Promote durable state before teardown

The shared task list is **session-scoped** — it disappears when the Implement team is cleaned up. Before any teardown:

- Skim the anchor task and its subtasks. Anything that captures a **decision** or **lesson** gets promoted to durable state:
  - Decisions → `MILESTONES.md` → Decision Log
  - Implementation notes future-you would want → a Linear issue comment on the feature
- Ephemeral status pings, WIP markers, and routine hand-offs **do not** get promoted — that's the whole point of transient state.

## After-merge follow-up

This skill does **not** auto-merge. Merge is a separate step (`/merge-pr`) gated on QA approval and a human review.
