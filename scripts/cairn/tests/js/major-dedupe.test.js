"use strict";

// PT-22: dedupeMajorIds(majors) -- the major-tabs bar's dedup. PT-3's
// escape: two repos both having a founding major "V1" rendered "All |
// V1 | V1" (two buttons) instead of one deduped, union-filtering tab --
// caught only by team-lead's Chrome pass.
//
// Returns bare ids (a string[]), not the full major records: the actual
// call site (renderHeader's tab-button loop) only ever reads `major.id`
// for the button label and the onclick's state.currentMajor assignment
// -- which of two identical-id major records "won" the dedup is not
// observable in the rendered board, so testing for a specific survivor
// object would be over-specifying the contract. implementation-lead's
// naming/shape, matches the actual consumer.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("PT-3 regression: two repos sharing a major id collapse to one tab", () => {
  var majors = [
    { id: "V1", repo: "PT" },
    { id: "V1", repo: "SB" },
  ];
  assert.deepEqual(CairnLogic.dedupeMajorIds(majors), ["V1"]);
});

test("distinct ids each survive, in first-seen order", () => {
  var majors = [
    { id: "V2", repo: "PT" },
    { id: "V1", repo: "PT" },
    { id: "V2", repo: "SB" },
  ];
  assert.deepEqual(CairnLogic.dedupeMajorIds(majors), ["V2", "V1"]);
});

test("empty input yields empty output", () => {
  assert.deepEqual(CairnLogic.dedupeMajorIds([]), []);
});

test("single-root board (no collisions possible) is unaffected", () => {
  var majors = [{ id: "V1", repo: "PT" }];
  assert.deepEqual(CairnLogic.dedupeMajorIds(majors), ["V1"]);
});
