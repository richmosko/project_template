"use strict";

// PT-22: milestoneLabel(board, id, repoId) -- the swimlane-header /
// filter-milestone / new-issue-milestone label builder. PT-3's escape:
// a bare-id lookup with no repo scoping meant repo B's "0.5" lane
// rendered repo A's milestone name ("polish" instead of
// "sibling-polish") -- caught only by team-lead's Chrome pass, not the
// 258-test Python suite (board.js has zero server-side representation).

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function board() {
  return {
    milestones: [
      { id: "0.5", name: "polish", repo: "PT" },
      { id: "0.5", name: "sibling-polish", repo: "SB" },
      { id: "0.4", name: "hardening", repo: "PT" },
      { id: "A", name: "", repo: "PT" }, // explicit empty name -- fallback case
    ],
  };
}

test("renders id · name when a repo-scoped match has a name", () => {
  assert.equal(CairnLogic.milestoneLabel(board(), "0.5", "PT"), "0.5 · polish");
});

test("PT-3 regression: a same-id milestone in another repo never leaks through", () => {
  // This is the exact bug: SB's "0.5" must never render PT's "polish".
  assert.equal(CairnLogic.milestoneLabel(board(), "0.5", "SB"), "0.5 · sibling-polish");
  assert.notEqual(CairnLogic.milestoneLabel(board(), "0.5", "SB"), "0.5 · polish");
});

test("falls back to the bare id when the repo-scoped milestone has no name", () => {
  assert.equal(CairnLogic.milestoneLabel(board(), "A", "PT"), "A");
});

test("falls back to the bare id when no milestone matches at all (dangling ref)", () => {
  assert.equal(CairnLogic.milestoneLabel(board(), "9.9", "PT"), "9.9");
});

test("falls back to the bare id for the (none) swimlane key", () => {
  assert.equal(CairnLogic.milestoneLabel(board(), "(none)", "PT"), "(none)");
});

test("repoId omitted (null/undefined) does not scope by repo -- single-root callers", () => {
  // Single-root boards never have two milestones sharing an id, so the
  // first match is the only match in practice; this pins the contract
  // for callers that pass no repoId at all (pre-PT-3 call shape).
  var singleRootBoard = { milestones: [{ id: "1.0", name: "MVP", repo: "PT" }] };
  assert.equal(CairnLogic.milestoneLabel(singleRootBoard, "1.0"), "1.0 · MVP");
  assert.equal(CairnLogic.milestoneLabel(singleRootBoard, "1.0", null), "1.0 · MVP");
});
