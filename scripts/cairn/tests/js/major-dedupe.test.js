"use strict";

// PT-22: dedupeMajors(majors) -- the major-tabs bar's dedup. PT-3's
// escape: two repos both having a founding major "V1" rendered "All |
// V1 | V1" (two buttons) instead of one deduped, union-filtering tab --
// caught only by team-lead's Chrome pass.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("PT-3 regression: two repos sharing a major id collapse to one tab", () => {
  var majors = [
    { id: "V1", repo: "PT" },
    { id: "V1", repo: "SB" },
  ];
  var deduped = CairnLogic.dedupeMajors(majors);
  assert.equal(deduped.length, 1);
  assert.equal(deduped[0].id, "V1");
});

test("keeps the first-seen entry when ids collide", () => {
  var majors = [
    { id: "V1", repo: "PT", label: "first" },
    { id: "V1", repo: "SB", label: "second" },
  ];
  var deduped = CairnLogic.dedupeMajors(majors);
  assert.equal(deduped[0].repo, "PT");
});

test("distinct ids each survive, in first-seen order", () => {
  var majors = [
    { id: "V2", repo: "PT" },
    { id: "V1", repo: "PT" },
    { id: "V2", repo: "SB" },
  ];
  var deduped = CairnLogic.dedupeMajors(majors);
  assert.deepEqual(deduped.map((m) => m.id), ["V2", "V1"]);
});

test("empty input yields empty output", () => {
  assert.deepEqual(CairnLogic.dedupeMajors([]), []);
});

test("single-root board (no collisions possible) is unaffected", () => {
  var majors = [{ id: "V1", repo: "PT" }];
  assert.deepEqual(CairnLogic.dedupeMajors(majors), majors);
});
