// board.js — cairn board. Vanilla JS, no framework, no CDN, works offline.
//
// Talks to the four endpoints described in process/TRACKER.md:
//   GET  /api/board          full board state (majors, milestones, issues)
//   GET  /api/issue/<id>     one issue: description, acceptance criteria, comments, seen
//   POST /api/issue          create
//   POST /api/issue/<id>     mutate: {seen, patch?, comment?}
//
// Phase-1 scope only — see process/TRACKER.md § Board — phase 1 scope.

(function () {
  "use strict";

  // PT-22: pure logic lives in board-logic.js (loaded before this file --
  // see board.html), reached as the CairnLogic global. Destructuring at
  // the top rather than calling CairnLogic.xxx() at every use site means
  // (a) call sites stay exactly as short as they were pre-extraction, and
  // (b) a load-order mistake (board-logic.js missing, or loaded after
  // this file) throws a ReferenceError right here, at parse/init time,
  // instead of silently producing `undefined` deep inside a render pass.
  var primaryRootId = CairnLogic.primaryRootId;
  var milestoneLabel = CairnLogic.milestoneLabel;
  var milestoneMajor = CairnLogic.milestoneMajor;
  var dedupeMajorIds = CairnLogic.dedupeMajorIds;
  var milestoneProgress = CairnLogic.milestoneProgress;
  var issueMilestoneKey = CairnLogic.issueMilestoneKey;
  var uniqueMilestoneKeys = CairnLogic.uniqueMilestoneKeys;
  var primaryMilestones = CairnLogic.primaryMilestones;
  var isDraggable = CairnLogic.isDraggable;
  var orderRoots = CairnLogic.orderRoots;
  var laneStateKey = CairnLogic.laneStateKey;
  var uniqueSorted = CairnLogic.uniqueSorted;
  var groupByMilestone = CairnLogic.groupByMilestone;
  var childProgress = CairnLogic.childProgress;
  var childrenOf = CairnLogic.childrenOf;
  var blockersOf = CairnLogic.blockersOf;
  var blocksOf = CairnLogic.blocksOf;
  var openBlockers = CairnLogic.openBlockers;
  // PT-37: STATUS_LABELS/statusLabel relocated into board-logic.js -- same
  // move PT-29 made for BOARD_COLUMNS below, and for the same reason: the
  // column header (:627) and the collapsed-lane chip (:767) had drifted to
  // different fallback behaviour for an unknown status because each held
  // its own copy of this lookup. One map, one fallback-safe accessor, two
  // callers.
  var STATUS_LABELS = CairnLogic.STATUS_LABELS;
  var statusLabel = CairnLogic.statusLabel;
  // PT-40: RECORD_STATUS_LABELS' fallback-safe accessor -- a SEPARATE
  // vocabulary from statusLabel/STATUS_LABELS above (milestone/major
  // lifecycle, not issue lifecycle). Never folded together -- see
  // RECORD_STATUS_LABELS' own comment in board-logic.js.
  var recordStatusLabel = CairnLogic.recordStatusLabel;
  // PT-51: the record drawer's status <select> option list (mirrors
  // STATUS_LABELS' role for the issue drawer, line above) -- Object.keys
  // order is this dict's own insertion order (board-logic.js), not
  // re-sorted here.
  var RECORD_STATUS_LABELS = CairnLogic.RECORD_STATUS_LABELS;
  // PT-44: releaseChipLabel (the release chip's shared text formatter)
  // and appendMilestoneOnlyLanes (the "a lane for every milestone" fix)
  // -- both board-logic.js pure functions, board.js supplies the DOM.
  var releaseChipLabel = CairnLogic.releaseChipLabel;
  var appendMilestoneOnlyLanes = CairnLogic.appendMilestoneOnlyLanes;
  // PT-29: BOARD_COLUMNS relocated into board-logic.js (architect's
  // ruling § 4) as the single canonical column-order list. PT-35 (closing
  // review finding): the bare BOARD_COLUMNS alias that used to live here is
  // deleted -- board.js has no direct consumer left (columnsFor/laneSummary
  // both go through activeColumns()/boardColumns() now), and keeping the
  // alias around would let a future call site reach for the raw five-column
  // list and pass it where activeColumns() belongs, sailing straight past
  // laneSummary's Array.isArray guard (JC1 catches a MISSING columns
  // argument, not a WRONG one) and silently reproducing the undercount this
  // issue exists to fix.
  var laneExpanded = CairnLogic.laneExpanded;
  var nextExpandedLanes = CairnLogic.nextExpandedLanes;
  var disclosureToken = CairnLogic.disclosureToken;
  var laneSummary = CairnLogic.laneSummary;
  var boardColumns = CairnLogic.boardColumns;
  // PT-38 (architect's ruling § 4): resolveColumns is the payload-columns
  // -> active-base-list step activeColumns() now threads through before
  // boardColumns's own Show-cancelled append -- see activeColumns() below.
  var resolveColumns = CairnLogic.resolveColumns;
  // PT-30: the localStorage schema's pure half -- board.js supplies the
  // three guarded primitives that actually touch the `localStorage`
  // global (readViewState/writeViewState/clearViewState, below); every
  // decision about the blob's shape lives in board-logic.js so it's
  // covered by the node:test suite without a DOM.
  var viewStateKey = CairnLogic.viewStateKey;
  var serializeExpandedLanes = CairnLogic.serializeExpandedLanes;
  var parseExpandedLanes = CairnLogic.parseExpandedLanes;
  var expandAllLanes = CairnLogic.expandAllLanes;
  // PT-32: the pull-down-to-refresh gesture's pure, input-agnostic half --
  // board.js supplies the touch listeners, the `passive: false`
  // registration, and the #pull-indicator DOM; every decision (arming,
  // resistance/cap math, copy, cancel predicate) lives in board-logic.js.
  var PULL_THRESHOLD = CairnLogic.PULL_THRESHOLD;
  var PULL_MIN_SPINNER_MS = CairnLogic.PULL_MIN_SPINNER_MS;
  var pullPhase = CairnLogic.pullPhase;
  var pullIndicatorOffset = CairnLogic.pullIndicatorOffset;
  var pullIndicatorLabel = CairnLogic.pullIndicatorLabel;
  var shouldCancelPull = CairnLogic.shouldCancelPull;
  // PT-32 (architect's micro-ruling): the three-state refresh outcome --
  // board.js is the ONLY producer of these constants (refreshBoardSilently,
  // below); board-logic.js's pullRefreshToast is their only consumer.
  // Importing rather than re-typing the string literals here is what makes
  // a future rename of any of the three break a test, since
  // refreshBoardSilently itself can't be reached from node:test.
  var REFRESH_UPDATED = CairnLogic.REFRESH_UPDATED;
  var REFRESH_UNCHANGED = CairnLogic.REFRESH_UNCHANGED;
  var REFRESH_FAILED = CairnLogic.REFRESH_FAILED;
  var pullRefreshToast = CairnLogic.pullRefreshToast;
  // PT-33 (architect's ruling @ e319208): the trackpad-overscroll wheel
  // adapter -- a new input feeding the SAME pullPhase machine above, not a
  // second one. WHEEL_PULL_IDLE_MS also doubles as the release signal (§3)
  // and the wheel handler's own idle-timer duration (see wirePullToRefresh).
  var WHEEL_PULL_IDLE_MS = CairnLogic.WHEEL_PULL_IDLE_MS;
  var wheelPullInitialState = CairnLogic.wheelPullInitialState;
  var wheelPullReduce = CairnLogic.wheelPullReduce;
  var wheelPullShouldFire = CairnLogic.wheelPullShouldFire;

  // PT-5: "" is the sentinel option value for a null priority — inlineSelect
  // translates it to/from JSON null at the DOM boundary (see inlineSelect).
  var PRIORITY_LABELS = {
    "": "(none)",
    "P0": "P0",
    "P1": "P1",
    "P2": "P2",
    "P3": "P3",
  };

  var isListView = window.location.pathname === "/list";

  // PT-55 (architect ruling § 3): computed once at module load, same
  // precedent as isListView above -- board.js embedded via PT-55's iframe
  // is loaded fresh each time (it's a real page load, not a client-side
  // route change), so there's no case where this needs to be re-derived
  // mid-session.
  var isEmbedMode = CairnLogic.isEmbedMode(window.location.search);

  var state = {
    board: null,       // last-known-good /api/board payload
    etag: null,
    currentMajor: "all",
    filters: { text: "", milestone: "", assignee: "", label: "", repo: "" },
    showCancelled: false,
    // PT-42: default off, in-memory only -- NOT persisted to localStorage
    // (matches showCancelled's own convention exactly, one view-toggle
    // pattern rather than two).
    showArchived: false,
    // PT-38: the pre-fetch default (first paint, before init()'s
    // apiGetBoard() resolves) -- overwritten once by payload.swimlane at
    // the initial load (see init()), then owned entirely by the
    // Swimlanes checkbox for the rest of the session.
    swimlanesOn: true,
    sortKey: "id",
    sortDir: 1,
    // PT-40 (joint PT-40/43/44 ruling § 5): generalized from openIssueId
    // (issue-only) to {kind, id} | null so a milestone/major card can
    // share the SAME open/close state and race-guard machinery as the
    // issue drawer -- one encoding of "what's open," not a parallel
    // openMilestoneId/openMajorId (the PT-29 polarity trap this ruling
    // explicitly calls out). kind is "issue" | "milestone" | "major".
    openRecord: null,
    // PT-29 (architect's ruling § 2, judgment call a): expandedLanes and
    // collapsedRepos have OPPOSITE polarity -- read that carefully before
    // touching either.
    //
    //   expandedLanes  -- opt-in-OPEN.  Absence of a key means collapsed;
    //                     presence (always `true`) means expanded. Milestone
    //                     lanes default-collapse (this feature's ask), so
    //                     a lane key that doesn't exist yet -- first paint,
    //                     or one a filter change/poll just revealed -- must
    //                     read as collapsed for free, which absence-means-
    //                     collapsed gives structurally. The SINGLE read/
    //                     write path is CairnLogic.laneExpanded /
    //                     nextExpandedLanes (board-logic.js) -- board.js
    //                     must never read/write this map by hand.
    //   collapsedRepos -- opt-in-CLOSED, unchanged from PT-3. Absence means
    //                     expanded; presence means collapsed. Repo sections
    //                     do NOT default-collapse -- collapsing a repo by
    //                     default would hide its milestone headers too, one
    //                     level further in than this feature asks for.
    //
    // This asymmetry is deliberate (not an oversight to "harmonise") --
    // reversal, if ever wanted: flip repoSectionEl's read/write and rename
    // to expandedRepos. Both maps are Object.create(null): a real fix for
    // collapsedRepos (bare root.id keys collide with Object.prototype
    // members, the PT-23 class); insurance only for expandedLanes (its
    // keys are always "<repo>::<milestone>" composites via laneStateKey,
    // and no Object.prototype member contains "::").
    //
    // PT-30: expandedLanes is now the ONE piece of board state that
    // survives a reload -- every toggle/expand-all/collapse-all persists
    // it to localStorage (persistExpandedLanes, below), guarded so a
    // storage failure degrades silently to this feature's pre-PT-30,
    // purely-in-memory behavior. collapsedRepos remains UNPERSISTED,
    // deliberately (architect's ruling § 3): it has the opposite polarity,
    // repo sections don't default-collapse so there's no N-clicks problem
    // to solve for them, and a persisted collapsed repo's failure mode --
    // an entire repo silently reduced to one header row next session -- is
    // worse than a lane's. No server-side change either way: still no
    // disk write, no network call, on any toggle.
    expandedLanes: Object.create(null),
    collapsedRepos: Object.create(null),
    // PT-30: set true the first time state.board lands after a fresh page
    // load, so the localStorage restore (which needs primaryRootId(board),
    // and therefore can't happen before the board arrives) runs EXACTLY
    // ONCE, from the board-load path -- never from renderKanban, which
    // runs on every refresh/poll/toggle and would otherwise stomp a
    // same-session toggle back to the stored value the instant the user
    // made it (architect's ruling § 2).
    viewStateRestored: false,
    // PT-30: the repo-scoped lane keys the MOST RECENT renderKanban() pass
    // actually rendered a .swimlane for -- populated at the same call
    // sites that decide whether to call milestoneLaneEl at all (so it
    // naturally respects the active filters and collapsedRepos), read by
    // the Expand-all button so it unions exactly what's visible, never a
    // parallel reconstruction of the grouping rules (the "universe
    // builder" duplication the ruling warns against in § 2).
    renderedLaneKeys: [],
    // PT-32 (architect's ruling § 2): cancel-condition inputs for
    // shouldCancelPull (board-logic.js). cardDragActive is set/cleared at
    // cardEl's dragstart/dragend, the same two call sites that already
    // toggle the .dragging class -- one fact, not a DOM query inferring
    // it later. pullRefreshing gates re-entrancy (no stacking repeated
    // pulls while one is already in flight) and also drives the
    // indicator's "refreshing" phase, which pullPhase itself can never
    // return (it's async-entered -- see runPullRefresh, below).
    cardDragActive: false,
    pullRefreshing: false,
  };

  // ------------------------------------------------------------------
  // API
  // ------------------------------------------------------------------

  function apiGetBoard() {
    var headers = {};
    if (state.etag) headers["If-None-Match"] = state.etag;
    // PT-42: ?archived=1 is the ONLY accepted spelling server-side --
    // appended only when the toggle is actually on, so the default
    // request stays byte-identical to pre-PT-42 (AC2). The etag-clear
    // that must accompany a showArchived flip lives at the TOGGLE site
    // (the #filter-archived listener below), not here -- by the time
    // apiGetBoard runs, state.etag is already correct for whichever
    // shape state.showArchived currently says.
    var url = state.showArchived ? "/api/board?archived=1" : "/api/board";
    return fetch(url, { headers: headers }).then(function (resp) {
      if (resp.status === 304) return null;
      // PT-32 (architect's micro-ruling § 4, ratified prerequisite for the
      // three-state refresh outcome): without this, a non-2xx response
      // with a well-formed JSON error body would parse successfully and
      // get assigned to state.board, rendering the error object as if it
      // were the board -- the observed 503 only reached refreshBoardSilently's
      // .catch by luck, because its body happened not to be valid JSON.
      // Scope note: this also changes behaviour for the poll/SSE/focus
      // paths, not just the pull gesture -- a non-ok response that used to
      // be parsed and applied is now caught and discarded, leaving the
      // last-known-good board on screen, which is the correct outcome.
      if (!resp.ok) throw new Error("board fetch failed: " + resp.status);
      var etag = resp.headers.get("ETag");
      return resp.json().then(function (data) {
        state.etag = etag;
        return data;
      });
    });
  }

  function apiGetIssue(id) {
    return fetch("/api/issue/" + encodeURIComponent(id)).then(function (resp) {
      if (!resp.ok) throw new Error("not found");
      return resp.json();
    });
  }

  function apiCreateIssue(payload) {
    return fetch("/api/issue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (resp) { return resp.json(); });
  }

  function apiMutateIssue(id, payload) {
    return fetch("/api/issue/" + encodeURIComponent(id), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    });
  }

  // PT-51 §1: the milestone/major sibling of apiMutateIssue -- identical
  // shape, posts to the NEW /api/record/<id> endpoint (never a widening
  // of /api/issue/<id> -- see cairn.py's find_record_path docstring for
  // why that separation is structural).
  function apiMutateRecord(id, payload) {
    return fetch("/api/record/" + encodeURIComponent(id), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    });
  }

  // ------------------------------------------------------------------
  // Toast
  // ------------------------------------------------------------------

  var toastTimer = null;
  function showToast(message, isError) {
    var el = document.getElementById("toast");
    el.textContent = message;
    el.classList.toggle("error", !!isError);
    el.classList.add("visible");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("visible"); }, 3500);
  }

  // ------------------------------------------------------------------
  // PT-30: view-state persistence (localStorage)
  //
  // Precedent copied deliberately from docs/_assets/toc.js's theme
  // toggle -- the only prior `localStorage` use in this repo, and it does
  // guarded storage correctly: the `localStorage` global reference itself
  // lives INSIDE each `try`, never hoisted to a module-level `var`, since
  // merely TOUCHING `localStorage` throws in some blocked-cookie/private-
  // mode configurations -- a top-level reference would take the whole
  // board down on load instead of degrading. No `storageAvailable` cached
  // flag either (architect's ruling § 5): silent per-call degradation is
  // enough, and a cached flag is state that can itself go stale.
  // ------------------------------------------------------------------

  function readViewState(key) {
    try {
      return localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function writeViewState(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (e) {
      // Private mode, blocked storage, quota exceeded -- degrade silently
      // to this feature's pre-PT-30 purely-in-memory behavior. The toggle
      // that triggered this write has already applied to state.expandedLanes
      // and already rendered; only the NEXT reload fails to remember it.
    }
  }

  function clearViewState(key) {
    try {
      localStorage.removeItem(key);
    } catch (e) {
      // Same degrade-silently contract as writeViewState.
    }
  }

  // The SINGLE write-then-persist path for every toggle that mutates
  // state.expandedLanes -- computes the repo-scoped storage key itself
  // (viewStateKey needs primaryRootId(state.board), so this can't run
  // before a board exists) and serializes the CURRENT map, whatever it is
  // at call time. Callers assign state.expandedLanes first, then call
  // this -- it never mutates state itself.
  function persistExpandedLanes() {
    if (!state.board) return;
    var key = viewStateKey(primaryRootId(state.board));
    // PT-30 (empty-state invariant, ruled in during diff review @ ef5ae9f):
    // clearViewState, not writeViewState("...lanes\":[]}"), when the map is
    // empty -- collapsing the very last expanded lane one at a time
    // (as opposed to the Collapse-all button, which already removeItem's)
    // would otherwise leave an empty-lanes blob on disk. Without this, "the
    // storage key exists" stops meaning "at least one lane is expanded" --
    // exactly the two-encodings-of-the-same-state hazard PT-29's
    // absence-means-collapsed invariant exists to prevent, one layer down
    // at the persistence boundary instead of the in-memory map.
    if (Object.keys(state.expandedLanes).length === 0) {
      clearViewState(key);
      return;
    }
    writeViewState(key, serializeExpandedLanes(state.expandedLanes));
  }

  // Fires exactly once, from the board-load path (init's first
  // apiGetBoard().then, below) -- never from renderKanban, which runs on
  // every refresh/poll/toggle and would otherwise overwrite a same-session
  // toggle with the stored value the instant the user made it (architect's
  // ruling § 2). parseExpandedLanes never throws and degrades a corrupt/
  // foreign/oversized blob to the empty map on its own, so there is
  // nothing else to guard here.
  //
  // PT-30 (restore-flag ordering, ruled in during diff review @ ef5ae9f):
  // state.viewStateRestored is set AFTER the `!state.board` guard, not
  // before it -- setting it first was only accidentally safe (it happened
  // to work because apiGetBoard's resolution always assigns state.board
  // before calling this), not structurally guaranteed by this function's
  // own body. A null/falsy first payload would otherwise mark the restore
  // as "done" without ever having attempted it, permanently skipping a
  // legitimate later restore.
  function restoreViewStateOnce() {
    if (state.viewStateRestored) return;
    if (!state.board) return;
    state.viewStateRestored = true;
    var raw = readViewState(viewStateKey(primaryRootId(state.board)));
    state.expandedLanes = parseExpandedLanes(raw);
  }

  // ------------------------------------------------------------------
  // Filtering
  // ------------------------------------------------------------------

  function filteredIssues() {
    if (!state.board) return [];
    var f = state.filters;
    var text = f.text.trim().toLowerCase();
    return state.board.issues.filter(function (issue) {
      if (!state.showCancelled && issue.status === "cancelled") return false;
      if (state.currentMajor !== "all") {
        // PT-22: milestoneMajor (board-logic.js) does the repo-scoped
        // lookup; the comparison against the selected tab is a bare-id
        // union across repos (team-lead ruling -- majors are a
        // portfolio-wide concept in this template's versioning
        // convention, unlike milestones). "The union changes only the
        // final id comparison, the lookup stays repo-qualified."
        var major = milestoneMajor(state.board, issue.milestone, issue.repo);
        if (major !== state.currentMajor) return false;
      }
      // PT-22: issueMilestoneKey (board-logic.js) is the SAME function
      // the filter-milestone select's option builder calls (see
      // renderHeader) -- one shared "repo::milestone" key, not two
      // independently hand-written expressions that must happen to agree.
      if (f.milestone && issueMilestoneKey(issue) !== f.milestone) return false;
      if (f.assignee && issue.assignee !== f.assignee) return false;
      if (f.label && (issue.labels || []).indexOf(f.label) === -1) return false;
      if (f.repo && issue.repo !== f.repo) return false;
      if (text) {
        var hay = (issue.id + " " + issue.title).toLowerCase();
        if (hay.indexOf(text) === -1) return false;
      }
      return true;
    });
  }

  // ------------------------------------------------------------------
  // Header: major tabs, milestone progress, filter option lists
  // ------------------------------------------------------------------

  function renderHeader() {
    var board = state.board;
    if (!board) return;

    var multiRoot = (board.roots || []).length > 1;
    var primaryId = primaryRootId(board);

    var majorsTabs = document.getElementById("majors-tabs");
    majorsTabs.innerHTML = "";
    var allBtn = document.createElement("button");
    allBtn.textContent = "All";
    allBtn.className = state.currentMajor === "all" ? "active" : "";
    allBtn.onclick = function () { state.currentMajor = "all"; render(); };
    majorsTabs.appendChild(allBtn);
    // PT-3: majors aren't repo-qualified in this template's versioning
    // convention (every repo's founding major is typically V1, per
    // TRACKER.md), so the VISIBLE tab bar dedupes by bare id -- one "V1"
    // button, first-seen order, not one per repo. A tab filters across
    // every repo (union); issues still render inside their own repo
    // section. Internal lookups (milestoneMajor, filteredIssues) stay
    // repo-scoped -- only this dedupe/comparison is at the bare-id level
    // (team-lead ruling, 2026-08-21). PT-22: dedupeMajorIds (board-logic.js).
    dedupeMajorIds(board.majors).forEach(function (majorId) {
      var btn = document.createElement("button");
      btn.className = state.currentMajor === majorId ? "active" : "";
      // PT-40 (ruling § 6): a status dot, colour via the SAME
      // recordStatusLabel/RECORD_STATUS_LABELS vocabulary the card uses --
      // no room for text on a tab, so the label lives in title/aria-label
      // instead. First matching record wins on a dedupe collision (rare,
      // multi-root only -- not special-cased further, same posture the
      // ruling takes for the card itself).
      var majorRecord = (board.majors || []).filter(function (m) { return m.id === majorId; })[0];
      if (majorRecord) {
        var dot = document.createElement("span");
        dot.className = "major-status-dot";
        dot.dataset.status = majorRecord.status;
        dot.title = recordStatusLabel(majorRecord.status);
        dot.setAttribute("aria-hidden", "true");
        btn.appendChild(dot);
      }
      // PT-48: same "no room for text on a tab" constraint the status dot
      // above already lives with -- an archived major gets the muted class
      // the issue card's own .is-archived treatment uses (opacity, not a
      // second dot vocabulary), plus a title for the a11y label the dot's
      // own aria-hidden span doesn't carry. A SEPARATE statement from the
      // className ternary above (not folded in) -- see record-drawer-
      // client.test.js's PT-40 regression guard for why.
      if (majorRecord && majorRecord.archived) {
        btn.className += " is-archived";
        btn.title = majorId + " (archived)";
      }
      btn.appendChild(document.createTextNode(majorId));
      // Tab click still means "filter" -- unchanged.
      btn.onclick = function () { state.currentMajor = majorId; render(); };
      majorsTabs.appendChild(btn);

      // PT-40 (ruling § 6): a SIBLING open button, not nested -- a
      // <button> inside a <button> is invalid HTML. Appended directly
      // into #majors-tabs right after its tab, same flex container.
      var openBtn = document.createElement("button");
      openBtn.type = "button";
      openBtn.className = "major-tab-open";
      openBtn.textContent = "▸";
      openBtn.setAttribute("aria-label", "Open " + majorId);
      openBtn.onclick = function (e) {
        e.stopPropagation();
        openRecordDrawer("major", majorId);
      };
      majorsTabs.appendChild(openBtn);
    });

    document.getElementById("tab-kanban").className = isListView ? "" : "active";
    document.getElementById("tab-list").className = isListView ? "active" : "";

    // PT-44 §7: the top progress strip's population block used to live
    // here. Retired -- its content (id · name · GA · target_tag · n/m done) is
    // now on the milestone's own lane header (PT-40) and card, with the
    // lane-for-every-milestone fix (§2, below) covering the strip's old
    // filter (`progress.total === 0 && ms.kind !== "product"`, gone with
    // it -- an issue-less milestone gets a real lane instead of being
    // silently dropped). milestoneProgress itself is UNCHANGED as a
    // function -- still the single producer, now with the §3 isComplete
    // branch (board-logic.js) -- only this strip-population call site is
    // gone.

    // PT-22: milestone ids collide across roots -- the filter value is
    // always a repo-qualified composite "<repo>::<milestone>" built by
    // uniqueMilestoneKeys (board-logic.js), the same function
    // filteredIssues' comparison calls via issueMilestoneKey -- one
    // shared invariant, not two hand-written expressions that must agree.
    var msPairs = uniqueMilestoneKeys(board.issues);
    populateSelect(
      "filter-milestone",
      msPairs.map(function (p) { return p.key; }),
      function (k) {
        var p = msPairs.filter(function (x) { return x.key === k; })[0];
        if (!p) return k;
        // PT-28: same redundancy as the progress-strip fix above -- with
        // self-qualifying milestone ids, prepending the repo id here read
        // "PT · PT-0.6 · ...", doubling PT. The filter VALUE (`k`, from
        // msPairs' repo-qualified key) still disambiguates correctly across
        // roots; only this display label drops the now-redundant prefix.
        var label = milestoneLabel(board, p.milestone, p.repo);
        return label;
      }
    );
    populateSelect("filter-assignee", uniqueSorted(board.issues.map(function (i) { return i.assignee; })));
    var labels = [];
    board.issues.forEach(function (i) { (i.labels || []).forEach(function (l) { labels.push(l); }); });
    populateSelect("filter-label", uniqueSorted(labels));

    // PT-3: repo filter -- client-side like every other filter (the API
    // stays at one read endpoint). Hidden entirely on a single-root board
    // so nothing changes visually for the overwhelming majority of setups.
    var repoFilterEl = document.getElementById("filter-repo");
    var roots = board.roots || [];
    if (multiRoot) {
      repoFilterEl.hidden = false;
      var repoLabelFor = function (v) {
        var root = roots.filter(function (r) { return r.id === v; })[0];
        return root ? root.id + " · " + root.label : v;
      };
      populateSelect("filter-repo", roots.map(function (r) { return r.id; }), repoLabelFor);
    } else {
      repoFilterEl.hidden = true;
      if (state.filters.repo) { state.filters.repo = ""; repoFilterEl.value = ""; }
    }

    // PT-30 (architect's ruling § 4; gap found in diff review @ ef5ae9f):
    // hidden, not disabled, when Swimlanes is off OR in list view -- no
    // lanes exist for either button to act on in either case. `/` and
    // `/list` serve the same board.html, and renderHeader runs in both, so
    // without the isListView guard both buttons showed on the list screen,
    // where state.renderedLaneKeys is permanently empty: Expand-all would
    // silently no-op, but Collapse-all would still destructively clear the
    // persisted view state from a screen with no lanes to show for it.
    // `filter-repo` above already establishes the toggle-the-hidden-
    // attribute precedent in this same function.
    var expandAllBtn = document.getElementById("expand-all-btn");
    var collapseAllBtn = document.getElementById("collapse-all-btn");
    expandAllBtn.hidden = isListView || !state.swimlanesOn;
    collapseAllBtn.hidden = isListView || !state.swimlanesOn;

    // PT-3 (team-lead ruling, NON-NEGOTIABLE -- data integrity, not
    // cosmetics): creation always writes to the PRIMARY root only, so
    // this select must offer PRIMARY-root milestones exclusively. Ever
    // listing a foreign milestone id here would let a user create a
    // primary-root issue referencing a milestone that doesn't exist
    // there, which `cairn check` then reports as an unknown-milestone
    // lint error. All known primary milestones, not just ones already
    // carrying an issue -- a fresh milestone with zero issues yet should
    // still be choosable when creating the first one for it.
    // PT-22: primaryMilestones (board-logic.js) has the null-guard built
    // in (architect review, 2026-08-21) -- a payload with no `roots`/
    // `repo` dimension at all (stale cached board.js against an older
    // cairn serve) must not filter every milestone out via
    // `undefined === null`; treat "no repo dimension" as "everything is
    // the primary" rather than an empty, broken select.
    populateSelect(
      "new-issue-milestone",
      primaryMilestones(board.milestones, primaryId).map(function (m) { return m.id; }).sort(),
      function (v) { return milestoneLabel(board, v, primaryId); }
    );
  }

  function populateSelect(id, values, labelFor) {
    var el = document.getElementById(id);
    var current = el.value;
    var placeholder = el.options[0];
    el.innerHTML = "";
    el.appendChild(placeholder);
    values.forEach(function (v) {
      var opt = document.createElement("option");
      opt.value = v; // PT-16: label decorates, value stays the bare id
      opt.textContent = labelFor ? labelFor(v) : v;
      el.appendChild(opt);
    });
    el.value = current;
  }

  // ------------------------------------------------------------------
  // Kanban rendering
  // ------------------------------------------------------------------

  function cardEl(issue) {
    var card = document.createElement("div");
    card.className = "card";
    // PT-42: muted visual treatment for an archived card -- read-only on
    // the board (server-side 403 on mutation, isDraggable's own widening
    // below keeps it non-draggable), rendered in its ORIGINAL milestone
    // lane/status column, not a separate Archive lane (ruling § 3).
    if (issue.archived) card.className += " is-archived";
    // PT-3: a foreign-root card is not draggable -- UI courtesy only
    // (§3.3.2: "not the security boundary"), the server's 403
    // read_only_root is what actually enforces this. PT-22: isDraggable
    // (board-logic.js) is the SAME shared predicate handleDrop's refusal
    // guard calls below -- including its null-guard (architect review,
    // 2026-08-21: a payload with no `roots` dimension at all must read as
    // "everything is the primary", not "nothing is draggable").
    card.draggable = isDraggable(issue, primaryRootId(state.board));
    card.dataset.id = issue.id;
    card.addEventListener("dragstart", function (e) {
      card.classList.add("dragging");
      // PT-32 (architect's ruling § 2, cancel condition 2): a flag set at
      // the SAME two call sites that already toggle .dragging, not
      // inferred later by querying the DOM for it -- one fact, not two.
      state.cardDragActive = true;
      e.dataTransfer.setData("text/plain", issue.id);
    });
    card.addEventListener("dragend", function () {
      card.classList.remove("dragging");
      state.cardDragActive = false;
    });
    card.addEventListener("click", function () { openDrawer(issue.id); });

    var idEl = document.createElement("div");
    idEl.className = "card-id";
    idEl.textContent = issue.id;
    card.appendChild(idEl);

    var titleEl = document.createElement("div");
    titleEl.className = "card-title";
    titleEl.textContent = issue.title;
    card.appendChild(titleEl);

    var meta = document.createElement("div");
    meta.className = "card-meta";
    // PT-3: repo tag -- redundant with the repo-grouped section header
    // when roots.length > 1, but harmless, and it survives if a card is
    // ever shown outside its section (design note §3.3.1).
    if (state.board && state.board.roots && state.board.roots.length > 1) {
      meta.appendChild(chip("repo", issue.repo));
    }
    // PT-42: same chip() helper every other card badge uses -- not a
    // bespoke element for just this one, the "two independently-
    // duplicated expressions" drift class isDraggable's own PT-22 history
    // is the canonical example of.
    if (issue.archived) meta.appendChild(chip("archived", "archived"));
    if (issue.assignee) meta.appendChild(chip("assignee", issue.assignee));
    if (issue.milestone) meta.appendChild(chip("milestone", issue.milestone));
    (issue.labels || []).forEach(function (l) { meta.appendChild(chip("", l)); });
    // PT-25: the n/m child badge is computed client-side (childProgress,
    // board-logic.js), repo-scoped from the first line -- replaces the
    // removed server-side sub_issue_count, which was a second answer to
    // the same question.
    var progress = state.board ? childProgress(state.board.issues, issue) : { done: 0, total: 0 };
    if (progress.total > 0) meta.appendChild(chip("subissues", progress.done + "/" + progress.total));
    if (issue.parent) meta.appendChild(chip("subissues", "↳ " + issue.parent));
    // PT-26: the blocked chip appears only when OPEN blockers exist
    // (architect's ruling #4) -- an all-resolved blocked_by list is no
    // longer a live constraint, and flagging one anyway is noise on the
    // card, the scarcest surface. The reverse "blocks" list never appears
    // on cards at all -- drawer and `cairn show` only.
    var open = state.board ? openBlockers(state.board.issues, issue) : [];
    if (open.length > 0) meta.appendChild(chip("blocked", "⛔ " + open.length + " blocked"));
    card.appendChild(meta);

    return card;
  }

  function chip(cls, text) {
    var span = document.createElement("span");
    span.className = "chip" + (cls ? " " + cls : "");
    span.textContent = text;
    return span;
  }

  function makeColumn(status, issues) {
    var col = document.createElement("div");
    col.className = "column";
    col.dataset.status = status;

    var header = document.createElement("div");
    header.className = "column-header";
    // PT-37 (architect's review finding, F2): DOM-built via textContent,
    // not an innerHTML concat -- pre-fix, statusLabel's input was always a
    // hardcoded STATUS_LABELS value or undefined; post-fix (and once PT-38
    // lets a column's status come from config.yml) it can be arbitrary
    // free text from a hand-editable file. PT-20's ruling: free text from
    // a hand-editable file is DOM-built, never HTML-parsed, so it renders
    // literally instead of being interpreted as markup.
    var labelSpan = document.createElement("span");
    labelSpan.textContent = statusLabel(status);
    var countSpan = document.createElement("span");
    countSpan.textContent = issues.length;
    header.appendChild(labelSpan);
    header.appendChild(countSpan);
    col.appendChild(header);

    if (issues.length === 0) {
      var empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "—";
      col.appendChild(empty);
    }
    issues.forEach(function (issue) { col.appendChild(cardEl(issue)); });

    col.addEventListener("dragover", function (e) {
      e.preventDefault();
      col.classList.add("drop-target");
    });
    col.addEventListener("dragleave", function () { col.classList.remove("drop-target"); });
    col.addEventListener("drop", function (e) {
      e.preventDefault();
      col.classList.remove("drop-target");
      var id = e.dataTransfer.getData("text/plain");
      handleDrop(id, status);
    });

    return col;
  }

  // PT-35 (architect's ruling § 1): the SINGLE read path for the active
  // column set, same pattern PT-29 established for laneExpanded/
  // state.expandedLanes. A FUNCTION of state.showCancelled, not a
  // render-scoped cached variable (JC4) -- a `var activeColumns` assigned
  // once at the top of render() is one derivation today, but it is also a
  // stale-cache surface and a rule ("remember to set this at the top of
  // every render path") a new render path can quietly violate. Every one
  // of the five call sites below computes this SAME function of the SAME
  // input, so "counted iff rendered" holds by construction (AC2) rather
  // than as a convention someone has to keep re-deriving correctly.
  // PT-38 (architect's ruling § 4): now threads resolveColumns(payload
  // columns) as boardColumns's required first argument, instead of
  // boardColumns reading module-level BOARD_COLUMNS directly -- a
  // board-config'd column subset flows through the SAME single read path
  // every existing call site already goes through, no new call sites to
  // audit.
  function activeColumns() {
    return boardColumns(resolveColumns(state.board && state.board.columns), state.showCancelled);
  }

  function columnsFor(issues) {
    var columns = activeColumns();
    var wrap = document.createElement("div");
    wrap.className = "board";
    columns.forEach(function (status) {
      var subset = issues.filter(function (i) { return i.status === status; });
      wrap.appendChild(makeColumn(status, subset));
    });
    return wrap;
  }

  // PT-16, extracted for PT-3 (pure extraction -- zero behavior change),
  // rewired for PT-29 (architect's ruling, sections 1/2/3): one milestone
  // swimlane -- id·name label (milestoneLabel falls back to the bare key
  // for "(none)" and any dangling milestone id -- no special-casing
  // needed) + a per-lane disclosure toggle, default-COLLAPSED (absence in
  // state.expandedLanes). `.swimlane` IS the containing card now -- no new
  // wrapper element; `is-collapsed` only tightens CSS padding, it drives
  // no JS branch. Collapse state lives only in state.expandedLanes
  // (in-memory) -- never written to disk, no network call fires on toggle.
  function milestoneLaneEl(board, key, issues, stateKey, repoId, laneId) {
    var lane = document.createElement("div");
    lane.className = "swimlane";

    // PT-3 (architect amendment b): `stateKey` is always an explicit,
    // repo-qualified composite ("<root.id>::<milestone key>") -- every
    // caller passes one, single-root included. There are no JS tests and
    // collapse keys never appear in the DOM, so there was nothing to gain
    // from keeping the old bare-id shape as a conditional special case:
    // one read/write path beats two that have to stay in sync.
    //
    // PT-29: laneExpanded is the SINGLE read path (board-logic.js) --
    // never `state.expandedLanes[stateKey]` read directly here.
    var expanded = laneExpanded(state.expandedLanes, stateKey);
    lane.classList.toggle("is-collapsed", !expanded);
    var laneHeader = document.createElement("div");
    laneHeader.className = "swimlane-header";

    var toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "swimlane-toggle";
    // PT-29: disclosureToken reports STATE (▼ shown / ▶ hidden); the
    // aria-label keeps reporting the ACTION a click would take.
    toggleBtn.textContent = disclosureToken(expanded);
    toggleBtn.setAttribute("aria-label", (expanded ? "Collapse " : "Expand ") + key);
    toggleBtn.setAttribute("aria-expanded", expanded ? "true" : "false");
    // PT-31 (architect's triage ruling, item 3): aria-controls ONLY when
    // expanded -- the disclosed .board is not in the DOM when collapsed
    // (that's the whole point of the roll-up), so pointing aria-controls
    // at an id that doesn't exist half the time is worse than omitting
    // it. laneId is computed by the CALLER (renderKanban/repoSectionEl),
    // the same call sites that already compute stateKey -- never derived
    // a second way in here.
    if (expanded) toggleBtn.setAttribute("aria-controls", laneId);
    toggleBtn.addEventListener("click", function () {
      // PT-29: nextExpandedLanes is the SINGLE write path -- non-mutating,
      // returns a fresh map; board.js never assigns into the map by hand.
      state.expandedLanes = nextExpandedLanes(state.expandedLanes, stateKey);
      // PT-30: persist AFTER the map is updated, BEFORE render -- render()
      // doesn't depend on the write's success either way (parseExpandedLanes/
      // writeViewState both degrade silently), but ordering it here keeps
      // "the toggle happened" and "we tried to remember it" next to each
      // other at the one call site that does both.
      persistExpandedLanes();
      render();
    });
    laneHeader.appendChild(toggleBtn);

    var labelSpan = document.createElement("span");
    labelSpan.className = "swimlane-label";
    labelSpan.textContent = milestoneLabel(board, key, repoId);
    // PT-40 (joint PT-40/43/44 ruling § 2's own wording: "Clicking the
    // label opens the milestone card"): minimal open affordance on the
    // EXISTING lane header, this loop -- the full lane-header rewrite
    // (every-milestone/empty lanes, GA/release chips, strip removal) is
    // PT-44's. Guarded against the "(none)" bucket (unmilestoned issues)
    // -- there is no record to open for it.
    if (key !== "(none)") {
      labelSpan.classList.add("swimlane-label-clickable");
      labelSpan.setAttribute("role", "button");
      labelSpan.setAttribute("tabindex", "0");
      labelSpan.addEventListener("click", function (e) {
        e.stopPropagation();
        openRecordDrawer("milestone", key, repoId);
      });
      // Architect's PT-40 approval finding: role="button" on a <span>
      // (not a real <button>, which synthesizes click from Enter/Space on
      // its own) needs its OWN keydown handler -- without this, Enter/
      // Space silently do nothing for a keyboard user, unlike the major
      // tab's open button (a real <button>, unaffected).
      labelSpan.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          e.stopPropagation();
          openRecordDrawer("milestone", key, repoId);
        }
      });
    }
    laneHeader.appendChild(labelSpan);

    // PT-44 (joint PT-40/43/44 ruling § 2/§3/§4): the retired strip's
    // content, now on the lane header itself -- status pill, progress
    // (n/m, or a checkmark with no ratio at all once the milestone's own
    // status is done/cancelled -- § 3's "decided by status, not by
    // counting archive/"), release chip, and the GA chip moved off its
    // old "· GA" text suffix. Only rendered when a real milestone record
    // is found for this lane (the "(none)" bucket, or a dangling id with
    // no matching record, has nothing to show here).
    var msRecord = (board.milestones || []).filter(function (m) {
      return m.id === key && m.repo === repoId;
    })[0];
    if (msRecord) {
      var statusChip = chip("status", recordStatusLabel(msRecord.status));
      statusChip.dataset.status = msRecord.status;
      laneHeader.appendChild(statusChip);

      var msProgress = milestoneProgress(board.issues, msRecord);
      laneHeader.appendChild(
        chip("progress", msProgress.isComplete ? "✓ Done" : (msProgress.done + "/" + msProgress.total))
      );

      var releaseText = releaseChipLabel(msRecord.released, msRecord.target_tag);
      if (releaseText !== null) {
        laneHeader.appendChild(chip("release", releaseText));
      }
      if (msRecord.ga) {
        laneHeader.appendChild(chip("ga", "GA"));
      }
      // PT-48: same chip("archived", "archived") treatment cardEl already
      // uses -- lane headers ignored the flag entirely before this.
      if (msRecord.archived) {
        laneHeader.appendChild(chip("archived", "archived"));
      }
    }

    // PT-31 (architect's triage ruling, item 1): ONE laneSummary call
    // backs both the header count and the collapsed chips, so they
    // cannot disagree by construction -- total is the sum of byStatus
    // (column-backed statuses only), not issues.length, since an issue
    // whose status has no active-column entry (e.g. "cancelled" when
    // Show-cancelled is off) renders in no column, expanded or collapsed.
    // PT-35 (ruling § 1/§6): activeColumns() threaded through explicitly --
    // laneSummary's columns argument is required (no default), so this
    // lane's count includes the sixth "cancelled" column exactly when the
    // board itself renders it.
    var summary = laneSummary(issues, activeColumns());
    var countSpan = document.createElement("span");
    countSpan.className = "swimlane-count";
    countSpan.textContent = summary.total;
    laneHeader.appendChild(countSpan);

    // PT-29 (architect's ruling § 1, judgment call): shown ONLY when
    // collapsed -- when expanded the columns below already carry these
    // numbers, so a second copy in the header would be noise. One chip
    // per non-empty status, board-column order (laneSummary,
    // board-logic.js) -- decides whether a collapsed lane is worth
    // opening without opening it.
    if (!expanded) {
      if (summary.byStatus.length) {
        var summaryEl = document.createElement("span");
        summaryEl.className = "swimlane-summary";
        summary.byStatus.forEach(function (entry) {
          summaryEl.appendChild(chip("", statusLabel(entry.status) + " · " + entry.count));
        });
        laneHeader.appendChild(summaryEl);
      }
    }

    lane.appendChild(laneHeader);
    if (expanded) {
      // PT-31 (item 3): the .board carrying laneId is what aria-controls
      // (above) points at -- rendered only here, never "always rendered
      // and hidden" (that would restore the wall of DOM PT-29 removed).
      var boardEl = columnsFor(issues);
      boardEl.id = laneId;
      lane.appendChild(boardEl);
    }
    return lane;
  }

  // PT-3: one repo section under repo-grouped multi-root view -- a
  // top-level collapse toggle (state.collapsedRepos, in-memory only --
  // PT-29: OPPOSITE polarity from state.expandedLanes, see the state
  // declaration comment) around either milestone lanes (Swimlanes
  // checkbox on -- reuses milestoneLaneEl unchanged, composite state key)
  // or a flat column board (Swimlanes checkbox off). Repo grouping itself
  // is NOT governed by the Swimlanes checkbox -- team-lead's ruling:
  // repo separation is the entire point of this view, so it stays on
  // regardless; the checkbox only decides whether milestone lanes
  // subdivide *within* a section.
  function repoSectionEl(board, root, issues) {
    var section = document.createElement("div");
    section.className = "repo-group";

    // PT-29: collapsedRepos keeps its PT-3 polarity (opt-in-closed) and
    // its direct-mutation read/write -- unlike expandedLanes, this map is
    // NOT default-collapsed by this feature (see the state.collapsedRepos
    // comment above), so there is no absence-means-collapsed contract to
    // route through a shared helper here.
    var collapsed = !!state.collapsedRepos[root.id];
    section.classList.toggle("is-collapsed", collapsed);
    var header = document.createElement("div");
    header.className = "repo-group-header";

    var toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "repo-group-toggle";
    // PT-29 (architect's ruling § 3, judgment call a): same filled-triangle
    // token as the milestone toggle -- disclosureToken takes "is expanded",
    // the inverse of this map's "is collapsed" polarity.
    toggleBtn.textContent = disclosureToken(!collapsed);
    toggleBtn.setAttribute("aria-label", (collapsed ? "Expand " : "Collapse ") + root.label);
    toggleBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggleBtn.addEventListener("click", function () {
      state.collapsedRepos[root.id] = !collapsed;
      render();
    });
    header.appendChild(toggleBtn);

    var labelSpan = document.createElement("span");
    labelSpan.className = "repo-group-label";
    labelSpan.textContent = root.label;
    header.appendChild(labelSpan);

    var idSpan = document.createElement("span");
    idSpan.className = "repo-group-id";
    idSpan.textContent = root.id;
    header.appendChild(idSpan);

    // PT-31 (architect's triage ruling, item 1): same fix as
    // milestoneLaneEl's swimlane-count -- laneSummary(issues, ...).total,
    // not issues.length, so this section's count also excludes issues
    // that render in no active column. PT-35: activeColumns() threaded
    // through the same way, so this count includes "cancelled" exactly
    // when Show-cancelled is on -- both the swimlane sub-path (above) and
    // this flat/repo-section sub-path get the sixth column identically.
    var countSpan = document.createElement("span");
    countSpan.className = "repo-group-count";
    countSpan.textContent = laneSummary(issues, activeColumns()).total;
    header.appendChild(countSpan);

    section.appendChild(header);

    if (!collapsed) {
      if (state.swimlanesOn) {
        var grouped = groupByMilestone(issues);
        // PT-44 § 2: "render a lane for every milestone" -- groupByMilestone
        // alone only produces a lane for a milestone with at least one
        // issue in `issues` (already major-tab-filtered by this point,
        // via filteredIssues). Milestones are filtered the SAME way here
        // (by state.currentMajor) so an issue-less milestone under the
        // active major still gets an empty lane; appendMilestoneOnlyLanes
        // itself scopes to root.id.
        var repoMilestonesForLanes = (board.milestones || []).filter(function (ms) {
          return state.currentMajor === "all" || ms.major === state.currentMajor;
        });
        grouped = appendMilestoneOnlyLanes(grouped.order, grouped.groups, repoMilestonesForLanes, root.id);
        grouped.order.forEach(function (key) {
          var stateKey = laneStateKey(root.id, key);
          // PT-31 (item 3): laneId computed at the call site, same
          // pattern as stateKey -- state.renderedLaneKeys.length is the
          // GLOBAL lane index across the whole render pass (reset once at
          // the top of renderKanban, pushed to at both this call site and
          // renderKanban's single-root branch), so it stays collision-
          // proof even if two different stateKeys sanitize to the same
          // string.
          var laneId = "lane-" + state.renderedLaneKeys.length + "-" + stateKey.replace(/[^A-Za-z0-9_-]/g, "-");
          section.appendChild(milestoneLaneEl(board, key, grouped.groups[key], stateKey, root.id, laneId));
          // PT-30: record every lane key actually rendered here -- Expand-all
          // reads state.renderedLaneKeys rather than reconstructing the
          // grouping rules itself (the ruling's "universe builder"
          // duplication warning). Naturally respects collapsedRepos: this
          // forEach doesn't run at all when the repo section is collapsed.
          state.renderedLaneKeys.push(stateKey);
        });
      } else {
        section.appendChild(columnsFor(issues));
      }
    }

    return section;
  }

  function renderKanban() {
    var board = state.board;
    var main = document.getElementById("main");
    main.innerHTML = "";
    var issues = filteredIssues();

    var roots = (board && board.roots) || [];

    // PT-30: reset at the top of every render pass -- repopulated below (and
    // inside repoSectionEl, for the multi-root branch) with exactly the
    // lane keys THIS pass actually rendered a .swimlane for. Stays empty in
    // Swimlanes-off mode (neither branch below reaches a milestoneLaneEl
    // call in that mode), which is what hides the Expand/Collapse-all
    // buttons in renderHeader.
    state.renderedLaneKeys = [];

    // Single-root: byte-identical to the pre-PT-3 code path -- no
    // .repo-group wrapper anywhere in the DOM (architect's PT-3 review
    // criterion 2: the multi-root branch is strictly additive).
    if (roots.length <= 1) {
      if (!state.swimlanesOn) {
        main.appendChild(columnsFor(issues));
        return;
      }
      var grouped = groupByMilestone(issues);
      var soleRootId = primaryRootId(board);
      // PT-44 § 2: same "a lane for every milestone" fix as repoSectionEl
      // -- called BEFORE the empty-check below, since an issue-less
      // milestone (e.g. a project with milestones defined but nothing
      // filed yet, or PT-0.3/PT-0.4-style fully-archived-away milestones
      // with Show-archived off) must still get an empty lane instead of
      // silently falling into "No issues match the current filters,"
      // which would be exactly the information loss § 2 exists to close.
      var soleRootMilestonesForLanes = (board.milestones || []).filter(function (ms) {
        return state.currentMajor === "all" || ms.major === state.currentMajor;
      });
      grouped = appendMilestoneOnlyLanes(grouped.order, grouped.groups, soleRootMilestonesForLanes, soleRootId);
      if (grouped.order.length === 0) {
        main.innerHTML = '<div class="empty-state">No issues match the current filters.</div>';
        return;
      }
      grouped.order.forEach(function (key) {
        var stateKey = laneStateKey(soleRootId, key);
        // PT-31 (item 3): same laneId scheme as repoSectionEl's -- global
        // index (state.renderedLaneKeys.length, read BEFORE this lane's
        // own push below) + sanitized stateKey.
        var laneId = "lane-" + state.renderedLaneKeys.length + "-" + stateKey.replace(/[^A-Za-z0-9_-]/g, "-");
        main.appendChild(milestoneLaneEl(board, key, grouped.groups[key], stateKey, soleRootId, laneId));
        state.renderedLaneKeys.push(stateKey);
      });
      return;
    }

    // Multi-root: repo-grouped (ruling A, 2026-08-21) -- top-level
    // section per root, primary first then remaining roots by id.
    //
    // PT-44 § 2: the "no empty shells" skip below (a repo with nothing to
    // show renders nothing) originally meant "repoIssues.length === 0" --
    // but a repo can now have SOMETHING to show with zero live issues: a
    // milestone-only lane (fully-archived-away, Show-archived off; or
    // simply nothing filed against it yet). Both this top fast-path and
    // the per-repo skip below are widened to also check for milestones
    // under the active major tab, so a repo isn't dropped from the board
    // entirely just because its issue count happens to be zero.
    var anyMilestonesAtAll = (board.milestones || []).some(function (ms) {
      return state.currentMajor === "all" || ms.major === state.currentMajor;
    });
    if (issues.length === 0 && !anyMilestonesAtAll) {
      main.innerHTML = '<div class="empty-state">No issues match the current filters.</div>';
      return;
    }
    var orderedRoots = orderRoots(roots);
    orderedRoots.forEach(function (root) {
      var repoIssues = issues.filter(function (issue) { return issue.repo === root.id; });
      var repoHasMilestones = (board.milestones || []).some(function (ms) {
        return ms.repo === root.id && (state.currentMajor === "all" || ms.major === state.currentMajor);
      });
      if (repoIssues.length === 0 && !repoHasMilestones) return; // truly nothing to show for this repo
      main.appendChild(repoSectionEl(board, root, repoIssues));
    });
  }

  function handleDrop(id, newStatus) {
    var issue = state.board.issues.filter(function (i) { return i.id === id; })[0];
    if (!issue || issue.status === newStatus) return;
    // PT-3: card.draggable=false already keeps a foreign-root card from
    // starting a real drag, but a drop can still be dispatched (a stale
    // drag started before a refresh, a programmatic dispatch) -- refuse
    // before any optimistic state change or network round trip, rather
    // than relying on the server's 403 read_only_root round-trip to be
    // the only thing that catches it (architect review, 2026-08-21).
    //
    // PT-22: !isDraggable(...) -- the SAME shared predicate cardEl calls
    // above (board-logic.js), inverted for a refusal rather than a
    // permission. Not a separately-maintained comparison: isDraggable IS
    // the permission function; this call site is the one place that
    // negates it, so the two can never silently drift out of agreement
    // the way the pre-PT-22 inline comparisons did.
    if (!isDraggable(issue, primaryRootId(state.board))) {
      showToast(id + " is read-only (lives in a different root)", true);
      return;
    }
    var previousStatus = issue.status;
    issue.status = newStatus; // optimistic
    render();
    apiMutateIssue(id, { seen: issue.seen, patch: { status: newStatus } }).then(function (result) {
      if (result.status === 409) {
        Object.assign(issue, result.data.current);
        render();
        showToast(id + " changed on disk — refreshed.", true);
        return;
      }
      if (!result.ok) {
        issue.status = previousStatus;
        render();
        showToast("Failed to update " + id, true);
        return;
      }
      Object.assign(issue, result.data);
      render();
    }).catch(function () {
      issue.status = previousStatus;
      render();
      showToast("Failed to update " + id, true);
    });
  }

  // ------------------------------------------------------------------
  // List view
  // ------------------------------------------------------------------

  // PT-3: a function, not a module-level const, so it can carry a "Repo"
  // column when the board has more than one root -- the list is a
  // first-class view (its own tab, /list), not a Kanban-only affordance,
  // so multi-root's repo dimension belongs here too (architect's review,
  // ratified by team-lead: not Kanban-only for v1). Single-root gets the
  // exact pre-PT-3 column set, unchanged.
  function listColumns(board) {
    var cols = [{ key: "id", label: "ID" }];
    if (board && board.roots && board.roots.length > 1) {
      cols.push({ key: "repo", label: "Repo" });
    }
    return cols.concat([
      { key: "title", label: "Title" },
      { key: "status", label: "Status" },
      { key: "milestone", label: "Milestone" },
      { key: "assignee", label: "Assignee" },
      { key: "priority", label: "Priority" },
      { key: "updated", label: "Updated" },
    ]);
  }

  function renderList() {
    var main = document.getElementById("main");
    main.innerHTML = "";
    var columns = listColumns(state.board);
    var issues = filteredIssues().slice();
    issues.sort(function (a, b) {
      var av = a[state.sortKey] || "";
      var bv = b[state.sortKey] || "";
      if (av < bv) return -1 * state.sortDir;
      if (av > bv) return 1 * state.sortDir;
      return 0;
    });

    var table = document.createElement("table");
    table.className = "issue-list";
    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    columns.forEach(function (col) {
      var th = document.createElement("th");
      th.textContent = col.label + (state.sortKey === col.key ? (state.sortDir === 1 ? " ▲" : " ▼") : "");
      th.onclick = function () {
        if (state.sortKey === col.key) { state.sortDir *= -1; } else { state.sortKey = col.key; state.sortDir = 1; }
        render();
      };
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement("tbody");
    issues.forEach(function (issue) {
      var row = document.createElement("tr");
      row.onclick = function () { openDrawer(issue.id); };
      columns.forEach(function (col) {
        var td = document.createElement("td");
        // PT-44 § 2: the milestone cell becomes a link to the same
        // milestone card the lane header opens -- list view lost the
        // strip too (its only other source of milestone status/release
        // state), so this is the list-view compensation the ruling calls
        // for. Every other column stays plain text, unchanged.
        if (col.key === "milestone" && issue.milestone) {
          var link = document.createElement("a");
          link.href = "#";
          link.textContent = issue.milestone;
          link.onclick = function (e) {
            e.preventDefault();
            e.stopPropagation();
            openRecordDrawer("milestone", issue.milestone, issue.repo);
          };
          td.appendChild(link);
        } else {
          td.textContent = issue[col.key] || "";
        }
        row.appendChild(td);
      });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    main.appendChild(table);
  }

  // ------------------------------------------------------------------
  // Detail drawer
  // ------------------------------------------------------------------

  // The engine returns `description` as the whole pre-"## Comments" body,
  // including any "## Acceptance criteria" section, raw (see
  // process/TRACKER.md — cairn.parse_issue's "description" is
  // split_comments(body)[0], not a separately-parsed structure). The board
  // splits it client-side purely for display; there is no write-back path
  // for these checkboxes in phase 1 (see TRACKER.md's "Deferred" ruling).
  var AC_HEADING_RE = /^##\s*Acceptance criteria\s*$/;
  var AC_ITEM_RE = /^- \[( |x|X)\]\s*(.*)$/;

  function splitAcceptanceCriteria(description) {
    var lines = (description || "").split("\n");
    var headingIdx = -1;
    for (var i = 0; i < lines.length; i++) {
      if (AC_HEADING_RE.test(lines[i])) { headingIdx = i; break; }
    }
    if (headingIdx === -1) return { description: description || "", items: [] };
    var items = [];
    lines.slice(headingIdx + 1).forEach(function (line) {
      var m = AC_ITEM_RE.exec(line);
      if (m) items.push({ text: m[2], checked: m[1].toLowerCase() === "x" });
    });
    var descText = lines.slice(0, headingIdx).join("\n").replace(/\n+$/, "");
    return { description: descText, items: items };
  }

  // PT-4: markdown rendering, display-only (edit surfaces -- the comment
  // textarea, inline fields -- always show/submit raw markdown source;
  // this only touches how description/comment bodies are *displayed*).
  //
  // Vendored marked (parses markdown -> HTML, does not sanitize by design)
  // + DOMPurify (sanitizes) -- see vendor/NOTICE.md. Order matters:
  // sanitize marked's *output*, never the raw markdown source (seceng
  // PT-4 pre-clear) -- sanitizing pre-parse is bypassable via markdown
  // reconstruction. USE_PROFILES: {html: true} restricts DOMPurify's
  // parser to the HTML grammar only (no SVG/MathML surface -- issue
  // bodies have no legitimate use for either, and SVG is the source of
  // most historical DOMPurify mXSS bypass classes) -- seceng's
  // recommended hardening on top of otherwise-default config.
  //
  // Defense in depth: if either library failed to load for any reason,
  // falls back to the pre-PT-4 plain-text <pre> (a textContent assignment
  // -- never innerHTML) rather than ever rendering unsanitized HTML.
  function renderMarkdown(container, text) {
    if (window.marked && window.DOMPurify) {
      var html = window.DOMPurify.sanitize(
        window.marked.parse(text || ""),
        { USE_PROFILES: { html: true } }
      );
      var wrap = document.createElement("div");
      wrap.className = "markdown-body";
      wrap.innerHTML = html;
      container.appendChild(wrap);
      return;
    }
    var pre = document.createElement("pre");
    pre.textContent = text || "";
    container.appendChild(pre);
  }

  function closeDrawer() {
    state.openRecord = null;
    document.getElementById("drawer-overlay").classList.remove("open");
  }

  function openDrawer(id) {
    state.openRecord = { kind: "issue", id: id };
    apiGetIssue(id).then(renderDrawer).catch(function () {
      showToast("Could not load " + id, true);
    });
  }

  // PT-40 (joint PT-40/43/44 ruling § 5): the milestone/major sibling of
  // openDrawer. A LOOKUP against the already-fetched state.board (ruling
  // §1 rejects a second endpoint -- record data, body included, is
  // already in the /api/board payload), never a fetch. `repoId` scopes
  // the lookup when given (multi-root: two records can share a bare id
  // across repos, ruling §6) -- `undefined` matches the first record
  // found, same permissive default primaryRootId(null) uses elsewhere.
  function openRecordDrawer(recordKind, id, repoId) {
    var collection = recordKind === "major" ? (state.board && state.board.majors) : (state.board && state.board.milestones);
    var record = (collection || []).filter(function (r) {
      return r.id === id && (repoId == null || r.repo === repoId);
    })[0];
    if (!record) {
      showToast("Could not load " + id, true);
      return;
    }
    state.openRecord = { kind: recordKind, id: id };
    renderRecordDrawer(recordKind, record);
  }

  // PT-25/PT-26 shared drawer list renderer: Children, "Blocked by", and
  // "Blocks" are the same shape (id + title, opens that issue's own
  // drawer, a trailing status annotation) -- one function, not a third
  // hand-written copy of the same block (the standing duplicated-inline-
  // expression criterion, applied at the second-use moment rather than
  // waiting for a third). `opts.markResolved` adds a `.resolved` class to
  // done/cancelled entries -- PT-26's "open vs resolved distinguished"
  // requirement for the "Blocked by" list; Children and "Blocks" don't
  // pass it, so they render with no resolved/open distinction at all.
  function issueLinkListEl(items, opts) {
    opts = opts || {};
    var ul = document.createElement("ul");
    ul.className = "children-list";
    items.forEach(function (item) {
      var li = document.createElement("li");
      if (opts.markResolved && (item.status === "done" || item.status === "cancelled")) {
        li.className = "resolved";
      }
      var link = document.createElement("a");
      link.href = "#";
      link.textContent = item.id + " — " + item.title;
      link.onclick = function (e) {
        e.preventDefault();
        openDrawer(item.id);
      };
      li.appendChild(link);
      li.appendChild(document.createTextNode(" (" + item.status + ")"));
      ul.appendChild(li);
    });
    return ul;
  }

  function renderDrawer(issue) {
    // PT-40: race-guard widened to compare BOTH kind and id -- a fetch for
    // issue PT-1 that resolves after the user opened milestone PT-1.0
    // (same literal id string possible across schemas) must not render
    // over the record that's actually open now.
    if (!state.openRecord || state.openRecord.kind !== "issue" || state.openRecord.id !== issue.id) return; // user navigated away while fetching
    var overlay = document.getElementById("drawer-overlay");
    var drawer = document.getElementById("drawer");
    drawer.innerHTML = "";
    overlay.classList.add("open");
    overlay.onclick = function (e) { if (e.target === overlay) closeDrawer(); };

    var closeBtn = document.createElement("button");
    closeBtn.className = "close-btn";
    closeBtn.textContent = "×";
    closeBtn.onclick = closeDrawer;
    drawer.appendChild(closeBtn);

    var idEl = document.createElement("div");
    idEl.className = "drawer-id";
    idEl.textContent = issue.id;
    drawer.appendChild(idEl);

    var h2 = document.createElement("h2");
    h2.textContent = issue.title;
    drawer.appendChild(h2);

    // PT-3: a secondary-root issue is read-only -- suppress the inline
    // edit controls (courtesy only, see inlineField's note; the real
    // boundary is the server's 403 read_only_root).
    var readOnly = !!issue.read_only;
    drawer.appendChild(inlineField("title", "text", issue.title, issue, false, readOnly));
    drawer.appendChild(inlineSelect("status", Object.keys(STATUS_LABELS), issue.status, issue, STATUS_LABELS, readOnly));
    drawer.appendChild(inlineField("assignee", "text", issue.assignee || "", issue, false, readOnly));
    drawer.appendChild(inlineField("milestone", "text", issue.milestone || "", issue, false, readOnly));
    drawer.appendChild(inlineField("labels", "text", (issue.labels || []).join(", "), issue, true, readOnly));
    drawer.appendChild(inlineSelect("priority", ["", "P0", "P1", "P2", "P3"], issue.priority, issue, PRIORITY_LABELS, readOnly));

    if (issue.pr) {
      // PT-20: DOM-built, not innerHTML string concat -- `pr` is free-text
      // frontmatter with no server-side format validation (hand-editable
      // issue files are untrusted per the ratified threat model). Building
      // via createElement/property-assignment (never HTML-parsing the
      // value) closes the attribute-breakout variant (a pr value like
      // `"><img src=x onerror=...>` can no longer escape the attribute
      // context, since it's never parsed as markup at all). That alone
      // does NOT close a javascript: URI in `pr` though -- an <a> built
      // via the DOM still executes a javascript: href on click, same as
      // one built via innerHTML -- so the scheme is explicitly allowlisted
      // to http(s) before rendering as a clickable link; anything else
      // (including javascript:/data:/vbscript: etc.) renders as inert
      // plain text instead.
      var prP = document.createElement("div");
      prP.className = "pr-link";
      prP.appendChild(document.createTextNode("PR: "));
      if (/^https?:\/\//i.test(issue.pr)) {
        var prLink = document.createElement("a");
        prLink.href = issue.pr;
        prLink.target = "_blank";
        prLink.rel = "noopener";
        prLink.textContent = issue.pr;
        prP.appendChild(prLink);
      } else {
        var prText = document.createElement("span");
        prText.textContent = issue.pr;
        prP.appendChild(prText);
      }
      drawer.appendChild(prP);
    }
    var fileP = document.createElement("div");
    fileP.className = "file-link";
    // PT-10: the server now serves the issue's real on-disk path (correct
    // for both process/cairn/... and any other --data-dir setup, and for
    // an archived issue's archive/ location) -- no longer hardcoded here.
    fileP.textContent = "File: " + issue.path;
    drawer.appendChild(fileP);

    // PT-25: a child's drawer links back to its parent.
    if (issue.parent) {
      var parentP = document.createElement("div");
      parentP.className = "parent-link";
      parentP.appendChild(document.createTextNode("Parent: "));
      var parentLink = document.createElement("a");
      parentLink.href = "#";
      parentLink.textContent = issue.parent;
      parentLink.onclick = function (e) {
        e.preventDefault();
        openDrawer(issue.parent);
      };
      parentP.appendChild(parentLink);
      drawer.appendChild(parentP);
    }

    // PT-25/PT-26: Children, "Blocked by", and "Blocks" are the same
    // rendering shape -- id + title, opens that issue's own drawer, a
    // status annotation -- factored into one helper (issueLinkListEl,
    // below) rather than a third hand-written copy of the same block.
    // Computed from the full board payload (childrenOf/blockersOf/
    // blocksOf, board-logic.js) -- GET /api/issue/<id> (the `issue` this
    // function receives) carries no sibling-issue list of its own, only
    // this one issue's frontmatter + description + comments.
    var kids = state.board ? childrenOf(state.board.issues, issue) : [];
    if (kids.length) {
      var childrenHeading = document.createElement("div");
      childrenHeading.className = "section-heading";
      childrenHeading.textContent = "Children";
      drawer.appendChild(childrenHeading);
      drawer.appendChild(issueLinkListEl(kids));
    }

    // PT-26: "Blocked by" -- open vs resolved (done/cancelled) visually
    // distinguished (architect's ruling #4); "Blocks" is the reverse
    // lookup, drawer-and-cairn-show-only, never on cards.
    var blockers = state.board ? blockersOf(state.board.issues, issue) : [];
    if (blockers.length) {
      var blockedByHeading = document.createElement("div");
      blockedByHeading.className = "section-heading";
      blockedByHeading.textContent = "Blocked by";
      drawer.appendChild(blockedByHeading);
      drawer.appendChild(issueLinkListEl(blockers, { markResolved: true }));
    }
    var blocks = state.board ? blocksOf(state.board.issues, issue) : [];
    if (blocks.length) {
      var blocksHeading = document.createElement("div");
      blocksHeading.className = "section-heading";
      blocksHeading.textContent = "Blocks";
      drawer.appendChild(blocksHeading);
      drawer.appendChild(issueLinkListEl(blocks));
    }

    var split = splitAcceptanceCriteria(issue.description);

    var descHeading = document.createElement("div");
    descHeading.className = "section-heading";
    descHeading.textContent = "Description";
    drawer.appendChild(descHeading);
    renderMarkdown(drawer, split.description);

    if (split.items.length) {
      var acHeading = document.createElement("div");
      acHeading.className = "section-heading";
      acHeading.textContent = "Acceptance criteria";
      drawer.appendChild(acHeading);
      var ul = document.createElement("ul");
      ul.className = "ac-list";
      split.items.forEach(function (item) {
        var li = document.createElement("li");
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = !!item.checked;
        cb.disabled = true; // checkbox write-back is deferred — see TRACKER.md
        li.appendChild(cb);
        var span = document.createElement("span");
        span.textContent = item.text;
        li.appendChild(span);
        ul.appendChild(li);
      });
      drawer.appendChild(ul);
    }

    // PT-51 §4: shared with the record drawer via commentSectionEl --
    // every default (apiMutateIssue, openDrawer(issue.id) on stale/post)
    // is exactly this function's pre-extraction behavior, so passing
    // only `readOnly` here changes nothing about the issue drawer.
    drawer.appendChild(commentSectionEl(issue, { readOnly: readOnly }));
  }

  // PT-40 (joint PT-40/43/44 ruling § 5): the milestone/major card.
  // REUSES the existing drawer/overlay DOM (no second panel) -- same
  // reset-innerHTML / open-overlay / close-on-overlay-click plumbing
  // renderDrawer already has above. `recordKind` is passed explicitly by
  // the caller (openRecordDrawer already knows it), never inferred from a
  // field on `record` -- milestones carry their OWN `kind` field
  // (process|product, definition vs. development), semantically
  // unrelated to "is this a milestone or a major"; reusing it here would
  // collide with that meaning.
  //
  // Read-only in 0.7.0 (ruling § 5): no inline editors -- a second
  // mutation endpoint for a different schema, `seen` tokens for records
  // that have none, and an interaction with archive semantics, all for a
  // field a human changes a handful of times per release, is not free
  // now. Names the CLI command instead of offering a control guaranteed
  // to be rejected.
  //
  // Progress/release-state are the PLAIN forms for this loop
  // (milestoneProgress unfiltered by status, no release chip yet) --
  // PT-43 (§3, archive-aware/status-suppressed counting) and PT-44 (§4,
  // git-tag release chips) extend this same function rather than
  // rewriting it; do not duplicate its DOM-building shape elsewhere.
  function renderRecordDrawer(recordKind, record) {
    if (!state.openRecord || state.openRecord.kind !== recordKind || state.openRecord.id !== record.id) return;
    var overlay = document.getElementById("drawer-overlay");
    var drawer = document.getElementById("drawer");
    drawer.innerHTML = "";
    overlay.classList.add("open");
    overlay.onclick = function (e) { if (e.target === overlay) closeDrawer(); };

    var closeBtn = document.createElement("button");
    closeBtn.className = "close-btn";
    closeBtn.textContent = "×";
    closeBtn.onclick = closeDrawer;
    drawer.appendChild(closeBtn);

    var idEl = document.createElement("div");
    idEl.className = "drawer-id";
    idEl.textContent = record.id;
    drawer.appendChild(idEl);

    var h2 = document.createElement("h2");
    h2.textContent = recordKind === "major" ? record.id : (record.name || record.id);
    drawer.appendChild(h2);

    var meta = document.createElement("div");
    meta.className = "card-meta";
    meta.appendChild(chip("", recordKind));
    if (record.major) meta.appendChild(chip("milestone", record.major));
    meta.appendChild(chip("", recordStatusLabel(record.status)));
    if (record.ga) meta.appendChild(chip("", "GA"));
    // PT-44 § 4: the release chip (unreleased / "<tag> released"), not
    // the bare target_tag -- releaseChipLabel is the SAME formatter the
    // lane header uses, so the two never drift on wording.
    var recordReleaseText = releaseChipLabel(record.released, record.target_tag);
    if (recordReleaseText !== null) meta.appendChild(chip("release", recordReleaseText));
    // PT-48: same chip("archived", "archived") treatment cardEl already
    // uses -- the record drawer ignored the flag entirely before this.
    if (record.archived) meta.appendChild(chip("archived", "archived"));
    drawer.appendChild(meta);

    // PT-51 §5: the SAME disjunction the issue path folds into its own
    // server-side `read_only` -- archived, or living in a non-primary
    // root. Courtesy only here (as inlineField's own note says); the
    // server's 403 archived / 403 read_only_root is the real boundary.
    var primaryId = primaryRootId(state.board);
    var readOnly = !!record.archived || (primaryId != null && record.repo !== primaryId);
    // PT-51 §1/§4: every record editor/comment posts through the SAME
    // POST /api/record/<id> endpoint and re-opens THIS drawer (not
    // openDrawer -- that's the issue drawer's own re-open) on both a
    // stale-seen conflict and a successful post -- one options object,
    // reused by every editor call below and by commentSectionEl.
    var recordOpts = {
      mutate: apiMutateRecord,
      onStale: function () { openRecordDrawer(recordKind, record.id, record.repo); },
      onPosted: function () { openRecordDrawer(recordKind, record.id, record.repo); },
    };

    // PT-51 §3: board-editable fields only -- `id` (filename-authoritative,
    // a rename is a `git mv`) and milestone `kind` (pinned to the id
    // shape by lint, itself not board-editable) are CLI-only by design,
    // so neither gets an editor here at all, not just a disabled one.
    if (recordKind === "milestone") {
      drawer.appendChild(inlineField("name", "text", record.name || "", record, false, readOnly, recordOpts));
      drawer.appendChild(inlineSelect(
        "status", Object.keys(RECORD_STATUS_LABELS), record.status, record, RECORD_STATUS_LABELS, readOnly, recordOpts
      ));
      drawer.appendChild(inlineSelect(
        "major", dedupeMajorIds(state.board ? state.board.majors : []), record.major, record, null, readOnly, recordOpts
      ));
      drawer.appendChild(inlineField("target_tag", "text", record.target_tag || "", record, false, readOnly, recordOpts));
      // `ga` needs a real JSON bool server-side (§3) -- inlineSelect's
      // opts.boolean flag (added alongside this feature) does the DOM-
      // boundary "true"/"false" string -> real bool coercion; the SAME
      // spot the "" -> null sentinel already lives, not a new mechanism.
      var gaOpts = { mutate: recordOpts.mutate, onStale: recordOpts.onStale, onPosted: recordOpts.onPosted, boolean: true };
      drawer.appendChild(inlineSelect(
        "ga", ["false", "true"], String(!!record.ga), record, { "true": "GA", "false": "Not GA" }, readOnly, gaOpts
      ));
    } else {
      drawer.appendChild(inlineSelect(
        "status", Object.keys(RECORD_STATUS_LABELS), record.status, record, RECORD_STATUS_LABELS, readOnly, recordOpts
      ));
      // MAJOR_HEALTH_VALUES mirrors cairn.py's own enum of the same name
      // (process/TRACKER.md's major-file health vocabulary) -- no shared
      // board-logic.js constant for it since, unlike RECORD_STATUS_LABELS,
      // nothing else in board.js needs this vocabulary yet.
      drawer.appendChild(inlineSelect(
        "health", ["on-track", "at-risk", "off-track"], record.health, record, null, readOnly, recordOpts
      ));
      drawer.appendChild(inlineField("owner", "text", record.owner || "", record, false, readOnly, recordOpts));
      drawer.appendChild(inlineField("target_ship", "text", record.target_ship || "", record, false, readOnly, recordOpts));
    }

    if (recordKind === "milestone") {
      // PT-44 § 3: isComplete branch -- a done/cancelled milestone shows
      // completion, never a ratio (the release chip above already
      // carries the release state; a "3/3 done" ratio next to it would
      // be redundant with the SAME fact restated two ways).
      var progress = milestoneProgress(state.board ? state.board.issues : [], record);
      var progressEl = document.createElement("div");
      progressEl.className = "drawer-progress";
      progressEl.textContent = progress.isComplete ? "✓ Done" : (progress.done + "/" + progress.total + " done");
      drawer.appendChild(progressEl);
    }

    renderMarkdown(drawer, record.body || "");

    var fileP = document.createElement("div");
    fileP.className = "file-link";
    fileP.textContent = "File: " + record.path;
    drawer.appendChild(fileP);

    // PT-51 §5: re-scoped -- the note's old claim ("read-only on the
    // board", unconditionally) stopped being true the moment records
    // became editable. Archived and foreign-root records are STILL
    // genuinely read-only and keep a note (worded per which); a live
    // primary-root record gets NO note at all -- it's editable now, so
    // a leftover "read-only" note would be actively wrong, not just stale.
    if (record.archived) {
      var archivedNote = document.createElement("div");
      archivedNote.className = "record-readonly-note";
      archivedNote.textContent = "Archived — read-only on the board; use `cairn set` / `cairn comment`.";
      drawer.appendChild(archivedNote);
    } else if (readOnly) {
      var foreignNote = document.createElement("div");
      foreignNote.className = "record-readonly-note";
      foreignNote.textContent = record.id + " lives in a different root — read-only on the board.";
      drawer.appendChild(foreignNote);
    }

    // PT-51 §4: same commentSectionEl the issue drawer uses, endpoint-
    // and re-open swapped via recordOpts (mutate/onStale/onPosted).
    drawer.appendChild(commentSectionEl(record, {
      mutate: recordOpts.mutate,
      readOnly: readOnly,
      onStale: recordOpts.onStale,
      onPosted: recordOpts.onPosted,
    }));
  }

  function inlineField(field, type, value, entity, isLabelsList, readOnly, opts) {
    var wrap = document.createElement("div");
    wrap.className = "drawer-field";
    var label = document.createElement("label");
    label.textContent = field;
    wrap.appendChild(label);
    var input = document.createElement("input");
    input.type = type;
    input.value = value;
    if (readOnly) {
      // PT-3: UI courtesy only, not the security boundary -- the board
      // is read-only across roots because _mutate_issue refuses a
      // foreign-root id server-side (403 read_only_root) regardless of
      // what the DOM allows; disabling the control here just keeps
      // someone from submitting an edit that's guaranteed to be rejected.
      input.disabled = true;
    } else {
      input.addEventListener("change", function () {
        var newValue = isLabelsList
          ? input.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean)
          : input.value;
        submitPatch(entity, field, newValue, input, value, opts);
      });
    }
    wrap.appendChild(input);
    return wrap;
  }

  function inlineSelect(field, options, value, entity, labels, readOnly, opts) {
    // "" is the sentinel option value for a null field (e.g. priority's
    // none option) — translated to/from JSON null here at the DOM boundary,
    // since <select>.value is always a string and JS null stringifies to
    // the literal "null" if assigned directly, matching no real option.
    var wrap = document.createElement("div");
    wrap.className = "drawer-field";
    var label = document.createElement("label");
    label.textContent = field;
    wrap.appendChild(label);
    var select = document.createElement("select");
    options.forEach(function (opt) {
      var o = document.createElement("option");
      o.value = opt;
      o.textContent = (labels && labels[opt]) || opt || "(none)";
      select.appendChild(o);
    });
    var initialSelectValue = (value === null || value === undefined) ? "" : value;
    select.value = initialSelectValue;
    if (readOnly) {
      select.disabled = true; // PT-3: UI courtesy only -- see inlineField's note
    } else {
      select.addEventListener("change", function () {
        var raw = select.value === "" ? null : select.value;
        // PT-51 §3: `ga` must reach the server as a real JSON bool, not
        // the string "true"/"false" every <select>.value always is --
        // opts.boolean (set only by the record drawer's ga select) is
        // the DOM-boundary coercion, same spot the "" -> null sentinel
        // above already lives at, not a field-name special-case.
        var newValue = (opts && opts.boolean && raw !== null) ? (raw === "true") : raw;
        submitPatch(entity, field, newValue, select, initialSelectValue, opts);
      });
    }
    wrap.appendChild(select);
    return wrap;
  }

  function submitPatch(entity, field, newValue, el, previousValue, opts) {
    opts = opts || {};
    var mutate = opts.mutate || apiMutateIssue;
    var patch = {};
    patch[field] = newValue;
    mutate(entity.id, { seen: entity.seen, patch: patch }).then(function (result) {
      if (result.status === 409) {
        el.value = previousValue;
        showToast(entity.id + " changed on disk — refreshed.", true);
        if (opts.onStale) opts.onStale(); else openDrawer(entity.id);
        return;
      }
      if (!result.ok) {
        el.value = previousValue;
        showToast("Failed to update " + field, true);
        return;
      }
      entity.seen = result.data.seen;
      if (field === "title") {
        // PT-11: reflect the new title in the open drawer's h2 straight
        // from this response, not the next poll -- gated on `field` so a
        // different field's response (e.g. status, landing before or
        // after a title edit) never touches the h2. The card behind the
        // drawer still refreshes via the existing refreshBoardSilently()
        // path below, unchanged. `field === "title"` is issue-only in
        // practice (the record drawer's name-equivalent field is called
        // `name`, never `title`), so this needs no entity-kind guard.
        entity.title = result.data.title;
        if (state.openRecord && state.openRecord.kind === "issue" && state.openRecord.id === entity.id) {
          var h2 = document.querySelector("#drawer h2");
          if (h2) h2.textContent = result.data.title;
        }
      }
      refreshBoardSilently();
    });
  }

  // PT-51 §4: extracted from the issue drawer's own comment log + add-
  // comment box (the ONLY prior instance) at the second use (the record
  // drawer) -- the issueLinkListEl precedent stated at its own top
  // comment. `opts.mutate` is the submit callback per endpoint (issue ->
  // apiMutateIssue, the default; record -> apiMutateRecord); `opts.
  // onStale`/`opts.onPosted` default to `openDrawer(record.id)` (the
  // issue drawer's original behavior) and are overridden by the record
  // drawer to re-open the record drawer instead.
  function commentSectionEl(record, opts) {
    opts = opts || {};
    var mutate = opts.mutate || apiMutateIssue;
    var readOnly = !!opts.readOnly;

    var frag = document.createDocumentFragment();
    var commentsHeading = document.createElement("div");
    commentsHeading.className = "section-heading";
    commentsHeading.textContent = "Comments";
    frag.appendChild(commentsHeading);
    var log = document.createElement("div");
    log.className = "comment-log";
    (record.comments || []).forEach(function (c) {
      var div = document.createElement("div");
      div.className = "comment";
      var meta = document.createElement("div");
      meta.className = "comment-meta";
      meta.textContent = "@" + c.author + " — " + c.date;
      div.appendChild(meta);
      renderMarkdown(div, c.body);
      log.appendChild(div);
    });
    if (!record.comments || !record.comments.length) {
      var noneEl = document.createElement("div");
      noneEl.className = "empty-state";
      noneEl.textContent = "No comments yet.";
      log.appendChild(noneEl);
    }
    frag.appendChild(log);

    if (!readOnly) {
      var addComment = document.createElement("div");
      addComment.className = "add-comment";
      var textarea = document.createElement("textarea");
      textarea.placeholder = "Add a comment…";
      addComment.appendChild(textarea);
      var postBtn = document.createElement("button");
      postBtn.textContent = "Comment";
      postBtn.onclick = function () {
        var body = textarea.value.trim();
        if (!body) return;
        mutate(record.id, { seen: record.seen, comment: { author: "board", body: body } }).then(function (result) {
          if (result.status === 409) {
            showToast(record.id + " changed on disk — refreshed.", true);
            if (opts.onStale) opts.onStale(); else openDrawer(record.id);
            return;
          }
          if (!result.ok) { showToast("Failed to add comment", true); return; }
          if (opts.onPosted) opts.onPosted(); else openDrawer(record.id);
          refreshBoardSilently();
        });
      };
      addComment.appendChild(postBtn);
      frag.appendChild(addComment);
    }
    return frag;
  }

  // ------------------------------------------------------------------
  // Top-level render + polling
  // ------------------------------------------------------------------

  // PT-49 §6: a persistent banner, not a toast (showToast above always
  // auto-dismisses in 3.5s -- wrong for a condition that doesn't self-
  // resolve). Reads state.board.engine.stale fresh on every render() pass
  // -- shown when true, removed the moment a later payload reports false
  // (no separate "was it shown before" state to track). Never touches
  // #main/the header/interaction -- a stale server still serves true
  // data, only its behaviour is old (§6's own wording).
  function renderEngineBanner() {
    var el = document.getElementById("engine-stale-banner");
    var engine = state.board && state.board.engine;
    if (engine && engine.stale) {
      el.textContent =
        "Board server is running older code than scripts/cairn/cairn.py — restart it (`/cairn stop`, then `/cairn`).";
      el.hidden = false;
    } else {
      el.hidden = true;
    }
  }

  function render() {
    renderEngineBanner();
    renderHeader();
    if (isListView) renderList(); else renderKanban();
  }

  // PT-32 (architect's ruling § 4, then a micro-ruling after the Chrome
  // pass drew a real 503 that toasted "Already up to date" -- the § 4
  // boolean put "failed" on the same, reassuring branch as "unchanged").
  // Resolves to exactly one of REFRESH_UPDATED/REFRESH_UNCHANGED/
  // REFRESH_FAILED (board-logic.js's exported constants -- board.js is
  // their only producer, pullRefreshToast their only consumer) and STILL
  // NEVER REJECTS: six existing bare-statement call sites (the poll
  // timer, SSE's onmessage, visibilitychange/focus, the comment/patch
  // flows above) discard the returned promise structurally, with nowhere
  // to attach a `.catch` -- a rejection is the one thing those call sites
  // cannot ignore, so this changes no existing behaviour at any of them
  // (QA-verified). Depends on apiGetBoard's resp.ok check (above) to be
  // trustworthy -- without it, a non-2xx response with a well-formed JSON
  // body would have resolved as "updated" with an error object as the
  // board.
  function refreshBoardSilently() {
    return apiGetBoard().then(function (data) {
      if (data) { state.board = data; render(); return REFRESH_UPDATED; }
      return REFRESH_UNCHANGED;
    }).catch(function () { return REFRESH_FAILED; });
  }

  // PT-44 (ruling § 4's own wording: "one rule, not a special case"): the
  // SINGLE producer for "a request-shaping parameter changed, so the
  // cached etag is no longer valid for the NEXT response shape" -- an
  // etag minted for one representation must never be sent as
  // If-None-Match for a different one (release state, or PT-42's
  // archived flag). Both runPullRefresh and the #filter-archived listener
  // route through this instead of each carrying its own copy of
  // `state.etag = null; refreshBoardSilently();` -- runPullRefresh
  // previously did NOT clear the etag at all (a real gap: a bare `git
  // tag` add with no file mtime change would 304 a pull-to-refresh,
  // silently serving a stale `released` value).
  function clearEtagAndRefresh() {
    state.etag = null;
    return refreshBoardSilently();
  }

  // ------------------------------------------------------------------
  // PT-32/PT-33: pull-down-to-refresh gesture, touch AND trackpad wheel --
  // two inputs feeding the SAME pullPhase machine (board-logic.js), never
  // two independent decisions. PT-33 (architect's ruling @ e319208) added
  // the wheel adapter below as new plumbing; `pullPhase`/`pullIndicatorOffset`/
  // `pullIndicatorLabel`/`shouldCancelPull`/`pullRefreshToast` are untouched
  // by that change. The board scrolls the DOCUMENT, not a nested container
  // (ground truth established in the PT-32 ruling: nothing in board.css
  // sets overflow-y, and header.app-header is itself position: sticky) --
  // "at scroll top" is window.scrollY === 0, and listeners are registered
  // on `document`, not any particular element.
  //
  // Gesture-tracking state lives in closure-local vars, not `state` --
  // it's per-gesture bookkeeping with no meaning outside an in-flight
  // gesture, unlike state.cardDragActive/state.pullRefreshing (declared
  // with `state`) which shouldCancelPull and rendering both need to read
  // from outside this closure. `pullSource` (PT-33 § 7) is the arbiter that
  // keeps the two inputs from ever double-firing on a device with both.
  // ------------------------------------------------------------------

  var pullStartY = null; // null = no gesture currently being tracked
  var pullStartX = null;
  var pullAtScrollTop = false;
  var pullAxisDecided = false;
  var pullHorizontalDominant = false;
  var pullLastDeltaY = 0;
  var pullLastPhase = "idle";
  // PT-31 (architect's triage ruling, item 6b): hoisted -- wirePullToRefresh
  // already proves this element exists (and bails if it doesn't) before any
  // listener is attached, and #pull-indicator is static in board.html,
  // never re-created, so this cache can't go stale. Set once there instead
  // of a getElementById on every touchmove.
  var pullIndicatorEl = null;

  // PT-33 (architect's ruling § 7): the single arbiter that makes wheel and
  // touch double-firing structurally impossible on a device with both --
  // `null | "touch" | "wheel"`. Set to "touch" the moment touch tracking
  // begins (onPullTouchStart) and cleared in resetPullGesture; set to
  // "wheel" only once a wheel gesture actually reaches pulling/armed (never
  // on every wheel event, or ordinary desktop scrolling would hold the
  // token forever) and cleared at wheel quiescence. Touch wins when both are
  // live (JC7) -- it has an explicit release signal, wheel only an
  // inference.
  var pullSource = null;
  // PT-33: the wheel adapter's own reducer state + idle timer. Closure-local
  // for the same reason the touch vars above are -- per-gesture bookkeeping,
  // not `state`.
  var wheelState = wheelPullInitialState();
  var wheelIdleTimer = null;

  function pullCancelFlags(multiTouch) {
    // PT-32 (architect's ruling § 2): board.js's job is computing every
    // cancel flag and handing the union to shouldCancelPull (board-logic.js)
    // -- never re-deriving a subset of the predicate here.
    return shouldCancelPull({
      cardDragActive: state.cardDragActive,
      drawerOpen: state.openRecord !== null,
      multiTouch: multiTouch,
      horizontalDominant: pullHorizontalDominant,
      refreshing: state.pullRefreshing,
    });
  }

  // PT-33 (architect's ruling § 5): the wheel path's cancel-flag union --
  // same shared shouldCancelPull, but multiTouch is always false (no wheel
  // analogue) and horizontalDominant is always false HERE, deliberately:
  // the axis decision for a wheel gesture is made upstream, inside
  // wheelPullReduce's opening gate, because only the reducer knows where a
  // wheel gesture begins -- board.js has no touchstart to latch it at.
  // Passing the flag twice would gate the same fact in two places.
  function wheelCancelFlags() {
    return shouldCancelPull({
      cardDragActive: state.cardDragActive,
      drawerOpen: state.openRecord !== null,
      multiTouch: false,
      horizontalDominant: false,
      refreshing: state.pullRefreshing,
    });
  }

  // PT-32 (architect's fix, diff review @ 295785c -- BLOCKING: verified
  // empirically that the indicator was never visible at any viewport,
  // occluded under the header regardless of header height). The at-rest
  // position is `translateY(-100%)` -- fully off-canvas, above its own
  // height, decoupled from header.app-header's height entirely. Pulling
  // reveals it by adding the (capped) offset back: `translateY(calc(-100%
  // + <offset>px))`, so it overlays the header by exactly `offset` pixels
  // -- the conventional iOS/Android look, and one CSS custom property
  // change here can never re-couple to a header-height constant the way
  // raising PULL_MAX_OFFSET to "clear the header" would have.
  //
  // The `dragging` class suppresses board.css's transition WHILE
  // pulling/armed -- the indicator must track the finger 1:1 during an
  // active drag; the transition is for snap-back-to-hidden (idle) and the
  // release-to-refreshing/refreshing-to-idle settle, never the drag itself.
  function updatePullIndicator(phase, deltaY) {
    var el = pullIndicatorEl;
    if (!el) return; // PT-32 (ruling § 5): bail if the indicator isn't in the DOM
    // PT-33 (architect's post-review fix, confirmed empirically in the
    // Chrome pass @ beab54c -- R1): refuse to leave "refreshing" while a
    // refresh is actually in flight. A wheel event arriving mid-refresh
    // computes cancelled:true (shouldCancelPull's refreshing flag) and
    // therefore phase:"idle" -- without this guard that call would hide the
    // spinner before runPullRefresh's own promise settles and calls this
    // function with "idle" itself. Fixed HERE, once, rather than at each of
    // the (touch/wheel) call sites, which also closes the identical latent
    // case on the touch path (a touchmove landing mid-refresh hits the same
    // cancelled:true -> phase:"idle" path). runPullRefresh always flips
    // state.pullRefreshing to false BEFORE it calls updatePullIndicator("idle", 0)
    // itself, so the guard never blocks the real transition out.
    if (state.pullRefreshing) phase = "refreshing";
    el.classList.toggle("dragging", phase === "pulling" || phase === "armed");
    if (phase === "idle") {
      el.hidden = true;
      el.style.transform = "";
      return;
    }
    el.hidden = false;
    // PT-31 (item 6c): spin ONLY the leading glyph, not the whole label --
    // rotating the entire "↻ Refreshing…" text node would spin the words
    // too. Split the glyph into its own span so the CSS keyframe (below)
    // has something narrower to target; the rest of the label is a plain
    // trailing text node, unchanged. PULL_MIN_SPINNER_MS is a MINIMUM
    // hold, not a duration -- a slow/stalled network can make it
    // arbitrarily long, and a motionless glyph during that window reads
    // as a frozen page rather than a working one.
    var label = pullIndicatorLabel(phase);
    el.textContent = "";
    var glyphEl = document.createElement("span");
    glyphEl.className = "pull-indicator-glyph";
    glyphEl.classList.toggle("spinning", phase === "refreshing");
    glyphEl.textContent = label.charAt(0);
    el.appendChild(glyphEl);
    el.appendChild(document.createTextNode(label.slice(1)));
    el.style.transform = "translateY(calc(-100% + " + pullIndicatorOffset(deltaY) + "px))";
  }

  function resetPullGesture() {
    // PT-31 (architect's triage ruling, item 6a): complete reset -- the
    // three vars added below were previously left standing across a
    // reset, safe only because every read is guarded by the
    // `pullStartY === null` early return at the top of onPullTouchMove/
    // onPullTouchEnd. Zero behavior change (onPullTouchEnd already reads
    // pullLastPhase/pullLastDeltaY into locals BEFORE calling this), and
    // it removes a trap for whoever next adds a read path that isn't
    // guarded the same way.
    pullStartY = null;
    pullStartX = null;
    pullAtScrollTop = false;
    pullAxisDecided = false;
    pullHorizontalDominant = false;
    pullLastDeltaY = 0;
    pullLastPhase = "idle";
    // PT-33 (ruling § 7): cleared here, not just set at touch-start -- this
    // is the ONE function every touch-gesture exit path (onPullTouchEnd,
    // onPullTouchCancel, the second-finger-cancel branch below) already
    // funnels through, so the arbiter token release can't be forgotten on
    // any of them separately.
    pullSource = null;
  }

  function onPullTouchStart(e) {
    if (pullStartY !== null) {
      // A second finger touching down mid-gesture -- cancel immediately
      // rather than waiting for the next touchmove to notice (§2, cancel
      // condition 4: pinch-zoom is not a pull).
      if (e.touches.length > 1) {
        resetPullGesture();
        updatePullIndicator("idle", 0);
      }
      return;
    }
    if (e.touches.length !== 1) return; // starting with >1 touch: never begin tracking
    // PT-33 (ruling § 7): touch discards any in-flight wheel gesture first
    // and takes the arbiter token -- touch wins (JC7) because it has an
    // explicit release signal and wheel only an inference. PRESERVES
    // wheelState.lastTs (architect's post-review fix -- same shape
    // onWheelQuiesce already uses) rather than wiping it to -Infinity via
    // wheelPullInitialState(): a full wipe would make the NEXT wheel event
    // read as "the very first wheel event ever seen" regardless of how
    // recently one actually fired, which errs toward OPENING a gesture too
    // easily rather than too cautiously. Keeping lastTs errs safe (the next
    // event is, if anything, more likely to be refused as "too soon") and
    // removes the asymmetry between this reset path and onWheelQuiesce's.
    clearTimeout(wheelIdleTimer);
    wheelState = { status: "idle", distance: 0, lastTs: wheelState.lastTs };
    updatePullIndicator("idle", 0);
    pullSource = "touch";
    pullStartY = e.touches[0].clientY;
    pullStartX = e.touches[0].clientX;
    // PT-32 (ruling § 2, cancel condition 1): checked ONCE, at gesture
    // start, not continuously -- this is what lets normal mid-list
    // scrolling proceed untouched once it's under way.
    pullAtScrollTop = window.scrollY === 0;
    pullAxisDecided = false;
    pullHorizontalDominant = false;
    pullLastDeltaY = 0;
    pullLastPhase = "idle";
  }

  function onPullTouchMove(e) {
    if (pullStartY === null) return;
    var touch = e.touches[0];
    if (!touch) return;
    var deltaY = touch.clientY - pullStartY;
    var deltaX = touch.clientX - pullStartX;

    // PT-32 (ruling § 2, cancel condition 5): decided ONCE, on the first
    // move past a tiny noise threshold, and held for the rest of the
    // gesture -- a swipe that starts vertical and drifts horizontal later
    // (or vice versa) doesn't flip allegiance mid-gesture.
    if (!pullAxisDecided && (Math.abs(deltaX) > 4 || Math.abs(deltaY) > 4)) {
      pullAxisDecided = true;
      pullHorizontalDominant = Math.abs(deltaX) > Math.abs(deltaY);
    }

    var cancelled = pullCancelFlags(e.touches.length > 1);
    var phase = pullPhase({ atScrollTop: pullAtScrollTop, deltaY: deltaY, cancelled: cancelled });
    pullLastDeltaY = deltaY;
    pullLastPhase = phase;

    // PT-32 (ruling § 3): preventDefault ONLY while pulling/armed --
    // registered non-passive (see wirePullToRefresh) so this call has any
    // effect at all. Calling it unconditionally would break normal
    // scrolling; never calling it lets the native bounce fight the
    // indicator.
    if (phase === "pulling" || phase === "armed") e.preventDefault();
    updatePullIndicator(phase, deltaY);
  }

  function onPullTouchEnd() {
    if (pullStartY === null) return;
    var phase = pullLastPhase;
    var deltaYAtRelease = pullLastDeltaY;
    resetPullGesture();
    if (phase === "armed") {
      runPullRefresh(deltaYAtRelease);
    } else {
      updatePullIndicator("idle", 0);
    }
  }

  function onPullTouchCancel() {
    resetPullGesture();
    updatePullIndicator("idle", 0);
  }

  // PT-33 (architect's ruling § 6): the trackpad-overscroll adapter.
  // `wheel` has no start/end marker the way touch does, so EVERY event
  // (including ones the reducer will refuse) is routed through
  // wheelPullReduce -- an early return here that skips the reducer for
  // events it could cheaply reject would silently reopen the momentum hole
  // this whole issue exists to close (§4 property 1, JC2).
  function onWheel(e) {
    // PT-33 (ruling § 7): touch holds the arbiter token -- defer entirely.
    if (pullSource === "touch") return;
    wheelState = wheelPullReduce(wheelState, {
      deltaY: e.deltaY,
      deltaX: e.deltaX,
      deltaMode: e.deltaMode,
      timeStamp: e.timeStamp, // NOT Date.now() -- one clock for the whole gesture
      atScrollTop: window.scrollY === 0,
      horizontalDominant: Math.abs(e.deltaX) > Math.abs(e.deltaY),
    });
    var cancelled = wheelCancelFlags();
    var phase = wheelState.status === "pulling"
      ? pullPhase({ atScrollTop: true, deltaY: wheelState.distance, cancelled: cancelled })
      : "idle";
    if (phase === "pulling" || phase === "armed") {
      // PT-33 (ruling § 7): claim the token only once a gesture actually
      // arms/pulls -- not on every wheel event, or ordinary desktop
      // scrolling would hold it forever and lock out touch.
      pullSource = "wheel";
      e.preventDefault();
    }
    updatePullIndicator(phase, wheelState.distance);
    clearTimeout(wheelIdleTimer);
    wheelIdleTimer = setTimeout(onWheelQuiesce, WHEEL_PULL_IDLE_MS);
  }

  // PT-33 (ruling § 3): quiescence IS the release signal -- fires when the
  // wheel stream has gone silent for WHEEL_PULL_IDLE_MS and the accumulated
  // distance is still armed. Resets to idle but DELIBERATELY keeps
  // wheelState.lastTs (ruling § 6 pseudocode) rather than reinitializing it
  // to -Infinity -- the next wheel event's own opening-gap check still needs
  // to measure against when this gesture actually last moved, not treat
  // itself as the very first wheel event ever seen.
  function onWheelQuiesce() {
    var cancelled = wheelCancelFlags();
    if (wheelPullShouldFire(wheelState, cancelled)) {
      runPullRefresh(wheelState.distance);
    } else {
      updatePullIndicator("idle", 0);
    }
    wheelState = { status: "idle", distance: 0, lastTs: wheelState.lastTs };
    pullSource = null;
  }

  // PT-32 (ruling § 4): reuses refreshBoardSilently -- the same ETag-
  // conditional GET the poll fallback uses, satisfying AC1's "same path...
  // no full page reload" with zero new network code. Promise.all with a
  // PULL_MIN_SPINNER_MS floor so an instant localhost round trip doesn't
  // flash the spinner; the boolean result drives which toast fires --
  // "Board updated" when refreshBoardSilently applied new data, "Already
  // up to date" on a 304 (the common case in live mode, ruling § 6 -- this
  // toast is what turns that silent no-op into the confirmation the user
  // was asking for).
  // Three-way toast off refreshBoardSilently's three-state result (see its
  // comment) -- "unchanged" and "failed" are deliberately different toasts,
  // not one collapsed "nothing happened" message.
  // PT-32 (architect's micro-ruling § 3): pullRefreshToast (board-logic.js)
  // is the single home for the copy/isError mapping -- not a board.js-local
  // lookup table, so the "unrecognized outcome -> the FAILED shape, not a
  // neutral one" rule lives in the one function QA's suite can hold to it.
  // PULL_MIN_SPINNER_MS's floor (below) applies to all three outcomes with
  // no branching -- a failure resolving faster than a success would read
  // as "the gesture didn't register" rather than "the refresh was tried
  // and failed".
  function runPullRefresh(deltaYAtRelease) {
    state.pullRefreshing = true;
    updatePullIndicator("refreshing", deltaYAtRelease);
    var minDelay = new Promise(function (resolve) { setTimeout(resolve, PULL_MIN_SPINNER_MS); });
    // PT-44: routes through clearEtagAndRefresh, not the plain silent
    // refresh helper -- a pull-to-refresh is a deliberate user ask for
    // the LATEST state; a cached etag could otherwise 304 it against a
    // release-state change (a bare `git tag`, no file mtime touched).
    Promise.all([clearEtagAndRefresh(), minDelay]).then(function (results) {
      var outcome = results[0];
      state.pullRefreshing = false;
      updatePullIndicator("idle", 0);
      var toast = pullRefreshToast(outcome);
      showToast(toast.message, toast.isError);
    });
  }

  // PT-32 (ruling § 5): NO feature detection -- attach unconditionally.
  // On a device that never produces touch events, none of these listeners
  // ever fire, which is exactly AC4's "degrades to nothing"; an
  // "ontouchstart" in window branch would be one more thing that can be
  // wrong for zero benefit. touchmove is the only listener registered
  // { passive: false } (ruling § 3) -- it's the only one that ever calls
  // preventDefault.
  function wirePullToRefresh() {
    pullIndicatorEl = document.getElementById("pull-indicator");
    if (!pullIndicatorEl) return; // bail early, ruling § 5
    document.addEventListener("touchstart", onPullTouchStart, { passive: true });
    document.addEventListener("touchmove", onPullTouchMove, { passive: false });
    document.addEventListener("touchend", onPullTouchEnd, { passive: true });
    document.addEventListener("touchcancel", onPullTouchCancel, { passive: true });
    // PT-33 (ruling § 6): non-passive -- preventDefault is what keeps macOS's
    // native rubber-band from drawing alongside our own indicator (§ 8,
    // JC3). No feature detection, consistent with PT-32 § 5: on a device
    // that never fires `wheel`, this listener simply never runs.
    document.addEventListener("wheel", onWheel, { passive: false });
  }

  // ------------------------------------------------------------------
  // PT-1: live push (SSE) with a polling fallback.
  //
  // The 4s poll (below) is the byte-identical fallback path this always
  // had -- connectLive() only decides *when* it runs: continuously in
  // any browser without EventSource, or as coverage during the
  // connecting/reconnecting phase in one that has it. It's never torn
  // out or altered, only started/stopped.
  // ------------------------------------------------------------------

  var pollTimer = null;

  function startPolling() {
    if (pollTimer) return; // already running -- idempotent
    pollTimer = setInterval(refreshBoardSilently, 4000);
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function setConnectionState(newState) {
    var el = document.getElementById("connection-state");
    if (!el) return;
    el.textContent = newState === "live" ? "● live" : "○ polling";
    el.className = "connection-state " + newState;
  }

  function connectLive() {
    if (typeof window.EventSource === "undefined") {
      // No behavior change for browsers/environments where EventSource
      // isn't available -- straight back to the untouched polling path.
      setConnectionState("polling");
      startPolling();
      return;
    }
    // Poll runs as coverage until SSE actually opens, and resumes
    // whenever it errors -- EventSource retries the connection natively
    // (with its own backoff) without any code here re-creating it.
    setConnectionState("polling");
    startPolling();
    var source = new EventSource("/api/events");
    source.onopen = function () {
      setConnectionState("live");
      stopPolling();
    };
    source.onmessage = function () {
      refreshBoardSilently();
    };
    source.onerror = function () {
      setConnectionState("polling");
      startPolling();
    };
  }

  // PT-30 (architect's ruling § 4): "Expand all" unions state.renderedLaneKeys
  // -- the lane keys the LAST renderKanban() pass actually rendered, i.e.
  // exactly what's currently visible under the active filters and
  // collapsedRepos state -- into state.expandedLanes. Additive only
  // (expandAllLanes never removes a key), so a lane that's expanded but
  // hidden by a filter keeps its state.
  function expandAll() {
    if (!state.board) return;
    state.expandedLanes = expandAllLanes(state.expandedLanes, state.renderedLaneKeys);
    persistExpandedLanes();
    render();
  }

  // PT-30 (architect's ruling § 4): sets the map to empty AND removes the
  // storage key entirely -- not a stored "everything closed". The default
  // state IS the empty set, and no-key is the cleanest representation of
  // empty; this is also the reset gesture the issue's Problem section
  // names ("reset gesture = collapse the lanes again").
  function collapseAll() {
    if (!state.board) return;
    state.expandedLanes = Object.create(null);
    clearViewState(viewStateKey(primaryRootId(state.board)));
    render();
  }

  function wireFilters() {
    document.getElementById("filter-text").addEventListener("input", function (e) {
      state.filters.text = e.target.value; render();
    });
    document.getElementById("filter-milestone").addEventListener("change", function (e) {
      state.filters.milestone = e.target.value; render();
    });
    document.getElementById("filter-assignee").addEventListener("change", function (e) {
      state.filters.assignee = e.target.value; render();
    });
    document.getElementById("filter-label").addEventListener("change", function (e) {
      state.filters.label = e.target.value; render();
    });
    document.getElementById("filter-repo").addEventListener("change", function (e) {
      state.filters.repo = e.target.value; render();
    });
    document.getElementById("filter-cancelled").addEventListener("change", function (e) {
      state.showCancelled = e.target.checked; render();
    });
    // PT-42: unlike showCancelled (a pure client-side display filter over
    // a payload that already contains every status), showArchived changes
    // what the SERVER sends -- archive/ is never in the response at all
    // unless ?archived=1 is on the request. A bare render() here would
    // re-render the SAME already-fetched board and show nothing new.
    // state.etag is cleared BEFORE the refetch: an etag minted for one
    // payload shape (archived on/off) must never be sent as
    // If-None-Match for the other, or the server would wrongly 304 a
    // request for the shape it hasn't served yet.
    document.getElementById("filter-archived").addEventListener("change", function (e) {
      state.showArchived = e.target.checked;
      clearEtagAndRefresh();
    });
    document.getElementById("toggle-swimlanes").addEventListener("change", function (e) {
      state.swimlanesOn = e.target.checked; render();
    });
    document.getElementById("expand-all-btn").addEventListener("click", expandAll);
    document.getElementById("collapse-all-btn").addEventListener("click", collapseAll);
  }

  // Minimal create affordance (title + milestone only) — see
  // process/TRACKER.md's board out-of-scope line ("issue creation from the
  // board beyond title + milestone") and architect conformance review
  // finding 5. Calls the existing apiCreateIssue via the existing
  // POST /api/issue route; nothing new server-side.
  function wireNewIssueForm() {
    var btn = document.getElementById("new-issue-btn");
    var form = document.getElementById("new-issue-form");
    var titleInput = document.getElementById("new-issue-title");
    var milestoneSelect = document.getElementById("new-issue-milestone");
    var submitBtn = document.getElementById("new-issue-submit");
    var cancelBtn = document.getElementById("new-issue-cancel");

    function closeForm() {
      form.hidden = true;
      titleInput.value = "";
      milestoneSelect.value = "";
    }

    btn.addEventListener("click", function () {
      form.hidden = !form.hidden;
      if (!form.hidden) titleInput.focus();
    });
    cancelBtn.addEventListener("click", closeForm);
    submitBtn.addEventListener("click", submit);
    titleInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") submit();
      if (e.key === "Escape") closeForm();
    });

    function submit() {
      var title = titleInput.value.trim();
      if (!title) { titleInput.focus(); return; }
      submitBtn.disabled = true;
      apiCreateIssue({ title: title, milestone: milestoneSelect.value || null }).then(function (issue) {
        submitBtn.disabled = false;
        closeForm();
        showToast((issue && issue.id ? issue.id : "Issue") + " created.");
        refreshBoardSilently();
      }).catch(function () {
        submitBtn.disabled = false;
        showToast("Failed to create issue.", true);
      });
    }
  }

  function init() {
    // PT-55 (architect ruling § 3): toggled here (not applied inline at
    // module scope) so it reads alongside the rest of init's one-time
    // setup -- `document.body` is guaranteed to exist by DOMContentLoaded,
    // the event this function is bound to below.
    if (isEmbedMode) document.body.classList.add("embed");
    wireFilters();
    wireNewIssueForm();
    wirePullToRefresh();
    apiGetBoard().then(function (data) {
      state.board = data;
      // PT-38 (architect's ruling § 6): swimlanesOn's payload-driven
      // initial value -- ONLY here, the one-time initial-load path, never
      // in refreshBoardSilently's recurring poll/SSE-refresh path. Config
      // sets the STARTING value; the Swimlanes checkbox owns it for the
      // rest of the session (state.swimlanesOn = e.target.checked, below)
      // -- re-deriving from every subsequent payload would silently
      // overwrite a user's manual toggle the next time the board polls.
      // An older server's payload (no `swimlane` key) reads `undefined`,
      // and `undefined !== "none"` is `true` -- the pre-PT-38 hardcoded
      // default, preserved for forward/backward compat.
      state.swimlanesOn = data.swimlane !== "none";
      // PT-30: the ONE call site on the board-load path -- restoreViewStateOnce
      // is a no-op on every subsequent apiGetBoard resolution (refreshBoardSilently's
      // 4s poll, SSE push, focus/visibilitychange), guarded by state.viewStateRestored.
      restoreViewStateOnce();
      render();
    });
    connectLive();
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") refreshBoardSilently();
    });
    window.addEventListener("focus", refreshBoardSilently);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
