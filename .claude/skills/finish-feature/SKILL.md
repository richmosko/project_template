---
name: finish-feature
description: Closes a feature — commits, pushes, opens a PR linked to the active cairn issue, updates the issue (status → in-review, pr → URL), and prepares the Validate handoff. Use when the implementation is complete, tests are green, and the feature is ready to merge. No arguments needed; reads feature state from process/MILESTONES.md and the issue file.
---

# finish-feature

Wraps one Implement→Validate loop (one feature) and queues it for merge. The tracker is **cairn** (`process/cairn/`, via the `scripts/cairn/cairn` CLI).

## Pre-flight checks

Run these in parallel; abort with a clear message if any fails:

```bash
# 1. We're on a feature branch
git rev-parse --abbrev-ref HEAD | grep -q '^feature/' || echo "ERROR: not on a feature branch"

# 2. Tests are green (heuristic: project should have a test script)
npm test 2>/dev/null || yarn test 2>/dev/null || pytest 2>/dev/null || echo "WARNING: no test runner detected"

# 3. No uncommitted changes beyond the tracker's own status edits
git status --porcelain
```

If tests are red, **do not proceed**. Surface the failure and let the user (or QA agent) fix it.

## Steps

### 1. Stage and commit

- `git status` / `git diff` to see what's changing.
- Group into logical commits — one per logical change. The cairn issue-file edits from this loop (status flips, comments) ride with the feature's commits.
- Commit message format: `<type>(<issue-id>): <subject>` — e.g. `feat(PT-14): add login form`.
- Trailer per global git instructions.

### 2. Push and open PR

```bash
git push -u origin HEAD
```

Then `gh pr create` with:
- Title: matches the issue title, prefixed with the ID (`feat(PT-14): …`)
- Body:
  - `Tracker: PT-14 — process/cairn/issues/PT-14.md` (there is no auto-close integration; `/merge-pr` flips the status)
  - `## Summary` (2–4 bullets)
  - `## Test plan` (checklist of what QA validated)
  - The standard footer

### 3. Update the issue

```bash
scripts/cairn/cairn set <ID> status=in-review pr=<PR-URL>
scripts/cairn/cairn comment <ID> --author team-lead --body - <<'EOF'
PR opened: <PR-URL>. Awaiting Validate.
EOF
```

Commit this tracker edit as a final chore commit on the branch (`chore(PT-14): tracker → in-review`) and push — the PR then carries its own status change.

### 4. Update process/MILESTONES.md

Update the `## Active Feature` block: Status → "In Review", add the PR URL. (The board's in-review column shows the same fact — MILESTONES.md keeps only the active-feature pointer, per the table dissolution ruled in `process/TRACKER.md`.)

### 5. Run validation handshake

`SendMessage` to qa-engineer: "Feature <ID> opened as PR <url>. Drive Validate." (If teammate messaging is unavailable, the qa-engineer picks up via the anchor task or a `temp/` note — see the hand-off protocol in `process/WORKFLOW.md`.)

The Validate phase begins. QA + DevOps + Architect review, deploy to staging, and either approve merge (then `/merge-pr`) or send back a fix request.

### 6. Promote durable state before teardown

The shared task list is **session-scoped** — it disappears with the team. Before teardown:

- Anything on the anchor task that captures a **decision** or **lesson** gets promoted:
  - Decisions → `process/DECISIONS.md`
  - Implementation notes future-you wants → `cairn comment <ID> --author <role> --body -` (the issue file is the durable record)
- Ephemeral status pings and WIP markers stay transient — that's the point.

## After-merge follow-up

This skill does **not** auto-merge. Merge is a separate step (`/merge-pr`) gated on QA approval and a human review.
