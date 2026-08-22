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
  // purely in-memory (PT-29: state.expandedLanes), never a DOM attribute value
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

  // PT-26: renamed from PT-25's parentKeyOf (architect's ruling #4). Its
  // body was never parent-specific -- it's the issue's own repo-scoped
  // identity key -- and PT-26's blockersOf/blocksOf need exactly this
  // same key. A second, identically-bodied key function (a "blockerKeyOf")
  // would have been the fifth instance of the isDraggable/
  // issueMilestoneKey/groupByMilestone/childProgress bare-id-across-roots
  // defect class.
  function issueKeyOf(issue) {
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
    var key = issueKeyOf(issue);
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

  // PT-26: the blocker records named in `issue.blocked_by`, sorted
  // numerically by id. Repo-scoped from the FIRST line: `blocked_by`
  // entries are same-root-only by construction (TRACKER.md § Dependencies
  // -- `cairn check` runs per-root, so a cross-root ref could never be
  // validated), so `issue`'s own repo is the correct scope for every ref
  // in its list -- never a bare-id lookup across the aggregated multi-root
  // payload. `wanted` uses Object.create(null), same reasoning as
  // uniqueSorted/dedupeMajorIds/groupByMilestone: a blocked_by ref shaped
  // like "constructor" must not silently match or miss via an inherited
  // Object.prototype member.
  function blockersOf(issues, issue) {
    var repo = issue.repo || "";
    var key = issueKeyOf(issue);
    // Resolve `issue`'s OWN record from `issues` rather than trusting a
    // `blocked_by` field on the passed-in `issue` object -- callers may
    // pass a minimal {id, repo} stub (e.g. a stale card re-render before
    // the next /api/board poll lands the full record); the full board
    // payload in `issues` is the source of truth for what blocks it.
    var self_ = (issues || []).filter(function (i) { return issueKeyOf(i) === key; })[0];
    var refs = (self_ && self_.blocked_by) || issue.blocked_by || [];
    var wanted = Object.create(null);
    refs.forEach(function (ref) { wanted[repo + "::" + ref] = true; });
    return (issues || [])
      .filter(function (i) { return wanted[issueKeyOf(i)]; })
      .sort(compareByIdSortKey);
  }

  // The reverse lookup -- every issue that names `issue`'s id in ITS OWN
  // blocked_by, sorted numerically by id. Repo-scoped the same way
  // blockersOf is: a candidate blocker's blocked_by ref only ever
  // resolves within ITS OWN repo, so the candidate must share `issue`'s
  // repo to be considered at all -- same-repo comparison, not a bare-id
  // match across roots.
  function blocksOf(issues, issue) {
    var key = issueKeyOf(issue);
    return (issues || [])
      .filter(function (i) {
        var repo = i.repo || "";
        var refs = i.blocked_by || [];
        for (var j = 0; j < refs.length; j++) {
          if (repo + "::" + refs[j] === key) return true;
        }
        return false;
      })
      .sort(compareByIdSortKey);
  }

  // The OPEN subset of blockersOf's list -- not done, not cancelled. The
  // board's card chip and its count derive from THIS list, never a
  // parallel filter (the F1 correction from PT-25's review, applied
  // before the fact rather than after) -- so the chip can never disagree
  // with what the drawer's own "Blocked by" section marks as open.
  function openBlockers(issues, issue) {
    return blockersOf(issues, issue).filter(function (i) {
      return i.status !== "done" && i.status !== "cancelled";
    });
  }

  // PT-29: the board-column order laneSummary iterates, and (unchanged)
  // makeColumn's own column set -- relocated from board.js verbatim as
  // the single canonical copy (architect's ruling § 4): a second,
  // board.js-local copy of this exact list would be the drift class
  // PT-22's extraction pass exists to close.
  var BOARD_COLUMNS = ["backlog", "todo", "in-progress", "in-review", "done"];

  // PT-29 (architect's ruling § 2): the SINGLE read path for
  // state.expandedLanes. Absence of `stateKey` in `expandedMap` means
  // collapsed -- there is no second encoding of "closed" (see
  // nextExpandedLanes below) -- so this is a plain presence-and-truthy
  // check, never `expandedMap[stateKey] !== false` or similar.
  function laneExpanded(expandedMap, stateKey) {
    // Object.prototype.hasOwnProperty.call, not a bare truthy read of
    // expandedMap[stateKey] -- a stateKey shaped like "constructor" reads
    // as already-truthy on a bare `{}` via the inherited
    // Object.prototype.constructor function, before any key was ever
    // inserted. Own-property guard makes this safe on Object.create(null)
    // maps (the normal case) AND on a bare `{}` a caller might still pass.
    return !!(expandedMap && Object.prototype.hasOwnProperty.call(expandedMap, stateKey) && expandedMap[stateKey]);
  }

  // PT-29 (architect's ruling § 2): the SINGLE write path for
  // state.expandedLanes -- board.js does
  // `state.expandedLanes = nextExpandedLanes(state.expandedLanes, key)`
  // and never assigns into the map by hand. Returns a FRESH
  // `Object.create(null)` map (non-mutating: the "never store `false`"
  // invariant is only assertable from outside if a caller can compare the
  // input against the output). Toggling an absent key ADDS it; toggling a
  // present key DELETES it -- two encodings of "closed" (present-false vs
  // absent) is how the next reader gets it wrong, per the ruling.
  //
  // Object.create(null) here is insurance, not a live fix (architect's
  // ruling): every real caller builds `stateKey` via laneStateKey, whose
  // "<repo>::<milestone>" composite never collides with an
  // Object.prototype member name. Tested anyway (prototype-collision.test.js)
  // against a bare prototype-shaped key, because that's a property of
  // THIS function's own implementation, not of board.js's call sites.
  function nextExpandedLanes(expandedMap, stateKey) {
    var next = Object.create(null);
    for (var key in expandedMap) {
      if (Object.prototype.hasOwnProperty.call(expandedMap, key)) next[key] = expandedMap[key];
    }
    if (laneExpanded(expandedMap, stateKey)) {
      delete next[stateKey];
    } else {
      next[stateKey] = true;
    }
    return next;
  }

  // PT-29 (architect's ruling § 3): the exact filled-triangle codepoints
  // -- `▼` U+25BC (expanded) / `▶` U+25B6 (collapsed) -- NOT the thin
  // `▾`/`▸` (U+25BE/U+25B8) PT-16 originally shipped. The token reports
  // *state*, not the action; callers still write their own
  // "Expand "/"Collapse " aria-label text.
  function disclosureToken(expanded) {
    return expanded ? "▼" : "▶";
  }

  // PT-29 (architect's ruling § 1/4): the collapsed-card status-breakdown
  // -- `{ total, byStatus: [{status, count}] }`. `total` is
  // `issues.length`, unchanged from the pre-existing `.swimlane-count`
  // semantics. `byStatus` iterates BOARD_COLUMNS in order and OMITS a
  // zero-count status entirely (never a `{status, count: 0}` entry) --
  // an issue whose status isn't one of BOARD_COLUMNS still counts toward
  // `total` but contributes no byStatus entry (QA's pinned contract,
  // 2026-08-22: byStatus enumerates known columns only, it does not
  // discover statuses from the data).
  function laneSummary(issues) {
    var list = issues || [];
    var counts = Object.create(null);
    list.forEach(function (issue) {
      var status = issue.status;
      if (counts[status] === undefined) counts[status] = 0;
      counts[status] += 1;
    });
    var byStatus = [];
    BOARD_COLUMNS.forEach(function (status) {
      var count = counts[status] || 0;
      if (count > 0) byStatus.push({ status: status, count: count });
    });
    return { total: list.length, byStatus: byStatus };
  }

  // PT-30 (architect's ruling § 5): schema constants, exported so tests
  // assert the exact values the code uses rather than a copy of them.
  var VIEW_STATE_VERSION = 1;
  var VIEW_STATE_MAX_LANES = 500;

  // PT-30 (architect's ruling § 1/5): the localStorage key, namespaced by
  // the primary root id (§0's ruling: localStorage is scoped to ORIGIN,
  // not to project -- every board on the same port shares one bucket
  // without this). Deliberately does NOT guard a null primaryId -- yields
  // "cairn.board.expandedLanes.null", matching laneStateKey's documented
  // non-guarding convention rather than inventing a third one for absent
  // repo ids (ruling's noted tension: unlike laneStateKey's key, this
  // string IS user-visible in devtools -- consistency with the
  // neighbouring key builder wins anyway; revisit both together if ever
  // revisited).
  function viewStateKey(primaryId) {
    return "cairn.board.expandedLanes." + primaryId;
  }

  // PT-30 (architect's ruling § 1): serialize state.expandedLanes to the
  // v1 JSON shape -- an ARRAY of expanded keys, not the map. The map's
  // values are always `true` (PT-29's invariant: absence is the only
  // encoding of "closed"); serializing the map as an object would persist
  // a redundant value and reopen the door to a stored `false` coming back
  // from disk on the next load -- the exact second-encoding hazard PT-29
  // closed structurally. Own+truthy keys only -- the last line of defense
  // against ever writing that second encoding, not a blind trust of the
  // in-memory invariant. Sorted ascending so two sessions holding the same
  // set produce a byte-identical blob regardless of click order.
  function serializeExpandedLanes(map) {
    var lanes = [];
    for (var key in map) {
      if (Object.prototype.hasOwnProperty.call(map, key) && map[key]) lanes.push(key);
    }
    lanes.sort();
    return JSON.stringify({ v: VIEW_STATE_VERSION, lanes: lanes });
  }

  // PT-30 (architect's ruling § 1/2/5): parse a persisted blob back into an
  // expandedLanes-shaped map. THE highest-value function in this feature
  // (ruling's own words) -- it parses untrusted input that survives across
  // versions and is the one function a hostile or merely stale blob
  // reaches first. Its ONE contract: NEVER THROW, always return a usable
  // (possibly empty) Object.create(null) map -- a corrupt, foreign,
  // future/past-versioned, or oversized blob degrades to "nothing was ever
  // expanded", never a crash.
  //
  // No pruning against "live" lanes (ruling § 2) -- this function has no
  // notion of which lanes currently render; a key with no corresponding
  // lane is carried through inert (only ever read by laneExpanded for a
  // lane actually being rendered). Unknown `v` returns the empty map
  // (ruling: no forward-migration attempt) -- the caller is expected to
  // removeItem the stale-shaped key on next write. An oversized `lanes`
  // array (over VIEW_STATE_MAX_LANES) discards the WHOLE blob as corrupt
  // rather than truncating -- one comparison, no ordering metadata needed.
  function parseExpandedLanes(raw) {
    var out = Object.create(null);
    if (typeof raw !== "string" || raw === "") return out;
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      return out;
    }
    if (!parsed || typeof parsed !== "object") return out;
    if (parsed.v !== VIEW_STATE_VERSION) return out;
    var lanes = parsed.lanes;
    if (!Array.isArray(lanes)) return out;
    if (lanes.length > VIEW_STATE_MAX_LANES) return out;
    lanes.forEach(function (key) {
      if (typeof key === "string") out[key] = true;
    });
    return out;
  }

  // PT-30 (architect's ruling § 4/5): the pure half of "Expand all" --
  // unions `laneKeys` (the currently-RENDERED lane keys, per the ruling;
  // filter-hidden lanes are simply not in this list) into `map`. Additive
  // only: never removes a key, so a lane that's expanded but hidden by an
  // active filter keeps its state. Same non-mutating "fresh
  // Object.create(null) map" contract shape as nextExpandedLanes -- board.js
  // does `state.expandedLanes = expandAllLanes(state.expandedLanes, keys)`.
  function expandAllLanes(map, laneKeys) {
    var next = Object.create(null);
    for (var key in map) {
      if (Object.prototype.hasOwnProperty.call(map, key)) next[key] = map[key];
    }
    (laneKeys || []).forEach(function (key) { next[key] = true; });
    return next;
  }

  // PT-32 (architect's ruling § 5): the pull-down-to-refresh gesture's
  // constants, exported so tests assert the exact values the code uses.
  var PULL_THRESHOLD = 64;
  var PULL_MAX_OFFSET = 96;
  var PULL_RESISTANCE = 0.5;
  var PULL_MIN_SPINNER_MS = 400;

  // PT-32 (architect's ruling § 2/5): the arming state machine's phase
  // decision. DELIBERATELY input-agnostic -- consumes a pull DISTANCE, not
  // a touch event, so a trackpad `wheel` adapter (PT-33, deferred) can feed
  // this same function a synthesized deltaY later without a redesign
  // (touch-only scope, Mosko's ruling § 1). DELIBERATELY memoryless -- a
  // pure function of its CURRENT inputs only, no "was this armed a moment
  // ago" argument, which is what makes the no-latch rule (armed falling
  // back to pulling on retreat) a property of calling this twice with a
  // shrinking deltaY rather than something an internal flag could get
  // wrong. DELIBERATELY PARTIAL -- never returns "refreshing": that phase
  // is entered and left by promise resolution, the async caller's
  // business, not a synchronous decision. Do not "complete" the machine by
  // threading async state through this function.
  function pullPhase(input) {
    if (input.cancelled) return "idle";
    if (!input.atScrollTop) return "idle";
    if (input.deltaY <= 0) return "idle";
    if (input.deltaY < PULL_THRESHOLD) return "pulling";
    return "armed";
  }

  // PT-32 (architect's ruling § 2/5): the presentational pull-indicator
  // offset -- half finger speed (the rubber-band resistance feel), capped
  // at PULL_MAX_OFFSET, floored at 0 for an upward/zero deltaY. Purely
  // cosmetic -- does not feed back into pullPhase's decision -- but
  // computed by a pure function so the resistance/cap math is testable
  // without a DOM.
  function pullIndicatorOffset(deltaY) {
    return Math.min(Math.max(deltaY, 0) * PULL_RESISTANCE, PULL_MAX_OFFSET);
  }

  // PT-32 (architect's ruling § 4/5): the single home for the indicator's
  // three phase-copy strings, so board.js never hand-writes them at a
  // second call site. An unrecognized/idle phase (the indicator is hidden
  // entirely in "idle" -- board.js's own concern, not this function's)
  // returns an empty string rather than throwing.
  function pullIndicatorLabel(phase) {
    if (phase === "pulling") return "↓ Pull to refresh";
    if (phase === "armed") return "↑ Release to refresh";
    if (phase === "refreshing") return "↻ Refreshing…";
    return "";
  }

  // PT-32 (architect's ruling § 2/5): true when ANY cancel condition holds
  // -- each flag is independent, board.js is responsible for computing
  // every one of them (active card drag, the fixed-position-drawer trap,
  // multi-touch/pinch, a lane's horizontal swipe, an already-in-flight
  // refresh) and passing the union in as booleans, never re-deriving a
  // subset of them here.
  function shouldCancelPull(flags) {
    return !!(
      flags.cardDragActive ||
      flags.drawerOpen ||
      flags.multiTouch ||
      flags.horizontalDominant ||
      flags.refreshing
    );
  }

  // PT-32 (architect's micro-ruling, 2026-08-22 -- the § 4 boolean this
  // supersedes collapsed "confirmed unchanged" and "the request failed"
  // onto the same branch, so a real 503 toasted the most reassuring
  // message the board can show). refreshBoardSilently (board.js) resolves
  // to exactly one of these three strings and STILL NEVER REJECTS -- six
  // existing bare-statement call sites (setInterval, a focus listener,
  // etc.) discard the returned promise structurally, with nowhere to
  // attach a `.catch`; a rejection is the one thing they cannot ignore.
  // Exported as constants, not left as string literals independently
  // typed in board.js (the producer) and here (the consumer), because
  // refreshBoardSilently itself isn't reachable from node:test -- nothing
  // could otherwise catch the two copies drifting apart.
  var REFRESH_UPDATED = "updated";
  var REFRESH_UNCHANGED = "unchanged";
  var REFRESH_FAILED = "failed";

  // PT-32 (architect's micro-ruling § 3): the single home for the pull
  // gesture's post-refresh toast copy -- {message, isError}. The failure
  // copy has TWO clauses deliberately: "Refresh failed" alone answers the
  // wrong question (the user's real question is "is what I'm looking at
  // current?"), so it also states that the board is showing last-known
  // data, not something empty/partial/half-applied. An outcome that isn't
  // one of the three known constants maps to the SAME failed shape --
  // the opposite default from pullIndicatorLabel's "" for an unknown
  // phase, and deliberately so: an unknown phase means "show nothing", an
  // unknown outcome means "something went wrong and I can't characterise
  // it" -- defaulting an unrecognized state to a reassuring message is
  // exactly the defect this function exists to close, one level up.
  function pullRefreshToast(outcome) {
    if (outcome === REFRESH_UPDATED) return { message: "Board updated", isError: false };
    if (outcome === REFRESH_UNCHANGED) return { message: "Already up to date", isError: false };
    return { message: "Couldn't refresh — showing last known data", isError: true };
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
    blockersOf: blockersOf,
    blocksOf: blocksOf,
    openBlockers: openBlockers,
    BOARD_COLUMNS: BOARD_COLUMNS,
    laneExpanded: laneExpanded,
    nextExpandedLanes: nextExpandedLanes,
    disclosureToken: disclosureToken,
    laneSummary: laneSummary,
    VIEW_STATE_VERSION: VIEW_STATE_VERSION,
    VIEW_STATE_MAX_LANES: VIEW_STATE_MAX_LANES,
    viewStateKey: viewStateKey,
    serializeExpandedLanes: serializeExpandedLanes,
    parseExpandedLanes: parseExpandedLanes,
    expandAllLanes: expandAllLanes,
    PULL_THRESHOLD: PULL_THRESHOLD,
    PULL_MAX_OFFSET: PULL_MAX_OFFSET,
    PULL_RESISTANCE: PULL_RESISTANCE,
    PULL_MIN_SPINNER_MS: PULL_MIN_SPINNER_MS,
    pullPhase: pullPhase,
    pullIndicatorOffset: pullIndicatorOffset,
    pullIndicatorLabel: pullIndicatorLabel,
    shouldCancelPull: shouldCancelPull,
    REFRESH_UPDATED: REFRESH_UPDATED,
    REFRESH_UNCHANGED: REFRESH_UNCHANGED,
    REFRESH_FAILED: REFRESH_FAILED,
    pullRefreshToast: pullRefreshToast,
  };
})();
