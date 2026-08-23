"use strict";

// PT-44 §4 (joint ruling's own wording: "one rule, not a special case"):
// any change to a request-shaping parameter must clear state.etag before
// the next fetch -- an etag minted for one payload shape must never be
// sent as If-None-Match for a different one. implementation-lead's real
// finding reading the code: runPullRefresh currently does NOT clear the
// etag before refreshing (a bare `git tag` add with no file mtime change
// would 304 a pull-to-refresh today, serving a stale released state) --
// this is the gap the new `clearEtagAndRefresh()` helper closes, as the
// SINGLE producer both runPullRefresh and the #filter-archived listener
// (PT-42, currently `state.etag = null; refreshBoardSilently();` inline)
// route through, instead of two independent copies of the same rule.
//
// Source-text guards, same brace-matching-extractor technique as the
// rest of this suite's board.js coverage (no jsdom).
//
// Nothing under test exists yet: clearEtagAndRefresh is not defined, and
// runPullRefresh calls refreshBoardSilently() directly with no etag
// clear at all (the real, confirmed gap). Every test below is expected
// to fail until implementation-lead's PT-44 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_JS_PATH = path.join(__dirname, "..", "..", "board", "board.js");

class ExtractionError extends Error {}

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
    throw new ExtractionError("unbalanced braces while extracting `" + functionName + "`'s body.");
  }
  return source.slice(start, i - 1);
}

function readSource() {
  return fs.readFileSync(BOARD_JS_PATH, "utf8");
}

test("PT-44: clearEtagAndRefresh exists and clears state.etag before refreshing", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "clearEtagAndRefresh");
  assert.match(body, /state\.etag\s*=\s*null/, "clearEtagAndRefresh must clear state.etag");
  assert.match(body, /refreshBoardSilently\(\)/, "clearEtagAndRefresh must call refreshBoardSilently()");
});

test("PT-44: runPullRefresh routes through clearEtagAndRefresh (the real gap implementation-lead found)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "runPullRefresh");
  assert.match(
    body,
    /clearEtagAndRefresh\(\)/,
    "runPullRefresh must call clearEtagAndRefresh() -- a bare `git tag` add with no file mtime " +
      "change would otherwise 304 a pull-to-refresh, serving a stale released state"
  );
  assert.doesNotMatch(
    body,
    /refreshBoardSilently\(\)/,
    "runPullRefresh must not call refreshBoardSilently() directly anymore -- only through clearEtagAndRefresh"
  );
});

test("PT-44: the #filter-archived listener routes through clearEtagAndRefresh, not its own inline etag-clear (single producer)", () => {
  const source = readSource();
  const listenerMatch = source.match(
    /getElementById\(\s*"filter-archived"\s*\)\.addEventListener\(\s*"change"\s*,\s*function[\s\S]*?\{([\s\S]*?)\}\s*\)\s*;/
  );
  assert.ok(listenerMatch, "expected the #filter-archived change-listener callback to be extractable");
  assert.match(listenerMatch[1], /clearEtagAndRefresh\(\)/, "the listener must call clearEtagAndRefresh()");
});
