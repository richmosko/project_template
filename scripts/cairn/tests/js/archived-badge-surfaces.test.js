"use strict";

// PT-48: PT-42 stamps `archived` on every milestone/major record in the
// board payload (build_board_payload, cairn.py), but only the issue card
// renders it today (cardEl's `.is-archived` class + chip("archived",
// "archived") meta chip, board.js:606/652). Lane headers (milestoneLaneEl),
// major tabs (renderHeader), and the milestone/major record drawer
// (renderRecordDrawer) all ignore the flag -- an archived milestone/major
// looks identical to a live one on every one of those three surfaces.
//
// This slice adds an archived indicator to all three, reusing the existing
// chip("archived", "archived") treatment (lane header, drawer) or a muted
// class + title (major tab -- PT-40's own "no room for text on a tab"
// constraint already established for the status label, so the tab gets the
// SAME muted-not-text treatment the issue card itself uses via .is-archived,
// rather than fighting that constraint with a cramped chip).
//
// board.js is DOM/render-flow code with no jsdom harness in this suite --
// every test below is a source-text guard, same brace-matching-extractor
// technique as record-drawer-client.test.js/swimlane-init.test.js.
//
// Nothing under test exists yet: none of the three render functions read
// `.archived` off their record at all. Every red test below is expected to
// fail until implementation-lead's PT-48 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_JS_PATH = path.join(__dirname, "..", "..", "board", "board.js");
const BOARD_CSS_PATH = path.join(__dirname, "..", "..", "board", "board.css");

class ExtractionError extends Error {}

// Same brace-matching extractor as record-drawer-client.test.js /
// swimlane-init.test.js (duplicated, not imported -- each file in this
// suite is small and self-contained by convention).
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

function readBoardSource() {
  return fs.readFileSync(BOARD_JS_PATH, "utf8");
}

function readBoardCss() {
  return fs.readFileSync(BOARD_CSS_PATH, "utf8");
}

// ================= Lane header (milestoneLaneEl) =================

test("PT-48: milestoneLaneEl appends an archived chip when msRecord.archived is true", () => {
  const source = readBoardSource();
  const body = extractFunctionBody(source, "milestoneLaneEl");
  assert.match(body, /msRecord\.archived/, "expected milestoneLaneEl to read msRecord.archived");
  assert.match(
    body,
    /chip\(\s*"archived"\s*,\s*"archived"\s*\)/,
    'expected the SAME chip("archived", "archived") treatment cardEl already uses'
  );
});

// ================= Record drawer (renderRecordDrawer) =================

test("PT-48: renderRecordDrawer appends an archived chip when record.archived is true", () => {
  const source = readBoardSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /record\.archived/, "expected renderRecordDrawer to read record.archived");
  assert.match(
    body,
    /chip\(\s*"archived"\s*,\s*"archived"\s*\)/,
    'expected the SAME chip("archived", "archived") treatment cardEl already uses'
  );
});

// ================= Major tab (renderHeader) =================

test("PT-48: renderHeader's tab-button className ternary is UNCHANGED (regression guard)", () => {
  // Same guard as record-drawer-client.test.js's PT-40 regression test --
  // the archived indicator must be a SEPARATE statement, not folded into
  // this ternary, so the two features can never drift against each other.
  const source = readBoardSource();
  const body = extractFunctionBody(source, "renderHeader");
  assert.match(
    body,
    /state\.currentMajor\s*===\s*majorId\s*\?\s*"active"\s*:\s*""/,
    "the existing per-major tab button's className ternary must be byte-identical, untouched by this feature"
  );
});

test("PT-48: renderHeader marks an archived major's tab with a muted class + a title, not a cramped chip", () => {
  const source = readBoardSource();
  const body = extractFunctionBody(source, "renderHeader");
  assert.match(body, /majorRecord\.archived/, "expected renderHeader to read majorRecord.archived");
  assert.match(body, /is-archived/, "expected the tab button to gain an is-archived class when archived");
  assert.match(body, /\.title\s*=/, "expected a title attribute set on the archived tab for accessibility");
});

// ================= CSS: the muted major-tab treatment actually exists =================

test("PT-48: board.css defines a muted .majors-tabs button.is-archived treatment", () => {
  const css = readBoardCss();
  assert.match(
    css,
    /\.majors-tabs\s+button\.is-archived/,
    "expected a .majors-tabs button.is-archived rule in board.css"
  );
});
