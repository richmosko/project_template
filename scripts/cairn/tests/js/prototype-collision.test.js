"use strict";

// PT-23: board.js (and, since PT-22, board-logic.js) uses bare `{}` as
// sets/maps in four spots -- an id/value shaped like an Object.prototype
// key name ("constructor", "toString", "hasOwnProperty", "valueOf",
// "__proto__") reads as ALREADY PRESENT the very first time it's looked
// up, before anything is ever inserted, and is silently dropped from the
// output. Verified the mechanism directly: `({})["constructor"]` is
// truthy (inherited from Object.prototype) even on a brand-new object;
// `Object.create(null)["constructor"]` is `undefined`.
//
// Architect's finding: unreachable in practice today (milestone/major
// ids are version strings, assignee/label values are free text that
// happens not to collide) -- hence P3, RECORD not a blocker. But it's a
// real, load-bearing correctness gap the moment any of those fields ever
// holds a value like "toString", and the fix (Object.create(null)
// instead of {}) costs nothing behaviorally for the normal case, which
// every other test file in this suite already covers.
//
// All four affected sites, and which test covers each:
//   1. dedupeMajorIds (already CairnLogic, PT-22)      -> below
//   2. uniqueMilestoneKeys (already CairnLogic, PT-22) -> below
//   3. uniqueSorted (board.js-only pre-PT-23)           -> below, new function
//   4. the byMilestone grouping (duplicated in TWO places in board.js
//      pre-PT-23: renderKanban's single-root branch AND repoSectionEl --
//      itself another instance of PT-3's "duplicated inline expression"
//      bug class) -> below, extracted as groupByMilestone
//
// PT-29 (architect's ruling, section 2/4, red-first case 7): laneExpanded /
// nextExpandedLanes' expandedLanes map must ALSO use Object.create(null)
// internally -- the architect names this "insurance only" (expandedLanes'
// real keys are always "<repo>::<milestone>" composites via laneStateKey,
// and no Object.prototype member contains "::", so an actual collision via
// the normal call path cannot fire) rather than a live defect the way
// collapsedRepos' bare root.id keys are. Tested anyway, directly against a
// bare prototype-shaped stateKey (bypassing laneStateKey's composite),
// because "insurance only" is a claim about board.js's call sites, not a
// property of laneExpanded/nextExpandedLanes' own implementation -- the
// functions themselves must not silently misbehave on such a key regardless
// of whether today's callers happen to never construct one.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

// A representative sample, not just "constructor" -- different bare-{}
// bugs are triggered by different inherited members (some tests use
// bracket-vs-dot access, truthy-vs-callable checks, etc.), so covering
// a few closes more of the actual risk surface than one alone would.
const PROTOTYPE_KEY_SHAPED_VALUES = ["constructor", "toString", "hasOwnProperty", "valueOf"];

test("dedupeMajorIds: a major id shaped like an Object.prototype key is not silently dropped", () => {
  PROTOTYPE_KEY_SHAPED_VALUES.forEach((id) => {
    var majors = [{ id: id, repo: "PT" }];
    var result = CairnLogic.dedupeMajorIds(majors);
    assert.deepEqual(result, [id], `dedupeMajorIds dropped major id ${JSON.stringify(id)}`);
  });
});

test("dedupeMajorIds: a real duplicate of a prototype-key-shaped id still collapses normally", () => {
  // Confirms the fix doesn't accidentally defeat the actual dedup logic
  // -- only the false-positive "already seen" read needs fixing, real
  // repeats must still collapse to one entry.
  var majors = [
    { id: "constructor", repo: "PT" },
    { id: "constructor", repo: "SB" },
  ];
  assert.deepEqual(CairnLogic.dedupeMajorIds(majors), ["constructor"]);
});

test("uniqueMilestoneKeys: an issue whose milestone id is prototype-key-shaped is not silently dropped", () => {
  // Passes ALREADY, even pre-fix -- documented deliberately, not an
  // oversight. uniqueMilestoneKeys' seen-set is keyed by the COMPOSITE
  // "repo::milestone" string (e.g. "PT::constructor"), not the bare
  // milestone id -- and a composite key essentially never collides with
  // an Object.prototype member name. Architect listed "seenMsKeys" among
  // the four risk sites; this test proves that specific site is safe by
  // construction (the prefix incidentally protects it), which is a real,
  // useful thing to have pinned rather than silently assumed.
  PROTOTYPE_KEY_SHAPED_VALUES.forEach((milestoneId) => {
    var issues = [{ id: "PT-1", repo: "PT", milestone: milestoneId }];
    var result = CairnLogic.uniqueMilestoneKeys(issues);
    assert.equal(result.length, 1, `uniqueMilestoneKeys dropped milestone id ${JSON.stringify(milestoneId)}`);
    assert.equal(result[0].key, "PT::" + milestoneId);
  });
});

test("uniqueSorted: a value shaped like an Object.prototype key is not silently dropped", () => {
  PROTOTYPE_KEY_SHAPED_VALUES.forEach((value) => {
    var result = CairnLogic.uniqueSorted([value]);
    assert.deepEqual(result, [value], `uniqueSorted dropped value ${JSON.stringify(value)}`);
  });
});

test("uniqueSorted: normal values still dedup and sort (regression, not just the prototype case)", () => {
  assert.deepEqual(
    CairnLogic.uniqueSorted(["backend-lead", "frontend-lead", "backend-lead"]),
    ["backend-lead", "frontend-lead"]
  );
});

test("uniqueSorted: falsy values (empty string, null, undefined) are excluded, not counted as real values", () => {
  assert.deepEqual(CairnLogic.uniqueSorted(["a", "", null, undefined, "b"]), ["a", "b"]);
});

test("groupByMilestone: an issue whose milestone id is prototype-key-shaped is not silently dropped from the group order", () => {
  PROTOTYPE_KEY_SHAPED_VALUES.forEach((milestoneId) => {
    var issues = [{ id: "PT-1", milestone: milestoneId }];
    var result = CairnLogic.groupByMilestone(issues);
    assert.deepEqual(result.order, [milestoneId], `groupByMilestone dropped milestone id ${JSON.stringify(milestoneId)} from order`);
    assert.equal(result.groups[milestoneId].length, 1);
    assert.equal(result.groups[milestoneId][0].id, "PT-1");
  });
});

test("groupByMilestone: groups issues with no milestone under the (none) key", () => {
  var issues = [{ id: "PT-1", milestone: null }, { id: "PT-2", milestone: undefined }];
  var result = CairnLogic.groupByMilestone(issues);
  assert.deepEqual(result.order, ["(none)"]);
  assert.deepEqual(
    result.groups["(none)"].map((i) => i.id),
    ["PT-1", "PT-2"]
  );
});

test("groupByMilestone: order is sorted ascending across distinct milestone keys", () => {
  var issues = [
    { id: "PT-1", milestone: "0.5" },
    { id: "PT-2", milestone: "0.4" },
    { id: "PT-3", milestone: "1.0" },
  ];
  var result = CairnLogic.groupByMilestone(issues);
  assert.deepEqual(result.order, ["0.4", "0.5", "1.0"]);
});

test("laneExpanded: a prototype-key-shaped stateKey reads as collapsed on an empty map, not already-expanded", () => {
  PROTOTYPE_KEY_SHAPED_VALUES.concat(["__proto__"]).forEach((key) => {
    assert.equal(
      CairnLogic.laneExpanded({}, key),
      false,
      `laneExpanded misread stateKey ${JSON.stringify(key)} as already-expanded on an empty map`
    );
  });
});

test("nextExpandedLanes: a prototype-key-shaped stateKey toggles open and closed like any other key", () => {
  PROTOTYPE_KEY_SHAPED_VALUES.concat(["__proto__"]).forEach((key) => {
    var opened = CairnLogic.nextExpandedLanes({}, key);
    assert.equal(CairnLogic.laneExpanded(opened, key), true, `key ${JSON.stringify(key)} did not open`);
    var closed = CairnLogic.nextExpandedLanes(opened, key);
    assert.equal(CairnLogic.laneExpanded(closed, key), false, `key ${JSON.stringify(key)} did not close`);
    assert.equal(Object.keys(closed).length, 0, `key ${JSON.stringify(key)} left a stray entry on close`);
  });
});
