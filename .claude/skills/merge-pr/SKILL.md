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

### 6. Tag and draft GitHub Release if appropriate

If this PR completes a release milestone (the milestone's Gate in `MILESTONES.md` Roadmap, or PRD's release shape), prompt:
> "Tag this as a release? (y/n) — recommended tag: vX.Y.Z"

If yes, run sequentially:

**a. Tag locally and push:**
```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z — <milestone name>"
git push origin vX.Y.Z
```

**b. Draft GitHub Release notes** from the auto-generated PR list:
```bash
gh release create vX.Y.Z --generate-notes --draft --title "vX.Y.Z — <milestone name>"
```

`--generate-notes` auto-populates the body from PR titles merged since the previous tag. `--draft` holds it unpublished so the user can curate it for end-user framing before publishing.

**c. Hand off to the user for curation:**
> "Draft Release created at `https://github.com/<owner>/<repo>/releases`. Review the auto-generated notes, curate for end-user framing (soften engineering jargon, group by user impact, add migration notes if applicable), then **Publish** when ready."

The lead does *not* publish on the user's behalf — release notes are a Principal decision.

**d. Add a row to `## Releases` in MILESTONES.md** with version, date, milestone shipped, and a link to the (still-draft, will become published) release URL. If the user hasn't published yet, mark the row as `Draft` and the lead can update it later when the user confirms publication.

Do **not** tag automatically. Releases are a human decision. **Process milestones (M0, M1) typically don't get tagged releases** — they're internal phase gates, not user-facing ship points.

See `WORKFLOW.md` → Release process for the full convention.

### 7. Hand off

`SendMessage` to the team-lead (you): "Feature <id> merged. Pick next feature or transition phase."

The lead reads MILESTONES.md and decides: another feature in the current sprint, next sprint planning, or phase escalation (milestone complete → next milestone, or PRD-invalidating findings → Research mini-loop).

### 8. Tear down the team

Once the lead has decided the next move:

- "Clean up the team" — tears down the Implement team. The **shared task list disappears with it** (any state that mattered should already be in MILESTONES.md / Linear per `/finish-feature` step 6).
- The next phase (or next feature in the same sprint) spawns a fresh team.
