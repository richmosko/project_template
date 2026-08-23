"use strict";

// PT-38 (architect's ruling § 6): `state.swimlanesOn` initializes from the
// payload's `swimlane` key -- `data.swimlane !== "none"` -- but ONLY on
// the one-time initial load inside `init()`'s `apiGetBoard().then(...)`
// callback, NEVER inside `refreshBoardSilently`'s recurring poll/SSE-
// refresh path. The ruling's own reasoning: the Swimlanes checkbox owns
// `swimlanesOn` for the rest of the session once a user toggles it --
// re-deriving from every subsequent payload (a poll fires every few
// seconds) would silently stomp a manual toggle the next time the board
// refreshes in the background.
//
// board.js is DOM/render-flow code with no jsdom harness in this suite
// (see status-label.test.js's header comment, same class of problem PT-37
// hit) -- this is a source-text guard, same technique as PT-37's dedupe
// guards: read board.js as text, extract each named function's body via
// brace-matching (regex alone can't handle nested braces reliably), and
// assert on presence/absence within the RIGHT function specifically, not
// just "does this substring appear anywhere in the file" (which would
// pass even if the assignment were in the wrong callback entirely).
//
// implementation-lead self-verified this placement already (their PT-38
// completion message, 2026-08-23) -- this test exists as the PERMANENT
// regression guard for that verification, not a first red/green cycle:
// expected GREEN against the current board.js, confirmed by reading the
// real init()/refreshBoardSilently source directly before writing the
// extractor (same non-vacuity discipline as every other guard in this
// suite -- see the negative-control tests below, which prove the
// extractor can actually fail).

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_JS_PATH = path.join(__dirname, "..", "..", "board", "board.js");

class ExtractionError extends Error {}

// Brace-matching extractor: finds `function <name>(...) {`, then walks
// forward counting `{`/`}` (naively, char-by-char -- board.js has no
// string/regex literals containing brace characters inside either of the
// two functions this guard targets, verified by inspection) until the
// count returns to zero, i.e. the function's closing brace.
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
        "naive brace-counter doesn't handle a brace inside a string/regex literal; if " +
        functionName + " grew one, this needs a smarter extractor, not a silenced test."
    );
  }
  return source.slice(start, i - 1);
}

test("extractor sanity: init() and refreshBoardSilently() are both found in board.js", () => {
  const source = fs.readFileSync(BOARD_JS_PATH, "utf8");
  const initBody = extractFunctionBody(source, "init");
  const refreshBody = extractFunctionBody(source, "refreshBoardSilently");
  assert.ok(initBody.length > 0);
  assert.ok(refreshBody.length > 0);
});

test("extractor negative control: a missing function raises loudly, not silently", () => {
  assert.throws(
    () => extractFunctionBody("function noop() {}", "doesNotExist"),
    ExtractionError
  );
});

test("extractor negative control: unbalanced braces raise loudly", () => {
  assert.throws(
    () => extractFunctionBody("function broken() { if (x) {", "broken"),
    ExtractionError
  );
});

test("PT-38 §6: init()'s apiGetBoard callback sets swimlanesOn from the payload", () => {
  const source = fs.readFileSync(BOARD_JS_PATH, "utf8");
  const initBody = extractFunctionBody(source, "init");
  assert.match(
    initBody,
    /state\.swimlanesOn\s*=\s*data\.swimlane\s*!==\s*"none"/,
    "expected init()'s apiGetBoard().then callback to set " +
      'state.swimlanesOn = data.swimlane !== "none"'
  );
});

test("PT-38 §6: refreshBoardSilently() does NOT re-derive swimlanesOn from the payload", () => {
  const source = fs.readFileSync(BOARD_JS_PATH, "utf8");
  const refreshBody = extractFunctionBody(source, "refreshBoardSilently");
  assert.doesNotMatch(
    refreshBody,
    /swimlanesOn/,
    "refreshBoardSilently must never touch state.swimlanesOn -- re-deriving it on every " +
      "poll/SSE refresh would silently overwrite a user's manual Swimlanes-checkbox toggle " +
      "the next time the board refreshes in the background (the ruling's own reasoning)"
  );
});
