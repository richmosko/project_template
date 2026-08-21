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
    // PT-16: per-swimlane collapse, view-local only -- keyed by the same
    // lane key renderKanban groups on (a milestone id, or the literal
    // string "(none)"), or (PT-3, multi-root) a "<root.id>::<milestone
    // key>" composite -- see milestoneLaneEl. Never persisted -- the
    // board is a stateless lens.
    collapsedLanes: {},
    // PT-3: per-repo-section collapse under repo grouping, keyed by
    // root.id. Same in-memory-only contract as collapsedLanes.
    collapsedRepos: {},
  };

  // ------------------------------------------------------------------
  // API
  // ------------------------------------------------------------------

  function apiGetBoard() {
    var headers = {};
    if (state.etag) headers["If-None-Match"] = state.etag;
    return fetch("/api/board", { headers: headers }).then(function (resp) {
      if (resp.status === 304) return null;
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
  // Filtering
  // ------------------------------------------------------------------

  // PT-3: milestone ids are NOT unique across roots (a milestone "0.5"
  // in repo A is unrelated to a milestone "0.5" in repo B) -- the lookup
  // must be repo-scoped, or an issue can silently inherit a different
  // repo's same-id milestone's major. `repoId` is optional only for
  // single-root callers where there's nothing to disambiguate; every
  // multi-root call site below passes it. (architect + team-lead review,
  // 2026-08-21: "the union changes only the final id comparison, the
  // lookup stays repo-qualified".)
  function milestoneMajor(milestoneId, repoId) {
    var candidates = (state.board.milestones || []).filter(function (m) { return m.id === milestoneId; });
    var ms = repoId != null ? candidates.filter(function (m) { return m.repo === repoId; })[0] : candidates[0];
    return ms ? ms.major : null;
  }

  function filteredIssues() {
    if (!state.board) return [];
    var f = state.filters;
    var text = f.text.trim().toLowerCase();
    return state.board.issues.filter(function (issue) {
      if (!state.showCancelled && issue.status === "cancelled") return false;
      if (state.currentMajor !== "all") {
        // Lookup repo-scoped (see milestoneMajor's docstring); the
        // comparison against the selected tab is a bare-id union across
        // repos (team-lead ruling -- majors are a portfolio-wide concept
        // in this template's versioning convention, unlike milestones).
        var major = milestoneMajor(issue.milestone, issue.repo);
        if (major !== state.currentMajor) return false;
      }
      // PT-3: milestone ids collide across roots (unlike issue ids), so
      // the filter-milestone select's value is always a repo-qualified
      // composite "<repo>::<milestone>" -- see its populateSelect call in
      // renderHeader. Comparing bare issue.milestone here would match an
      // unrelated same-id milestone in another repo.
      if (f.milestone && (issue.repo + "::" + (issue.milestone || "")) !== f.milestone) return false;
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
    // (team-lead ruling, 2026-08-21).
    var seenMajorIds = {};
    (board.majors || []).forEach(function (major) {
      if (seenMajorIds[major.id]) return;
      seenMajorIds[major.id] = true;
      var btn = document.createElement("button");
      btn.textContent = major.id;
      btn.className = state.currentMajor === major.id ? "active" : "";
      btn.onclick = function () { state.currentMajor = major.id; render(); };
      majorsTabs.appendChild(btn);
    });

    document.getElementById("tab-kanban").className = isListView ? "" : "active";
    document.getElementById("tab-list").className = isListView ? "active" : "";

    var progressEl = document.getElementById("milestone-progress");
    progressEl.innerHTML = "";
    (board.milestones || []).forEach(function (ms) {
      // PT-3: scope the issue count to THIS record's own repo -- matching
      // on bare milestone id alone would fuse two repos' done/total into
      // one number, shown identically on both repos' same-id entries.
      var msIssues = board.issues.filter(function (i) { return i.milestone === ms.id && i.repo === ms.repo; });
      if (msIssues.length === 0 && ms.kind !== "product") return;
      var done = msIssues.filter(function (i) { return i.status === "done"; }).length;
      var span = document.createElement("span");
      var tag = ms.ga ? " · GA" : "";
      var target = ms.target_tag ? " · " + ms.target_tag : "";
      var repoPrefix = multiRoot ? ms.repo + " · " : "";
      span.textContent = repoPrefix + ms.id + " · " + (ms.name || "") + tag + target + " · " + done + "/" + msIssues.length + " done";
      progressEl.appendChild(span);
    });

    // PT-3: milestone ids collide across roots -- the filter value is
    // always a repo-qualified composite "<repo>::<milestone>" (mirrors
    // filteredIssues' comparison), built from the (repo, milestone) pairs
    // actually present among issues, not board.milestones (an unused
    // milestone in a filter dropdown would be dead weight here, unlike
    // new-issue-milestone below where an *empty* milestone must still be
    // choosable).
    var msPairs = [];
    var seenMsKeys = {};
    board.issues.forEach(function (i) {
      if (!i.milestone) return;
      var k = i.repo + "::" + i.milestone;
      if (seenMsKeys[k]) return;
      seenMsKeys[k] = true;
      msPairs.push({ key: k, repo: i.repo, milestone: i.milestone });
    });
    msPairs.sort(function (a, b) { return a.key < b.key ? -1 : a.key > b.key ? 1 : 0; });
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

    // PT-3 (team-lead ruling, NON-NEGOTIABLE -- data integrity, not
    // cosmetics): creation always writes to the PRIMARY root only, so
    // this select must offer PRIMARY-root milestones exclusively. Ever
    // listing a foreign milestone id here would let a user create a
    // primary-root issue referencing a milestone that doesn't exist
    // there, which `cairn check` then reports as an unknown-milestone
    // lint error. All known primary milestones, not just ones already
    // carrying an issue -- a fresh milestone with zero issues yet should
    // still be choosable when creating the first one for it.
    // Null-guard (architect review, 2026-08-21): mirrors cardEl/handleDrop
    // -- a payload with no `roots`/`repo` dimension at all (stale cached
    // board.js against an older cairn serve) must not filter every
    // milestone out via `undefined === null`; treat "no repo dimension"
    // as "everything is the primary" rather than an empty, broken select.
    populateSelect(
      "new-issue-milestone",
      (board.milestones || [])
        .filter(function (m) { return primaryId == null || m.repo === primaryId; })
        .map(function (m) { return m.id; })
        .sort(),
      function (v) { return milestoneLabel(board, v, primaryId); }
    );
  }

  function uniqueSorted(values) {
    var set = {};
    values.forEach(function (v) { if (v) set[v] = true; });
    return Object.keys(set).sort();
  }

  // PT-16: "id · name", falling back to the bare id when the milestone has
  // no `name` or `id` names no milestone file at all (e.g. the "(none)"
  // swimlane key, or a dangling milestone reference) -- mirrors the
  // progress-strip's existing id·name rendering (renderHeader, above).
  //
  // PT-3: `repoId`, when given, scopes the lookup so repo B's "0.5"
  // never renders repo A's milestone name (the collision architect
  // caught: this exact bug would have shown up in the first repo-grouped
  // screenshot). Every multi-root call site passes it.
  function milestoneLabel(board, id, repoId) {
    var candidates = (board.milestones || []).filter(function (m) { return m.id === id; });
    var ms = repoId != null ? candidates.filter(function (m) { return m.repo === repoId; })[0] : candidates[0];
    return ms && ms.name ? id + " · " + ms.name : id;
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

  // PT-3: the id of the one root with primary:true in the current board
  // payload. Single-root payloads carry exactly one root (always
  // primary), so this is safe to call unconditionally.
  function primaryRootId(board) {
    var roots = (board && board.roots) || [];
    for (var i = 0; i < roots.length; i++) {
      if (roots[i].primary) return roots[i].id;
    }
    return null;
  }

  function cardEl(issue) {
    var card = document.createElement("div");
    card.className = "card";
    // PT-3: a foreign-root card is not draggable -- UI courtesy only
    // (§3.3.2: "not the security boundary"), the server's 403
    // read_only_root is what actually enforces this.
    //
    // Null-guard (architect review, 2026-08-21): a payload with no
    // `roots` dimension at all -- e.g. stale board.js cached against an
    // older cairn serve process, since _send_static sets no
    // Cache-Control -- makes primaryRootId return null and issue.repo
    // undefined. `undefined === null` is false, which would make every
    // card undraggable and every drop refuse itself with a misleading
    // "read-only" toast. Treat "no repo dimension at all" as "everything
    // is the primary" (the true pre-PT-3 behavior) rather than degrading
    // into a board where nothing drags for the wrong reason.
    var cardPrimaryId = primaryRootId(state.board);
    card.draggable = cardPrimaryId == null || issue.repo === cardPrimaryId;
    card.dataset.id = issue.id;
    card.addEventListener("dragstart", function (e) {
      card.classList.add("dragging");
      e.dataTransfer.setData("text/plain", issue.id);
    });
    card.addEventListener("dragend", function () { card.classList.remove("dragging"); });
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
    if (issue.sub_issue_count) meta.appendChild(chip("subissues", issue.sub_issue_count + " sub"));
    if (issue.parent) meta.appendChild(chip("subissues", "↳ " + issue.parent));
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

  var BOARD_COLUMNS = ["backlog", "todo", "in-progress", "in-review", "done"];

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

  // PT-16, extracted for PT-3 (pure extraction -- zero behavior change):
  // one milestone swimlane -- id·name label (milestoneLabel falls back to
  // the bare key for "(none)" and any dangling milestone id -- no
  // special-casing needed) + a per-lane collapse toggle. Collapse state
  // lives only in state.collapsedLanes (in-memory) -- never written to
  // disk, no network call fires on toggle.
  function milestoneLaneEl(board, key, issues, stateKey, repoId) {
    var lane = document.createElement("div");
    lane.className = "swimlane";

    // PT-3 (architect amendment b): `stateKey` is always an explicit,
    // repo-qualified composite ("<root.id>::<milestone key>") -- every
    // caller passes one, single-root included. There are no JS tests and
    // collapse keys never appear in the DOM, so there was nothing to gain
    // from keeping the old bare-id shape as a conditional special case:
    // one read/write path beats two that have to stay in sync.
    var collapsed = !!state.collapsedLanes[stateKey];
    var laneHeader = document.createElement("div");
    laneHeader.className = "swimlane-header";

    var toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "swimlane-toggle";
    toggleBtn.textContent = collapsed ? "▸" : "▾";
    toggleBtn.setAttribute("aria-label", (collapsed ? "Expand " : "Collapse ") + key);
    toggleBtn.addEventListener("click", function () {
      state.collapsedLanes[stateKey] = !collapsed;
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

    lane.appendChild(laneHeader);
    if (!collapsed) lane.appendChild(columnsFor(issues));
    return lane;
  }

  // PT-3: one repo section under repo-grouped multi-root view -- a
  // top-level collapse toggle (state.collapsedRepos, in-memory only, same
  // contract as collapsedLanes) around either milestone lanes (Swimlanes
  // checkbox on -- reuses milestoneLaneEl unchanged, composite state key)
  // or a flat column board (Swimlanes checkbox off). Repo grouping itself
  // is NOT governed by the Swimlanes checkbox -- team-lead's ruling:
  // repo separation is the entire point of this view, so it stays on
  // regardless; the checkbox only decides whether milestone lanes
  // subdivide *within* a section.
  function repoSectionEl(board, root, issues) {
    var section = document.createElement("div");
    section.className = "repo-group";

    var collapsed = !!state.collapsedRepos[root.id];
    var header = document.createElement("div");
    header.className = "repo-group-header";

    var toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "repo-group-toggle";
    toggleBtn.textContent = collapsed ? "▸" : "▾";
    toggleBtn.setAttribute("aria-label", (collapsed ? "Expand " : "Collapse ") + root.label);
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
        var byMilestone = {};
        var order = [];
        issues.forEach(function (issue) {
          var key = issue.milestone || "(none)";
          if (!byMilestone[key]) { byMilestone[key] = []; order.push(key); }
          byMilestone[key].push(issue);
        });
        order.sort();
        order.forEach(function (key) {
          section.appendChild(milestoneLaneEl(board, key, byMilestone[key], root.id + "::" + key, root.id));
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

    // Single-root: byte-identical to the pre-PT-3 code path -- no
    // .repo-group wrapper anywhere in the DOM (architect's PT-3 review
    // criterion 2: the multi-root branch is strictly additive).
    if (roots.length <= 1) {
      if (!state.swimlanesOn) {
        main.appendChild(columnsFor(issues));
        return;
      }
      var byMilestone = {};
      var order = [];
      issues.forEach(function (issue) {
        var key = issue.milestone || "(none)";
        if (!byMilestone[key]) { byMilestone[key] = []; order.push(key); }
        byMilestone[key].push(issue);
      });
      if (order.length === 0) {
        main.innerHTML = '<div class="empty-state">No issues match the current filters.</div>';
        return;
      }
      order.sort();
      var soleRootId = primaryRootId(board);
      order.forEach(function (key) {
        main.appendChild(milestoneLaneEl(board, key, byMilestone[key], soleRootId + "::" + key, soleRootId));
      });
      return;
    }

    // Multi-root: repo-grouped (ruling A, 2026-08-21) -- top-level
    // section per root, primary first then remaining roots by id.
    if (issues.length === 0) {
      main.innerHTML = '<div class="empty-state">No issues match the current filters.</div>';
      return;
    }
    var orderedRoots = roots.slice().sort(function (a, b) {
      if (a.primary !== b.primary) return a.primary ? -1 : 1;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
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
    // Null-guard (architect review, 2026-08-21): mirrors cardEl's --
    // a payload with no `roots` dimension makes primaryRootId return
    // null; treat that as "everything is the primary" rather than
    // refusing every drop with a toast that blames the wrong thing.
    var dropPrimaryId = primaryRootId(state.board);
    if (dropPrimaryId != null && issue.repo !== dropPrimaryId) {
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

  function refreshBoardSilently() {
    return apiGetBoard().then(function (data) {
      if (data) { state.board = data; render(); }
    }).catch(function () {});
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
    apiGetBoard().then(function (data) {
      state.board = data;
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
