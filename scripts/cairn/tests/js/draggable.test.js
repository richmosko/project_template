"use strict";

// PT-22: isDraggable(issue, primaryId) -- architect's shared-predicate
// finding, the second "two independently-duplicated expressions" bug of
// this session (issueMilestoneKey/uniqueMilestoneKeys was the first).
// cardEl (card.draggable) and handleDrop's refusal-guard each had their
// own inline `issue.repo === primaryRootId(...)` comparison in PT-3 --
// both needed the identical null-guard fix (commit 89d5a30) applied
// separately when a roots-less payload made the comparison
// `undefined === null` (false), silently killing drag on every card and
// refusing every drop with a misleading "read-only" toast that blamed
// the wrong thing. One shared predicate structurally prevents that class
// of drift between the two call sites.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("a primary-root issue is draggable", () => {
  assert.equal(CairnLogic.isDraggable({ repo: "PT" }, "PT"), true);
});

test("a foreign-root issue is not draggable", () => {
  assert.equal(CairnLogic.isDraggable({ repo: "SB" }, "PT"), false);
});

test("89d5a30 regression: a roots-less payload (primaryId null) makes everything draggable, not nothing", () => {
  // The exact bug: undefined === null is false, so every card looked
  // foreign and drag silently died board-wide. The fix treats "no repo
  // dimension known at all" as "everything is the primary" -- the true
  // pre-PT-3 behavior.
  assert.equal(CairnLogic.isDraggable({ repo: "PT" }, null), true);
  assert.equal(CairnLogic.isDraggable({ repo: undefined }, null), true);
});

test("89d5a30 regression: primaryId undefined behaves the same as null", () => {
  assert.equal(CairnLogic.isDraggable({ repo: "PT" }, undefined), true);
});
