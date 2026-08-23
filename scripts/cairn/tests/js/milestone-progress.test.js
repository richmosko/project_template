"use strict";

// PT-22: milestoneProgress(issues, milestone) -- the progress strip's
// done/total count. PT-3's escape: an unscoped `i.milestone === ms.id`
// filter fused two repos' same-id milestones into one shared count
// (shown identically, wrongly, on both repos' entries) -- caught only
// by team-lead's Chrome pass.
//
// PT-44 (joint PT-40/43/44 ruling § 3, implementation-lead's Pass-1
// message, 2026-08-23): the strip is retired; milestoneProgress's return
// shape gains `isComplete` (`milestone.status === "done" ||
// milestone.status === "cancelled"`), so `{done, total}` becomes
// `{done, total, isComplete}`. This is the mechanism that makes PT-43's
// "0/0 for an archived-away milestone" bug UNREPRESENTABLE, not merely
// fixed: a done/cancelled milestone's callers branch on isComplete and
// never render a ratio at all -- "decided by the milestone's own status,
// not by counting archive/" (the ruling's own wording).
//
// Every EXISTING assertion below is updated to the new 3-key shape --
// argument-threading-only diff for the pre-existing behavior (same PT-35/
// PT-38 precedent: the done/total VALUES these tests pin are unchanged,
// only the shape grows a key), plus new PT-44 cases for isComplete itself.
// None of the existing fixture milestones carry a `status` field, so
// isComplete reads `undefined === "done" || undefined === "cancelled"` ->
// false for all of them -- expected, not a gap this file needs to close
// (the new isComplete-specific tests below cover the true/false split).

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function issues() {
  return [
    { id: "PT-1", milestone: "0.5", repo: "PT", status: "done" },
    { id: "PT-2", milestone: "0.5", repo: "PT", status: "todo" },
    { id: "PT-3", milestone: "0.5", repo: "PT", status: "done" },
    { id: "SB-1", milestone: "0.5", repo: "SB", status: "done" },
    { id: "SB-2", milestone: "0.5", repo: "SB", status: "todo" },
  ];
}

test("counts done/total scoped to the milestone's own repo", () => {
  var result = CairnLogic.milestoneProgress(issues(), { id: "0.5", repo: "PT" });
  assert.deepEqual(result, { done: 2, total: 3, isComplete: false });
});

test("PT-3 regression: two repos' same-id milestones never fuse their counts", () => {
  var pt = CairnLogic.milestoneProgress(issues(), { id: "0.5", repo: "PT" });
  var sb = CairnLogic.milestoneProgress(issues(), { id: "0.5", repo: "SB" });
  assert.deepEqual(pt, { done: 2, total: 3, isComplete: false });
  assert.deepEqual(sb, { done: 1, total: 2, isComplete: false });
  assert.notDeepEqual(pt, sb);
});

test("a milestone with zero issues counts as 0/0", () => {
  var result = CairnLogic.milestoneProgress(issues(), { id: "9.9", repo: "PT" });
  assert.deepEqual(result, { done: 0, total: 0, isComplete: false });
});

// ================= PT-44 §3: isComplete =================

test("PT-44: isComplete is true when the milestone's own status is done", () => {
  var result = CairnLogic.milestoneProgress(issues(), { id: "0.5", repo: "PT", status: "done" });
  assert.equal(result.isComplete, true);
});

test("PT-44: isComplete is true when the milestone's own status is cancelled", () => {
  var result = CairnLogic.milestoneProgress(issues(), { id: "0.5", repo: "PT", status: "cancelled" });
  assert.equal(result.isComplete, true);
});

test("PT-44: isComplete is false for every other RECORD_STATUSES value", () => {
  ["planned", "in-progress", "paused"].forEach(function (status) {
    var result = CairnLogic.milestoneProgress(issues(), { id: "0.5", repo: "PT", status: status });
    assert.equal(result.isComplete, false, "status=" + status);
  });
});

test("PT-44: isComplete does NOT change the done/total counts themselves -- a done milestone's ratio is still computed, callers decide whether to render it", () => {
  // milestoneProgress's OWN job stays "count done/total" -- the ruling's
  // "no ratio at all" rule is a RENDERING decision at the caller
  // (isComplete ? show checkmark : show n/m), not something this pure
  // function should suppress by returning a different done/total shape.
  var result = CairnLogic.milestoneProgress(issues(), { id: "0.5", repo: "PT", status: "done" });
  assert.equal(result.done, 2);
  assert.equal(result.total, 3);
  assert.equal(result.isComplete, true);
});

test("PT-44: a done milestone with archived issues (Show-archived on) still counts them -- no archive-read here, just whatever's in the issues array", () => {
  // PT-42 architecture: archived issues are ordinary members of the SAME
  // issues array once Show-archived is on -- milestoneProgress never
  // reads archive/ itself, it just counts whatever it's handed. This
  // pins that an issue carrying archived:true is counted identically to
  // a live one -- no special-casing needed, and none should be added.
  var withArchived = issues().concat([
    { id: "PT-9", milestone: "0.5", repo: "PT", status: "done", archived: true },
  ]);
  var result = CairnLogic.milestoneProgress(withArchived, { id: "0.5", repo: "PT", status: "done" });
  assert.equal(result.done, 3);
  assert.equal(result.total, 4);
});
