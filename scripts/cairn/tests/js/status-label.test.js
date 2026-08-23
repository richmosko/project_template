"use strict";

// PT-37 (architect's ruling reference, 2026-08-23, PT-36 review § "board.js:622
// asymmetry"): board.js's column-header label (`STATUS_LABELS[status]`, no
// fallback) and the collapsed-lane summary chip's label
// (`STATUS_LABELS[entry.status] || entry.status`) are the same lookup
// duplicated with different fallback behaviour -- a status absent from
// STATUS_LABELS renders literally "undefined" as a column header today.
//
// implementation-lead's fix, confirmed as design of record by team-lead
// (2026-08-23): relocate STATUS_LABELS from board.js into board-logic.js --
// same move PT-29 made for BOARD_COLUMNS -- as CairnLogic.STATUS_LABELS,
// and add CairnLogic.statusLabel(status) as the single fallback-safe lookup
// BOTH call sites (column header, collapsed-lane chip) route through. This
// supersedes this suite's earlier status-label-fallback.test.js (source-text
// extraction directly against board.js's inline expression, written before
// this relocation was decided and deleted in this commit) -- that file's
// anchor pattern (`header.innerHTML = "<span>" + STATUS_LABELS[status] +
// ...`) stops matching entirely once the inline expression is replaced by a
// statusLabel(status) call, so keeping it around would mean a permanently
// loud ExtractionError post-fix, not a clean red-then-green story.
//
// Expected RED until CairnLogic.statusLabel exists: CairnLogic.statusLabel
// is undefined on the current board-logic.js, so calling it throws
// "CairnLogic.statusLabel is not a function". The two dedupe-guard tests at
// the bottom (reading board.js as text) are ALSO red today, for a
// different, complementary reason: they assert on board.js's CALL SITES
// (has the inline `STATUS_LABELS[...]` shape been fully retired there, in
// favour of statusLabel() at both :627 and :767?), independent of whether
// board-logic.js's own export is correct -- a board-logic.js fix alone,
// with board.js never wired up to call it, would leave these two red while
// the CairnLogic-level tests above go green. Both guards must be green
// together for PT-37 to be done.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();
const BOARD_JS_PATH = path.join(__dirname, "..", "..", "board", "board.js");

test("statusLabel: a known status returns its mapped label", () => {
  assert.equal(CairnLogic.statusLabel("done"), "Done");
});

test("statusLabel: every current STATUS_LABELS key maps through unchanged (no accidental typo during relocation)", () => {
  assert.equal(CairnLogic.statusLabel("backlog"), "Backlog");
  assert.equal(CairnLogic.statusLabel("todo"), "Todo");
  assert.equal(CairnLogic.statusLabel("in-progress"), "In Progress");
  assert.equal(CairnLogic.statusLabel("in-review"), "In Review");
  assert.equal(CairnLogic.statusLabel("cancelled"), "Cancelled");
});

test("PT-37: an unknown/future status falls back to the raw status string, not undefined", () => {
  assert.equal(CairnLogic.statusLabel("some-future-status"), "some-future-status");
});

test("PT-37: falsy-but-real status values are not swallowed by the fallback (|| pitfall)", () => {
  // A naive `STATUS_LABELS[status] || status` is safe here because the
  // FALLBACK side is always truthy for any non-empty status string -- this
  // pins that an empty-string status (falsy on both sides) still returns
  // the empty string, not some other coerced value, in case a future
  // rewrite changes the expression shape.
  assert.equal(CairnLogic.statusLabel(""), "");
});

test("PT-37 (architect's review finding F1): an Object.prototype member name reads as unknown, not as an inherited function", () => {
  // A naive `STATUS_LABELS[status] || status` reads THROUGH the prototype
  // chain for a key shaped like an inherited Object.prototype member --
  // "constructor" would resolve to the Object function itself (rendered as
  // "function Object() { [native code] }" in a column header). The
  // own-property guard treats it as absent from the map, same as any
  // other unknown status.
  assert.equal(CairnLogic.statusLabel("constructor"), "constructor");
});

test("PT-37 (architect's review finding F1): __proto__ does not throw on string coercion", () => {
  // The sharper failure mode: `STATUS_LABELS["__proto__"]` resolves to
  // STATUS_LABELS's own prototype object, and coercing THAT to a string
  // (as the header's old "<span>" + statusLabel(status) concat did) threw
  // TypeError: Cannot convert object to primitive value -- killing the
  // whole render, not just that one header. Asserting this doesn't throw
  // (and returns the bare key, per the own-property guard) pins the fix.
  assert.doesNotThrow(() => CairnLogic.statusLabel("__proto__"));
  assert.equal(CairnLogic.statusLabel("__proto__"), "__proto__");
});

test("STATUS_LABELS is exported from CairnLogic (single source of truth, board.js no longer owns it)", () => {
  assert.deepEqual(CairnLogic.STATUS_LABELS, {
    backlog: "Backlog",
    todo: "Todo",
    "in-progress": "In Progress",
    "in-review": "In Review",
    done: "Done",
    cancelled: "Cancelled",
  });
});

// -- Dedupe guards (team-lead's ask, per WORKFLOW.md's grep-for-old-inline-
// shape convention): the CairnLogic tests above prove statusLabel() BEHAVES
// correctly in isolation; they say nothing about whether board.js's two
// call sites were actually rewired to use it. These two read board.js as
// text and check for the ABSENCE of the old inline `STATUS_LABELS[...]`
// indexing shape, and the PRESENCE of statusLabel( calls, so a fix that
// only touches board-logic.js (leaving board.js's :627/:767 untouched)
// still shows red here even though the tests above are green.

test("dedupe guard: board.js no longer inlines STATUS_LABELS[...] indexing at the header or chip call sites", () => {
  const source = fs.readFileSync(BOARD_JS_PATH, "utf8");
  // Matches the OLD inline shape at both call sites: `STATUS_LABELS[status]`
  // (header, pre-fix) and `STATUS_LABELS[entry.status]` (chip, pre-fix --
  // it already had a `|| entry.status` fallback bolted on, but the indexing
  // itself was still inline). Deliberately does NOT match line ~1182's
  // `Object.keys(STATUS_LABELS)` / bare `STATUS_LABELS` drawer usage --
  // that one legitimately keeps reading the raw map (it enumerates every
  // known status for a <select>, no per-status fallback applies there) and
  // is out of scope for this guard.
  const inlineIndexing = source.match(/STATUS_LABELS\[\s*(?:status|entry\.status)\s*\]/g) || [];
  assert.deepEqual(
    inlineIndexing,
    [],
    "found " +
      inlineIndexing.length +
      " inline STATUS_LABELS[...] indexing site(s) still in board.js -- " +
      "both the column header and the collapsed-lane chip must route through " +
      "CairnLogic.statusLabel(status) instead of indexing the map directly " +
      "(PT-37's dedupe requirement, not just a correct board-logic.js export)"
  );
});

test("dedupe guard: both the column header and the chip call statusLabel(...)", () => {
  const source = fs.readFileSync(BOARD_JS_PATH, "utf8");
  const statusLabelCalls = source.match(/\bstatusLabel\(\s*(?:status|entry\.status)\s*\)/g) || [];
  assert.equal(
    statusLabelCalls.length,
    2,
    "expected exactly 2 statusLabel(...) call sites in board.js (column header " +
      "+ collapsed-lane chip), found " +
      statusLabelCalls.length +
      ". If a third legitimate call site is added, update this guard's expected " +
      "count deliberately -- don't just raise it to make a failure go away."
  );
});

// PT-37 (architect's review finding F2): the column header's label used to
// be built via `header.innerHTML = "<span>" + statusLabel(status) + ...`
// -- once statusLabel's input can be arbitrary free text (a status is no
// longer necessarily one of the five/six hardcoded STATUS_LABELS keys,
// e.g. once PT-38 lets a column's status come from config.yml), an
// innerHTML concat means that free text is HTML-PARSED, not just
// rendered -- a status value containing "<" would be interpreted as
// markup. PT-20's ruling: free text from a hand-editable file must be
// DOM-built (createElement + textContent), never HTML-parsed. This guard
// pins the DOM-built shape at the source-text level -- no test in this
// suite can execute board.js's DOM code directly (see this file's header
// comment / status-label-fallback.test.js's retirement), so "does the
// label ever cross an innerHTML boundary" is checked the same way the
// dedupe guards above check call-site wiring: read as text, assert on the
// pattern.
test("dedupe guard: statusLabel's result never crosses an innerHTML boundary (DOM-built via textContent, per PT-20)", () => {
  const source = fs.readFileSync(BOARD_JS_PATH, "utf8");

  // Nothing that assigns to `.innerHTML` may have `statusLabel(` anywhere
  // in the same statement -- scoped to a single `;`-terminated statement
  // (non-greedy up to the first semicolon) so this can't false-positive
  // by matching some unrelated later innerHTML assignment elsewhere in
  // the file merely because statusLabel( appears earlier in the source.
  const innerHTMLWithStatusLabel = source.match(/innerHTML\s*=[^;]*?statusLabel\([^;]*?;/g) || [];
  assert.deepEqual(
    innerHTMLWithStatusLabel,
    [],
    "found statusLabel(...) feeding an innerHTML assignment in board.js -- " +
      "per PT-20/F2, a status label must be DOM-built (createElement + " +
      "textContent), never HTML-parsed, since its input is no longer " +
      "guaranteed to be one of the hardcoded STATUS_LABELS values"
  );

  // And the positive half: the column header specifically routes
  // statusLabel(status) through a .textContent assignment (not just
  // "innerHTML happens to be absent nearby" -- that alone wouldn't prove
  // textContent is what's actually used).
  const textContentAssignment = source.match(/\.textContent\s*=\s*statusLabel\(status\)/);
  assert.ok(
    textContentAssignment,
    "expected to find `<span>.textContent = statusLabel(status)` in board.js's " +
      "makeColumn -- the column header's label must be set via textContent, " +
      "not innerHTML string-concatenation"
  );
});
