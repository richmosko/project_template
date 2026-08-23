"use strict";

// PT-44 §7 (joint PT-40/43/44 ruling): the top progress strip is retired
// with zero information loss -- `#milestone-progress` removed from
// board.html, its renderHeader() block removed from board.js, its CSS
// rule removed from board.css. Everything it used to show (id, name, GA,
// target_tag, n/m done) is reachable on the milestone's own lane header
// (PT-40, already landed) or its card (PT-40's drawer + this loop's §3
// done-ratio-suppression / §4 release-state additions).
//
// Plain text-presence/absence checks across three static files -- no
// execution needed, so no brace-matching extractor required here (unlike
// the drawer/lane-header guards elsewhere in this suite).
//
// Expected RED until implementation-lead's PT-44 slice removes all three
// references -- the strip is still fully present today (verified directly:
// board.html:33, board.css:197, board.js:484 all reference it as of this
// commit).

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_DIR = path.join(__dirname, "..", "..", "board");
const BOARD_HTML_PATH = path.join(BOARD_DIR, "board.html");
const BOARD_JS_PATH = path.join(BOARD_DIR, "board.js");
const BOARD_CSS_PATH = path.join(BOARD_DIR, "board.css");

function readFile(p) {
  return fs.readFileSync(p, "utf8");
}

test("PT-44 §7: #milestone-progress element is removed from board.html", () => {
  const source = readFile(BOARD_HTML_PATH);
  assert.doesNotMatch(
    source,
    /id="milestone-progress"/,
    "expected the #milestone-progress element to be removed from board.html entirely"
  );
});

test("PT-44 §7: no remaining reference to \"milestone-progress\" in board.js", () => {
  const source = readFile(BOARD_JS_PATH);
  const remaining = source.match(/milestone-progress/g) || [];
  assert.deepEqual(
    remaining, [],
    `found ${remaining.length} remaining "milestone-progress" reference(s) in board.js -- ` +
      "the strip-population block in renderHeader() must be fully removed, not left dead/unreachable"
  );
});

test("PT-44 §7: no remaining \".milestone-progress\" CSS rule in board.css", () => {
  const source = readFile(BOARD_CSS_PATH);
  assert.doesNotMatch(
    source,
    /\.milestone-progress\s*\{/,
    "expected the .milestone-progress CSS rule to be removed from board.css"
  );
});

// Regression guard, not a red -- the strip's underlying data producer
// (milestoneProgress, board-logic.js) is explicitly KEPT per the ruling
// ("stays and gains the §3 status branch") -- only the STRIP UI goes,
// never the function every lane header/card now depends on for its own
// progress display. A test that only checked "no more mentions of
// milestone-progress" could not by itself distinguish "the strip was
// removed" from "the whole feature was gutted" -- this pins that the
// underlying computation survives.
test("PT-44 regression guard: milestoneProgress itself is NOT removed from board-logic.js (only the strip UI is)", () => {
  const boardLogicSource = readFile(path.join(BOARD_DIR, "board-logic.js"));
  assert.match(
    boardLogicSource,
    /function\s+milestoneProgress\s*\(/,
    "milestoneProgress must survive -- lane headers and cards depend on it for their own progress display"
  );
});
