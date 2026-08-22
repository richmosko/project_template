---
name: sweep-memory
description: Audit the persistent memory stores (team-lead auto-memory + every teammate agent-memory dir) for bloat, staleness, and append-drift — each memory gets verified against the current tree and kept, merged, condensed, or deleted, and the MEMORY.md indexes rebuilt to match. Use at session close (same priority class as /sweep-temp), or on demand when memory feels stale. Pass "status" for a read-only inventory without the walk.
---

# sweep-memory

Counters the structural append-bias of LLM memory: the dedupe rule ("check for an existing file before saving; update, don't duplicate; delete what's wrong") fires only at **write time**, and appending is always the lower-friction path — so resolved incidents, point-in-time snapshots, and facts since ratified into tracked artifacts accumulate as fossils. Nothing else ever forces a retrospective walk; this skill is that walk. It is a session-close obligation in `.claude/roles/team-lead.md`, peer to `/sweep-temp`.

**Memory is local, so there is no git flow here.** Both stores are per-machine scratch cognition — never committed, never pushed (see `.gitignore`: "session-derived working memory, per-machine — not ratified project state"). Every action in this sweep is a direct file edit with no branch or PR. Anything a memory holds that deserves to be *ratified* is not a memory problem — place it in a tracked artifact (CLAUDE.md, `process/WORKFLOW.md`, the decision ledger, a cairn issue) via the normal doc-update flow, then delete the memory as duplicated.

## The stores

| Store | Location | Written by |
|---|---|---|
| Team-lead auto-memory | `~/.claude/projects/<project-slug>/memory/` — slug is the project path with `/` → `-` (e.g. `-Users-mosko-Projects-project-template`) | the main session |
| Teammate agent-memory | `**/.claude/agent-memory/<role>/` under the repo — **glob the whole tree**, not just the root: agents that ran with a nested cwd leave stray stores (e.g. `scripts/cairn/.claude/agent-memory/`) | each spawned teammate |

Both are workflow surface under `.claude/**` / the lead's project dir — the team-lead owns them and edits directly; no teammate dispatch is needed for hygiene.

## Inputs

- *(none)* — full interactive sweep.
- `status` — read-only inventory: the tables from Step 1, then stop. No decisions, no writes.

## Steps

### 1. Inventory

```bash
# team-lead store
ls -la "$HOME/.claude/projects/$(pwd | tr '/' '-')/memory/"
# teammate stores, strays included
find . -type d -path '*/.claude/agent-memory/*' -not -path '*/node_modules/*'
```

For each store, one compact table: file, size, `metadata.type` (from frontmatter), mtime age, and **index consistency** — flag *orphans* (file present, no `MEMORY.md` line) and *dangling lines* (`MEMORY.md` line, no file). Report totals per store. If invoked as `status`, stop here.

### 2. Verify each memory against the tree

Read each file and test its claims **against current state, not plausibility**:

- **Referents still exist?** A memory naming a file, function, flag, skill, or agent is checked with a grep/ls before it survives. (The recall rules already require this check before *recommending* a memory — the sweep simply runs it proactively.)
- **Status markers.** Anything self-marked RESOLVED / superseded / "pending X" where X has since shipped is presumptively dead.
- **Duplicated into tracked artifacts?** A fact now recorded in CLAUDE.md, WORKFLOW.md, TRACKER.md, the decision ledger, or a cairn issue no longer needs a memory — the repo copy is the authoritative one.
- **Point-in-time snapshots.** "Current status of X" memories (tool availability, outages, counts) rot silently; verify against the live tree or kill.

### 3. Triage — one decision per file

- **Keep** — still true, still non-derivable from the repo, still useful. Untouched.
- **Condense** — the fact survives but the narrative around it is fossil (e.g. a resolved incident whose only living residue is a one-line rule). Rewrite the file down to the residue; update its `description:`.
- **Merge** — two files cover one fact, or a resolved memory's residue belongs inside a related one. Fold in, delete the source, fix `[[links]]`.
- **Delete** — resolved, superseded, contradicted by the tree, or duplicated into a tracked artifact. Echo a one-line rationale per deletion so the decision is visible in the transcript.

**Type-based guardrails:**

- `feedback` and `user` memories encode the user's own guidance — **never delete or condense one on the lead's judgment alone** unless it is plainly superseded (a later ruling reversed it, or the thing it governs no longer exists). Anything short of plainly: batch into one question set for the user, per the role file's Deciding rules.
- `project` and `reference` memories are the lead's call; state each decision.
- Teammate stores get the same triage with the same guardrails — their `feedback_*` files record corrections given to that role and are as protected as the lead's.

### 4. Rebuild the indexes

Each store's `MEMORY.md` is rewritten to exactly match the surviving files — one line per memory, no orphans, no dangling lines, no content beyond the pointer format. A stray store whose files all died is removed entirely (the directory too).

### 5. Report

One summary block per store: *N kept, N condensed, N merged, N deleted (with rationales), index rebuilt*. Then one line for anything routed **out** of memory into a tracked artifact — that placement rides the normal doc-update flow and is the only part of a sweep that touches git.

## Rules

- **Never delete without a decision** — same discipline as `/sweep-temp`. No auto-deletion exists anywhere in this system.
- **Verification is against the tree, not memory-of-the-tree.** Run the grep; don't trust that a referent "surely still exists."
- **Don't relitigate kept files every session.** A memory that survived a sweep unchallenged is presumed good until the tree contradicts it or a later sweep's verification fails; sweeps should get *faster* on a healthy store, not re-read everything from scratch.
- **No SessionStart nag, by design.** `temp/` gets a hook because a pending file is mechanically detectable; memory staleness is only detectable by verification, which needs a model, not an `awk` line. The session-close obligation is the enforcement.

## Related machinery

- `/sweep-temp` — the same walk for the `temp/` hand-off buffer (session-close peer of this skill).
- Memory write-time rules — the auto-memory instructions in the session context (dedupe-before-save, delete-when-wrong); this skill is their retrospective backstop.
