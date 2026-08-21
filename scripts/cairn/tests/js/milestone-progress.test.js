"use strict";

// PT-22: milestoneProgress(issues, milestone) -- the progress strip's
// done/total count. PT-3's escape: an unscoped `i.milestone === ms.id`
// filter fused two repos' same-id milestones into one shared count
// (shown identically, wrongly, on both repos' entries) -- caught only
// by team-lead's Chrome pass.

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
  assert.deepEqual(result, { done: 2, total: 3 });
});

test("PT-3 regression: two repos' same-id milestones never fuse their counts", () => {
  var pt = CairnLogic.milestoneProgress(issues(), { id: "0.5", repo: "PT" });
  var sb = CairnLogic.milestoneProgress(issues(), { id: "0.5", repo: "SB" });
  assert.deepEqual(pt, { done: 2, total: 3 });
  assert.deepEqual(sb, { done: 1, total: 2 });
  assert.notDeepEqual(pt, sb);
});

test("a milestone with zero issues counts as 0/0", () => {
  var result = CairnLogic.milestoneProgress(issues(), { id: "9.9", repo: "PT" });
  assert.deepEqual(result, { done: 0, total: 0 });
});
