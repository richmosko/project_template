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
    var seen = {};
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
  function laneStateKey(repoId, milestoneKey) {
    return repoId + "::" + milestoneKey;
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
  };
})();
