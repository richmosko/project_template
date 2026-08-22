"use strict";

// PT-30 (architect's ruling, 2026-08-22): localStorage persistence for
// state.expandedLanes. Everything here is the PURE half of the feature --
// viewStateKey/serializeExpandedLanes/parseExpandedLanes/expandAllLanes plus
// the VIEW_STATE_VERSION/VIEW_STATE_MAX_LANES constants -- board.js's own
// readViewState/writeViewState/clearViewState wrap the actual `localStorage`
// global (guarded, inside `try`, per the ruling's precedent-copy from
// docs/_assets/toc.js) and are NOT testable here; that's the browser
// checklist's job.
//
// parseExpandedLanes is "the highest-value target in this feature" per the
// ruling -- it parses untrusted, persisted-across-versions input, and is the
// one function a hostile or merely stale blob reaches first. Its ONE
// contract, repeated in every malformed-input test below: NEVER THROW,
// ALWAYS return a usable (possibly empty) Object.create(null) map. A
// corrupt/foreign/future-versioned/oversized blob degrades to "nothing was
// ever expanded", never a crash.
//
// None of viewStateKey/serializeExpandedLanes/parseExpandedLanes/
// expandAllLanes/VIEW_STATE_VERSION/VIEW_STATE_MAX_LANES exist in
// board-logic.js as of this commit -- every test below is expected to fail
// with "not a function" / undefined-constant errors until implementation-
// lead's PT-30 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

// ---- constants ----

test("VIEW_STATE_VERSION is exported and equals 1 (the ruling's schema v1)", () => {
  assert.equal(CairnLogic.VIEW_STATE_VERSION, 1);
});

test("VIEW_STATE_MAX_LANES is exported and equals 500 (the ruling's cap)", () => {
  assert.equal(CairnLogic.VIEW_STATE_MAX_LANES, 500);
});

// ---- 10. viewStateKey ----

test("viewStateKey: differs across primary root ids", () => {
  assert.notEqual(CairnLogic.viewStateKey("PT"), CairnLogic.viewStateKey("SB"));
});

test("viewStateKey: stable for the same root id", () => {
  assert.equal(CairnLogic.viewStateKey("PT"), CairnLogic.viewStateKey("PT"));
});

test("viewStateKey: exact namespaced shape", () => {
  assert.equal(CairnLogic.viewStateKey("PT"), "cairn.board.expandedLanes.PT");
});

test("viewStateKey: does NOT guard a null primaryId -- matches laneStateKey's documented non-guarding convention", () => {
  // Explicit ruling (§5): "does not guard a null primaryId -- it yields
  // 'cairn.board.expandedLanes.null'". Pinned here so a future "helpful"
  // null-guard doesn't silently change every single-root-with-no-primary
  // user's storage key out from under their existing blob.
  assert.equal(CairnLogic.viewStateKey(null), "cairn.board.expandedLanes.null");
});

// ---- 2/3. serializeExpandedLanes ----

test("serializeExpandedLanes: exact literal shape for a single-key map", () => {
  assert.equal(CairnLogic.serializeExpandedLanes({ "PT::0.5": true }), '{"v":1,"lanes":["PT::0.5"]}');
});

test("serializeExpandedLanes: lanes are SORTED ascending regardless of insertion order -- byte-identical output", () => {
  var insertedAscending = {};
  insertedAscending["PT::0.4"] = true;
  insertedAscending["PT::0.5"] = true;
  insertedAscending["PT::1.0"] = true;

  var insertedDescending = {};
  insertedDescending["PT::1.0"] = true;
  insertedDescending["PT::0.5"] = true;
  insertedDescending["PT::0.4"] = true;

  var a = CairnLogic.serializeExpandedLanes(insertedAscending);
  var b = CairnLogic.serializeExpandedLanes(insertedDescending);
  assert.equal(a, b, "two maps with the same key SET must serialize identically regardless of insertion order");
  assert.equal(a, '{"v":1,"lanes":["PT::0.4","PT::0.5","PT::1.0"]}');
});

test("serializeExpandedLanes: a falsy-valued key is excluded -- never emits a stored false", () => {
  // PT-29's invariant is that a map holding `false` should never exist, but
  // serializeExpandedLanes must not trust that invariant blindly -- it is
  // the last line of defense against ever writing a second encoding of
  // "closed" to disk. Own+truthy keys only (ruling §5's exact phrase).
  var map = { "PT::0.5": true, "PT::0.4": false };
  assert.equal(CairnLogic.serializeExpandedLanes(map), '{"v":1,"lanes":["PT::0.5"]}');
});

test("serializeExpandedLanes: an inherited (non-own) property is excluded", () => {
  var proto = { "PT::inherited": true };
  var map = Object.assign(Object.create(proto), { "PT::0.5": true });
  var parsed = JSON.parse(CairnLogic.serializeExpandedLanes(map));
  assert.deepEqual(parsed.lanes, ["PT::0.5"]);
});

test("serializeExpandedLanes: empty map serializes to an empty lanes array", () => {
  assert.equal(CairnLogic.serializeExpandedLanes({}), '{"v":1,"lanes":[]}');
});

// ---- 1/4. parseExpandedLanes: round-trip ----

test("round-trip: serialize -> parse yields an equivalent map", () => {
  var original = Object.create(null);
  original["PT::0.4"] = true;
  original["PT::0.5"] = true;
  var restored = CairnLogic.parseExpandedLanes(CairnLogic.serializeExpandedLanes(original));
  assert.deepEqual(Object.keys(restored).sort(), ["PT::0.4", "PT::0.5"]);
  assert.equal(CairnLogic.laneExpanded(restored, "PT::0.4"), true);
  assert.equal(CairnLogic.laneExpanded(restored, "PT::0.5"), true);
});

test("round-trip: an empty map round-trips to an empty map", () => {
  var restored = CairnLogic.parseExpandedLanes(CairnLogic.serializeExpandedLanes({}));
  assert.deepEqual(Object.keys(restored), []);
});

// ---- 4. parseExpandedLanes never throws, always degrades to empty ----

const MALFORMED_INPUTS = [
  null,
  "",
  "not json",
  "[]",
  "{}",
  '{"v":1}',
  '{"v":1,"lanes":"x"}',
  '{"v":1,"lanes":[1,2]}',
  '{"v":9,"lanes":["a"]}', // unrecognized version -> ruling: return empty, let caller removeItem
];

MALFORMED_INPUTS.forEach((input) => {
  test(`parseExpandedLanes: does not throw and returns an empty map for ${JSON.stringify(input)}`, () => {
    var result;
    assert.doesNotThrow(() => { result = CairnLogic.parseExpandedLanes(input); });
    assert.deepEqual(Object.keys(result), []);
  });
});

test("parseExpandedLanes: an oversized lanes array (over VIEW_STATE_MAX_LANES) is treated as corrupt -- discarded, not truncated", () => {
  var tooMany = [];
  for (var i = 0; i <= CairnLogic.VIEW_STATE_MAX_LANES; i++) tooMany.push("PT::" + i); // MAX + 1
  var raw = JSON.stringify({ v: CairnLogic.VIEW_STATE_VERSION, lanes: tooMany });
  var result;
  assert.doesNotThrow(() => { result = CairnLogic.parseExpandedLanes(raw); });
  assert.deepEqual(Object.keys(result), [], "an over-cap blob must discard the WHOLE blob, not truncate to the cap");
});

test("parseExpandedLanes: exactly VIEW_STATE_MAX_LANES entries is still valid (boundary, not over the cap)", () => {
  var atCap = [];
  for (var i = 0; i < CairnLogic.VIEW_STATE_MAX_LANES; i++) atCap.push("PT::" + i);
  var raw = JSON.stringify({ v: CairnLogic.VIEW_STATE_VERSION, lanes: atCap });
  var result = CairnLogic.parseExpandedLanes(raw);
  assert.equal(Object.keys(result).length, CairnLogic.VIEW_STATE_MAX_LANES);
});

// ---- 5. parseExpandedLanes: Object.create(null), prototype-shaped entries land in prototype-collision.test.js ----

test("parseExpandedLanes: returns an Object.create(null) map (no inherited Object.prototype)", () => {
  var result = CairnLogic.parseExpandedLanes('{"v":1,"lanes":["PT::0.5"]}');
  assert.equal(Object.getPrototypeOf(result), null);
});

// ---- 6/7. laneExpanded agreement + stale-key survival ----

test("after restore, laneExpanded agrees for every stored key, and an absent key reads collapsed", () => {
  var raw = '{"v":1,"lanes":["PT::0.4","PT::0.5"]}';
  var restored = CairnLogic.parseExpandedLanes(raw);
  assert.equal(CairnLogic.laneExpanded(restored, "PT::0.4"), true);
  assert.equal(CairnLogic.laneExpanded(restored, "PT::0.5"), true);
  assert.equal(CairnLogic.laneExpanded(restored, "PT::0.9"), false, "a key never stored must read collapsed");
});

test("a stale key (no corresponding live lane) survives a round trip and changes no live lane's state", () => {
  // "PT::9.9" stands in for a milestone that has since been deleted --
  // parseExpandedLanes has no notion of "live" lanes at all (§2's
  // no-pruning ruling), so it must simply carry the key through.
  var original = Object.create(null);
  original["PT::9.9"] = true; // stale
  original["PT::0.5"] = true; // live
  var blob = CairnLogic.serializeExpandedLanes(original);
  var restored = CairnLogic.parseExpandedLanes(blob);

  assert.equal(CairnLogic.laneExpanded(restored, "PT::9.9"), true, "the stale key itself must still read expanded");
  assert.equal(CairnLogic.laneExpanded(restored, "PT::0.5"), true, "the live key must be unaffected by the stale one");
  assert.equal(CairnLogic.laneExpanded(restored, "PT::0.1"), false, "an unrelated live key must still read collapsed");

  // And the stale key must survive a SECOND round trip unchanged -- parsing
  // then re-serializing must not silently drop it (that would be pruning
  // under a different name).
  var reserialized = CairnLogic.serializeExpandedLanes(restored);
  assert.equal(JSON.parse(reserialized).lanes.indexOf("PT::9.9") !== -1, true);
});

// ---- 8. bare-id-across-roots guard on restore (mandatory) ----

test("two roots, same milestone id: only the stored root's lane restores expanded", () => {
  var ptKey = CairnLogic.laneStateKey("PT", "0.5");
  var sbKey = CairnLogic.laneStateKey("SB", "0.5");

  var stored = Object.create(null);
  stored[ptKey] = true; // only PT's 0.5 was ever expanded
  var restored = CairnLogic.parseExpandedLanes(CairnLogic.serializeExpandedLanes(stored));

  assert.equal(CairnLogic.laneExpanded(restored, ptKey), true, "PT::0.5 must restore expanded");
  assert.equal(CairnLogic.laneExpanded(restored, sbKey), false, "SB::0.5 must NOT restore expanded -- it was never stored");
});

// ---- 9. expandAllLanes ----

test("expandAllLanes: unions the given lane keys into the map, additive only", () => {
  var existing = Object.create(null);
  existing["PT::0.4"] = true; // already expanded, e.g. via a prior manual toggle
  var next = CairnLogic.expandAllLanes(existing, ["PT::0.5", "PT::0.6"]);
  assert.deepEqual(Object.keys(next).sort(), ["PT::0.4", "PT::0.5", "PT::0.6"]);
});

test("expandAllLanes: does not mutate its input map", () => {
  var existing = Object.create(null);
  CairnLogic.expandAllLanes(existing, ["PT::0.5"]);
  assert.deepEqual(Object.keys(existing), [], "input map must be untouched");
});

test("expandAllLanes: returns a DIFFERENT object identity than its input", () => {
  var existing = Object.create(null);
  var next = CairnLogic.expandAllLanes(existing, ["PT::0.5"]);
  assert.notEqual(next, existing);
});

test("expandAllLanes: a no-op (empty lane-key list) still returns an equivalent, non-mutated copy", () => {
  var existing = Object.create(null);
  existing["PT::0.4"] = true;
  var next = CairnLogic.expandAllLanes(existing, []);
  assert.deepEqual(Object.keys(next), ["PT::0.4"]);
});

test("expandAllLanes: never removes an already-expanded key that isn't in the given lane-key list", () => {
  // The union is additive-only -- expanding the currently-rendered lanes
  // must never collapse a lane that's expanded but hidden by a filter.
  var existing = Object.create(null);
  existing["PT::9.9"] = true; // expanded but, say, filtered out of view
  var next = CairnLogic.expandAllLanes(existing, ["PT::0.5"]);
  assert.equal(CairnLogic.laneExpanded(next, "PT::9.9"), true);
  assert.equal(CairnLogic.laneExpanded(next, "PT::0.5"), true);
});
