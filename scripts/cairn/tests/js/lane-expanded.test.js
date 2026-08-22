"use strict";

// PT-29 (architect's ruling, 2026-08-22, section 2): state.collapsedLanes ->
// state.expandedLanes, absence means collapsed. laneExpanded is the SINGLE
// read path, nextExpandedLanes the SINGLE write path -- board.js must never
// touch state.expandedLanes[key] directly, the same "one shared function,
// not two hand-maintained call sites" discipline as issueMilestoneKey/
// isDraggable elsewhere in this file.
//
// Red-first cases 1-4 from the ruling's numbered list:
//   1. absence => collapsed, for an empty map and for a map holding other keys
//   2. toggle -> expanded; toggle again -> key ABSENT again (not present-false)
//   3. nextExpandedLanes does not mutate its input
//   4. two lanes with the same milestone id under different repos toggle
//      independently (the bare-id-across-roots regression guard -- MANDATORY
//      per architect, not trimmable)
//
// All four functions are missing from board-logic.js as of this commit
// (PT-16/PT-22's CairnLogic has no laneExpanded/nextExpandedLanes export) --
// every test below is expected to fail with "CairnLogic.laneExpanded is not
// a function" / "...nextExpandedLanes is not a function" until
// implementation-lead's PT-29 slice lands. That is red for the right reason:
// a missing export, not a wrong assertion.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

// ---- 1. absence => collapsed ----

test("laneExpanded: an empty map reads every key as collapsed", () => {
  assert.equal(CairnLogic.laneExpanded({}, "PT::0.5"), false);
});

test("laneExpanded: a map holding OTHER keys still reads an absent key as collapsed", () => {
  var expanded = { "PT::0.4": true, "SB::0.5": true };
  assert.equal(CairnLogic.laneExpanded(expanded, "PT::0.5"), false);
});

test("laneExpanded: a key present with a truthy value reads as expanded", () => {
  assert.equal(CairnLogic.laneExpanded({ "PT::0.5": true }, "PT::0.5"), true);
});

// ---- 2. toggle -> expanded; toggle again -> key ABSENT (not present-false) ----

test("nextExpandedLanes: toggling an absent key adds it (now expanded)", () => {
  var next = CairnLogic.nextExpandedLanes({}, "PT::0.5");
  assert.equal(CairnLogic.laneExpanded(next, "PT::0.5"), true);
  assert.deepEqual(Object.keys(next), ["PT::0.5"]);
});

test("nextExpandedLanes: toggling a present key DELETES it -- key count returns to zero, never a 1-holding-false", () => {
  var opened = CairnLogic.nextExpandedLanes({}, "PT::0.5");
  var closed = CairnLogic.nextExpandedLanes(opened, "PT::0.5");
  assert.equal(CairnLogic.laneExpanded(closed, "PT::0.5"), false);
  // The invariant the ruling calls out explicitly: closing must delete the
  // key, not set it to false. Object.keys().length must be 0, not 1.
  assert.equal(Object.keys(closed).length, 0, "closed key must be ABSENT, not present-with-false");
  assert.equal(Object.prototype.hasOwnProperty.call(closed, "PT::0.5"), false);
});

// ---- 3. non-mutating ----

test("nextExpandedLanes: does not mutate the map it was given (open case)", () => {
  var input = {};
  var frozenKeysBefore = Object.keys(input);
  CairnLogic.nextExpandedLanes(input, "PT::0.5");
  assert.deepEqual(Object.keys(input), frozenKeysBefore, "input map must be untouched");
});

test("nextExpandedLanes: does not mutate the map it was given (close case)", () => {
  var input = { "PT::0.5": true };
  CairnLogic.nextExpandedLanes(input, "PT::0.5");
  // input must still show the key present and truthy -- a fresh map was
  // returned, the caller's map was not edited in place.
  assert.equal(input["PT::0.5"], true);
  assert.deepEqual(Object.keys(input), ["PT::0.5"]);
});

test("nextExpandedLanes: returns a DIFFERENT object identity than its input", () => {
  var input = {};
  var output = CairnLogic.nextExpandedLanes(input, "PT::0.5");
  assert.notEqual(output, input);
});

// ---- 4. bare-id-across-roots regression guard (mandatory) ----

test("two lanes with the same milestone id under different repos toggle independently", () => {
  var expanded = {};
  var ptKey = CairnLogic.laneStateKey("PT", "0.5");
  var sbKey = CairnLogic.laneStateKey("SB", "0.5");

  // Expand PT's 0.5 lane only.
  expanded = CairnLogic.nextExpandedLanes(expanded, ptKey);

  assert.equal(CairnLogic.laneExpanded(expanded, ptKey), true, "PT::0.5 should be expanded");
  assert.equal(CairnLogic.laneExpanded(expanded, sbKey), false, "SB::0.5 must remain collapsed");

  // Now expand SB's 0.5 lane too, and collapse PT's again -- each toggle
  // must only ever touch its own composite key.
  expanded = CairnLogic.nextExpandedLanes(expanded, sbKey);
  expanded = CairnLogic.nextExpandedLanes(expanded, ptKey);

  assert.equal(CairnLogic.laneExpanded(expanded, ptKey), false, "PT::0.5 should be collapsed again");
  assert.equal(CairnLogic.laneExpanded(expanded, sbKey), true, "SB::0.5 must still be expanded -- toggling PT must not have touched it");
});

test("a NEW lane key that appears after a refresh/filter change is collapsed, not expanded", () => {
  // The ruling's stated rejection of "eagerly initialise to true": a key
  // that simply never appeared in the map yet (e.g. a milestone freshly
  // revealed by a filter change) must read as collapsed, exactly like case 1
  // -- there is no separate "new key" code path, which is the whole point of
  // the absence-means-collapsed invariant.
  var expanded = CairnLogic.nextExpandedLanes({}, CairnLogic.laneStateKey("PT", "0.4"));
  var freshlyAppearedKey = CairnLogic.laneStateKey("PT", "0.9");
  assert.equal(CairnLogic.laneExpanded(expanded, freshlyAppearedKey), false);
});
