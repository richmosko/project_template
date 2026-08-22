"use strict";

// PT-25: childProgress(issues, issue) -- the board's parent-card n/m
// badge (done-children / total-children), computed client-side, mirroring
// milestoneProgress's done/total-over-a-filtered-set shape (architect's
// ruling). Child lookup is repo-scoped from the FIRST line, not added
// after a review finding: build_board_payload's child_counts keys off
// the bare parent id with no repo dimension, safe only because it runs
// per-root server-side. Computed client-side over the aggregated
// multi-root payload, an unscoped filter would fuse two repos' same-id
// issues' children into one shared, wrong count -- the fourth instance of
// the isDraggable/issueMilestoneKey/groupByMilestone bare-id-across-roots
// defect class (all three caught late). This cross-repo regression test
// is deliberately the FIRST test in this file, ahead of every other
// PT-25 feature test -- the acceptance criterion's explicit ordering,
// not a style choice.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function crossRepoIssues() {
  return [
    { id: "PT-14", parent: null, repo: "PT", status: "todo", title: "Parent in PT" },
    { id: "PT-15", parent: "PT-14", repo: "PT", status: "done", title: "Child A" },
    { id: "PT-16", parent: "PT-14", repo: "PT", status: "todo", title: "Child B" },
    { id: "SB-14", parent: null, repo: "SB", status: "todo", title: "Unrelated parent in SB" },
    { id: "SB-15", parent: "SB-14", repo: "SB", status: "done", title: "SB's own child" },
  ];
}

test("cross-repo regression: two repos' same-id parent issues never fuse their child counts", () => {
  var issues = crossRepoIssues();
  var pt = CairnLogic.childProgress(issues, { id: "PT-14", repo: "PT" });
  // A same-id "PT-14" scoped to repo SB must NOT pick up PT's children --
  // SB's own parent issue in this fixture is "SB-14", not "PT-14", so this
  // must read as 0/0, not silently inherit PT's 1/2.
  var sb = CairnLogic.childProgress(issues, { id: "PT-14", repo: "SB" });
  assert.deepEqual(pt, { done: 1, total: 2 });
  assert.deepEqual(sb, { done: 0, total: 0 });
  assert.notDeepEqual(pt, sb);
});

test("counts done/total among an issue's own children", () => {
  var result = CairnLogic.childProgress(crossRepoIssues(), { id: "PT-14", repo: "PT" });
  assert.deepEqual(result, { done: 1, total: 2 });
});

test("an issue with no children counts as 0/0", () => {
  var result = CairnLogic.childProgress(crossRepoIssues(), { id: "PT-16", repo: "PT" });
  assert.deepEqual(result, { done: 0, total: 0 });
});

test("childrenOf returns the child records themselves, sorted numerically by id", () => {
  var issues = [
    { id: "PT-1", parent: null, repo: "PT", status: "todo", title: "Parent" },
    { id: "PT-10", parent: "PT-1", repo: "PT", status: "todo", title: "Tenth child" },
    { id: "PT-2", parent: "PT-1", repo: "PT", status: "done", title: "Second child" },
    { id: "PT-9", parent: "PT-1", repo: "PT", status: "todo", title: "Ninth child" },
  ];
  var kids = CairnLogic.childrenOf(issues, { id: "PT-1", repo: "PT" });
  assert.deepEqual(kids.map(function (i) { return i.id; }), ["PT-2", "PT-9", "PT-10"]);
});

test("childrenOf is repo-scoped the same way childProgress is", () => {
  var issues = crossRepoIssues();
  var kids = CairnLogic.childrenOf(issues, { id: "PT-14", repo: "SB" });
  assert.deepEqual(kids, []);
});
