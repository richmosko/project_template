"use strict";

// PT-32 (architect's micro-ruling, 2026-08-22, requested by team-lead after
// a real 503 on the pull path drew the falsely-reassuring "Already up to
// date" toast): refreshBoardSilently()'s two-state boolean collapsed
// "confirmed unchanged" and "the request failed" onto the same branch --
// exactly the outcome the pull-to-refresh gesture exists to be honest
// about. Fix: a three-state string outcome (never a rejection -- six
// existing bare-statement call sites structurally can't attach a `.catch`)
// plus a pure toast mapper.
//
// board.js's producer side (refreshBoardSilently returning these constants,
// apiGetBoard's new resp.ok check) is NOT reachable from node:test -- it
// touches fetch/DOM. This file covers only the pure consumer half:
// REFRESH_UPDATED/REFRESH_UNCHANGED/REFRESH_FAILED as exact exported string
// values (a rename must break a test, since the producer side can't be
// reached from the suite to catch drift) and pullRefreshToast's mapping.
//
// None of REFRESH_UPDATED/REFRESH_UNCHANGED/REFRESH_FAILED/pullRefreshToast
// exist in board-logic.js as of this commit -- every test below is expected
// to fail with "not a function" / undefined-constant errors until
// implementation-lead's batch lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

// ---- 1. exact string values ----

test("REFRESH_UPDATED is exported and equals \"updated\"", () => {
  assert.equal(CairnLogic.REFRESH_UPDATED, "updated");
});

test("REFRESH_UNCHANGED is exported and equals \"unchanged\"", () => {
  assert.equal(CairnLogic.REFRESH_UNCHANGED, "unchanged");
});

test("REFRESH_FAILED is exported and equals \"failed\"", () => {
  assert.equal(CairnLogic.REFRESH_FAILED, "failed");
});

// ---- 2. pullRefreshToast per-outcome mapping (three separate cases) ----

test("pullRefreshToast(REFRESH_UPDATED): \"Board updated\", not an error", () => {
  var result = CairnLogic.pullRefreshToast(CairnLogic.REFRESH_UPDATED);
  assert.deepEqual(result, { message: "Board updated", isError: false });
});

test("pullRefreshToast(REFRESH_UNCHANGED): \"Already up to date\", not an error", () => {
  var result = CairnLogic.pullRefreshToast(CairnLogic.REFRESH_UNCHANGED);
  assert.deepEqual(result, { message: "Already up to date", isError: false });
});

test("pullRefreshToast(REFRESH_FAILED): the two-clause failure copy, IS an error", () => {
  var result = CairnLogic.pullRefreshToast(CairnLogic.REFRESH_FAILED);
  assert.deepEqual(result, { message: "Refresh failed — showing last known data", isError: true });
});

// ---- 3. isError on REFRESH_FAILED, asserted on its own ----
// This is the exact property the original boolean-collapse defect
// violated -- a 503 must never resolve to isError: false.

test("pullRefreshToast(REFRESH_FAILED).isError is strictly true", () => {
  assert.equal(CairnLogic.pullRefreshToast(CairnLogic.REFRESH_FAILED).isError, true);
});

// ---- 4. unknown outcome -> the FAILED shape, not empty/neutral (deliberately opposite of pullIndicatorLabel) ----

test("pullRefreshToast: an unrecognized outcome maps to the FAILED shape, not a neutral/empty one", () => {
  [undefined, null, "", "bogus", "REFRESH_UPDATED", 0, false].forEach((outcome) => {
    var result;
    assert.doesNotThrow(() => { result = CairnLogic.pullRefreshToast(outcome); }, `outcome ${JSON.stringify(outcome)} must not throw`);
    assert.equal(result.isError, true, `unrecognized outcome ${JSON.stringify(outcome)} must map to isError: true`);
    assert.equal(
      result.message,
      CairnLogic.pullRefreshToast(CairnLogic.REFRESH_FAILED).message,
      `unrecognized outcome ${JSON.stringify(outcome)} must use the SAME message as REFRESH_FAILED, not its own copy`
    );
  });
});

test("pullRefreshToast: the unknown-outcome default is the OPPOSITE convention from pullIndicatorLabel's unknown-phase default", () => {
  // pullIndicatorLabel("bogus") -> "" (an unknown PHASE means "show
  // nothing"). pullRefreshToast("bogus") -> the failed shape (an unknown
  // OUTCOME means "something went wrong and I can't characterise it").
  // Pinning both defaults in one test so a future "harmonise these two
  // similar-looking functions" refactor has to deliberately break this
  // assertion rather than silently doing it.
  assert.equal(CairnLogic.pullIndicatorLabel("bogus"), "");
  assert.notEqual(CairnLogic.pullRefreshToast("bogus").message, "");
  assert.equal(CairnLogic.pullRefreshToast("bogus").isError, true);
});

// ---- 5. all three messages pairwise distinct and non-empty ----

test("pullRefreshToast: the three outcome messages are pairwise distinct and non-empty", () => {
  var updated = CairnLogic.pullRefreshToast(CairnLogic.REFRESH_UPDATED).message;
  var unchanged = CairnLogic.pullRefreshToast(CairnLogic.REFRESH_UNCHANGED).message;
  var failed = CairnLogic.pullRefreshToast(CairnLogic.REFRESH_FAILED).message;

  [updated, unchanged, failed].forEach((message, i) => {
    assert.equal(typeof message, "string", `message ${i} must be a string`);
    assert.notEqual(message.length, 0, `message ${i} must not be empty`);
  });

  assert.notEqual(updated, unchanged);
  assert.notEqual(unchanged, failed);
  assert.notEqual(updated, failed);
});

// ---- constants are pairwise distinct too (guards against a copy-paste alias) ----

test("REFRESH_UPDATED/REFRESH_UNCHANGED/REFRESH_FAILED are pairwise distinct values", () => {
  var values = [CairnLogic.REFRESH_UPDATED, CairnLogic.REFRESH_UNCHANGED, CairnLogic.REFRESH_FAILED];
  assert.equal(new Set(values).size, 3, "all three outcome constants must be distinct strings");
});
