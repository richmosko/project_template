"use strict";

// PT-55 (architect's embed-strategy ruling, 2026-08-27): `isEmbedMode(search)`
// is a pure function on CairnLogic reading the `?embed=1` query string --
// same "only the exact spelling counts" posture as PT-42's `archived=1`
// (absent, empty, `embed=0`, and any other garbage value are all OFF, so a
// typo'd/garbage query param can never accidentally trigger embed mode).
// `board.js` calls it once in `init` and toggles a `body.embed` class; that
// DOM-level effect is NOT tested here (see the escalation to architect on
// PT-55 for why) -- this file pins the pure predicate only.
//
// Written against implementation-lead's in-flight (uncommitted at write time)
// isEmbedMode, which already exists in board-logic.js as `new
// URLSearchParams(search || "")`. Every test below currently fails, but NOT
// with "not a function" -- with `ReferenceError: URLSearchParams is not
// defined`. That's a real environment gap, not a missing implementation:
// URLSearchParams is a genuine global in both real browsers and Node's own
// top-level scope, but `vm.runInNewContext`'s fresh sandbox (helpers.js's
// loadCairnLogic) does NOT inherit it -- confirmed directly (`node -e
// "vm.runInNewContext('typeof URLSearchParams', {})"` -> "undefined"). Every
// other board-logic.js function is plain ECMAScript with no Web/Node-API
// dependency, so this is the first time that gap has mattered. Escalated to
// architect/implementation-lead rather than silently patched -- either
// helpers.js's sandbox should be handed a `URLSearchParams` global (narrow,
// faithful to the real browser), or isEmbedMode should do its own string
// parsing to keep the file's zero-Web-API-footprint convention; not my call
// to make unilaterally since helpers.js is shared infrastructure every test
// file in this directory depends on.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("embed=1 (exact spelling) turns embed mode on", () => {
  assert.equal(CairnLogic.isEmbedMode("?embed=1"), true);
});

test("no query string at all is off", () => {
  assert.equal(CairnLogic.isEmbedMode(""), false);
});

test("empty query string ('?') is off", () => {
  assert.equal(CairnLogic.isEmbedMode("?"), false);
});

test("embed=0 is explicitly off, not just 'not on'", () => {
  assert.equal(CairnLogic.isEmbedMode("?embed=0"), false);
});

test("garbage values are off -- 'true', 'yes', empty value, case variants", () => {
  assert.equal(CairnLogic.isEmbedMode("?embed=true"), false);
  assert.equal(CairnLogic.isEmbedMode("?embed=yes"), false);
  assert.equal(CairnLogic.isEmbedMode("?embed="), false);
  assert.equal(CairnLogic.isEmbedMode("?embed=Embed=1"), false);
  assert.equal(CairnLogic.isEmbedMode("?EMBED=1"), false);
});

test("embed=1 still fires alongside other query params, in either order", () => {
  assert.equal(CairnLogic.isEmbedMode("?foo=bar&embed=1"), true);
  assert.equal(CairnLogic.isEmbedMode("?embed=1&foo=bar"), true);
});

test("a repeated embed param uses the first value, same as URLSearchParams.get", () => {
  // Not pinning a specific "right" answer for the ambiguous case beyond
  // matching the standard URLSearchParams#get semantics implementation is
  // expected to build on -- this documents the behavior rather than
  // demanding a bespoke one.
  assert.equal(CairnLogic.isEmbedMode("?embed=1&embed=0"), true);
  assert.equal(CairnLogic.isEmbedMode("?embed=0&embed=1"), false);
});

test("does not raise on malformed input", () => {
  assert.doesNotThrow(() => CairnLogic.isEmbedMode(null));
  assert.doesNotThrow(() => CairnLogic.isEmbedMode(undefined));
  assert.equal(CairnLogic.isEmbedMode(null), false);
  assert.equal(CairnLogic.isEmbedMode(undefined), false);
});
