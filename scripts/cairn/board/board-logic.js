// board-logic.js — pure-logic functions extracted from board.js (PT-22).
//
// Vanilla JS, no framework, no CDN, no module system, no build step --
// the exact same "works offline" contract board.js itself carries. A
// plain <script>, loaded by board.html BEFORE board.js, exposing a
// single global via a top-level `var` (NOT `window.CairnLogic = ...`,
// no `module.exports`, no ES `import`/`export` -- architect's ruling,
// 2026-08-21: a top-level `var` lands on the global object in both
// environments this file runs in -- `window` in a real browser, a
// node:vm sandbox's context object in the test harness -- so one file
// serves both with zero dual-mode branching):
//
//   var CairnLogic = (function () { ... return {...}; })();
//
// board.js's own IIFE reads the global `CairnLogic` by normal scope
// lookup (no `window.` prefix needed there either) and destructures at
// the top (`var isDraggable = CairnLogic.isDraggable;` etc.) -- loading
// board-logic.js in the wrong order (or not at all) fails loudly at
// board.js's very first line that touches CairnLogic, rather than
// quietly producing `undefined` deep inside a render.
//
// CONVENTION (architect's PT-3/PT-22 review): every function below is
// called from a SYNCHRONOUS RENDER PASS ONLY -- board.js's
// renderHeader()/renderKanban() both snapshot `var board = state.board`
// at the top before calling into here, so these functions always see the
// current board. None of them may be called from inside a `.then()`
// callback (e.g. after apiMutateIssue resolves) without first re-checking
// that the board these functions would read is still the one the
// callback was issued against -- a function taking `board` as an
// explicit parameter is only as fresh as whatever the caller captured,
// and a stale capture across an async boundary would silently reintroduce
// the exact class of bug this extraction exists to close structurally
// (PT-3's milestoneLabel/milestoneMajor collisions). This is a code-read
// audit item on every call site, not something a pure-logic unit test
// can catch.

var CairnLogic = (function () {
  "use strict";

  // The distinct truthy values among `values`, sorted ascending -- the
  // filter-assignee/filter-label dropdown dedup. PT-23 extraction from
  // board.js's own uniqueSorted, fixed in the same move: uses
  // Object.create(null) internally (architect's finding), not a bare
  // {} -- a value shaped like "constructor"/"toString"/"hasOwnProperty"
  // reads as already-seen on a bare {} the moment it's looked up, before
  // anything is inserted, and silently drops from the option list.
  function uniqueSorted(values) {
    var set = Object.create(null);
    (values || []).forEach(function (v) { if (v) set[v] = true; });
    return Object.keys(set).sort();
  }

  // The id of the one root in board.roots marked primary, or null when
  // board is falsy, board.roots is absent/empty, or no root is primary.
  // Every other function below that takes a `primaryId` parameter treats
  // a null value as "no repo dimension is known at all" (a roots-less
  // payload -- e.g. board.js cached against an older cairn serve process,
  // since _send_static sends no Cache-Control) -- distinct from "a real
  // primaryId that just doesn't match anything". Pre-existing function
  // (PT-3), extracted verbatim.
  function primaryRootId(board) {
    var roots = (board && board.roots) || [];
    for (var i = 0; i < roots.length; i++) {
      if (roots[i].primary) return roots[i].id;
    }
    return null;
  }

  // Internal: the milestone record matching `id` (and `repo === repoId`
  // when repoId is given). Milestone ids are NOT unique across roots (a
  // milestone "0.5" in repo A is unrelated to one in repo B) -- an
  // unscoped lookup silently returns whichever root's record happened to
  // land first in the concatenated /api/board payload. `repoId == null`
  // means "don't scope by repo" (single-root callers, or callers that
  // already know `id` is unambiguous).
  function milestoneRecord(board, id, repoId) {
    var candidates = ((board && board.milestones) || []).filter(function (m) {
      return m.id === id;
    });
    return repoId != null
      ? candidates.filter(function (m) { return m.repo === repoId; })[0]
      : candidates[0];
  }

  // "id · name" when a repo-scoped match has a name; falls back to the
  // bare id otherwise (no match at all, or a match with no name).
  // Pre-existing function (PT-16/PT-3), extracted verbatim -- already
  // pure, already took board/id/repoId as parameters.
  function milestoneLabel(board, id, repoId) {
    var ms = milestoneRecord(board, id, repoId);
    return ms && ms.name ? id + " · " + ms.name : id;
  }

  // The `major` of the milestone matching milestoneId (repo-scoped when
  // repoId given), or null. Signature change from board.js's
  // pre-extraction version: takes `board` explicitly instead of reading
  // `state.board.milestones` via closure -- the "params over closure"
  // fix the extraction requires. Callers in board.js now pass
  // `state.board` explicitly.
  function milestoneMajor(board, milestoneId, repoId) {
    var ms = milestoneRecord(board, milestoneId, repoId);
    return ms ? ms.major : null;
  }

  // The distinct ids among `majors`, in first-seen order (later
  // duplicates dropped) -- the major-tabs bar's dedup. Returns bare ids,
  // not the full major records: the tab-button loop only ever reads
  // `major.id` (button label + the onclick's `state.currentMajor`
  // assignment), so which of two identical-id major records "won" isn't
  // observable in the rendered board. Majors aren't repo-qualified in
  // this template's versioning convention (every repo's founding major is
  // typically V1), so the VISIBLE tab bar dedupes by bare id (team-lead's
  // ruling) -- this function does the dedup only; it does not decide
  // filtering semantics (board.js's union-comparison logic, unchanged, is
  // not part of this extraction).
  function dedupeMajorIds(majors) {
    // PT-23 (architect's finding): Object.create(null), not a bare {} --
    // a bare {} inherits Object.prototype, so a major id shaped like
    // "constructor"/"toString"/"hasOwnProperty" reads as already-seen
    // (truthy) the very first time it's looked up, before anything is
    // ever inserted, and silently drops from the tab bar. Unreachable
    // today (major ids are version strings) but load-bearing the moment
    // that's not true, and costs nothing for the normal case.
    var seen = Object.create(null);
    var out = [];
    (majors || []).forEach(function (m) {
      if (seen[m.id]) return;
      seen[m.id] = true;
      out.push(m.id);
    });
    return out;
  }

  // {done, total} among `issues` belonging to `milestone` -- matched by
  // `issue.milestone === milestone.id && issue.repo === milestone.repo`
  // (repo-scoped: the PT-3 progress-strip fix, so two repos' same-id
  // milestones never fuse their counts into one shared, wrong number).
  function milestoneProgress(issues, milestone) {
    var msIssues = (issues || []).filter(function (i) {
      return i.milestone === milestone.id && i.repo === milestone.repo;
    });
    var done = msIssues.filter(function (i) { return i.status === "done"; }).length;
    return { done: done, total: msIssues.length };
  }

  // The shared "repo::milestone" key -- THE extraction that matters most
  // (architect's finding): both the filter-milestone select's option
  // builder (uniqueMilestoneKeys, below) and filteredIssues' comparison
  // must call this SAME function, not two independently hand-written
  // expressions that happen to agree today and can silently drift
  // tomorrow. Converts a hand-maintained invariant into a structural one.
  //
  // DEVIATION FROM VERBATIM (named explicitly, per architect's review,
  // 2026-08-21): the two pre-extraction inline expressions this replaces
  // (`issue.repo + "::" + (issue.milestone || "")` in filteredIssues,
  // `i.repo + "::" + i.milestone` in the msPairs builder) did NOT guard
  // `issue.repo` -- on a roots-less payload (issue.repo undefined) both
  // produced the literal string "undefined::0.5". This version guards it
  // (`issue.repo || ""`), producing "::0.5" instead. Verified safe: the
  // change is symmetric (both the producer and the sole consumer of this
  // key go through this same function now, so producer/consumer
  // agreement holds either way), and the key is never displayed -- only
  // used as a <select> option `value`, with the visible label coming from
  // milestoneLabel -- so nothing user-visible moves. Kept because
  // "undefined::0.5" landing in a DOM attribute is worse than "::0.5" for
  // no offsetting benefit, but flagged explicitly rather than folded
  // silently into a commit whose contract is "moved verbatim" -- an
  // extraction that quietly normalises a comparison is exactly the
  // failure mode a mechanical body-diff exists to catch, and this is the
  // one real instance of it in this pass.
  function issueMilestoneKey(issue) {
    return (issue.repo || "") + "::" + (issue.milestone || "");
  }

  // One {key, repo, milestone} entry per distinct issueMilestoneKey(issue)
  // among `issues` that have a non-null milestone, sorted by key
  // ascending -- the filter-milestone select's option list (PT-3's
  // `msPairs` block in renderHeader, extracted). Built from
  // issueMilestoneKey itself, not a second hand-written concatenation --
  // that's what makes the agreement with filteredIssues' comparison
  // structural rather than coincidental.
  //
  // DELIBERATELY a bare {}, not Object.create(null) (PT-23, qa-engineer's
  // finding, verified by architect 2026-08-21) -- unlike dedupeMajorIds/
  // uniqueSorted/groupByMilestone, this `seen` set is keyed by
  // issueMilestoneKey's composite "repo::milestone" string (e.g.
  // "PT::constructor"), which always contains "::" -- no
  // Object.prototype member name does, so no inherited key can ever be
  // hit here. Safe by construction, not by omission. Three other sets in
  // this file use Object.create(null); do not "harmonise" this one to
  // match them without re-deriving this reasoning first (see
  // laneStateKey's matching note for the same pattern on the absent-repo
  // question).
  function uniqueMilestoneKeys(issues) {
    var seen = {};
    var out = [];
    (issues || []).forEach(function (issue) {
      if (!issue.milestone) return;
      var key = issueMilestoneKey(issue);
      if (seen[key]) return;
      seen[key] = true;
      out.push({ key: key, repo: issue.repo, milestone: issue.milestone });
    });
    out.sort(function (a, b) { return a.key < b.key ? -1 : a.key > b.key ? 1 : 0; });
    return out;
  }

  // `milestones` filtered to `m.repo === primaryId`, OR (the PT-3
  // null-guard fix, commit 89d5a30) every milestone when
  // `primaryId == null` -- a roots-less/repo-less payload; treat "no repo
  // dimension at all" as "everything is the primary" (the true pre-PT-3
  // fallback) rather than emptying the select. This is
  // new-issue-milestone's option-list filter -- DATA-INTEGRITY-CRITICAL:
  // creation always writes to the primary root, so offering a foreign
  // milestone id here would let a user create a primary-root issue
  // referencing a milestone `cairn check` would then flag as unknown.
  function primaryMilestones(milestones, primaryId) {
    return (milestones || []).filter(function (m) {
      return primaryId == null || m.repo === primaryId;
    });
  }

  // Can `issue` be dragged / mutated from this board? The shared
  // predicate (architect's finding): both cardEl (sets card.draggable)
  // and handleDrop's refusal-guard must call this SAME function -- they
  // were two independently-duplicated inline comparisons in PT-3 that
  // both needed the identical null-guard fix (commit 89d5a30) applied
  // separately when a roots-less payload made the naive comparison
  // `undefined === null` (false), silently killing drag on every card
  // and refusing every drop with a toast that blamed the wrong thing.
  function isDraggable(issue, primaryId) {
    return primaryId == null || issue.repo === primaryId;
  }

  // `roots` sorted primary-first, then remaining roots by id ascending.
  // Extracted from renderKanban's orderedRoots.sort(...) comparator.
  // Second-tier: same "id comparison across roots" shape as the functions
  // above, no specific escaped defect, moved alongside the first tier
  // since it was already moving.
  function orderRoots(roots) {
    return (roots || []).slice().sort(function (a, b) {
      if (a.primary !== b.primary) return a.primary ? -1 : 1;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
  }

  // The composite collapse-state key for a milestone lane under repo
  // grouping -- "<repoId>::<milestoneKey>". Extracted from
  // milestoneLaneEl's stateKey construction (PT-3) -- the same "must
  // produce distinct keys per repo so collapsing one repo's lane doesn't
  // collapse another's" property as issueMilestoneKey, for swimlane
  // collapse state instead of the filter-milestone select. Second-tier,
  // same reasoning as orderRoots.
  //
  // DELIBERATELY does NOT guard `repoId` the way issueMilestoneKey guards
  // `issue.repo` (architect review, 2026-08-21) -- moved verbatim from
  // the original `root.id + "::" + key` / `soleRootId + "::" + key`
  // construction, so `laneStateKey(null, "0.5")` still yields
  // "null::0.5", unchanged from pre-extraction behavior. This key is
  // purely in-memory (state.collapsedLanes), never a DOM attribute value
  // and never displayed, so there was no "undefined"-in-a-user-visible-
  // place motivation to normalise it the way issueMilestoneKey's guard
  // was added. Two key builders now have different conventions for an
  // absent repo id -- that's intentional, not an oversight; do not
  // "harmonise" this one to match issueMilestoneKey without re-checking
  // this reasoning first.
  function laneStateKey(repoId, milestoneKey) {
    return repoId + "::" + milestoneKey;
  }

  // {order, groups} -- groups `issues` by `issue.milestone || "(none)"`;
  // `order` is the group keys sorted ascending. PT-23 extraction: this
  // block was duplicated VERBATIM in two places in board.js
  // (renderKanban's single-root branch and repoSectionEl) -- itself
  // another instance of PT-3's "duplicated inline expression" bug class
  // (the same shape issueMilestoneKey/isDraggable closed), found while
  // fixing the Object.prototype-collision issue rather than a separately
  // escaped defect. `groups` uses Object.create(null) internally
  // (architect's finding, same reasoning as uniqueSorted/dedupeMajorIds)
  // -- on a bare {}, a milestone id shaped like "constructor" is a
  // DIFFERENT failure mode than dedupeMajorIds' silent drop: `!groups[key]`
  // is false (the inherited function is truthy), so the `groups[key] = []`
  // branch is skipped, then `groups[key].push(issue)` calls `.push` on
  // `Object.prototype.constructor` -- which has no `.push` -- and THROWS
  // a TypeError that crashes the render, rather than silently vanishing.
  // Worse than dedupeMajorIds' failure mode, not the same one -- corrected
  // per architect's review, 2026-08-21, after an earlier draft of this
  // comment mistakenly generalised dedupeMajorIds' wording here without
  // re-deriving it for this function's actual code shape.
  function groupByMilestone(issues) {
    var groups = Object.create(null);
    var order = [];
    (issues || []).forEach(function (issue) {
      var key = issue.milestone || "(none)";
      if (!groups[key]) { groups[key] = []; order.push(key); }
      groups[key].push(issue);
    });
    order.sort();
    return { order: order, groups: groups };
  }

  // PT-25: the shared "repo::parentId" key a child issue's `parent` field
  // must match to belong to a given parent issue -- mirrors
  // issueMilestoneKey's repo-scoping shape (architect's ruling #2). Repo-
  // scoped from the FIRST line, not added after a review finding:
  // build_board_payload's server-side child_counts (now removed) keyed
  // off the bare parent id with no repo dimension, safe only because it
  // ran per-root; computed client-side over the aggregated multi-root
  // payload, an unscoped key would fuse two repos' same-id issues'
  // children into one shared, wrong count -- the fourth instance of the
  // isDraggable/issueMilestoneKey/groupByMilestone bare-id-across-roots
  // defect class (all three caught late).
  function childKeyOf(issue) {
    return (issue.repo || "") + "::" + issue.parent;
  }

  function parentKeyOf(issue) {
    return (issue.repo || "") + "::" + issue.id;
  }

  // Numeric-aware id sort key -- the JS twin of cairn.py's _id_sort_key
  // (PT-2/PT-21). PT-25 names this a DRIFT PAIR (architect's ruling #4):
  // no shared-code seam exists across Python and JS in this stack, so the
  // same numeric-aware sort logic exists twice, by design; both sides are
  // tested against the SAME case list (PT-2 < PT-9 < PT-10,
  // tests/test_id_sort.py / tests/js/id-sort.test.js) so they cannot
  // silently diverge from each other. [prefix, number, full] -- falls
  // back to [full, -1, full] for anything that doesn't match
  // "<prefix>-<digits>", so a malformed id still sorts (just not
  // meaningfully) instead of throwing.
  var ID_SORT_RE = /^(.*?)-(\d+)$/;
  function idSortKey(id) {
    var s = id == null ? "" : String(id);
    var m = ID_SORT_RE.exec(s);
    if (m) return [m[1], parseInt(m[2], 10), s];
    return [s, -1, s];
  }

  function compareByIdSortKey(a, b) {
    var ka = idSortKey(a.id);
    var kb = idSortKey(b.id);
    if (ka[0] !== kb[0]) return ka[0] < kb[0] ? -1 : 1;
    if (ka[1] !== kb[1]) return ka[1] - kb[1];
    return ka[2] < kb[2] ? -1 : ka[2] > kb[2] ? 1 : 0;
  }

  // The child records belonging to `issue`, unsorted -- THE single
  // membership rule for "is this a child of that issue". childProgress
  // counts over it, childrenOf sorts it, so the badge and the drawer
  // list cannot disagree about which issues count (the standing
  // duplicated-inline-expression criterion: one shared function, never
  // two hand-maintained copies of the same predicate).
  function childRecords(issues, issue) {
    var key = parentKeyOf(issue);
    return (issues || []).filter(function (i) { return childKeyOf(i) === key; });
  }

  // {done, total} among `issue`'s own children -- the board's parent-card
  // n/m badge, computed client-side, mirroring milestoneProgress's
  // done/total-over-a-filtered-set shape (architect's PT-25 ruling #1).
  // /api/board already carries every issue's `parent` and `status`, so
  // the client has everything the badge needs; the server-side
  // sub_issue_count this replaces was a second answer to the same
  // question and has been removed.
  function childProgress(issues, issue) {
    var kids = childRecords(issues, issue);
    var done = kids.filter(function (i) { return i.status === "done"; }).length;
    return { done: done, total: kids.length };
  }

  // `issue`'s own children (full records), sorted numerically by id
  // (idSortKey) -- the drawer's children list. Same repo-scoped key as
  // childProgress, so the two can never disagree on which issues count
  // as `issue`'s children.
  function childrenOf(issues, issue) {
    return childRecords(issues, issue).sort(compareByIdSortKey);
  }

  return {
    primaryRootId: primaryRootId,
    milestoneLabel: milestoneLabel,
    milestoneMajor: milestoneMajor,
    dedupeMajorIds: dedupeMajorIds,
    milestoneProgress: milestoneProgress,
    issueMilestoneKey: issueMilestoneKey,
    uniqueMilestoneKeys: uniqueMilestoneKeys,
    primaryMilestones: primaryMilestones,
    isDraggable: isDraggable,
    orderRoots: orderRoots,
    laneStateKey: laneStateKey,
    uniqueSorted: uniqueSorted,
    groupByMilestone: groupByMilestone,
    idSortKey: idSortKey,
    childProgress: childProgress,
    childrenOf: childrenOf,
  };
})();
