"use strict";

// PT-22: milestoneMajor(board, milestoneId, repoId) -- resolves a
// milestone's major, repo-scoped (the currentMajor filter's lookup).
// Extraction changes the signature from board.js's pre-PT-22 shape
// (which read state.board.milestones via closure) to taking `board`
// explicitly -- see INTERFACE.md's note on this being the "params over
// closure" fix.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function board() {
  return {
    milestones: [
      { id: "0.5", major: "V1", repo: "PT" },
      { id: "0.5", major: "V9", repo: "SB" },
    ],
  };
}

test("returns the repo-scoped milestone's major", () => {
  assert.equal(CairnLogic.milestoneMajor(board(), "0.5", "PT"), "V1");
});

test("PT-3 regression: a same-id milestone in another repo never leaks its major through", () => {
  assert.equal(CairnLogic.milestoneMajor(board(), "0.5", "SB"), "V9");
  assert.notEqual(CairnLogic.milestoneMajor(board(), "0.5", "SB"), "V1");
});

test("returns null for a dangling milestone reference", () => {
  assert.equal(CairnLogic.milestoneMajor(board(), "9.9", "PT"), null);
});

test("returns null for a repo that has no milestone with that id", () => {
  assert.equal(CairnLogic.milestoneMajor(board(), "0.5", "ZZ"), null);
});
