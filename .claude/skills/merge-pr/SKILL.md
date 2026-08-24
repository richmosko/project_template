---
name: merge-pr
description: Merges the active feature's PR back to main after Validate has passed. Updates the cairn issue (status → done), cleans up the branch, updates process/STATE.md, and prepares the next feature slot. Use only after qa-engineer signs off. Optional argument: PR number (defaults to the PR for the current branch).
---

# merge-pr

Closes the Validate gate by merging the feature PR. The tracker is **cairn** (`process/cairn/`, via the `scripts/cairn/cairn` CLI).

## Pre-flight

- **Confirm QA sign-off.** The approval must be explicit ("validate green" or equivalent) — from qa-engineer's `SendMessage`, or their `temp/` verdict file when messaging is unavailable. If unclear, ask the user to confirm before proceeding.
- **Confirm SECURITY review passed** if the diff touched anything in the security controls catalog. Run `/security-review` if you haven't already this loop.
- **Confirm the PR has the required reviewers** (human approver, if your org requires one).

## Inputs

- `$ARGUMENTS` — optional PR number. If omitted, detect via `gh pr view --json number -q .number` on the current branch.

## Steps

### 1. Verify merge readiness

```bash
gh pr view --json mergeable,mergeStateStatus,reviewDecision
```

Abort with a clear message if `mergeable != "MERGEABLE"`, CI checks aren't green, or required reviews are missing.

### 2. Close the issue on the branch, then merge

The status flip rides the PR itself — it's the branch's **final commit**, so the squash merge lands the feature and its `done` status atomically. (If the merge aborts, the flip dies with the branch — nothing to unwind.)

```bash
git checkout feature/<id>-<slug>       # or gh pr checkout <pr-num>
scripts/cairn/cairn set <ID> status=done
scripts/cairn/cairn comment <ID> --author team-lead --body - <<'EOF'
Validate passed; merging via PR #<n>. Closing.
EOF
git add process/cairn/issues/<ID>.md
git commit -m "chore(<ID>): tracker → done"   # + standard trailer
git push
```

**If this merge closes the milestone** (this issue was its last open one — check `cairn ls --milestone <m>`), fold the milestone flip into the same commit: `scripts/cairn/cairn set <milestone-id> status=done` and `git add` the milestone file alongside the issue file. This is the only branch the flip can legally ride — after the merge there is no branch, and a direct push to `main` is forbidden.

Then squash-merge (one PR = one logical commit on main; override only if the user has set a different convention):

```bash
gh pr merge <pr-num> --squash --delete-branch
```

### 3. Sync local

```bash
git checkout main
git pull --ff-only
git branch -d feature/<id>-<slug>
```

Major-line completion isn't auto-tracked: when a line EOLs, the lead runs `scripts/cairn/cairn set <major-id> status=done` on a doc-update branch.

### 4. Update process/STATE.md

- Clear `## Active Feature`.
- Do **not** add session narrative to STATE.md — it keeps no history. Anything worth recording goes to the cairn issue as a comment (or the decision ledger).
- **If this feature completed a milestone**: the milestone flip already rode the final branch commit (step 2). **Policy (Mosko, 2026-08-24): archive the shipped milestone at release close** — after tagging (step 5), run `scripts/cairn/cairn archive --milestone <id>` (moves its done/cancelled issues and the milestone file; preview with `--dry-run`) on the release-prep doc branch so the move rides a PR. An archived milestone (and its issues) then appears only behind the board's Show-archived toggle — the default view drops its lane entirely; a done-but-unarchived milestone keeps a ✓ Done lane in the default view. Archive when the milestone no longer needs default-view presence. `cairn archive --done-before <date>` remains available as broader hygiene — never a quota, there is no cap.

(There is no Completed/In-Flight table to move rows between — those tables dissolved into the board; see `process/TRACKER.md` → Relationship to STATE.md.)

### 5. Tag and draft GitHub Release if appropriate

If this PR completes a release milestone, prompt. **Derive the version from the milestone file** (`milestones/<name>.md` → `target_tag`), never guess (see `process/WORKFLOW.md` → Versioning scheme): milestone `1.1` → `v1.1.0`; the `ga: true` milestone of a major → `vN.0.0`; a hotfix on a shipped milestone → PATCH bump. For a not-yet-GA milestone, offer a pre-release tag (`v2.0.0-rc.1`). For a `V1.x` maintenance release while `main` carries a newer major, tag from the `release/1.x` branch.

> "Tag this as a release? (y/n) — recommended tag: vX.Y.Z (from milestone <name>, target_tag <t>)"

If yes, run sequentially:

**a. Tag locally and push:**
```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z — <milestone name>"
git push origin vX.Y.Z
```

**b. Draft GitHub Release notes:**
```bash
gh release create vX.Y.Z --generate-notes --draft --title "vX.Y.Z — <milestone name>"
```

**c. Hand off to the user for curation:**
> "Draft Release created at `https://github.com/<owner>/<repo>/releases`. Curate for end-user framing, then **Publish** when ready."

The lead does *not* publish on the user's behalf — release notes are a Principal decision.

**d. Add a row to `## Releases` in process/STATE.md** with version, date, major, milestone shipped, branch, and the release URL (mark `Draft` until the user publishes).

Do **not** tag automatically. Releases are human decisions. **Definition milestones (`kind: process`) never tag.**

### 6. Hand off

Report: "Feature <ID> merged. Pick next feature or transition phase."

The lead reads process/STATE.md + `scripts/cairn/cairn ls --status todo` and decides: another feature in the current session cycle, plan a fresh session, or phase escalation.

### 7. Tear down the team

Once the next move is decided: "Clean up the team." The shared task list disappears with it — any state that mattered should already be in the issue file / STATE.md per `/finish-feature` step 6. The next feature spawns a fresh team.
