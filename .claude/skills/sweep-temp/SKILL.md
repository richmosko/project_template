---
name: sweep-temp
description: Interactive sweep of the temp/ hand-off buffer — every unplaced agent finding gets placed into a tracked artifact, discarded with a stated rationale, or explicitly held with a hold-until date. Use at session close (a team-lead obligation), when the SessionStart hook reports unplaced files, before /compact mid-arc, or on demand. Pass "status" for a read-only inventory without the walk.
---

# sweep-temp

Mechanizes the team-lead's session-close obligation #2 (see `.claude/roles/team-lead.md` → Session close): **`temp/` swept**. The buffer's state model is deliberately minimal — **a file exists in `temp/` if and only if it is unplaced.** Placement or discard *is* deletion; the only frontmatter that ever appears is a `hold-until:` stamp marking a deliberate multi-session keep.

## The state model

| State | Representation |
|---|---|
| Pending (unplaced finding) | file exists in `temp/`, no `hold-until:` |
| Held (deliberate multi-session keep) | file exists, `hold-until: YYYY-MM-DD` frontmatter, date in the future |
| Expired hold | file exists, `hold-until:` date in the past → treated as pending again |
| Placed or discarded | **file deleted** — there is no other record in `temp/` |

Files are named `temp/<YYYY-MM-DD>-<agent>-<topic>.md` (per the hand-off protocol baked into every agent file), so a bare `ls temp/` shows origin and age. No manifest, no status field, no ledger — anything like that becomes a second source of truth that drifts from the directory listing.

## Inputs

- *(none)* — run the full interactive sweep.
- `status` — read-only inventory: the table from Step 1, then stop. No decisions, no writes.

## Steps

### 1. Inventory

```bash
find temp -type f -name '*.md' 2>/dev/null | sort
```

If empty (or `temp/` doesn't exist): report "temp/ is clean — nothing to sweep" and stop.

For each file, gather: filename (date, agent, topic), size, first heading, `hold-until:` if present, and `kind: deliverable` + `target:` if present (see `process/WORKFLOW.md` → Findings vs deliverables). Present one compact table with an age classification per file:

| Classification | Rule | Default recommendation |
|---|---|---|
| fresh | ≤ 14 days old, no hold | none — read and decide |
| stale | > 14 days old, no hold | **discard** |
| held | `hold-until:` in the future | skip (report only) |
| expired hold | `hold-until:` in the past | **discard** |

Age comes from the filename's date prefix; fall back to file mtime if the prefix is missing or malformed. If invoked as `status`, stop here.

### 2. Triage — one decision per file

Walk pending files oldest-first (stale and expired holds first). For each, read the file and drive one of three decisions. Per the role file's Deciding rules: trivial calls (obviously dead scratch, a finding already visibly landed in a tracked artifact) the lead makes and states; anything genuinely judgment-bearing goes to the user — batched into one question set, not a drip.

- **Place** — copy the durable content into its tracked home (`process/DECISIONS.md`, a `docs/` artifact, `process/STATE.md`, or a cairn issue comment — `scripts/cairn/cairn comment <ID> …`), **verify the landed text against the temp file, then delete it** — in that order, never delete-first: the temp file is the only comparison source, and a lossy copy becomes undetectable once it's gone. For a *finding*, summarizing at placement is legitimate and "verify" means confirming the conclusion survived intact. For a **`kind: deliverable`** file, the strict path applies: land **verbatim** at the declared `target:`, diff the landed hunk against the temp file before deleting, and — once the placement is committed — report `landed @ <sha>` plus the target path back to the supplying agent, who verifies via `git show <sha>:<path>`. Placement without deletion is not placement — the file would read as pending forever.
- **Discard** — delete, echoing a one-line rationale ("superseded by ADR-—", "investigation dead-ended") so the decision is visible in the transcript.
- **Hold** — stamp or extend frontmatter at the top of the file:

  ```markdown
  ---
  hold-until: YYYY-MM-DD
  ---
  ```

  A hold needs a reason the lead can state in one line (a multi-session investigation, evidence awaiting a PR that hasn't opened). "I might need it someday" is a discard.

### 3. Land the placements

Placements touch tracked files, and **no direct pushes to `main`** applies to sweeps too:

- If a `feature/*` or `phase/*` branch is already active, the placement edits ride along on it.
- Otherwise, batch all placements from this sweep and land them through one `/start-doc-update` → `/finish-doc-update` → `/merge-pr` cycle (slug like `sweep-temp-placements`). Deletions of the temp files themselves are invisible to git (`temp/` is gitignored) and need no branch.

### 4. Report

Close with one summary line: *N placed (into which artifacts), N discarded, N held (latest `hold-until`)*. The exit condition: `temp/` contains only files with an unexpired `hold-until:`.

## Rules

- **Never delete without a decision.** The 14-day threshold and expired holds set the *default recommendation*, not an automatic action. There is no auto-deletion anywhere in this system — a stale unplaced finding gets louder (the SessionStart hook nags every session), never quieter.
- **Don't re-litigate held files** until their date passes; report them and move on.
- **One sweep, one placement PR.** Don't open a branch per file.

## Related machinery

- **SessionStart hook** (`.claude/settings.json`) — reports the pending/stale count whenever `temp/` is non-empty. Visibility only; it never modifies files.
- **Hand-off protocol** (every `.claude/agents/*.md`) — how files get *into* `temp/`. See `process/WORKFLOW.md` → Hand-off protocol & the `temp/` buffer.
- **Role file** (`.claude/roles/team-lead.md`) — the receiving-half obligation this skill discharges.
- **`/sweep-memory`** — the session-close peer of this skill: the same walk over the persistent memory stores (lead auto-memory + teammate agent-memory), which have no hook nag and only shrink when something audits them.
