"use strict";

// PT-25 named drift pair: idSortKey mirrors cairn.py's _id_sort_key
// (PT-2/PT-21, tests/test_id_sort.py) -- there is no shared-code seam
// across Python and JS in this stack, so the numeric-aware id sort exists
// twice, in two languages, by design (architect's ruling). Both sides are
// tested against the SAME case list (PT-2 < PT-9 < PT-10) so they cannot
// silently diverge from each other.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function byIdSortKey(a, b) {
  var ka = CairnLogic.idSortKey(a);
  var kb = CairnLogic.idSortKey(b);
  if (ka[0] !== kb[0]) return ka[0] < kb[0] ? -1 : 1;
  if (ka[1] !== kb[1]) return ka[1] - kb[1];
  return ka[2] < kb[2] ? -1 : ka[2] > kb[2] ? 1 : 0;
}

test("PT-2 sorts before PT-9 sorts before PT-10 (numeric, not lexicographic)", () => {
  var ids = ["PT-10", "PT-2", "PT-9"];
  assert.deepEqual(ids.slice().sort(byIdSortKey), ["PT-2", "PT-9", "PT-10"]);
});

test("a plain lexicographic sort gets this wrong -- regression guard for the bug idSortKey fixes", () => {
  var ids = ["PT-10", "PT-2", "PT-9"];
  assert.deepEqual(ids.slice().sort(), ["PT-10", "PT-2", "PT-9"]);
});

test("malformed ids fall back to a string key instead of throwing", () => {
  assert.deepEqual(CairnLogic.idSortKey("mvp"), ["mvp", -1, "mvp"]);
  assert.deepEqual(CairnLogic.idSortKey(null), ["", -1, ""]);
  assert.deepEqual(CairnLogic.idSortKey(undefined), ["", -1, ""]);
});

test("distinct prefixes sort by prefix first, then number", () => {
  var ids = ["SB-2", "PT-10", "SB-1", "PT-2"];
  assert.deepEqual(ids.slice().sort(byIdSortKey), ["PT-2", "PT-10", "SB-1", "SB-2"]);
});
