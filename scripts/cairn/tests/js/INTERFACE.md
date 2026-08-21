# board-logic.js — interface contract assumed by the JS test suite

Mirrors `scripts/cairn/tests/INTERFACE.md`'s role for the Python suite: this is not
the product spec, it's the concrete API surface these tests import and call —
someone has to pick names, and the tests need to pick the same ones the
implementation does.

If you (implementation-lead) find a function here awkward to implement as named,
change the name/signature and update this file in the same commit as the test fix
— keep behaviour-neutrality and PT-3-bug-coverage the north star, not this file's
word choice.

## Loading contract (how tests get at this file — read this first)

**Settled by architect's ruling, 2026-08-21** (an architecture call, not a testing
preference — this was a two-way contract question that had qa-engineer and
implementation-lead each waiting on the other; architect broke the deadlock).

`board-logic.js` is a plain `<script>` (no module system, no build step — same
"vanilla JS, no framework, no CDN, works offline" contract as `board.js` itself).
It exposes its functions as a **top-level `var`**, not a `window.` property:

```js
var CairnLogic = (function () {
  // ... function definitions ...
  return {
    milestoneLabel, milestoneMajor, dedupeMajorIds, milestoneProgress,
    issueMilestoneKey, uniqueMilestoneKeys, primaryMilestones,
    isDraggable, primaryRootId, orderRoots, laneStateKey,
    uniqueSorted, groupByMilestone,
  };
})();
```

A top-level `var` lands on the global object in both environments this file runs
in — `window` in a real browser (no `window.` prefix needed, `var` at script scope
already does this), and the `node:vm` sandbox's context object here — so one file
serves both with zero dual-mode branching. **No `window.CairnLogic = …` assignment,
no `module.exports`, no ES `import`/`export`.**

Tests load it via `node:vm` (`scripts/cairn/tests/js/helpers.js`'s `loadCairnLogic()`):
`vm.runInNewContext(source, sandbox)` against a fresh `{}` sandbox per call — the
top-level `var CairnLogic = …` becomes a property of that sandbox object, read back
as `sandbox.CairnLogic`. Fresh context per call is deliberate, not incidental: every
bug this suite exists to catch was about stale or accidentally-shared lookup state,
so the harness itself doesn't introduce a shared-state footgun of its own.

`board.html` must load `board-logic.js` via `<script src="/board/board-logic.js">`
**before** `board.js`. `board.js`'s own IIFE reads the global `CairnLogic` by normal
scope lookup (no `window.` prefix needed there either) — architect's suggested
pattern is destructuring at the top of `board.js` (e.g. `var isDraggable =
CairnLogic.isDraggable;`), so a load-order mistake throws immediately at parse/init
time instead of silently yielding `undefined` deep inside a render call.

**Convention board-logic.js's own header comment must state** (per architect's
review): every exported function is called from a synchronous render pass only,
never from inside a `.then()` — an extracted function takes `board`/`issues` as an
explicit parameter rather than reading closure-captured `state`, which is correct
inside a render pass (`board.js`'s `renderHeader`/`renderKanban` both snapshot
`var board = state.board` at the top) but would silently read a **stale** board if
called from an async callback that resolves after a refresh. This is a code-read
audit item on the refactor diff, not something a pure-logic unit test can catch —
the function itself is correct, only a hypothetical bad call site wouldn't be.

## Functions

- `milestoneLabel(board, id, repoId) -> string` — `"id · name"` when a milestone
  matching `id` (and `repo === repoId` when `repoId` is given) has a `name`; falls
  back to the bare `id` otherwise (no match at all, or a match with no `name`).
  `repoId == null` means "don't scope by repo" (single-root callers, or callers
  that already know `id` is unambiguous). Pre-existing function (PT-16/PT-3),
  extracted verbatim — no behavior change, already pure.

- `milestoneMajor(board, milestoneId, repoId) -> string | null` — the `major` of
  the milestone matching `milestoneId` (and `repo === repoId` when given), or
  `null` if no match. **Signature change from board.js's pre-extraction version**:
  takes `board` explicitly instead of reading `state.board.milestones` — this is
  the "params over closure" fix the extraction requires; the caller in `board.js`
  now passes `state.board` explicitly.

- `dedupeMajorIds(majors) -> string[]` — the distinct `id`s among `majors`, in
  first-seen order (later duplicates dropped). Existing PT-3 behavior (the inline
  `seenMajorIds` loop in `renderHeader`) as a named, testable function — majors
  aren't repo-qualified in this template's versioning convention (every repo's
  founding major is typically `V1`), so the **visible tab bar** dedupes by bare id
  (team-lead's ruling, PT-3 §"major tabs"). Returns bare ids, not the full major
  records: the tab-button loop only ever reads `major.id` (button label + the
  onclick's `state.currentMajor` assignment), so which of two identical-id major
  records "won" isn't observable in the rendered board — returning ids keeps the
  contract from over-specifying an internal detail nothing consumes. Does NOT
  decide filtering semantics (that's `board.js`'s union-comparison logic,
  unchanged, not part of this extraction).

- `milestoneProgress(issues, milestone) -> {done: number, total: number}` — counts
  issues belonging to `milestone` (matched by `issue.milestone === milestone.id
  && issue.repo === milestone.repo` — repo-scoped, this is the PT-3 progress-strip
  fix) and, of those, how many have `status === "done"`.

- `issueMilestoneKey(issue) -> string` — `issue.repo + "::" + (issue.milestone ||
  "")`. **The shared helper (architect's #5b finding)**: both the filter-milestone
  select's option-value builder (`uniqueMilestoneKeys`, below) and
  `filteredIssues`'s comparison must call this SAME function — not two separately
  written expressions that happen to produce the same string today and silently
  drift tomorrow. This is the single highest-value extraction: it converts a
  hand-maintained invariant (two expressions must agree) into a structural one
  (one function, two callers).

- `uniqueMilestoneKeys(issues) -> Array<{key: string, repo: string, milestone: string}>`
  — one entry per distinct `issueMilestoneKey(issue)` among `issues` that have a
  non-null `milestone`, sorted by `key` ascending. This is the filter-milestone
  select's option list (PT-3's `msPairs` block in `renderHeader`, extracted).

- `primaryMilestones(milestones, primaryId) -> Array` — `milestones` filtered to
  `m.repo === primaryId`, OR (the PT-3 null-guard fix, commit `89d5a30`) every
  milestone when `primaryId == null` (a roots-less/repo-less payload — treat "no
  repo dimension at all" as "everything is the primary", the true pre-PT-3
  fallback, rather than emptying the select). This is `new-issue-milestone`'s
  option-list filter — the **data-integrity-critical** one: creation always writes
  to the primary root, so offering a foreign milestone id here would let a user
  create a primary-root issue referencing a milestone `cairn check` would then
  flag as unknown.

- `isDraggable(issue, primaryId) -> boolean` — `primaryId == null || issue.repo
  === primaryId`. **The shared predicate (architect's finding)**: both `cardEl`
  (sets `card.draggable`) and `handleDrop`'s refusal-guard must call this SAME
  function — they were two independently-duplicated inline comparisons in PT-3
  that both needed the identical null-guard fix (commit `89d5a30`) applied
  separately. Same "two expressions must agree" bug class as `issueMilestoneKey`.

- `primaryRootId(board) -> string | null` — the `id` of the one root in
  `board.roots` with `primary: true`, or `null` when `board` is falsy, `board.roots`
  is absent/empty, or no root is marked primary. Pre-existing function (PT-3),
  extracted verbatim — already pure (takes `board` as its only param). The root of
  the null-return bug class: every function above that takes `primaryId` treats a
  `null` value as "no repo dimension known" rather than "no root is ever primary".

- `orderRoots(roots) -> Array` — `roots` sorted primary-first, then remaining
  roots by `id` ascending. Extracted from `renderKanban`'s `orderedRoots.sort(...)`
  comparator (PT-3). Second-tier: same "id comparison across roots" shape as the
  functions above, no specific escaped defect, but implementation-lead is moving
  it as part of the same refactor pass, so it gets coverage now rather than
  becoming a gap.

- `laneStateKey(repoId, milestoneKey) -> string` — `repoId + "::" + milestoneKey`.
  Extracted from `milestoneLaneEl`'s composite collapse-state key construction
  (PT-3, `root.id + "::" + key`) — the same "must produce distinct keys per repo
  so collapsing one repo's lane doesn't collapse another's" property as
  `issueMilestoneKey`, just for swimlane collapse state instead of the
  filter-milestone select. Second-tier, same reasoning as `orderRoots`.

- `uniqueSorted(values) -> string[]` — the distinct truthy values among `values`,
  sorted ascending. Extracted from `board.js`'s `uniqueSorted` (the filter-assignee/
  filter-label dropdown value dedup) for PT-23 — same function, now testable and
  fixed. **Must use `Object.create(null)` internally, not a bare `{}`**, per PT-23
  (architect's finding): an assignee/label value shaped like an `Object.prototype`
  key name (`"constructor"`, `"toString"`, `"hasOwnProperty"`, …) reads as already
  truthy on a bare `{}` *before* anything is ever inserted — see
  `prototype-collision.test.js`'s "an id shaped like `toString`" family of tests.

- `groupByMilestone(issues) -> {order: string[], groups: {[key: string]: Array}}` —
  groups `issues` by `issue.milestone || "(none)"`, `order` is the group keys
  sorted ascending. Extracted from the (previously duplicated verbatim in two
  places — `renderKanban`'s single-root branch and `repoSectionEl`) `byMilestone`
  grouping block, PT-23. Same `Object.create(null)`-not-bare-`{}` requirement as
  `uniqueSorted` — a milestone id shaped like an `Object.prototype` key would
  silently vanish from `order`/`groups` on a bare `{}`.

## Not extracted in this pass (stretch / out of scope)

- `filteredIssues`'s full predicate chain — the richest target (and
  `issueMilestoneKey`'s actual consumer), but reads four pieces of closure state
  (`state.board`, `state.filters`, `state.currentMajor`, `state.showCancelled`);
  the bigger lift is a stretch goal, not a blocker, since `issueMilestoneKey`
  alone already closes the specific invariant that broke.

## Running the suite

```
node --test scripts/cairn/tests/js/*.test.js
```

From the repo root. **The glob is required** — `node --test scripts/cairn/tests/js`
(a bare directory path, no glob) does NOT auto-discover files in this Node version
(26.5.1, verified) despite Node's docs suggesting directory args recurse; only an
explicit `*.test.js` glob (or `**/*.test.js` if subdirectories are ever added)
reliably picks up every file here. Confirmed empirically while writing this suite
— re-verify against whatever Node version CI/`finish-feature` actually runs before
wiring PT-24's gate to a bare-directory invocation.

No `package.json`, no `node_modules` — `node:test` and `node:assert` are Node's
stdlib (Node 18+). Skips with a notice (not a failure) when `node` isn't on `PATH`
at all — see the harness's own skip logic, not this file. The Python suite
(`scripts/cairn/tests/`) remains the hard gate; this one is additive.
