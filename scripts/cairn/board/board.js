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
  // PT-29: BOARD_COLUMNS relocated into board-logic.js (architect's
  // ruling § 4) as the single canonical column-order list -- laneSummary
  // iterates the SAME array makeColumn's column set is built from, not a
  // second board.js-local copy.
  var BOARD_COLUMNS = CairnLogic.BOARD_COLUMNS;
  var laneExpanded = CairnLogic.laneExpanded;
  var nextExpandedLanes = CairnLogic.nextExpandedLanes;
  var disclosureToken = CairnLogic.disclosureToken;
  var laneSummary = CairnLogic.laneSummary;
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

  var STATUS_LABELS = {
    "backlog": "Backlog",
    "todo": "Todo",
    "in-progress": "In Progress",
    "in-review": "In Review",
    "done": "Done",
    "cancelled": "Cancelled",
  };

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

  var state = {
    board: null,       // last-known-good /api/board payload
    etag: null,
    currentMajor: "all",
    filters: { text: "", milestone: "", assignee: "", label: "", repo: "" },
    showCancelled: false,
    swimlanesOn: true,
    sortKey: "id",
    sortDir: 1,
    openIssueId: null,
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
    return fetch("/api/board", { headers: headers }).then(function (resp) {
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
      btn.textContent = majorId;
      btn.className = state.currentMajor === majorId ? "active" : "";
      btn.onclick = function () { state.currentMajor = majorId; render(); };
      majorsTabs.appendChild(btn);
    });

    document.getElementById("tab-kanban").className = isListView ? "" : "active";
    document.getElementById("tab-list").className = isListView ? "active" : "";

    var progressEl = document.getElementById("milestone-progress");
    progressEl.innerHTML = "";
    (board.milestones || []).forEach(function (ms) {
      // PT-22: milestoneProgress (board-logic.js) scopes the issue count
      // to THIS record's own repo -- matching on bare milestone id alone
      // would fuse two repos' done/total into one number, shown
      // identically on both repos' same-id entries.
      var progress = milestoneProgress(board.issues, ms);
      if (progress.total === 0 && ms.kind !== "product") return;
      var span = document.createElement("span");
      var tag = ms.ga ? " · GA" : "";
      var target = ms.target_tag ? " · " + ms.target_tag : "";
      // PT-28 (architect's ruling, confirmation #3): ids are now
      // self-qualifying (ms.id is "PT-0.6", not "0.6"), so the repo
      // qualifier this used to prepend in multi-root mode is redundant --
      // it used to read "PT · PT-0.6 · ...", the repo id shown twice.
      // Render ms.id alone in both modes. laneStateKey's OWN repo-scoped
      // composite key is unrelated and untouched (board-logic.js) -- that
      // key still needs the repo dimension for multi-root collapse-state
      // correctness; this is purely a display string.
      span.textContent = ms.id + " · " + (ms.name || "") + tag + target + " · " + progress.done + "/" + progress.total + " done";
      progressEl.appendChild(span);
    });

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
        var label = milestoneLabel(board, p.milestone, p.repo);
        return multiRoot ? p.repo + " · " + label : label;
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
    header.innerHTML = "<span>" + STATUS_LABELS[status] + "</span><span>" + issues.length + "</span>";
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

  function columnsFor(issues) {
    var columns = BOARD_COLUMNS;
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
  function milestoneLaneEl(board, key, issues, stateKey, repoId) {
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
    laneHeader.appendChild(labelSpan);

    var countSpan = document.createElement("span");
    countSpan.className = "swimlane-count";
    countSpan.textContent = issues.length;
    laneHeader.appendChild(countSpan);

    // PT-29 (architect's ruling § 1, judgment call): shown ONLY when
    // collapsed -- when expanded the columns below already carry these
    // numbers, so a second copy in the header would be noise. One chip
    // per non-empty status, board-column order (laneSummary,
    // board-logic.js) -- decides whether a collapsed lane is worth
    // opening without opening it.
    if (!expanded) {
      var summary = laneSummary(issues);
      if (summary.byStatus.length) {
        var summaryEl = document.createElement("span");
        summaryEl.className = "swimlane-summary";
        summary.byStatus.forEach(function (entry) {
          summaryEl.appendChild(chip("", (STATUS_LABELS[entry.status] || entry.status) + " · " + entry.count));
        });
        laneHeader.appendChild(summaryEl);
      }
    }

    lane.appendChild(laneHeader);
    if (expanded) lane.appendChild(columnsFor(issues));
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

    var countSpan = document.createElement("span");
    countSpan.className = "repo-group-count";
    countSpan.textContent = issues.length;
    header.appendChild(countSpan);

    section.appendChild(header);

    if (!collapsed) {
      if (state.swimlanesOn) {
        var grouped = groupByMilestone(issues);
        grouped.order.forEach(function (key) {
          var stateKey = laneStateKey(root.id, key);
          section.appendChild(milestoneLaneEl(board, key, grouped.groups[key], stateKey, root.id));
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
      if (grouped.order.length === 0) {
        main.innerHTML = '<div class="empty-state">No issues match the current filters.</div>';
        return;
      }
      var soleRootId = primaryRootId(board);
      grouped.order.forEach(function (key) {
        var stateKey = laneStateKey(soleRootId, key);
        main.appendChild(milestoneLaneEl(board, key, grouped.groups[key], stateKey, soleRootId));
        state.renderedLaneKeys.push(stateKey);
      });
      return;
    }

    // Multi-root: repo-grouped (ruling A, 2026-08-21) -- top-level
    // section per root, primary first then remaining roots by id.
    if (issues.length === 0) {
      main.innerHTML = '<div class="empty-state">No issues match the current filters.</div>';
      return;
    }
    var orderedRoots = orderRoots(roots);
    orderedRoots.forEach(function (root) {
      var repoIssues = issues.filter(function (issue) { return issue.repo === root.id; });
      if (repoIssues.length === 0) return; // no empty shells -- a repo with nothing to show renders nothing
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
        td.textContent = issue[col.key] || "";
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
    state.openIssueId = null;
    document.getElementById("drawer-overlay").classList.remove("open");
  }

  function openDrawer(id) {
    state.openIssueId = id;
    apiGetIssue(id).then(renderDrawer).catch(function () {
      showToast("Could not load " + id, true);
    });
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
    if (state.openIssueId !== issue.id) return; // user navigated away while fetching
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

    var commentsHeading = document.createElement("div");
    commentsHeading.className = "section-heading";
    commentsHeading.textContent = "Comments";
    drawer.appendChild(commentsHeading);
    var log = document.createElement("div");
    log.className = "comment-log";
    (issue.comments || []).forEach(function (c) {
      var div = document.createElement("div");
      div.className = "comment";
      var meta = document.createElement("div");
      meta.className = "comment-meta";
      meta.textContent = "@" + c.author + " — " + c.date;
      div.appendChild(meta);
      renderMarkdown(div, c.body);
      log.appendChild(div);
    });
    if (!issue.comments || !issue.comments.length) {
      var noneEl = document.createElement("div");
      noneEl.className = "empty-state";
      noneEl.textContent = "No comments yet.";
      log.appendChild(noneEl);
    }
    drawer.appendChild(log);

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
        apiMutateIssue(issue.id, { seen: issue.seen, comment: { author: "board", body: body } }).then(function (result) {
          if (result.status === 409) {
            showToast(issue.id + " changed on disk — refreshed.", true);
            openDrawer(issue.id);
            return;
          }
          if (!result.ok) { showToast("Failed to add comment", true); return; }
          openDrawer(issue.id);
          refreshBoardSilently();
        });
      };
      addComment.appendChild(postBtn);
      drawer.appendChild(addComment);
    }
  }

  function inlineField(field, type, value, issue, isLabelsList, readOnly) {
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
        submitPatch(issue, field, newValue, input, value);
      });
    }
    wrap.appendChild(input);
    return wrap;
  }

  function inlineSelect(field, options, value, issue, labels, readOnly) {
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
        var newValue = select.value === "" ? null : select.value;
        submitPatch(issue, field, newValue, select, initialSelectValue);
      });
    }
    wrap.appendChild(select);
    return wrap;
  }

  function submitPatch(issue, field, newValue, el, previousValue) {
    var patch = {};
    patch[field] = newValue;
    apiMutateIssue(issue.id, { seen: issue.seen, patch: patch }).then(function (result) {
      if (result.status === 409) {
        el.value = previousValue;
        showToast(issue.id + " changed on disk — refreshed.", true);
        openDrawer(issue.id);
        return;
      }
      if (!result.ok) {
        el.value = previousValue;
        showToast("Failed to update " + field, true);
        return;
      }
      issue.seen = result.data.seen;
      if (field === "title") {
        // PT-11: reflect the new title in the open drawer's h2 straight
        // from this response, not the next poll -- gated on `field` so a
        // different field's response (e.g. status, landing before or
        // after a title edit) never touches the h2. The card behind the
        // drawer still refreshes via the existing refreshBoardSilently()
        // path below, unchanged.
        issue.title = result.data.title;
        if (state.openIssueId === issue.id) {
          var h2 = document.querySelector("#drawer h2");
          if (h2) h2.textContent = result.data.title;
        }
      }
      refreshBoardSilently();
    });
  }

  // ------------------------------------------------------------------
  // Top-level render + polling
  // ------------------------------------------------------------------

  function render() {
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

  // ------------------------------------------------------------------
  // PT-32: pull-down-to-refresh gesture (touch only -- see board-logic.js's
  // pullPhase comment and the architect's ruling § 1 for why trackpad
  // `wheel` overscroll is deliberately NOT handled here; PT-33 is the
  // deferred follow-up). The board scrolls the DOCUMENT, not a nested
  // container (ground truth established in the ruling: nothing in
  // board.css sets overflow-y, and header.app-header is itself
  // position: sticky) -- "at scroll top" is window.scrollY === 0, and
  // listeners are registered on `document`, not any particular element.
  //
  // Gesture-tracking state lives in closure-local vars, not `state` --
  // it's per-touch-sequence bookkeeping with no meaning outside an
  // in-flight gesture, unlike state.cardDragActive/state.pullRefreshing
  // (declared with `state`) which shouldCancelPull and rendering both
  // need to read from outside this closure.
  // ------------------------------------------------------------------

  var pullStartY = null; // null = no gesture currently being tracked
  var pullStartX = null;
  var pullAtScrollTop = false;
  var pullAxisDecided = false;
  var pullHorizontalDominant = false;
  var pullLastDeltaY = 0;
  var pullLastPhase = "idle";

  function pullCancelFlags(multiTouch) {
    // PT-32 (architect's ruling § 2): board.js's job is computing every
    // cancel flag and handing the union to shouldCancelPull (board-logic.js)
    // -- never re-deriving a subset of the predicate here.
    return shouldCancelPull({
      cardDragActive: state.cardDragActive,
      drawerOpen: state.openIssueId !== null,
      multiTouch: multiTouch,
      horizontalDominant: pullHorizontalDominant,
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
    var el = document.getElementById("pull-indicator");
    if (!el) return; // PT-32 (ruling § 5): bail early if the indicator isn't in the DOM
    el.classList.toggle("dragging", phase === "pulling" || phase === "armed");
    if (phase === "idle") {
      el.hidden = true;
      el.style.transform = "";
      return;
    }
    el.hidden = false;
    el.textContent = pullIndicatorLabel(phase);
    el.style.transform = "translateY(calc(-100% + " + pullIndicatorOffset(deltaY) + "px))";
  }

  function resetPullGesture() {
    pullStartY = null;
    pullStartX = null;
    pullAxisDecided = false;
    pullHorizontalDominant = false;
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
    Promise.all([refreshBoardSilently(), minDelay]).then(function (results) {
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
    if (!document.getElementById("pull-indicator")) return; // bail early, ruling § 5
    document.addEventListener("touchstart", onPullTouchStart, { passive: true });
    document.addEventListener("touchmove", onPullTouchMove, { passive: false });
    document.addEventListener("touchend", onPullTouchEnd, { passive: true });
    document.addEventListener("touchcancel", onPullTouchCancel, { passive: true });
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
    wireFilters();
    wireNewIssueForm();
    wirePullToRefresh();
    apiGetBoard().then(function (data) {
      state.board = data;
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
