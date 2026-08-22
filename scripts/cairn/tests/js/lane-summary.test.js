"use strict";

// PT-29 (architect's ruling, section 4): laneSummary(issues) drives the
// collapsed-card status-breakdown chips ("label · n" per non-empty status,
// board-column order) -- shown only when a lane is collapsed, per the
// ruling's judgment call in section 1. BOARD_COLUMNS relocates from
// board.js into board-logic.js in the same move, as the single canonical
// column-order list laneSummary iterates -- a second, board.js-local copy
// would be the exact drift class PT-22's extraction pass exists to close.
//
// Contract this suite pins beyond the ruling's bare signature
// (`laneSummary(issues) -> {total, byStatus}`), QA's call per INTERFACE.md's
// "someone has to pick the concrete behavior" convention -- flag if
// implementation-lead finds a reason to diverge:
//   - `total` is `issues.length` -- ALL issues in the lane, matching the
//     existing `.swimlane-count` semantics unchanged by this feature.
//   - `byStatus` iterates BOARD_COLUMNS in order; a status with zero issues
//     is omitted entirely (never a `{status, count: 0}` entry).
//   - a status value present on an issue but NOT in BOARD_COLUMNS (e.g. a
//     value this board build doesn't recognize) contributes to `total` but
//     produces no `byStatus` entry -- byStatus enumerates known columns
//     only, it does not discover statuses from the data.
//
// Both laneSummary and CairnLogic.BOARD_COLUMNS are missing from
// board-logic.js as of this commit -- expected to fail with
// "CairnLogic.laneSummary is not a function" / BOARD_COLUMNS undefined
// until implementation-lead's slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function issue(id, status) {
  return { id: id, status: status };
}

test("BOARD_COLUMNS is exported from CairnLogic, relocated verbatim from board.js", () => {
  assert.deepEqual(CairnLogic.BOARD_COLUMNS, ["backlog", "todo", "in-progress", "in-review", "done"]);
});

test("laneSummary: empty input yields zero total and an empty byStatus list", () => {
  var summary = CairnLogic.laneSummary([]);
  assert.deepEqual(summary, { total: 0, byStatus: [] });
});

test("laneSummary: total counts every issue in the lane regardless of status", () => {
  var issues = [issue("PT-1", "todo"), issue("PT-2", "done"), issue("PT-3", "backlog")];
  assert.equal(CairnLogic.laneSummary(issues).total, 3);
});

test("laneSummary: byStatus follows board-column order, not input order", () => {
  var issues = [issue("PT-1", "done"), issue("PT-2", "backlog"), issue("PT-3", "in-progress")];
  var summary = CairnLogic.laneSummary(issues);
  assert.deepEqual(
    summary.byStatus.map(function (s) { return s.status; }),
    ["backlog", "in-progress", "done"]
  );
});

test("laneSummary: a status with zero issues is omitted entirely, never a count:0 entry", () => {
  var issues = [issue("PT-1", "todo"), issue("PT-2", "todo")];
  var summary = CairnLogic.laneSummary(issues);
  assert.deepEqual(summary.byStatus, [{ status: "todo", count: 2 }]);
});

test("laneSummary: counts are correct per status", () => {
  var issues = [
    issue("PT-1", "todo"),
    issue("PT-2", "todo"),
    issue("PT-3", "done"),
    issue("PT-4", "in-review"),
    issue("PT-5", "in-review"),
    issue("PT-6", "in-review"),
  ];
  var summary = CairnLogic.laneSummary(issues);
  assert.deepEqual(summary.byStatus, [
    { status: "todo", count: 2 },
    { status: "in-review", count: 3 },
    { status: "done", count: 1 },
  ]);
  assert.equal(summary.total, 6);
});

test("laneSummary: a status value not in BOARD_COLUMNS contributes to total but not to byStatus", () => {
  var issues = [issue("PT-1", "cancelled"), issue("PT-2", "done")];
  var summary = CairnLogic.laneSummary(issues);
  assert.equal(summary.total, 2, "total must still count the unrecognized-status issue");
  assert.deepEqual(summary.byStatus, [{ status: "done", count: 1 }], "byStatus must not invent an entry for a non-column status");
});
