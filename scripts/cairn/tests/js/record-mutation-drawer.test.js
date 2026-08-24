"use strict";

// PT-51 §5/§7(JS): lifts the 0.7.0 read-only ruling on milestone/major
// cards. renderRecordDrawer must (a) compute readOnly = record.archived
// || foreign-root, (b) render field editors (inlineField/inlineSelect)
// for a live record and suppress them for an archived one, (c) reuse the
// shared commentSectionEl posting through apiMutateRecord (POST
// /api/record/<id>, never /api/issue/<id>), and (d) re-scope the
// read-only note so a live primary-root record gets none at all.
//
// board.js is DOM/render-flow code with no jsdom harness in this suite --
// every test below is a source-text guard, same brace-matching-extractor
// technique as archived-badge-surfaces.test.js/record-drawer-client.test.js.
//
// Nothing under test exists yet at the START of PT-51: renderRecordDrawer
// renders no editors at all, apiMutateRecord doesn't exist, and the
// readonly note is unconditional. Every test below is expected to fail
// against a pre-PT-51 board.js.

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

// ================= apiMutateRecord =================

test("PT-51: apiMutateRecord exists and posts to /api/record/<id>, never /api/issue/", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "apiMutateRecord");
  assert.match(body, /"\/api\/record\/"/, "expected apiMutateRecord to fetch \"/api/record/\" + id");
  assert.doesNotMatch(body, /\/api\/issue\//, "apiMutateRecord must never post to /api/issue/");
});

// ================= readOnly computation (§5) =================

test("PT-51: renderRecordDrawer computes readOnly from record.archived OR a foreign root", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /record\.archived/, "expected renderRecordDrawer to read record.archived");
  assert.match(body, /primaryRootId\(/, "expected renderRecordDrawer to compare against primaryRootId");
  assert.match(body, /record\.repo/, "expected renderRecordDrawer to compare record.repo against the primary root");
});

// ================= Field editors (§3, §5) =================

test("PT-51: renderRecordDrawer renders milestone editors (name/status/major/target_tag/ga)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /inlineField\(\s*"name"/, "expected an inlineField(\"name\", ...) call");
  assert.match(body, /inlineSelect\(\s*\n?\s*"status"/, "expected an inlineSelect(\"status\", ...) call");
  assert.match(body, /inlineSelect\(\s*\n?\s*"major"/, "expected an inlineSelect(\"major\", ...) call");
  assert.match(body, /inlineField\(\s*"target_tag"/, "expected an inlineField(\"target_tag\", ...) call");
  assert.match(body, /inlineSelect\(\s*\n?\s*"ga"/, "expected an inlineSelect(\"ga\", ...) call");
});

test("PT-51: renderRecordDrawer renders major editors (status/health/owner/target_ship)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /inlineSelect\(\s*\n?\s*"health"/, "expected an inlineSelect(\"health\", ...) call");
  assert.match(body, /inlineField\(\s*"owner"/, "expected an inlineField(\"owner\", ...) call");
  assert.match(body, /inlineField\(\s*"target_ship"/, "expected an inlineField(\"target_ship\", ...) call");
});

test("PT-51: renderRecordDrawer never renders an editor for id or kind (CLI-only, §3)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.doesNotMatch(body, /inlineField\(\s*"id"/, "id must never get a board editor");
  assert.doesNotMatch(body, /inlineSelect\(\s*"id"/, "id must never get a board editor");
  assert.doesNotMatch(body, /inline(Field|Select)\(\s*"kind"/, "milestone kind must never get a board editor");
});

test("PT-51: field editors are wired with the readOnly variable, not hardcoded (a live record must be editable)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  // Every inlineField/inlineSelect call in this function must pass the
  // computed `readOnly` variable as its 6th argument -- a literal `true`
  // anywhere here would mean records are STILL always read-only, the
  // exact bug this feature exists to fix.
  const calls = body.match(/inline(?:Field|Select)\([^;]*?\)/gs) || [];
  assert.ok(calls.length >= 5, `expected at least 5 inlineField/inlineSelect calls, found ${calls.length}`);
  calls.forEach((call) => {
    assert.doesNotMatch(call, /,\s*true\s*,\s*recordOpts\s*\)/, `an editor call is hardcoded read-only: ${call}`);
  });
});

// ================= Comments (§4) =================

test("PT-51: renderRecordDrawer's comment section is wired to apiMutateRecord, not apiMutateIssue", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /commentSectionEl\(/, "expected renderRecordDrawer to call commentSectionEl");
  assert.match(body, /apiMutateRecord/, "expected renderRecordDrawer to reference apiMutateRecord somewhere (recordOpts.mutate)");
});

test("PT-51: commentSectionEl exists and defaults to apiMutateIssue (the issue drawer's pre-existing behavior)", () => {
  const source = readSource();
  const match = source.match(/function\s+commentSectionEl\s*\(\s*record\s*,\s*opts\s*\)/);
  assert.ok(match, "expected `function commentSectionEl(record, opts)` in board.js");
  const body = extractFunctionBody(source, "commentSectionEl");
  assert.match(body, /opts\.mutate\s*\|\|\s*apiMutateIssue/, "expected the default mutate callback to be apiMutateIssue");
});

// ================= Read-only note re-scoping (§5) =================

test("PT-51: the readonly note is conditional on record.archived (archived wording)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /if\s*\(\s*record\.archived\s*\)/, "expected an `if (record.archived)` branch");
  assert.match(body, /Archived/, "expected the archived note to say \"Archived\"");
});

test("PT-51: the readonly note has a SEPARATE branch for a foreign (non-archived) root", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /else if\s*\(\s*readOnly\s*\)/, "expected an `else if (readOnly)` branch for the foreign-root case");
});
