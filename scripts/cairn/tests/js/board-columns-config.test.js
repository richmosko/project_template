"use strict";

// PT-38 (architect's ruling, temp/arch-ruling-pt38-board-columns.md § 4/§6):
// the client half of plumbing `/api/board`'s new `columns`/`swimlane` keys
// through to the rendered board.
//
// - `resolveColumns(configured)`: payload `columns` -> the active base
//   list. REFERENCE IDENTITY carries the byte-identical guarantee (PT-35
//   precedent, AC3): returns `BOARD_COLUMNS` ITSELF -- the same array
//   object -- when `configured` is absent/null, OR element-wise equal to
//   BOARD_COLUMNS; a fresh array only when the configured list actually
//   differs. Two cases must both hit the identity path: (a) an OLDER
//   server's payload that omits `columns` entirely (forward/backward
//   compat), (b) a payload that carries the default explicitly.
// - `boardColumns(columns, showCancelled)`: `columns` is now a REQUIRED
//   first argument, no default -- a missing/undefined argument throws
//   (same JC1 posture PT-35 established for laneSummary's `columns` arg).
// - `BOARD_COLUMNS` stays a literal array declaration in board-logic.js --
//   the PT-36 drift guard extracts it AS SOURCE TEXT; a dynamic
//   construction (e.g. computed from STATUSES minus cancelled at load
//   time) would silently defeat that guard. Not testable via node:vm
//   execution (both a literal and an equivalent dynamic construction
//   evaluate to the same array) -- pinned instead via a source-text
//   assertion here, same technique test_column_parity.py already applies
//   to this exact declaration from the Python side.
//
// `resolveColumns` does not exist in board-logic.js as of this commit;
// `boardColumns` still takes a single `showCancelled` argument (see
// board-columns.test.js's PT-38 header note for that half). Every test
// below is expected to fail (AttributeError-equivalent "not a function",
// a throw contract that doesn't fire, or a strictEqual identity check that
// fails) until implementation-lead's PT-38 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { loadCairnLogic, BOARD_LOGIC_PATH } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

// Same raw-realm escape hatch as board-columns.test.js's loadRawCairnLogic
// -- loadCairnLogic()'s wrapForRealm rehomes every function's return value
// fresh on each call, which makes strictEqual/reference-identity
// assertions unreliable through the wrapped API in BOTH directions (see
// that file's own extensive comment, or INTERFACE.md's Loading contract).
function loadRawCairnLogic() {
  var source = fs.readFileSync(BOARD_LOGIC_PATH, "utf8");
  var sandbox = {};
  vm.runInNewContext(source, sandbox, { filename: BOARD_LOGIC_PATH });
  return sandbox.CairnLogic;
}

// ================= resolveColumns: reference identity =================

test("resolveColumns(undefined) returns BOARD_COLUMNS ITSELF -- absent key, older-server compat (raw-realm check)", () => {
  var raw = loadRawCairnLogic();
  assert.strictEqual(raw.resolveColumns(undefined), raw.BOARD_COLUMNS);
});

test("resolveColumns(null) returns BOARD_COLUMNS ITSELF (raw-realm check)", () => {
  var raw = loadRawCairnLogic();
  assert.strictEqual(raw.resolveColumns(null), raw.BOARD_COLUMNS);
});

test("resolveColumns([...five default columns...]) returns BOARD_COLUMNS ITSELF, not an equal copy (raw-realm check)", () => {
  var raw = loadRawCairnLogic();
  var explicitDefault = ["backlog", "todo", "in-progress", "in-review", "done"];
  assert.strictEqual(
    raw.resolveColumns(explicitDefault),
    raw.BOARD_COLUMNS,
    "a payload carrying the default explicitly must still hit the identity path, not just the absent-key case"
  );
});

test("resolveColumns(customSubset) returns a DIFFERENT array, not BOARD_COLUMNS (raw-realm check)", () => {
  var raw = loadRawCairnLogic();
  var custom = ["todo", "done"];
  var result = raw.resolveColumns(custom);
  assert.notEqual(result, raw.BOARD_COLUMNS, "a genuinely different configured list must not alias BOARD_COLUMNS");
  assert.deepEqual(result, custom);
});

test("resolveColumns(customSubset) returns the values requested, in order", () => {
  assert.deepEqual(CairnLogic.resolveColumns(["done", "todo"]), ["done", "todo"]);
});

// ================= boardColumns: required columns argument =================

test("boardColumns throws when columns is missing/undefined (JC1, PT-35 precedent extended)", () => {
  [undefined, null, "not-an-array", {}, 5, false].forEach((badColumns) => {
    assert.throws(
      () => CairnLogic.boardColumns(badColumns, false),
      // instanceof is realm-sensitive across the vm boundary (verified
      // empirically in board-columns.test.js's own item 5) -- check
      // `.name`, not the class, same technique.
      (err) => err.name === "TypeError",
      `columns=${JSON.stringify(badColumns)} must throw a TypeError`
    );
  });
});

test("boardColumns(columns, false) returns columns itself when showCancelled is false (raw-realm check)", () => {
  var raw = loadRawCairnLogic();
  var custom = ["todo", "done"];
  assert.strictEqual(raw.boardColumns(custom, false), custom);
});

test("boardColumns(columns, true) appends cancelled to a CUSTOM column set too, not just the default", () => {
  assert.deepEqual(CairnLogic.boardColumns(["todo", "done"], true), ["todo", "done", "cancelled"]);
});

// ================= BOARD_COLUMNS stays a source-text literal =================

test("BOARD_COLUMNS is declared as a literal array in board-logic.js source (PT-36 drift-guard precondition)", () => {
  var source = fs.readFileSync(BOARD_LOGIC_PATH, "utf8");
  var match = source.match(/var\s+BOARD_COLUMNS\s*=\s*(\[[^\]]*\]);/);
  assert.ok(
    match,
    "expected `var BOARD_COLUMNS = [...]` as a literal array declaration -- a dynamic " +
      "construction (e.g. derived from STATUSES at load time) would silently defeat " +
      "test_column_parity.py's (PT-36) source-text extraction"
  );
  // The literal's VALUE must still be the five default columns -- this is
  // the JS half of §5 item 1 (the Python half extends test_column_parity.py
  // directly). Parsed as JSON since the literal is JSON-shaped (double-
  // quoted strings, no trailing comma).
  assert.deepEqual(JSON.parse(match[1]), ["backlog", "todo", "in-progress", "in-review", "done"]);
});

if (require.main === module) {
  // no-op; node:test's runner drives execution when invoked via `node --test`
}
