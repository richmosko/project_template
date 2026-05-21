---
name: merge-pr
description: Merges the active feature's PR back to main after Validate has passed. Updates Linear, cleans up the branch, updates MILESTONES.md, and prepares the next feature slot. Use only after qa-engineer signs off. Optional argument: PR number (defaults to the PR for the current branch).
---

# merge-pr

Closes the Validate gate by merging the feature PR.

## Pre-flight

- **Confirm QA sign-off.** Read the most recent `SendMessage` thread with qa-engineer; the approval must be explicit ("validate green" or equivalent). If unclear, ask the user to confirm before proceeding.
- **Confirm SECURITY review passed** if the diff touched anything in the security controls catalog. Run `/security-review` if you haven't already this loop.
- **Confirm the PR has the required reviewers** (human approver, if your org requires one).

## Inputs

- `$ARGUMENTS` — optional PR number. If omitted, detect via `gh pr view --json number -q .number` on the current branch.

## Steps

### 1. Verify merge readiness

```bash
gh pr view --json mergeable,mergeStateStatus,reviewDecision
```

Abort with a clear message if:
- `mergeable != "MERGEABLE"`
- CI checks aren't green
- Required reviews are missing

### 2. Merge

Default to **squash merge** (one PR = one logical commit on main). Override only if the user has set a different convention.

```bash
gh pr merge <pr-num> --squash --delete-branch
```

The `--delete-branch` flag cleans up the remote feature branch.

### 3. Sync local

```bash
git checkout main
git pull --ff-only
git branch -d feature/<issue-id>-<slug>  # delete local branch
```

### 4. Update Linear

- Set issue status to "Done".
- Add a final comment: "Merged in <commit-sha>. Closing."
- The parent Linear cycle (sprint) and project (milestone) auto-track completion as constituent issues close.

### 5. Update MILESTONES.md

- Move the feature entry from `### In Flight` to `### Completed` (under Features), with the merge date and PR link.
- Clear `## Active Feature`.
- If this feature completed a sprint (Linear cycle) or milestone (Linear project), update the corresponding row in `## Sprints` or `## Roadmap`.

### 6. Tag if appropriate

If this PR completes a release milestone (the milestone's "Definition of done" in `MILESTONES.md` / PRD), prompt:
> "Tag this as a release? (y/n) — recommended tag: vX.Y.Z"

If yes:
- Confirm the version number with the user (semver).
- `git tag -a vX.Y.Z -m "Release vX.Y.Z — <milestone name>"` then `git push origin vX.Y.Z`.
- Add a row to `## Releases` in MILESTONES.md.

Do **not** tag automatically. Releases are a human decision.

### 7. Hand off

`SendMessage` to the team-lead (you): "Feature <id> merged. Pick next feature or transition phase."

The lead reads MILESTONES.md and decides: another feature in the current sprint, next sprint planning, or phase escalation (milestone complete → next milestone, or PRD-invalidating findings → Research mini-loop).

### 8. Tear down the team

Once the lead has decided the next move:

- "Clean up the team" — tears down the Implement team. The **shared task list disappears with it** (any state that mattered should already be in MILESTONES.md / Linear per `/finish-feature` step 6).
- The next phase (or next feature in the same sprint) spawns a fresh team.
