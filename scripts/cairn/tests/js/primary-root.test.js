"use strict";

// PT-22: primaryRootId(board) -- the root of every other null-guard in
// this pass. Every function that takes a `primaryId` parameter treats
// this function's `null` return as "no repo dimension is known at all",
// distinct from "a real primaryId that just doesn't match" -- pin that
// distinction here so a future change to this function can't silently
// break every downstream null-guard at once.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("returns the id of the root marked primary", () => {
  var board = {
    roots: [
      { id: "SB", primary: false },
      { id: "PT", primary: true },
    ],
  };
  assert.equal(CairnLogic.primaryRootId(board), "PT");
});

test("returns null when board is falsy", () => {
  assert.equal(CairnLogic.primaryRootId(null), null);
  assert.equal(CairnLogic.primaryRootId(undefined), null);
});

test("returns null when board.roots is absent (the roots-less payload case)", () => {
  assert.equal(CairnLogic.primaryRootId({}), null);
});

test("returns null when board.roots is empty", () => {
  assert.equal(CairnLogic.primaryRootId({ roots: [] }), null);
});

test("returns null when no root is marked primary", () => {
  var board = { roots: [{ id: "PT", primary: false }] };
  assert.equal(CairnLogic.primaryRootId(board), null);
});

test("single-root board (the overwhelming majority case) resolves correctly", () => {
  var board = { roots: [{ id: "PT", primary: true }] };
  assert.equal(CairnLogic.primaryRootId(board), "PT");
});
