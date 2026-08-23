"use strict";

// PT-40 (joint PT-40/43/44 ruling § 5/§6, implementation-lead's Pass-1
// message, 2026-08-23): drawer/card generalization -- `state.openIssueId`
// becomes `state.openRecord = {kind, id, repo}`, with a new
// `openRecordDrawer(kind, id, repoId)` (a LOOKUP against
// `state.board.milestones`/`state.board.majors`, never a fetch -- ruling
// §1 rejects a second endpoint, the data is already in the payload) and a
// new `renderRecordDrawer(record)` that REUSES the existing drawer/overlay
// DOM (no second panel). Clicking a milestone lane header's label opens
// its card (ruling §2's own wording); a major tab gets a sibling `▸` open
// button (not nested -- a button-in-button is invalid HTML).
//
// board.js is DOM/render-flow code with no jsdom harness in this suite --
// every test below is a source-text guard, same brace-matching-extractor
// technique as swimlane-init.test.js/show-archived-client.test.js.
//
// Nothing under test exists yet: `openIssueId` is still the live state
// key everywhere, there is no `openRecordDrawer`/`renderRecordDrawer`,
// and no major-tab open button. Every test below is expected to fail
// until implementation-lead's PT-40 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_JS_PATH = path.join(__dirname, "..", "..", "board", "board.js");

class ExtractionError extends Error {}

// Same brace-matching extractor as swimlane-init.test.js /
// show-archived-client.test.js (duplicated, not imported -- each file in
// this suite is small and self-contained by convention).
function extractFunctionBody(source, functionName) {
  var match = source.match(new RegExp("function\\s+" + functionName + "\\s*\\([^)]*\\)\\s*\\{"));
  if (!match) {
    throw new ExtractionError(
      "could not find `function " + functionName + "(...) {` in board.js -- if this " +
        "function was renamed or restructured, this guard needs to be updated, not silenced."
    );
  }
  var start = match.index + match[0].length;
  var depth = 1;
  var i = start;
  for (; i < source.length && depth > 0; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}") depth--;
  }
  if (depth !== 0) {
    throw new ExtractionError(
      "unbalanced braces while extracting `" + functionName + "`'s body -- this guard's " +
        "naive brace-counter doesn't handle a brace inside a string/regex literal."
    );
  }
  return source.slice(start, i - 1);
}

function readSource() {
  return fs.readFileSync(BOARD_JS_PATH, "utf8");
}

// ================= state.openIssueId -> state.openRecord =================

test("PT-40: state.openIssueId no longer exists ANYWHERE in board.js (full rename, no half-migrated reader)", () => {
  const source = readSource();
  const remaining = source.match(/state\.openIssueId/g) || [];
  assert.deepEqual(
    remaining, [],
    `found ${remaining.length} remaining state.openIssueId reference(s) -- every reader/writer ` +
      "must move to state.openRecord (ruling §5: do NOT keep a parallel/half-migrated encoding)"
  );
});

test("PT-40: state literal declares openRecord: null (was openIssueId: null)", () => {
  const source = readSource();
  assert.match(source, /openRecord\s*:\s*null/, "expected `openRecord: null` in the state object literal");
});

test("PT-40: openDrawer STAYS the issue-only entry point, sets state.openRecord = {kind: \"issue\", id}", () => {
  // implementation-lead's locking message: openDrawer(id) is UNCHANGED as
  // an entry point (every existing caller -- issueLinkListEl, card click,
  // etc. -- stays the same) -- only its internal assignment changes.
  const source = readSource();
  const match = source.match(/function\s+openDrawer\s*\(\s*id\s*\)/);
  assert.ok(match, "openDrawer must keep its single-argument (id) signature -- existing callers are unchanged");
  const body = extractFunctionBody(source, "openDrawer");
  assert.match(body, /state\.openRecord\s*=/, "openDrawer must assign state.openRecord");
  assert.match(body, /kind\s*:\s*"issue"/, 'openDrawer must set kind: "issue"');
});

test("PT-40: closeDrawer clears state.openRecord (not state.openIssueId)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "closeDrawer");
  assert.match(body, /state\.openRecord\s*=\s*null/, "closeDrawer must set state.openRecord = null");
});

test("PT-40: renderDrawer's race-guard checks BOTH kind and id on state.openRecord", () => {
  // Locked shape: `if (!state.openRecord || state.openRecord.kind !== "issue"
  // || state.openRecord.id !== issue.id) return;` -- a bare id comparison
  // alone (the old `state.openIssueId !== issue.id` shape, minus the
  // rename) would silently pass for a milestone/major record that happens
  // to share an id string with a live issue.
  const source = readSource();
  const body = extractFunctionBody(source, "renderDrawer");
  assert.match(body, /state\.openRecord/, "renderDrawer's race-guard must read state.openRecord");
  assert.match(body, /\.kind\s*!==\s*"issue"/, 'the race-guard must check kind !== "issue"');
  assert.match(body, /\.id\s*!==\s*issue\.id/, "the race-guard must still check the id too");
});

test("PT-40: pullCancelFlags and wheelCancelFlags read state.openRecord for drawerOpen", () => {
  const source = readSource();
  const pullBody = extractFunctionBody(source, "pullCancelFlags");
  const wheelBody = extractFunctionBody(source, "wheelCancelFlags");
  assert.match(pullBody, /drawerOpen\s*:\s*state\.openRecord\s*!==\s*null/, "pullCancelFlags");
  assert.match(wheelBody, /drawerOpen\s*:\s*state\.openRecord\s*!==\s*null/, "wheelCancelFlags");
});

// ================= openRecordDrawer: lookup, not fetch =================

test("PT-40: openRecordDrawer exists and takes (recordKind, id, repoId)", () => {
  // Parameter named `recordKind`, NOT `kind` -- locked in implementation-
  // lead's signature message; a test anchored on the wrong parameter name
  // would never match even a correct implementation.
  const source = readSource();
  const match = source.match(/function\s+openRecordDrawer\s*\(\s*recordKind\s*,\s*id\s*,\s*repoId\s*\)/);
  assert.ok(match, "expected `function openRecordDrawer(recordKind, id, repoId)` in board.js");
});

test("PT-40: openRecordDrawer is a LOOKUP against state.board (milestones/majors), never a fetch", () => {
  // Ruling §1 explicitly rejects a second endpoint (GET /api/milestone/<id>)
  // -- the record data is already in the /api/board payload. A `fetch(`
  // call inside this function would mean a second read path implementation-
  // lead's own plan didn't intend. Synchronous lookup -- no `.then(`, no
  // await -- there's nothing to wait on.
  const source = readSource();
  const body = extractFunctionBody(source, "openRecordDrawer");
  assert.doesNotMatch(body, /fetch\(/, "openRecordDrawer must not fetch -- it looks up an already-fetched record");
  assert.match(
    body,
    /state\.board\.(milestones|majors)/,
    "openRecordDrawer must read state.board.milestones or state.board.majors"
  );
});

test("PT-40: openRecordDrawer calls renderRecordDrawer synchronously (no .then chain to await)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "openRecordDrawer");
  assert.doesNotMatch(body, /\.then\(/, "a synchronous lookup has nothing to .then() -- unlike openDrawer's fetch");
  assert.match(body, /renderRecordDrawer\(/, "openRecordDrawer must call renderRecordDrawer directly");
});

// ================= renderRecordDrawer: reuses the existing drawer DOM =================

test("PT-40: renderRecordDrawer takes (recordKind, record) -- kind is NEVER inferred from record.kind", () => {
  // The exact collision implementation-lead confirmed: milestones already
  // have their OWN `kind` field (process|product -- definition vs.
  // development), semantically unrelated to "is this a milestone or a
  // major". recordKind is always known at the call site (openRecordDrawer
  // passes it explicitly) -- there is nothing to infer, and inferring
  // from record.kind would silently misread a milestone's own field.
  const source = readSource();
  const match = source.match(/function\s+renderRecordDrawer\s*\(\s*recordKind\s*,\s*record\s*\)/);
  assert.ok(match, "expected `function renderRecordDrawer(recordKind, record)` -- two explicit params");
});

test("PT-40: renderRecordDrawer exists and reuses #drawer-overlay/#drawer, not a second panel", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /getElementById\(\s*"drawer-overlay"\s*\)/, "must reuse the existing #drawer-overlay");
  assert.match(body, /getElementById\(\s*"drawer"\s*\)/, "must reuse the existing #drawer");
});

test("PT-40: renderRecordDrawer renders the record's body via the existing renderMarkdown helper", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /renderMarkdown\(/, "must call the existing renderMarkdown helper, not a bespoke renderer");
});

// ================= Major tab: status dot + sibling open button =================

test("PT-40: renderHeader's existing tab-button className logic is UNCHANGED (regression guard)", () => {
  // implementation-lead's own point: the status dot is a CHILD of the
  // existing button, the open button is a SIBLING appended after it --
  // neither should touch the tab button's own active/"" className logic.
  const source = readSource();
  const body = extractFunctionBody(source, "renderHeader");
  assert.match(
    body,
    /state\.currentMajor\s*===\s*majorId\s*\?\s*"active"\s*:\s*""/,
    "the existing per-major tab button's className ternary must be byte-identical, untouched by this feature"
  );
});

test("PT-40: renderHeader adds a status-dot child + a sibling major-tab-open button with an aria-label", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderHeader");
  assert.match(body, /major-status-dot/, "expected a status-dot element (class major-status-dot) per major tab");
  assert.match(body, /major-tab-open/, "expected the sibling open button (class major-tab-open)");
  assert.match(body, /aria-label/, "expected an aria-label set on the major-tab open button");
  assert.match(
    body,
    /openRecordDrawer\(\s*"major"/,
    'expected an openRecordDrawer("major", ...) call wired into renderHeader (the tab open button)'
  );
});

test("PT-40: the major-tab open button stops click propagation (defense-in-depth against the tab's own filter click)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderHeader");
  assert.match(body, /stopPropagation\(\)/, "expected e.stopPropagation() on the major-tab open button's click handler");
});

// ================= Milestone lane header: label click opens the card =================

test("PT-40: milestoneLaneEl's label click opens the milestone's card (ruling §2's own wording)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "milestoneLaneEl");
  assert.match(
    body,
    /openRecordDrawer\(\s*"milestone"/,
    'expected an openRecordDrawer("milestone", ...) call wired into milestoneLaneEl (the label click)'
  );
});

test("PT-40 (architect's approval finding): the label span has its OWN keydown handler for Enter/Space", () => {
  // A `role="button"` <span> does NOT synthesize a click from Enter/Space
  // the way a real <button> does (the major tab's open button gets this
  // for free) -- without an explicit keydown handler here, a keyboard user
  // tabbing to the label and pressing Enter/Space gets silently nothing.
  const source = readSource();
  const body = extractFunctionBody(source, "milestoneLaneEl");

  // Isolate the "keydown" listener's own callback text specifically (not
  // just "does openRecordDrawer appear anywhere in milestoneLaneEl" --
  // the click handler already has that call; this must find it INSIDE
  // the keydown callback, or a keydown listener that does something else
  // entirely would false-pass).
  const keydownMatch = body.match(/addEventListener\(\s*"keydown"\s*,\s*function\s*\([^)]*\)\s*\{([\s\S]*?)\}\s*\)\s*;/);
  assert.ok(keydownMatch, "expected an addEventListener(\"keydown\", function (e) { ... }); listener on the label span");

  const keydownBody = keydownMatch[1];
  assert.match(
    keydownBody,
    /e\.key\s*===\s*"Enter"\s*\|\|\s*e\.key\s*===\s*" "/,
    'expected the keydown handler to check both Enter and Space (e.key === "Enter" || e.key === " ")'
  );
  assert.match(
    keydownBody,
    /openRecordDrawer\(\s*"milestone"/,
    'expected the keydown handler to call openRecordDrawer("milestone", ...) -- the same action as the click path'
  );
});
