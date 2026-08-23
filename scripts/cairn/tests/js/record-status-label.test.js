"use strict";

// PT-40 (joint PT-40/43/44 ruling § 2, implementation-lead's Pass-1
// message, 2026-08-23): `RECORD_STATUS_LABELS` -- a SEPARATE map from
// `STATUS_LABELS`, deliberately not folded in. `Object.keys(STATUS_LABELS)`
// is the issue drawer's status `<select>` option list (board.js) --
// adding record-only statuses (`planned`, `paused`) there would offer
// invalid issue statuses. `recordStatusLabel(status)` mirrors
// `statusLabel`'s own-property-guard pattern exactly (PT-37 finding F1:
// prototype-pollution safe -- "constructor"/"__proto__" as a status must
// read as unknown, not as an inherited Object.prototype member), same
// raw-slug fallback for an unlabeled status.
//
// This file mirrors status-label.test.js's own test shape test-for-test,
// one map/vocabulary over (RECORD_STATUSES: planned/in-progress/paused/
// done/cancelled, instead of STATUSES).
//
// Neither RECORD_STATUS_LABELS nor recordStatusLabel exists in
// board-logic.js as of this commit -- every test below is expected to
// fail (AttributeError-equivalent "not a function"/undefined) until
// implementation-lead's PT-40 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("recordStatusLabel: a known status returns its mapped label", () => {
  assert.equal(CairnLogic.recordStatusLabel("done"), "Done");
});

test("recordStatusLabel: every RECORD_STATUSES value maps through (planned/paused, not just the done/cancelled overlap with issues)", () => {
  assert.equal(typeof CairnLogic.recordStatusLabel("planned"), "string");
  assert.notEqual(CairnLogic.recordStatusLabel("planned"), "planned", "planned must have a REAL label, not just fall back to the raw slug");
  assert.equal(typeof CairnLogic.recordStatusLabel("in-progress"), "string");
  assert.notEqual(CairnLogic.recordStatusLabel("in-progress"), "in-progress");
  assert.equal(typeof CairnLogic.recordStatusLabel("paused"), "string");
  assert.notEqual(CairnLogic.recordStatusLabel("paused"), "paused");
  assert.equal(typeof CairnLogic.recordStatusLabel("cancelled"), "string");
  assert.notEqual(CairnLogic.recordStatusLabel("cancelled"), "cancelled");
});

test("PT-40: an unknown/future record status falls back to the raw status string, not undefined", () => {
  assert.equal(CairnLogic.recordStatusLabel("some-future-status"), "some-future-status");
});

test("PT-40: falsy-but-real status values are not swallowed by the fallback (|| pitfall)", () => {
  assert.equal(CairnLogic.recordStatusLabel(""), "");
});

test("PT-40 (mirrors PT-37 F1): an Object.prototype member name reads as unknown, not as an inherited function", () => {
  assert.equal(CairnLogic.recordStatusLabel("constructor"), "constructor");
});

test("PT-40 (mirrors PT-37 F1): __proto__ does not throw on string coercion", () => {
  assert.doesNotThrow(() => CairnLogic.recordStatusLabel("__proto__"));
  assert.equal(CairnLogic.recordStatusLabel("__proto__"), "__proto__");
});

test("RECORD_STATUS_LABELS is exported from CairnLogic and covers every RECORD_STATUSES value", () => {
  const keys = Object.keys(CairnLogic.RECORD_STATUS_LABELS).sort();
  assert.deepEqual(keys, ["cancelled", "done", "in-progress", "paused", "planned"]);
});

test("RECORD_STATUS_LABELS and STATUS_LABELS are genuinely separate objects, not one aliased under two names", () => {
  // Reference-identity here would mean board.js's `Object.keys(STATUS_LABELS)`
  // (the issue drawer's <select> options) silently gained planned/paused
  // the moment RECORD_STATUS_LABELS is populated -- the exact hazard the
  // ruling's "do NOT fold these into STATUS_LABELS" line exists to prevent.
  assert.notEqual(CairnLogic.RECORD_STATUS_LABELS, CairnLogic.STATUS_LABELS);
  assert.ok(!("planned" in CairnLogic.STATUS_LABELS), "STATUS_LABELS must not gain record-only statuses");
  assert.ok(!("paused" in CairnLogic.STATUS_LABELS), "STATUS_LABELS must not gain record-only statuses");
});
