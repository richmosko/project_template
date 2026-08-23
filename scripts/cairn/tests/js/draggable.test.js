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

// PT-42 (architect's ruling § 5, implementation-lead's Pass-1 message):
// isDraggable widens to `... && !issue.archived` -- both cardEl (sets
// card.draggable) and handleDrop's refusal-guard already call this ONE
// shared predicate, so the drag-disable-on-archived requirement falls out
// for free at both call sites with no new call site needed, same "one
// shared predicate" principle PT-22 established this function for in the
// first place. Expected RED until implementation-lead's PT-42 slice widens
// the body -- an archived issue on the primary root is currently (wrongly)
// still draggable.

test("PT-42: an archived issue on the primary root is NOT draggable", () => {
  assert.equal(CairnLogic.isDraggable({ repo: "PT", archived: true }, "PT"), false);
});

test("PT-42: a live (archived: false) issue on the primary root is still draggable -- regression guard", () => {
  assert.equal(CairnLogic.isDraggable({ repo: "PT", archived: false }, "PT"), true);
});

test("PT-42: an issue with no `archived` key at all is still draggable -- must not read as falsy-truthy", () => {
  // Every real payload record always carries the key (PT-3 no-conditional-
  // shape precedent), but this pins the predicate's own behavior for an
  // issue object that happens to omit it (e.g. a hand-built test fixture,
  // or older client-side cached state) -- `undefined` must not be treated
  // as "archived", only an explicit `true`.
  assert.equal(CairnLogic.isDraggable({ repo: "PT" }, "PT"), true);
});

test("PT-42: a foreign-root archived issue is not draggable for EITHER reason -- both guards compose", () => {
  assert.equal(CairnLogic.isDraggable({ repo: "SB", archived: true }, "PT"), false);
});
