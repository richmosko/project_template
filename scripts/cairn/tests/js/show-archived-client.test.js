"use strict";

// PT-42 (architect's ruling, temp/arch-ruling-pt42-show-archived.md §2/§3)
// client-side surface: `state.showArchived` (default false, in-memory
// only -- matches showCancelled's convention exactly), a `#filter-archived`
// checkbox wired the same way as `#filter-cancelled`, `apiGetBoard()`
// appending `?archived=1` when the toggle is on, clearing `state.etag`
// before that fetch (an etag minted for one payload shape must never be
// sent as If-None-Match for the other -- the ruling's own wording), and
// `cardEl` rendering a `.card.is-archived` treatment + an "archived" chip.
//
// board.js is DOM/render-flow code with no jsdom harness in this suite
// (see status-label.test.js / swimlane-init.test.js's own header comments,
// same recurring class of problem) -- every test below is a source-text
// guard: read board.js as text, extract the specific function body via
// brace-matching (regex alone can't handle nested braces reliably, same
// technique swimlane-init.test.js already established), and assert
// on presence/absence WITHIN the right function, not just "does this
// substring appear anywhere in the file".
//
// Nothing under test exists yet -- `showArchived` is not a state key,
// there is no `#filter-archived` element or listener, `apiGetBoard`
// never varies its request URL, and `cardEl` never reads `issue.archived`.
// Every test below is expected to fail until implementation-lead's PT-42
// client slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_JS_PATH = path.join(__dirname, "..", "..", "board", "board.js");

class ExtractionError extends Error {}

// Same brace-matching extractor as swimlane-init.test.js (duplicated, not
// imported -- both files are small and self-contained, matching this
// suite's existing convention of not sharing test-only helpers across
// files unless they're already factored into helpers.js).
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

function readSource() {
  return fs.readFileSync(BOARD_JS_PATH, "utf8");
}

// ================= state.showArchived =================

test("PT-42: state literal declares showArchived: false", () => {
  const source = readSource();
  assert.match(
    source,
    /showArchived\s*:\s*false/,
    'expected `showArchived: false` in the state object literal (matches showCancelled\'s default-off convention)'
  );
});

// ================= #filter-archived checkbox wiring =================

test("PT-42: a #filter-archived checkbox listener exists and sets state.showArchived", () => {
  const source = readSource();
  assert.match(
    source,
    /getElementById\(\s*"filter-archived"\s*\)/,
    'expected a `document.getElementById("filter-archived")` wiring site, matching `#filter-cancelled`\'s pattern'
  );
});

test("PT-42: toggling showArchived clears state.etag before the next fetch", () => {
  // Anchored loosely (not brace-matched to one function, since the
  // ruling's own wording applies this rule at the point of TOGGLING the
  // parameter, which could reasonably live in the checkbox listener OR
  // inside apiGetBoard itself keyed off a "did this change" check) --
  // what's pinned is that SOMEWHERE in the file, an etag-clear is
  // associated with the showArchived assignment, not that showArchived
  // is merely set. A bare `state.showArchived = e.target.checked;` with
  // no etag-clear anywhere nearby would defeat the ruling's requirement
  // silently (a stale etag would 304 the OTHER shape's fetch).
  const source = readSource();
  const listenerMatch = source.match(
    /getElementById\(\s*"filter-archived"\s*\)\.addEventListener\(\s*"change"\s*,\s*function[\s\S]*?\{([\s\S]*?)\}\s*\)\s*;/
  );
  assert.ok(listenerMatch, "expected the #filter-archived change-listener callback to be extractable");
  assert.match(
    listenerMatch[1],
    /state\.showArchived\s*=/,
    "the listener must assign state.showArchived"
  );
  assert.match(
    listenerMatch[1],
    /state\.etag\s*=\s*null/,
    "the listener must clear state.etag -- an etag minted for one payload shape " +
      "(archived on/off) must never be sent as If-None-Match for the other"
  );
});

// ================= apiGetBoard: ?archived=1 =================

test("PT-42: apiGetBoard's request URL includes archived=1 when state.showArchived is true", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "apiGetBoard");
  assert.match(
    body,
    /state\.showArchived/,
    "apiGetBoard must read state.showArchived somewhere in its request-building logic"
  );
  assert.match(
    body,
    /archived=1/,
    'apiGetBoard must include the literal query string `archived=1` when showArchived is true'
  );
});

// ================= cardEl: is-archived class + chip =================

test("PT-42: cardEl adds the is-archived class when issue.archived is true", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "cardEl");
  assert.match(
    body,
    /issue\.archived/,
    "cardEl must branch on issue.archived somewhere in its body"
  );
  assert.match(
    body,
    /is-archived/,
    'cardEl must apply an "is-archived" class/treatment for an archived card'
  );
});

test("PT-42: cardEl renders an archived chip via the existing chip() helper, not a bespoke element", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "cardEl");
  // Anchored on the SAME chip(...) call shape every other card badge uses
  // (chip("repo", ...), chip("assignee", ...), etc.) -- a bespoke
  // `document.createElement("span")` for just this one badge would be the
  // exact "two independently-duplicated expressions" drift class this
  // codebase keeps guarding against elsewhere (isDraggable's own PT-22
  // history is the canonical example).
  assert.match(
    body,
    /chip\(\s*"archived"/,
    'expected an `chip("archived", ...)` call inside cardEl, reusing the existing chip() helper'
  );
});
