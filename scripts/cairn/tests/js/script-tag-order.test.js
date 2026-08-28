"use strict";

// PT-55 (architect's "flash disposition" ruling, 2026-08-27): board.js
// moved its embed class-add + href rewrites from inside init() (bound to
// DOMContentLoaded) to MODULE SCOPE, closing a one-frame flash where the
// wordmark/#tab-dashboard could paint visible before body.embed applied.
// That move depends on a precondition that's real but was previously
// invisible: board-logic.js and board.js must be the LAST TWO elements
// before </body> in board.html, in that order -- only then is
// document.body (and every anchor board.js's module-scope code reaches
// for, #tab-kanban/#tab-list) already parsed and reachable at the moment
// these two <script> tags actually execute. board.js's own module-scope
// comment names this file by filename as the guard for that precondition
// -- this is that file.
//
// Moving either script tag to <head>, or adding `defer`/`async` to
// either, breaks the precondition with a null-deref at load (loud, not
// silent, so a human debugging it will find this comment fast) -- but a
// REORDER (board.js before board-logic.js, or either one moved earlier in
// the existing tail) fails silently at first (board.js still runs after
// DOMContentLoaded-adjacent parsing) and only breaks the FLASH FIX
// specifically, which is much harder to notice. This guard exists for
// that second, quieter failure mode.
//
// Source-text guard (no jsdom in this suite, same as every other DOM/
// render-flow check here) -- extracts the actual last-two-<script>-tags
// from board.html rather than scanning the whole file for the strings
// "board-logic.js"/"board.js" (which would also match the PT-4 vendor
// script comment above them, an ExtractionError-worthy false-positive
// risk of exactly the class architect's diff-review caught elsewhere in
// this feature).

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_HTML_PATH = path.join(__dirname, "..", "..", "board", "board.html");

class ExtractionError extends Error {}

function readBoardHtml() {
  return fs.readFileSync(BOARD_HTML_PATH, "utf8");
}

// The last two <script>...</script> tags appearing before </body>, in
// document order. Throws (never returns fewer than 2 silently) if
// </body> is missing or fewer than two script tags precede it.
function extractLastTwoScriptTagsBeforeBodyClose(html) {
  var bodyCloseIndex = html.lastIndexOf("</body>");
  if (bodyCloseIndex === -1) {
    throw new ExtractionError(
      "could not find </body> in board.html -- if the document structure changed, " +
        "this guard needs to be updated, not silenced."
    );
  }
  var beforeBodyClose = html.slice(0, bodyCloseIndex);
  var scriptTags = beforeBodyClose.match(/<script\b[^>]*>\s*<\/script>/g) || [];
  if (scriptTags.length < 2) {
    throw new ExtractionError(
      "expected at least two <script> tags before </body> in board.html, found " +
        scriptTags.length + " -- if script tags were removed/restructured, this guard " +
        "needs to be updated, not silenced."
    );
  }
  return { lastTwo: scriptTags.slice(-2), beforeBodyClose: beforeBodyClose };
}

test("PT-55 (flash-fix precondition): board-logic.js then board.js are the last two <script> tags before </body>, in that order", () => {
  var extracted = extractLastTwoScriptTagsBeforeBodyClose(readBoardHtml());
  var lastTwo = extracted.lastTwo;
  assert.match(
    lastTwo[0], /board-logic\.js/,
    "the second-to-last <script> before </body> must be board-logic.js, got: " + lastTwo[0]
  );
  assert.match(
    lastTwo[1], /board\.js"/,
    "the LAST <script> before </body> must be board.js (not board-logic.js, note the trailing " +
      "quote in the pattern), got: " + lastTwo[1]
  );
});

test("PT-55 (flash-fix precondition): nothing but whitespace sits between board.js's <script> tag and </body>", () => {
  // "Last element before </body>" is a loose claim if trailing markup
  // (another script, a stray element) could sit after board.js and still
  // pass the "last TWO tags" check above -- this closes that gap.
  var extracted = extractLastTwoScriptTagsBeforeBodyClose(readBoardHtml());
  var boardJsTag = extracted.lastTwo[1];
  var lastScriptEnd = extracted.beforeBodyClose.lastIndexOf(boardJsTag) + boardJsTag.length;
  var trailing = extracted.beforeBodyClose.slice(lastScriptEnd);
  assert.match(
    trailing, /^\s*$/,
    "unexpected non-whitespace content between board.js's <script> tag and </body>: " +
      JSON.stringify(trailing)
  );
});

test("negative control: fewer than two script tags before </body> raises loudly, not silently", () => {
  var fakeHtml = "<html><body><script src=\"only-one.js\"></script></body></html>";
  assert.throws(() => extractLastTwoScriptTagsBeforeBodyClose(fakeHtml), ExtractionError);
});

test("negative control: missing </body> raises loudly, not silently", () => {
  var fakeHtml = "<html><body><script src=\"a.js\"></script><script src=\"b.js\"></script>";
  assert.throws(() => extractLastTwoScriptTagsBeforeBodyClose(fakeHtml), ExtractionError);
});

test("negative control: a real order violation is caught (sanity)", () => {
  var fakeHtml =
    "<html><body>" +
    '<script src="/board/board.js"></script>' +
    '<script src="/board/board-logic.js"></script>' +
    "</body></html>";
  var extracted = extractLastTwoScriptTagsBeforeBodyClose(fakeHtml);
  // This fixture deliberately has board.js loading FIRST and board-logic.js
  // LAST -- the wrong order. The extractor must report what's actually
  // there (board-logic.js as the final tag), not silently "correct" it --
  // that's what lets the real assertion above catch a real regression.
  assert.match(
    extracted.lastTwo[1], /board-logic\.js/,
    "sanity: expected the extractor to faithfully report this deliberately-wrong fixture's " +
      "actual last tag (board-logic.js), proving it reflects reality rather than expectations"
  );
});
