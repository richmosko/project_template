"use strict";

// PT-35 (architect's ruling @ 189dbf4): the conditional sixth "cancelled"
// column. boardColumns(showCancelled) is the pure derivation (board-logic.js
// § 1); laneSummary's signature changes from `laneSummary(issues)` to
// `laneSummary(issues, columns)`, with `columns` REQUIRED (§ 2, JC1 -- a
// missing/non-array columns argument must throw, not default to
// BOARD_COLUMNS).
//
// scripts/cairn/tests/js/lane-summary.test.js is edited SEPARATELY, as an
// argument-threading-only diff (§ 6, JC5): every NEW behavior this ruling
// introduces -- boardColumns itself, the throw contract, and laneSummary's
// cancelled-inclusion behavior -- lives here instead, so that file's diff
// stays reviewable as "adds `, CairnLogic.BOARD_COLUMNS` to existing calls
// and changes nothing else."
//
// Neither `boardColumns` nor laneSummary's two-argument form exists in
// board-logic.js as of this commit -- every test below is expected to fail
// (either "not a function", a call that should throw but doesn't, or a
// silently-ignored second argument) until implementation-lead's PT-35 slice
// lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { loadCairnLogic, BOARD_LOGIC_PATH } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function issue(id, status) {
  return { id: id, status: status };
}

// PT-35 items 1 and 4 are REFERENCE-IDENTITY assertions -- the whole point
// of § 3's ruling ("boardColumns(false) returns BOARD_COLUMNS itself...
// pin the identity, a deep-equal would pass for a copy"). loadCairnLogic()'s
// wrapForRealm wraps every FUNCTION export so its return value is rehome()'d
// on each call (see helpers.js) -- necessary so cross-realm plain-object
// results deepEqual a same-realm literal, but it also means every wrapped
// function call returns a FRESH, freshly-rehomed array, even when the
// sandbox function being wrapped returns the exact same object twice. Tested
// empirically: through loadCairnLogic(), `CairnLogic.boardColumns(false)`
// is NEVER strictEqual to `CairnLogic.BOARD_COLUMNS` -- and two calls to
// `CairnLogic.boardColumns(true)` are NEVER strictEqual to each other
// either -- regardless of what the underlying sandbox function actually
// does. A strictEqual assertion written against the wrapped API would
// therefore fail for §3's correct implementation (item 1) and pass for a
// §3-violating one that wrongly caches/memoizes its "true" branch (item 4)
// -- red/green for the wrong reason in both directions.
//
// So items 1 and 4 load board-logic.js a SECOND time, raw, into their own
// fresh vm context, and assert identity directly on the UNWRAPPED sandbox
// object -- real object identity, observed within the one realm it's
// actually meaningful in, exactly the escape hatch BOARD_LOGIC_PATH is
// exported for (see helpers-realm.test.js's direct rehome/wrapForRealm
// self-tests for the same "don't let the harness's own fix mask what it's
// supposed to prove" principle, PT-31 item 5).
function loadRawCairnLogic() {
  var source = fs.readFileSync(BOARD_LOGIC_PATH, "utf8");
  var sandbox = {};
  vm.runInNewContext(source, sandbox, { filename: BOARD_LOGIC_PATH });
  return sandbox.CairnLogic;
}

// ================= 1-4: boardColumns =================

test("1: boardColumns(false) IS BOARD_COLUMNS -- reference identity, not a copy (§3, raw-realm check)", () => {
  var raw = loadRawCairnLogic();
  assert.strictEqual(
    raw.boardColumns(false),
    raw.BOARD_COLUMNS,
    "boardColumns(false) must return the SAME array object as BOARD_COLUMNS, not an equal copy -- this identity is AC3's structural enforcement"
  );
});

test("2: boardColumns(true) deep-equals the six columns, cancelled LAST, mirroring cairn.py:1277", () => {
  assert.deepEqual(CairnLogic.boardColumns(true), [
    "backlog", "todo", "in-progress", "in-review", "done", "cancelled",
  ]);
});

test("3: boardColumns(true) does not mutate BOARD_COLUMNS", () => {
  CairnLogic.boardColumns(true);
  assert.deepEqual(CairnLogic.BOARD_COLUMNS, ["backlog", "todo", "in-progress", "in-review", "done"]);
});

test("4: boardColumns(true) returns a FRESH array on each call, not a cached/memoized one (raw-realm check)", () => {
  var raw = loadRawCairnLogic();
  var a = raw.boardColumns(true);
  var b = raw.boardColumns(true);
  assert.notEqual(a, b, "two separate calls must not return the identical array object -- a memoized 'true' branch would violate this without violating deepEqual");
  assert.deepEqual(a, b, "sanity: they must still be equal in VALUE");
});

// ================= 5: laneSummary's columns argument is required =================

test("5: laneSummary throws TypeError when columns is missing or not an array (§2, JC1)", () => {
  var issues = [issue("PT-1", "todo")];
  // NOT `assert.throws(fn, TypeError)` -- board-logic.js runs in its own vm
  // realm (see helpers.js), so a `throw new TypeError(...)` thrown inside it
  // is an instance of the SANDBOX's own TypeError constructor, not this
  // file's. `instanceof` (which assert.throws's class-form uses) is
  // realm-sensitive and would fail this assertion even for a correct
  // implementation -- verified empirically before writing this test.
  // Checking `.name` (a string, realm-independent) is the correct way to
  // assert "this is a TypeError" across the sandbox boundary.
  [undefined, null, "not-an-array", {}, 5, false].forEach((badColumns) => {
    assert.throws(
      () => CairnLogic.laneSummary(issues, badColumns),
      (err) => err.name === "TypeError",
      `columns=${JSON.stringify(badColumns)} must throw a TypeError, not silently default or misbehave`
    );
  });
});

// ================= 6-10: laneSummary with the columns argument =================

test("6: laneSummary(issues, boardColumns(false)) excludes cancelled -- PT-31 behavior, unchanged", () => {
  var issues = [issue("PT-1", "cancelled"), issue("PT-2", "done")];
  var summary = CairnLogic.laneSummary(issues, CairnLogic.boardColumns(false));
  assert.equal(summary.total, 1);
  assert.deepEqual(summary.byStatus, [{ status: "done", count: 1 }]);
});

test("7: laneSummary(issues, boardColumns(true)) includes cancelled, entry LAST in byStatus", () => {
  var issues = [
    issue("PT-1", "cancelled"),
    issue("PT-2", "done"),
    issue("PT-3", "todo"),
    issue("PT-4", "cancelled"),
  ];
  var summary = CairnLogic.laneSummary(issues, CairnLogic.boardColumns(true));
  assert.equal(summary.total, 4, "all four issues are column-backed once cancelled is in the set");
  assert.deepEqual(summary.byStatus, [
    { status: "todo", count: 1 },
    { status: "done", count: 1 },
    { status: "cancelled", count: 2 },
  ]);
});

test("8: chip-sum invariant (total === sum of byStatus) holds for BOTH column sets", () => {
  var issues = [
    issue("PT-1", "todo"),
    issue("PT-2", "todo"),
    issue("PT-3", "done"),
    issue("PT-4", "cancelled"),
    issue("PT-5", "cancelled"),
  ];
  [CairnLogic.boardColumns(false), CairnLogic.boardColumns(true)].forEach((columns) => {
    var summary = CairnLogic.laneSummary(issues, columns);
    var chipSum = summary.byStatus.reduce((sum, entry) => sum + entry.count, 0);
    assert.equal(summary.total, chipSum, `total must equal the chip sum for columns=${JSON.stringify(columns)}`);
  });
});

test("9: zero cancelled issues + boardColumns(true) -- NO {status:'cancelled', count:0} entry (§4, omit-zero applies to the new column too)", () => {
  var issues = [issue("PT-1", "todo"), issue("PT-2", "done")];
  var summary = CairnLogic.laneSummary(issues, CairnLogic.boardColumns(true));
  assert.deepEqual(summary.byStatus, [
    { status: "todo", count: 1 },
    { status: "done", count: 1 },
  ]);
  assert.equal(
    summary.byStatus.some((entry) => entry.status === "cancelled"),
    false,
    "an empty cancelled column must not get a phantom count:0 chip"
  );
});

test("10: a status in NEITHER set (e.g. 'archived') is excluded from total under boardColumns(true) too -- the rule is column-backed, not not-cancelled", () => {
  var issues = [issue("PT-1", "archived"), issue("PT-2", "done")];
  var summary = CairnLogic.laneSummary(issues, CairnLogic.boardColumns(true));
  assert.equal(summary.total, 1, "the 'archived' issue is backed by neither the five base columns nor cancelled");
  assert.deepEqual(summary.byStatus, [{ status: "done", count: 1 }]);
});
