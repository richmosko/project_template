"use strict";

// PT-44 §2 (joint ruling, implementation-lead's Pass-1 message): "render a
// lane for every milestone" -- groupByMilestone only ever produces a lane
// for a milestone that has at least one live issue in the current filter;
// an issue-less milestone (e.g. freshly created, or fully archived with
// Show-archived off) must still get an empty, collapsed lane.
//
// Proposed shape (implementation-lead flagged this as "the piece I'm
// least certain of, flag before you lock tests to it"):
//
//   appendMilestoneOnlyLanes(order, groups, milestones, repoId)
//     -> { order: [...], groups: {...} }
//
// `order`/`groups` are groupByMilestone's own output shape (an array of
// keys, a key->issues map); `milestones` is the ALREADY major-tab-filtered
// array of milestone records for `repoId`. Appends a lane key for any
// milestone NOT already in `order`, "(none)" re-sorted to the very end
// regardless of where groupByMilestone's own alphabetical sort put it.
// Non-mutating -- returns a COPY, same convention as nextExpandedLanes/
// expandAllLanes (PT-29) -- never touches the `order`/`groups` arguments
// in place.
//
// Accepted as proposed (reasonable, mirrors an established non-mutating-
// copy convention already used elsewhere in this file) -- but this is
// the one function in this slice implementation-lead explicitly asked to
// confirm before locking tests to it. Flag to implementation-lead/team-
// lead if this shape changes; these tests would need updating alongside.
//
// Does not exist in board-logic.js as of this commit -- every test below
// is expected to fail until implementation-lead's PT-44 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function milestone(id, repo, major) {
  return { id: id, repo: repo || "PT", major: major || "PT-V1" };
}

test("a milestone with issues (already in order/groups) is left untouched", () => {
  var order = ["PT-1.0"];
  var groups = { "PT-1.0": [{ id: "PT-1" }] };
  var result = CairnLogic.appendMilestoneOnlyLanes(order, groups, [milestone("PT-1.0")], "PT");
  assert.deepEqual(result.order, ["PT-1.0"]);
  assert.deepEqual(result.groups["PT-1.0"], [{ id: "PT-1" }]);
});

test("a milestone with NO issues (not in order) gets an empty lane appended", () => {
  var order = [];
  var groups = {};
  var result = CairnLogic.appendMilestoneOnlyLanes(order, groups, [milestone("PT-0.4")], "PT");
  assert.deepEqual(result.order, ["PT-0.4"]);
  assert.deepEqual(result.groups["PT-0.4"], []);
});

test("milestone-only lanes are appended AFTER the existing order (issues-first, then empty)", () => {
  var order = ["PT-1.0"];
  var groups = { "PT-1.0": [{ id: "PT-1" }] };
  var result = CairnLogic.appendMilestoneOnlyLanes(order, groups, [milestone("PT-1.0"), milestone("PT-0.4")], "PT");
  assert.deepEqual(result.order, ["PT-1.0", "PT-0.4"]);
});

test('"(none)" is always last, even if it was already in the original order', () => {
  var order = ["(none)", "PT-1.0"];
  var groups = { "(none)": [{ id: "PT-9" }], "PT-1.0": [{ id: "PT-1" }] };
  var result = CairnLogic.appendMilestoneOnlyLanes(order, groups, [milestone("PT-1.0")], "PT");
  assert.equal(result.order[result.order.length - 1], "(none)", "\"(none)\" must be the last entry");
});

test("a milestone from a DIFFERENT repo is not appended (repoId scoping)", () => {
  var order = [];
  var groups = {};
  var result = CairnLogic.appendMilestoneOnlyLanes(order, groups, [milestone("SB-1.0", "SB")], "PT");
  assert.deepEqual(result.order, []);
});

test("does not mutate the input order array or groups object", () => {
  var order = ["PT-1.0"];
  var groups = { "PT-1.0": [{ id: "PT-1" }] };
  CairnLogic.appendMilestoneOnlyLanes(order, groups, [milestone("PT-1.0"), milestone("PT-0.4")], "PT");
  assert.deepEqual(order, ["PT-1.0"], "the input order array must not be mutated");
  assert.deepEqual(Object.keys(groups), ["PT-1.0"], "the input groups object must not be mutated");
});

test("a milestone already covered by an issue-bearing lane is not duplicated", () => {
  var order = ["PT-1.0"];
  var groups = { "PT-1.0": [{ id: "PT-1" }] };
  var result = CairnLogic.appendMilestoneOnlyLanes(order, groups, [milestone("PT-1.0")], "PT");
  var occurrences = result.order.filter(function (k) { return k === "PT-1.0"; }).length;
  assert.equal(occurrences, 1);
});
