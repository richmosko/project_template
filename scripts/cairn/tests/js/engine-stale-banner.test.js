"use strict";

// PT-49 §6/§9(e): "A persistent banner, not a toast: the condition does
// not self-resolve and toasts auto-dismiss in 3.5s. Render at the top of
// the board shell when board.engine.stale, remove it when a later payload
// reports false. Text names the fix... Do not disable interaction."
//
// board.js is DOM/render-flow code with no jsdom harness in this suite --
// every test below is a source-text guard, same brace-matching-extractor
// technique as record-drawer-client.test.js/archived-badge-surfaces.test.js.
//
// Nothing under test exists yet: no #engine-stale-banner element in
// board.html, no renderEngineBanner in board.js. Every red test below is
// expected to fail until implementation-lead's PT-49 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_JS_PATH = path.join(__dirname, "..", "..", "board", "board.js");
const BOARD_HTML_PATH = path.join(__dirname, "..", "..", "board", "board.html");

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

function readBoardSource() {
  return fs.readFileSync(BOARD_JS_PATH, "utf8");
}

function readBoardHtml() {
  return fs.readFileSync(BOARD_HTML_PATH, "utf8");
}

test("PT-49: board.html declares the #engine-stale-banner element, hidden by default", () => {
  const html = readBoardHtml();
  const match = html.match(/<div[^>]*id="engine-stale-banner"[^>]*>/);
  assert.ok(match, "expected a <div id=\"engine-stale-banner\"> in board.html");
  assert.match(match[0], /hidden/, "the banner must start hidden -- shown only when engine.stale is true");
});

test("PT-49: renderEngineBanner exists and reads state.board.engine.stale", () => {
  const source = readBoardSource();
  const body = extractFunctionBody(source, "renderEngineBanner");
  assert.match(body, /state\.board\.engine/, "expected renderEngineBanner to read state.board.engine");
  assert.match(body, /\.stale/, "expected renderEngineBanner to read the stale flag specifically");
});

test("PT-49: renderEngineBanner sets hidden = false when stale, true otherwise (not a class toggle)", () => {
  const source = readBoardSource();
  const body = extractFunctionBody(source, "renderEngineBanner");
  assert.match(body, /\.hidden\s*=\s*false/, "expected the banner element's hidden attribute cleared when stale");
  assert.match(body, /\.hidden\s*=\s*true/, "expected the banner element's hidden attribute set when not stale");
});

test("PT-49: renderEngineBanner's text names the fix (the exact restart instructions)", () => {
  const source = readBoardSource();
  const body = extractFunctionBody(source, "renderEngineBanner");
  assert.match(body, /running older code/i, "expected wording naming the actual condition");
  assert.match(body, /\/cairn stop/, "expected the restart instruction to name /cairn stop");
});

test("PT-49: render() calls renderEngineBanner on every pass (banner clears itself, no leftover stale state)", () => {
  const source = readBoardSource();
  const body = extractFunctionBody(source, "render");
  assert.match(body, /renderEngineBanner\(\)/, "expected render() to call renderEngineBanner()");
});

test("PT-49: renderEngineBanner never touches #main or disables interaction (a stale server still serves true data)", () => {
  const source = readBoardSource();
  const body = extractFunctionBody(source, "renderEngineBanner");
  assert.doesNotMatch(body, /disabled\s*=\s*true/, "the banner must not disable any control");
  assert.doesNotMatch(body, /getElementById\(\s*"main"\s*\)/, "the banner must not touch #main");
});
