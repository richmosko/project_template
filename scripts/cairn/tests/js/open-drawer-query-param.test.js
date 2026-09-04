"use strict";

// PT-79 delta (team-lead's Chrome re-check on b934262): "?open=<id> never
// opens the drawer in the embedded board, for live PT-77 or archived
// PT-69" -- surfaced by PT-79's bar-click fix, which now navigates to
// `/dashboard/issues?open=<id>` (see TokenCostChart.svelte's
// onTooltipClick -> window.location.href).
//
// Scope note, stated plainly: this file pins ONLY the part that's safely
// testable without a real browser/DOM -- parsing `?open=<id>` out of a
// location.search-shaped string, extracted as a pure function
// (board.js's current `new URLSearchParams(window.location.search).get(
// "open")` inline call, unchanged logic, just made unit-testable). The
// DEEPER "resolving across archive" half of the delta is NOT pinned
// here: `openDrawer(id)` already calls `apiGetIssue(id)` -> `GET
// /api/issue/<id>`, and that server route already searches live-then-
// archived (INTERFACE.md's find_issue_path contract) -- so the failure
// is NOT obviously a missing archive-search step on the client. Without
// being able to run the browser myself (ToolSearch/claude-in-chrome is
// disabled for this session), I can't diagnose whether the real break
// is in the dashboard's SPA routing not re-firing DOMContentLoaded, a
// timing race with apiGetBoard, or something else -- writing a test
// around a guessed root cause risks pinning the WRONG fix. Flagging this
// gap explicitly rather than fabricating a test that looks like coverage
// but doesn't test the actual failure.
//
// Proposed function (negotiable): CairnLogic.parseOpenIssueId(search)
// -> string | null, board.js's init() calls this instead of inlining
// the URLSearchParams read.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("parseOpenIssueId exists on CairnLogic", () => {
  assert.equal(
    typeof CairnLogic.parseOpenIssueId,
    "function",
    "CairnLogic.parseOpenIssueId does not exist yet -- see this file's own module comment " +
      "for scope (query-param parsing only, not the deeper archive-resolution question)"
  );
});

test("returns the id when ?open=<id> is present", () => {
  const id = CairnLogic.parseOpenIssueId("?open=PT-77");
  assert.equal(id, "PT-77");
});

test("returns the id for an archived-shaped id the same way as a live one", () => {
  // Parsing itself has no notion of live vs. archived -- that
  // distinction is resolved server-side. This just confirms the parse
  // step doesn't special-case (or accidentally reject) any particular
  // id shape.
  const id = CairnLogic.parseOpenIssueId("?open=PT-69");
  assert.equal(id, "PT-69");
});

test("returns null when there is no open param at all", () => {
  const id = CairnLogic.parseOpenIssueId("?embed=1");
  assert.equal(id, null);
});

test("returns null for an empty search string", () => {
  const id = CairnLogic.parseOpenIssueId("");
  assert.equal(id, null);
});

test("works alongside other query params, in either order", () => {
  assert.equal(CairnLogic.parseOpenIssueId("?embed=1&open=PT-42"), "PT-42");
  assert.equal(CairnLogic.parseOpenIssueId("?open=PT-42&embed=1"), "PT-42");
});

test("decodes a URL-encoded id", () => {
  const id = CairnLogic.parseOpenIssueId("?open=PT-42%2Fsub");
  assert.equal(id, "PT-42/sub");
});
