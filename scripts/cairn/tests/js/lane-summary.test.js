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
//   - `byStatus` iterates BOARD_COLUMNS in order; a status with zero issues
//     is omitted entirely (never a `{status, count: 0}` entry).
//   - a status value present on an issue but NOT in BOARD_COLUMNS (e.g.
//     "cancelled") produces no `byStatus` entry -- byStatus enumerates
//     known columns only, it does not discover statuses from the data.
//
// PT-31 (architect's triage ruling, item 1, superseding the PT-29 contract
// above): `total` is now the SUM of `byStatus` counts, not `issues.length`
// -- it counts only column-backed statuses, the same set byStatus already
// enumerates. Measured, not reasoned from the bug report: `columnsFor`
// builds columns for BOARD_COLUMNS only and a cancelled issue matches none
// of them, so it "renders nowhere" in an EXPANDED lane too -- the pre-PT-31
// `total: issues.length` therefore had an expanded lane reading e.g. "5"
// over four visible cards with Show-cancelled on, a mismatch chips (which
// only ever existed for the collapsed case) never touched. One source
// (`byStatus`) now backs both the header count and the chips, so they
// cannot disagree by construction -- chips summing to `total` is true FOR
// FREE, not a second invariant to maintain. Root cause (the checkbox being
// inert in kanban view) is explicitly NOT fixed here -- split to PT-35.
//
// laneSummary/BOARD_COLUMNS already shipped in PT-29 -- this commit's new
// cases (the exclude-cancelled-from-total tests below) are expected to fail
// against the CURRENT total-is-issues.length implementation, not against a
// missing function, until implementation-lead's PT-31 slice lands.

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

test("laneSummary: total counts every issue when every status is column-backed", () => {
  // Renamed from PT-29's "...regardless of status" -- PT-31 makes that
  // phrase false in general (see the cancelled-exclusion tests below);
  // this case still passes unchanged since all three statuses here ARE
  // column-backed, which is the point -- the common case is unaffected.
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

test("laneSummary: a status value not in BOARD_COLUMNS is excluded from total too (PT-31)", () => {
  // INVERTS the PT-29-era assertion (total used to be issues.length,
  // counting the cancelled issue). PT-31's ruling: total is the sum of
  // byStatus counts, so an issue whose status has no column contributes
  // to NEITHER -- an expanded lane's header count must equal what's
  // actually rendered, and a cancelled issue renders in no column.
  var issues = [issue("PT-1", "cancelled"), issue("PT-2", "done")];
  var summary = CairnLogic.laneSummary(issues);
  assert.equal(summary.total, 1, "total must exclude the cancelled issue -- it renders in no column, expanded or collapsed");
  assert.deepEqual(summary.byStatus, [{ status: "done", count: 1 }], "byStatus must not invent an entry for a non-column status");
});

test("laneSummary: total is exactly the sum of byStatus counts -- the chip-sum-equals-total invariant, with a cancelled issue present", () => {
  // The ruling's core property, asserted structurally (not by re-deriving
  // an expected number by hand) so it can never drift: whatever byStatus
  // says, total must match its sum. Mixes column-backed statuses with a
  // cancelled issue specifically, since that's the case PT-29 got wrong
  // (chips -- which sum byStatus -- and the header count -- issues.length
  // -- disagreed by exactly the cancelled count).
  var issues = [
    issue("PT-1", "todo"),
    issue("PT-2", "todo"),
    issue("PT-3", "done"),
    issue("PT-4", "cancelled"),
    issue("PT-5", "cancelled"),
  ];
  var summary = CairnLogic.laneSummary(issues);
  var chipSum = summary.byStatus.reduce(function (sum, entry) { return sum + entry.count; }, 0);
  assert.equal(summary.total, chipSum, "total must equal the sum of the chips -- one source, not two that must agree");
  assert.equal(summary.total, 3, "sanity: 3 column-backed issues (2 todo + 1 done), 2 cancelled excluded");
});

test("laneSummary: an all-cancelled lane has total 0 and an empty byStatus, not a phantom count", () => {
  var issues = [issue("PT-1", "cancelled"), issue("PT-2", "cancelled")];
  var summary = CairnLogic.laneSummary(issues);
  assert.deepEqual(summary, { total: 0, byStatus: [] });
});
