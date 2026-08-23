"use strict";

// PT-44 §4 (joint ruling, implementation-lead's Pass-1 message): a small,
// pure helper for the release chip's TEXT -- both the lane header and the
// card need the identical string, so it's a named function rather than
// two inlined ternaries that could drift.
//
//   releaseChipLabel(released, targetTag)
//     released == null (null OR undefined) -> null   (caller renders no chip)
//     released === false -> a string CONTAINING targetTag + "unreleased"
//     released === true  -> a string CONTAINING targetTag + "released"
//
// Architect's PT-44 review rejection (2026-08-23), two defects in the
// FIRST-draft shape this file originally pinned -- both fixed here before
// implementation-lead touches the implementation:
//
// F1: `released === null` (strict) was too narrow -- a MAJOR record has
// no `released` key AT ALL (majors have no target_tag, per the ruling's
// own §4 wording), so `record.released` reads `undefined`, not `null`,
// when a caller passes it straight through. An older server's payload
// (pre-PT-44) omits the key from EVERY record the same way. Both must
// render no chip, same as an explicit `null` -- `released == null` (loose
// equality, deliberately) covers both, `released === null` covered
// neither and rendered "undefined released" in production.
//
// F2: the chip text must carry `targetTag` in BOTH the false and true
// states, not just when released -- "unreleased" (bare, PT-44's original
// shape) lost the tag entirely for every not-yet-shipped milestone on the
// whole board, indistinguishable from each other. Pinned as SUBSTRING
// containment (targetTag present, AND the right qualifier word present),
// not an exact full-string match -- the separator ("v0.7.0 · unreleased"
// vs "v0.7.0 (unreleased)" etc.) is implementation-lead's call per the
// corrected ruling, not something this test should lock down.
//
// Neither exists in board-logic.js as of this commit -- every test below
// is expected to fail until implementation-lead's PT-44 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

// ================= released == null (both null and undefined) =================

test("releaseChipLabel(null, ...) returns null -- caller renders no chip", () => {
  assert.equal(CairnLogic.releaseChipLabel(null, "v1.0.0"), null);
});

test("releaseChipLabel(null, ...) returns null even when targetTag is also null (definition milestones)", () => {
  assert.equal(CairnLogic.releaseChipLabel(null, null), null);
});

test("F1: releaseChipLabel(undefined, ...) ALSO returns null -- a major record has no `released` key at all", () => {
  // The exact defect: a naive `released === null` check lets `undefined`
  // fall through to the false/true branches, rendering "undefined
  // released" for every major (and, pre-this-fix, every record on an
  // older server's payload that omitted the key entirely).
  assert.equal(CairnLogic.releaseChipLabel(undefined, "v1.0.0"), null);
});

test("F1: releaseChipLabel(undefined, undefined) returns null -- the fully-absent-key shape", () => {
  assert.equal(CairnLogic.releaseChipLabel(undefined, undefined), null);
});

// ================= released === false: unreleased, WITH the tag (F2) =================

test('F2: releaseChipLabel(false, targetTag) includes targetTag AND "unreleased" -- not a bare "unreleased"', () => {
  const label = CairnLogic.releaseChipLabel(false, "v1.1.0");
  assert.notEqual(label, null);
  assert.match(label, /v1\.1\.0/, "the chip must carry the target tag, not just say \"unreleased\" bare");
  assert.match(label, /unreleased/i);
});

test("F2: releaseChipLabel(false, targetTag) uses the ACTUAL targetTag value, distinguishing two not-yet-shipped milestones", () => {
  const a = CairnLogic.releaseChipLabel(false, "v1.1.0");
  const b = CairnLogic.releaseChipLabel(false, "v2.0.0");
  assert.notEqual(
    a, b,
    "two different not-yet-shipped milestones must render DIFFERENT chip text -- " +
      "a bare \"unreleased\" (PT-44's rejected first draft) made every one of them read identically"
  );
});

// ================= released === true: "<targetTag> released" =================

test('releaseChipLabel(true, targetTag) includes targetTag AND "released"', () => {
  const label = CairnLogic.releaseChipLabel(true, "v0.6.2");
  assert.match(label, /v0\.6\.2/);
  assert.match(label, /released/i);
});

test("releaseChipLabel(true, targetTag) uses the ACTUAL targetTag value, not a hardcoded example", () => {
  assert.notEqual(CairnLogic.releaseChipLabel(true, "v2.3.4"), CairnLogic.releaseChipLabel(true, "v0.6.2"));
});

// ================= true vs false must be visually/textually distinguishable =================

test("the true and false labels for the SAME targetTag are never equal (a released and an unreleased milestone must read differently)", () => {
  const unreleased = CairnLogic.releaseChipLabel(false, "v1.0.0");
  const released = CairnLogic.releaseChipLabel(true, "v1.0.0");
  assert.notEqual(unreleased, released);
});
