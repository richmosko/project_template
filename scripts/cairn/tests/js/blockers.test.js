"use strict";

// PT-26: blockersOf(issues, issue) / blocksOf(issues, issue) -- the board's
// "Blocked by" / reverse "Blocks" lists (architect's ruling #4). Repo-scoped
// from the FIRST line, reusing the same "repo::id" identity key PT-25's
// childProgress/childrenOf already established (renamed parentKeyOf ->
// issueKeyOf internally -- not tested here directly, that's an internal
// helper, never exported; this file tests the same black-box contract
// PT-25's child-progress.test.js does). Two roots each holding an issue
// literally named "PT-14" must not leak blockers into each other -- the
// fifth instance of the isDraggable/issueMilestoneKey/groupByMilestone/
// childProgress bare-id-across-roots defect class. This cross-repo
// regression test is deliberately the FIRST test in this file, ahead of
// every other PT-26 board test -- the acceptance criterion's explicit
// ordering, not a style choice.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function crossRepoIssues() {
  return [
    { id: "PT-14", repo: "PT", status: "todo", blocked_by: ["PT-10"] },
    { id: "PT-10", repo: "PT", status: "done", blocked_by: [] },
    { id: "PT-14", repo: "SB", status: "todo", blocked_by: ["SB-2"] },
    { id: "SB-2", repo: "SB", status: "todo", blocked_by: [] },
  ];
}

test("cross-repo regression: two roots each holding PT-14 must not leak blockers into each other", () => {
  var issues = crossRepoIssues();
  var pt = CairnLogic.blockersOf(issues, { id: "PT-14", repo: "PT" });
  var sb = CairnLogic.blockersOf(issues, { id: "PT-14", repo: "SB" });
  assert.deepEqual(pt.map(function (i) { return i.id; }), ["PT-10"]);
  assert.deepEqual(sb.map(function (i) { return i.id; }), ["SB-2"]);
  assert.notDeepEqual(pt, sb);
});

test("blockersOf returns the blocker records, sorted numerically by id", () => {
  var issues = [
    { id: "PT-1", repo: "PT", status: "todo", blocked_by: ["PT-10", "PT-2", "PT-9"] },
    { id: "PT-2", repo: "PT", status: "done", blocked_by: [] },
    { id: "PT-9", repo: "PT", status: "todo", blocked_by: [] },
    { id: "PT-10", repo: "PT", status: "todo", blocked_by: [] },
  ];
  var blockers = CairnLogic.blockersOf(issues, { id: "PT-1", repo: "PT" });
  assert.deepEqual(blockers.map(function (i) { return i.id; }), ["PT-2", "PT-9", "PT-10"]);
});

test("an issue with no blockers has an empty blockersOf list", () => {
  var issues = [{ id: "PT-1", repo: "PT", status: "todo", blocked_by: [] }];
  assert.deepEqual(CairnLogic.blockersOf(issues, { id: "PT-1", repo: "PT" }), []);
});

test("openBlockers excludes done/cancelled blockers -- a resolved blocker is legal, not an error, and not open", () => {
  var issues = [
    { id: "PT-1", repo: "PT", status: "todo", blocked_by: ["PT-2", "PT-3", "PT-4"] },
    { id: "PT-2", repo: "PT", status: "done", blocked_by: [] },
    { id: "PT-3", repo: "PT", status: "cancelled", blocked_by: [] },
    { id: "PT-4", repo: "PT", status: "in-progress", blocked_by: [] },
  ];
  var open = CairnLogic.openBlockers(issues, { id: "PT-1", repo: "PT" });
  assert.deepEqual(open.map(function (i) { return i.id; }), ["PT-4"]);
});

test("openBlockers is empty (no card chip) once every blocker is done/cancelled", () => {
  var issues = [
    { id: "PT-1", repo: "PT", status: "todo", blocked_by: ["PT-2", "PT-3"] },
    { id: "PT-2", repo: "PT", status: "done", blocked_by: [] },
    { id: "PT-3", repo: "PT", status: "cancelled", blocked_by: [] },
  ];
  assert.deepEqual(CairnLogic.openBlockers(issues, { id: "PT-1", repo: "PT" }), []);
});

test("openBlockers cannot silently diverge from blockersOf's list -- counts derive from the list, never a parallel filter (PT-25's F1 defect class)", () => {
  var issues = [
    { id: "PT-1", repo: "PT", status: "todo", blocked_by: ["PT-2", "PT-3", "PT-4", "PT-5"] },
    { id: "PT-2", repo: "PT", status: "done", blocked_by: [] },
    { id: "PT-3", repo: "PT", status: "cancelled", blocked_by: [] },
    { id: "PT-4", repo: "PT", status: "todo", blocked_by: [] },
    { id: "PT-5", repo: "PT", status: "in-progress", blocked_by: [] },
  ];
  var all = CairnLogic.blockersOf(issues, { id: "PT-1", repo: "PT" });
  var open = CairnLogic.openBlockers(issues, { id: "PT-1", repo: "PT" });
  var expectedOpen = all.filter(function (i) { return i.status !== "done" && i.status !== "cancelled"; });
  assert.deepEqual(open.map(function (i) { return i.id; }), expectedOpen.map(function (i) { return i.id; }));
  assert.deepEqual(open.map(function (i) { return i.id; }), ["PT-4", "PT-5"]);
});

test("blocksOf is the reverse lookup, sorted numerically by id", () => {
  var issues = [
    { id: "PT-1", repo: "PT", status: "todo", blocked_by: [] },
    { id: "PT-10", repo: "PT", status: "todo", blocked_by: ["PT-1"] },
    { id: "PT-2", repo: "PT", status: "todo", blocked_by: ["PT-1"] },
    { id: "PT-9", repo: "PT", status: "todo", blocked_by: ["PT-1"] },
    { id: "PT-3", repo: "PT", status: "todo", blocked_by: [] },  // does not block PT-1
  ];
  var blocks = CairnLogic.blocksOf(issues, { id: "PT-1", repo: "PT" });
  assert.deepEqual(blocks.map(function (i) { return i.id; }), ["PT-2", "PT-9", "PT-10"]);
});

test("blocksOf is repo-scoped the same way blockersOf is", () => {
  var issues = crossRepoIssues();
  // PT-10/repo:PT is blocked_by nothing itself, but IS a blocker of PT-14/repo:PT.
  var blocks = CairnLogic.blocksOf(issues, { id: "PT-10", repo: "PT" });
  assert.deepEqual(blocks.map(function (i) { return i.id; }), ["PT-14"]);
  // A same-id "PT-10" scoped to a repo that has no such issue at all must
  // not pick up PT's reverse links.
  var none = CairnLogic.blocksOf(issues, { id: "PT-10", repo: "SB" });
  assert.deepEqual(none, []);
});

test("an issue nothing depends on has an empty blocksOf list", () => {
  var issues = [{ id: "PT-1", repo: "PT", status: "todo", blocked_by: [] }];
  assert.deepEqual(CairnLogic.blocksOf(issues, { id: "PT-1", repo: "PT" }), []);
});
