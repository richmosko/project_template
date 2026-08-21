"use strict";

// PT-22: primaryMilestones(milestones, primaryId) -- new-issue-milestone's
// option-list filter. The DATA-INTEGRITY-CRITICAL one: creation always
// writes to the primary root, so this must never offer a foreign
// milestone id. PT-3's original escape: no repo scoping at all (any
// milestone from any root was offerable). The FIX's own escape (commit
// 89d5a30): the repo-scoping fix used strict `===`, so a roots-less/
// repo-less payload (primaryId === null via primaryRootId) emptied the
// select entirely via `undefined === null` being false for every entry,
// rather than falling back to "offer everything" (the true pre-PT-3
// behavior). Both bugs get a test here.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function milestones() {
  return [
    { id: "0.5", repo: "PT" },
    { id: "0.4", repo: "PT" },
    { id: "0.5", repo: "SB" }, // same id as PT's 0.5 -- must never appear for primaryId="PT"
  ];
}

test("data-integrity: only primary-repo milestones are offered", () => {
  var result = CairnLogic.primaryMilestones(milestones(), "PT");
  assert.deepEqual(
    result.map((m) => m.repo),
    ["PT", "PT"]
  );
});

test("PT-3 regression: a foreign-repo milestone with a colliding id is never offered", () => {
  var result = CairnLogic.primaryMilestones(milestones(), "PT");
  var sbEntries = result.filter((m) => m.repo === "SB");
  assert.equal(sbEntries.length, 0);
});

test("89d5a30 regression: a roots-less payload (primaryId null) falls back to offering everything", () => {
  // The null-guard fix -- NOT "offer nothing" (the bug this fix closed).
  var result = CairnLogic.primaryMilestones(milestones(), null);
  assert.equal(result.length, milestones().length);
});

test("89d5a30 regression: primaryId undefined behaves the same as null", () => {
  var result = CairnLogic.primaryMilestones(milestones(), undefined);
  assert.equal(result.length, milestones().length);
});

test("a primary repo with zero milestones of its own yields an empty list, not a fallback", () => {
  // Distinguishes "primaryId is known but matches nothing" from "primaryId
  // is unknown" -- only the latter should trigger the offer-everything
  // fallback.
  var result = CairnLogic.primaryMilestones(milestones(), "ZZ");
  assert.deepEqual(result, []);
});
