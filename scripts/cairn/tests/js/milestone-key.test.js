"use strict";

// PT-22: issueMilestoneKey(issue) + uniqueMilestoneKeys(issues) --
// architect's #5b finding, the highest-value extraction in this pass.
//
// The PT-3 bug here wasn't in EITHER key-producing expression alone --
// both, read individually, looked correct. It was that the
// filter-milestone select built its option values with one hand-written
// expression and filteredIssues compared against a SECOND, separately
// hand-written expression that had to happen to produce the same
// string. Two independent expressions that must agree forever is
// exactly the shape that drifts silently. Extracting ONE shared
// function and having both call sites call it converts that
// hand-maintained invariant into a structural one -- the agreement test
// below is the actual point of this file, not the individual-function
// tests around it.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("issueMilestoneKey composes repo::milestone", () => {
  assert.equal(
    CairnLogic.issueMilestoneKey({ repo: "PT", milestone: "0.5" }),
    "PT::0.5"
  );
});

test("issueMilestoneKey handles a null/absent milestone", () => {
  assert.equal(CairnLogic.issueMilestoneKey({ repo: "PT", milestone: null }), "PT::");
  assert.equal(CairnLogic.issueMilestoneKey({ repo: "PT" }), "PT::");
});

test("uniqueMilestoneKeys returns one entry per distinct (repo, milestone) pair", () => {
  var issues = [
    { id: "PT-1", repo: "PT", milestone: "0.5" },
    { id: "PT-2", repo: "PT", milestone: "0.5" }, // duplicate pair -- must collapse
    { id: "SB-1", repo: "SB", milestone: "0.5" }, // same milestone id, different repo
    { id: "PT-3", repo: "PT", milestone: "0.4" },
  ];
  var result = CairnLogic.uniqueMilestoneKeys(issues);
  assert.deepEqual(
    result.map((p) => p.key).sort(),
    ["PT::0.4", "PT::0.5", "SB::0.5"]
  );
});

test("uniqueMilestoneKeys excludes issues with no milestone", () => {
  var issues = [{ id: "PT-1", repo: "PT", milestone: null }];
  assert.deepEqual(CairnLogic.uniqueMilestoneKeys(issues), []);
});

test("uniqueMilestoneKeys sorts by key ascending", () => {
  var issues = [
    { id: "SB-1", repo: "SB", milestone: "0.5" },
    { id: "PT-1", repo: "PT", milestone: "0.5" },
  ];
  var result = CairnLogic.uniqueMilestoneKeys(issues);
  assert.deepEqual(result.map((p) => p.key), ["PT::0.5", "SB::0.5"]);
});

test("THE agreement invariant: every key in uniqueMilestoneKeys equals issueMilestoneKey(issue) for its own issues", () => {
  // This is the test that would have caught PT-3's actual bug: it
  // doesn't test either function's correctness in isolation, it tests
  // that they agree with each other on the same input -- exactly the
  // property that broke when the select and the filter each had their
  // own hand-written key expression.
  var issues = [
    { id: "PT-1", repo: "PT", milestone: "0.5" },
    { id: "SB-1", repo: "SB", milestone: "0.5" },
    { id: "PT-2", repo: "PT", milestone: "0.4" },
  ];
  var keys = CairnLogic.uniqueMilestoneKeys(issues);
  issues.forEach((issue) => {
    if (!issue.milestone) return;
    var expected = CairnLogic.issueMilestoneKey(issue);
    assert.ok(
      keys.some((p) => p.key === expected),
      `uniqueMilestoneKeys is missing the key issueMilestoneKey computed for ${issue.id}: ${expected}`
    );
  });
});
