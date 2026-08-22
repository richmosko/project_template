"use strict";

// PT-29 (architect's ruling, section 3): the disclosure glyph regresses from
// "reads as a triangle" to "reads as a dot" if it silently drifts from the
// FILLED codepoints (U+25BC / U+25B6) back to the thin ▾/▸ pair PT-16
// originally shipped -- CSS sizing alone can't fix a wrong glyph. Pinning
// the exact codepoints, not just string equality against a literal that
// could itself be the thin variant by a copy-paste slip, is the point of
// this test.
//
// disclosureToken is missing from board-logic.js as of this commit --
// expected to fail with "CairnLogic.disclosureToken is not a function"
// until implementation-lead's slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

// The exact codepoints named in the ruling -- FILLED triangles, not the thin
// ▾ (U+25BE) / ▸ (U+25B8) glyphs PT-16 shipped.
const FILLED_DOWN_TRIANGLE = "▼"; // ▼
const FILLED_RIGHT_TRIANGLE = "▶"; // ▶

test("disclosureToken(true) returns the filled down triangle (expanded)", () => {
  assert.equal(CairnLogic.disclosureToken(true), FILLED_DOWN_TRIANGLE);
  assert.equal(CairnLogic.disclosureToken(true).codePointAt(0), 0x25bc);
});

test("disclosureToken(false) returns the filled right triangle (collapsed)", () => {
  assert.equal(CairnLogic.disclosureToken(false), FILLED_RIGHT_TRIANGLE);
  assert.equal(CairnLogic.disclosureToken(false).codePointAt(0), 0x25b6);
});

test("disclosureToken never returns the thin ▾/▸ variants PT-16 shipped", () => {
  var THIN_DOWN = "▾"; // ▾
  var THIN_RIGHT = "▸"; // ▸
  assert.notEqual(CairnLogic.disclosureToken(true), THIN_DOWN);
  assert.notEqual(CairnLogic.disclosureToken(false), THIN_RIGHT);
});

test("disclosureToken returns a single-character string either way (fixed-box CSS assumption)", () => {
  assert.equal(CairnLogic.disclosureToken(true).length, 1);
  assert.equal(CairnLogic.disclosureToken(false).length, 1);
});
