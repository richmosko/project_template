"use strict";

// PT-55 (architect's second ruling, 2026-08-27, "DOM-level assertions"):
// the automated leg of the DOM-visibility check, converted from "assert
// computed visibility" (impossible -- no jsdom, no document, confirmed
// against 8 existing test files that already document the same limit) to
// a source-text guard that asserts AGREEMENT, not existence:
//
//   1. The class token board.js's init() adds to document.body, and the
//      token board.css hides selectors under, are extracted INDEPENDENTLY
//      and asserted to be the SAME STRING -- a rename in either file must
//      fail this, not just silently stop matching.
//   2. The set of selectors board.css hides under that class is EXACTLY
//      {".app-title", "#tab-dashboard"} -- not a superset (a later broad
//      `body.embed .app-header { display: none }` must fail this).
//   3. #tab-kanban, #tab-list, #filter-text, #majors-tabs, #new-issue-btn
//      are explicitly NOT among the hidden selectors -- AC2 (Kanban<->List
//      + lane collapse "come free") depends on the view tabs surviving.
//
// This proves "the two files agree and the ruling's scope is pinned," per
// the ruling's own words -- not "the browser actually renders it hidden,"
// which is the manual Validate-phase leg (team-lead, claude-in-chrome,
// elementFromPoint/screenshot, posted as a PT-55 comment -- PT-32's scar:
// property/class reads are not visibility).
//
// board.js/board.css are DOM/render-flow code with no jsdom harness in
// this suite -- same brace-matching/regex-extraction technique as
// archived-badge-surfaces.test.js / record-drawer-client.test.js.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_JS_PATH = path.join(__dirname, "..", "..", "board", "board.js");
const BOARD_CSS_PATH = path.join(__dirname, "..", "..", "board", "board.css");

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
    throw new ExtractionError(
      "unbalanced braces while extracting `" + functionName + "`'s body -- this guard's " +
        "naive brace-counter doesn't handle a brace inside a string/regex literal."
    );
  }
  return source.slice(start, i - 1);
}

// The literal string board.js's init() passes to
// `document.body.classList.add("...")` -- independent of the CSS-side
// extraction below, on purpose (§1 of the ruling: two separately-derived
// literals asserted equal, not one computation reused for both).
function extractEmbedClassTokenFromJs(source) {
  var initBody = extractFunctionBody(source, "init");
  var match = initBody.match(/document\.body\.classList\.add\(\s*"([\w-]+)"\s*\)/);
  if (!match) {
    throw new ExtractionError(
      "could not find `document.body.classList.add(\"...\")` inside init() in board.js -- " +
        "if the embed-mode toggle was renamed or moved, this guard needs to be updated, not silenced."
    );
  }
  return match[1];
}

// Every `.selector`/`#selector` immediately following `body.<token>` in
// ANY rule whose declaration block contains `display: none` -- handles
// both a single combined selector list (today's shape: `body.embed
// .app-title, body.embed #tab-dashboard { display: none; }`) and multiple
// separate rule blocks, without assuming which.
//
// Architect's PT-55 diff-review catch (2026-08-27): CSS comments are
// stripped FIRST, before rule-matching -- this file's own prose-heavy
// comments (e.g. the one right above the real rule, which contains the
// literal words "filters, majors tabs, expand/collapse, + New") sit in
// the text between one rule's `}` and the next rule's `{`, which the
// naive rule-boundary regex below would otherwise fold into that NEXT
// rule's "selector list" capture -- a comment that happened to mention
// `body.embed #something` in prose would then read as a real hidden
// selector. Generalizes the same principle the sandbox-attribute fix
// applies on the Python side: target extracted code, never file text
// that includes comments/prose.
function stripCssComments(cssSource) {
  return cssSource.replace(/\/\*[\s\S]*?\*\//g, "");
}

function extractEmbedHiddenSelectors(cssSource, token) {
  var hidden = new Set();
  var ruleRe = /([^{}]+)\{([^{}]*)\}/g;
  var ruleMatch;
  var selectorRe = new RegExp("body\\." + token + "\\s+([.#][\\w-]+)", "g");
  var source = stripCssComments(cssSource);
  while ((ruleMatch = ruleRe.exec(source))) {
    var selectorList = ruleMatch[1];
    var declarations = ruleMatch[2];
    if (!/display\s*:\s*none/.test(declarations)) continue;
    var selMatch;
    selectorRe.lastIndex = 0;
    while ((selMatch = selectorRe.exec(selectorList))) {
      hidden.add(selMatch[1]);
    }
  }
  return hidden;
}

function readBoardSource() {
  return fs.readFileSync(BOARD_JS_PATH, "utf8");
}

function readBoardCss() {
  return fs.readFileSync(BOARD_CSS_PATH, "utf8");
}

test("PT-55: the class token board.js toggles and the token board.css hides under are the same string", () => {
  var jsSource = readBoardSource();
  var cssSource = readBoardCss();
  var jsToken = extractEmbedClassTokenFromJs(jsSource);
  // Independent extraction on the CSS side: the first `body.<word>` token
  // found anywhere in the file, not parametrized by jsToken -- if this
  // finds nothing at all, that's a real ExtractionError below, not a
  // silent pass.
  var cssTokenMatch = cssSource.match(/body\.([\w-]+)\s/);
  if (!cssTokenMatch) {
    throw new ExtractionError(
      "could not find any `body.<token> ` selector in board.css -- if the embed CSS scope " +
        "was renamed or removed, this guard needs to be updated, not silenced."
    );
  }
  var cssToken = cssTokenMatch[1];
  assert.equal(
    jsToken, cssToken,
    "board.js's classList.add(\"" + jsToken + "\") and board.css's body." + cssToken +
      " selector must be the SAME class name -- a rename in either file breaks the embed hiding"
  );
});

test("PT-55: the hidden-selector set under body.embed is EXACTLY the wordmark + Dashboard tab", () => {
  var jsSource = readBoardSource();
  var cssSource = readBoardCss();
  var token = extractEmbedClassTokenFromJs(jsSource);
  var hidden = extractEmbedHiddenSelectors(cssSource, token);
  assert.deepEqual(
    Array.from(hidden).sort(),
    ["#tab-dashboard", ".app-title"],
    "expected exactly the wordmark (.app-title) and the Dashboard tab (#tab-dashboard) to be " +
      "hidden under body." + token + " -- got " + JSON.stringify(Array.from(hidden).sort()) +
      ". A broader selector here would hide board function the dashboard has no replacement for."
  );
});

test("PT-55: filters, majors tabs, +New, and the Kanban/List tabs are NOT hidden under body.embed", () => {
  var jsSource = readBoardSource();
  var cssSource = readBoardCss();
  var token = extractEmbedClassTokenFromJs(jsSource);
  var hidden = extractEmbedHiddenSelectors(cssSource, token);
  var mustStayVisible = ["#tab-kanban", "#tab-list", "#filter-text", "#majors-tabs", "#new-issue-btn"];
  for (var i = 0; i < mustStayVisible.length; i++) {
    assert.ok(
      !hidden.has(mustStayVisible[i]),
      mustStayVisible[i] + " must NOT be hidden under body." + token + " -- AC2 (Kanban<->List " +
        "+ lane collapse \"come free\") depends on the view tabs surviving, and the dashboard has " +
        "no replacement for filters/majors-tabs/+New"
    );
  }
});

test("negative control: extractor correctly reports a hidden selector that IS present (sanity)", () => {
  var fakeCss = "body.embed .app-title, body.embed #tab-dashboard { display: none; }";
  var hidden = extractEmbedHiddenSelectors(fakeCss, "embed");
  assert.deepEqual(Array.from(hidden).sort(), ["#tab-dashboard", ".app-title"]);
});

test("negative control: a rule without display:none is not counted as hidden", () => {
  var fakeCss = "body.embed .app-title { color: red; }";
  var hidden = extractEmbedHiddenSelectors(fakeCss, "embed");
  assert.deepEqual(Array.from(hidden), []);
});

test("negative control: a token mismatch between JS and CSS is caught, not silently ignored", () => {
  var fakeJsInit = 'function init() {\n  if (isEmbedMode) document.body.classList.add("embed");\n}\n';
  var fakeCssWrongToken = "body.embedded .app-title { display: none; }";
  var jsToken = extractEmbedClassTokenFromJs(fakeJsInit);
  var cssTokenMatch = fakeCssWrongToken.match(/body\.([\w-]+)\s/);
  assert.notEqual(jsToken, cssTokenMatch[1], "sanity: this fixture is deliberately mismatched");
});

test("negative control: missing classList.add in init() raises loudly, not silently", () => {
  var fakeJsInit = "function init() {\n  wireFilters();\n}\n";
  assert.throws(() => extractEmbedClassTokenFromJs(fakeJsInit), ExtractionError);
});

test("regression guard: a comment mentioning 'body.embed #foo' in prose must NOT be read as a hidden selector", () => {
  // Architect's PT-55 diff-review catch, generalized to this file: a
  // comment sitting between two real rules used to fold into the
  // NEXT rule's captured "selector list" (the naive rule-boundary regex
  // has no comment awareness on its own) -- if that comment's prose
  // happened to mention a body.<token> selector, it would silently read
  // as real. stripCssComments() is what closes this; this test proves it
  // actually does, not just that it exists.
  var fakeCss =
    "/* unrelated note: body.embed #tab-kanban should never be hidden, obviously */\n" +
    "body.embed .app-title { display: none; }\n";
  var hidden = extractEmbedHiddenSelectors(fakeCss, "embed");
  assert.deepEqual(Array.from(hidden), [".app-title"], "the comment's prose must not contribute a phantom hidden selector");
});
