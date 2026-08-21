"use strict";

// PT-22 second tier: orderRoots(roots) and laneStateKey(repoId,
// milestoneKey) -- same "id/key comparison across roots" shape as the
// first-tier functions, but no specific escaped PT-3 defect (team-lead's
// anchor task called these out as second-tier for that reason).
// implementation-lead is extracting them alongside the first tier since
// they're moving anyway -- cheap to cover now rather than leave as a
// gap.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("orderRoots: primary root sorts first regardless of id", () => {
  var roots = [
    { id: "ZZ", primary: false },
    { id: "AA", primary: true },
  ];
  var ordered = CairnLogic.orderRoots(roots);
  assert.deepEqual(
    ordered.map((r) => r.id),
    ["AA", "ZZ"]
  );
});

test("orderRoots: non-primary roots sort by id ascending after the primary", () => {
  var roots = [
    { id: "ZZ", primary: false },
    { id: "AA", primary: true },
    { id: "BB", primary: false },
  ];
  var ordered = CairnLogic.orderRoots(roots);
  assert.deepEqual(
    ordered.map((r) => r.id),
    ["AA", "BB", "ZZ"]
  );
});

test("orderRoots: single-root input is unaffected", () => {
  var roots = [{ id: "AA", primary: true }];
  assert.deepEqual(
    CairnLogic.orderRoots(roots).map((r) => r.id),
    ["AA"]
  );
});

test("laneStateKey composes a repo-qualified composite", () => {
  assert.equal(CairnLogic.laneStateKey("PT", "0.5"), "PT::0.5");
});

test("laneStateKey: two repos' same milestone key produce distinct composites", () => {
  // The exact property the composite-key design exists for: collapsing
  // one repo's "0.5" lane must never collapse another repo's "0.5" lane.
  assert.notEqual(
    CairnLogic.laneStateKey("PT", "0.5"),
    CairnLogic.laneStateKey("SB", "0.5")
  );
});

test("laneStateKey handles the (none) swimlane key like any other", () => {
  assert.equal(CairnLogic.laneStateKey("PT", "(none)"), "PT::(none)");
});
