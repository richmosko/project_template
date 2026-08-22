"use strict";

// PT-32 (architect's ruling, 2026-08-22): the pure, input-agnostic half of
// the pull-down-to-refresh gesture. Everything here consumes a pull
// DISTANCE and a handful of booleans -- never a touch event -- which is
// what keeps the touch-only scope decision (§1, Mosko's ruling) cheap to
// reverse later: a trackpad `wheel` adapter (PT-33) would feed this same
// machine a synthesized deltaY, not require a redesign.
//
// board.js's listener wiring, `passive: false` registration, `overscroll-
// behavior-y: contain`, the `#pull-indicator` DOM, and refreshBoardSilently's
// new boolean-resolution behavior are ALL untestable here -- they touch
// `document`/`fetch`/`localStorage` and are the browser checklist's job.
//
// None of pullPhase/pullIndicatorOffset/pullIndicatorLabel/shouldCancelPull/
// PULL_THRESHOLD/PULL_MAX_OFFSET/PULL_RESISTANCE/PULL_MIN_SPINNER_MS exist in
// board-logic.js as of this commit -- every test below is expected to fail
// with "not a function" / undefined-constant errors until implementation-
// lead's PT-32 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

// ---- constants ----

test("PULL_THRESHOLD is exported and equals 64", () => {
  assert.equal(CairnLogic.PULL_THRESHOLD, 64);
});

test("PULL_MAX_OFFSET is exported and equals 96", () => {
  assert.equal(CairnLogic.PULL_MAX_OFFSET, 96);
});

test("PULL_RESISTANCE is exported and equals 0.5", () => {
  assert.equal(CairnLogic.PULL_RESISTANCE, 0.5);
});

test("PULL_MIN_SPINNER_MS is exported and equals 400", () => {
  assert.equal(CairnLogic.PULL_MIN_SPINNER_MS, 400);
});

// ---- 1. pullPhase: not at scroll top ----

test("pullPhase: idle when atScrollTop is false, regardless of deltaY", () => {
  [0, 10, 64, 500].forEach((deltaY) => {
    assert.equal(
      CairnLogic.pullPhase({ atScrollTop: false, deltaY: deltaY, cancelled: false }),
      "idle",
      `deltaY=${deltaY} while not at scroll top must not arm`
    );
  });
});

// ---- 2. pullPhase: cancelled always wins ----

test("pullPhase: idle when cancelled is true, even at scroll top past threshold", () => {
  assert.equal(
    CairnLogic.pullPhase({ atScrollTop: true, deltaY: 500, cancelled: true }),
    "idle"
  );
});

// ---- 3. pullPhase: no downward movement ----

test("pullPhase: idle for deltaY <= 0 (zero or upward movement) at scroll top", () => {
  [0, -1, -50].forEach((deltaY) => {
    assert.equal(
      CairnLogic.pullPhase({ atScrollTop: true, deltaY: deltaY, cancelled: false }),
      "idle",
      `deltaY=${deltaY} must not start a pull`
    );
  });
});

// ---- 4. pullPhase: below threshold ----

test("pullPhase: pulling for 0 < deltaY < PULL_THRESHOLD", () => {
  var threshold = CairnLogic.PULL_THRESHOLD;
  [1, threshold / 2, threshold - 1].forEach((deltaY) => {
    assert.equal(
      CairnLogic.pullPhase({ atScrollTop: true, deltaY: deltaY, cancelled: false }),
      "pulling",
      `deltaY=${deltaY} (threshold ${threshold}) must read as pulling, not armed`
    );
  });
});

// ---- 5. pullPhase: exactly at threshold (boundary) ----

test("pullPhase: armed at EXACTLY PULL_THRESHOLD -- boundary is inclusive (at, not past)", () => {
  assert.equal(
    CairnLogic.pullPhase({ atScrollTop: true, deltaY: CairnLogic.PULL_THRESHOLD, cancelled: false }),
    "armed"
  );
});

test("pullPhase: armed for deltaY well past the threshold too", () => {
  assert.equal(
    CairnLogic.pullPhase({ atScrollTop: true, deltaY: CairnLogic.PULL_THRESHOLD + 200, cancelled: false }),
    "armed"
  );
});

// ---- 6. no-latch: armed must fall back to pulling, not stay armed ----

test("pullPhase does not latch: dropping back below threshold reads pulling again, not armed", () => {
  // pullPhase is a pure, memoryless function of its CURRENT inputs -- it
  // takes no "was this armed a moment ago" argument. The no-latch rule is
  // therefore a property of calling it twice with a shrinking deltaY, not
  // a property of any internal state: a naive implementation that
  // remembers "armed" once reached (e.g. `if (everReachedThreshold)
  // return "armed"`) is exactly what this catches.
  var atThreshold = CairnLogic.pullPhase({ atScrollTop: true, deltaY: CairnLogic.PULL_THRESHOLD + 10, cancelled: false });
  assert.equal(atThreshold, "armed", "sanity: this deltaY must read armed first");

  var afterRetreat = CairnLogic.pullPhase({ atScrollTop: true, deltaY: CairnLogic.PULL_THRESHOLD - 5, cancelled: false });
  assert.equal(afterRetreat, "pulling", "must fall back to pulling, not remain armed -- the no-latch rule");
});

// ---- 7. pullIndicatorOffset ----

test("pullIndicatorOffset: applies PULL_RESISTANCE to a positive deltaY", () => {
  assert.equal(CairnLogic.pullIndicatorOffset(10), 10 * CairnLogic.PULL_RESISTANCE);
});

test("pullIndicatorOffset: zero deltaY yields zero offset", () => {
  assert.equal(CairnLogic.pullIndicatorOffset(0), 0);
});

test("pullIndicatorOffset: floors at 0 for a negative deltaY", () => {
  assert.equal(CairnLogic.pullIndicatorOffset(-40), 0);
});

test("pullIndicatorOffset: caps at PULL_MAX_OFFSET for a large deltaY", () => {
  assert.equal(CairnLogic.pullIndicatorOffset(10000), CairnLogic.PULL_MAX_OFFSET);
});

test("pullIndicatorOffset: exactly at the cap boundary (deltaY * resistance === PULL_MAX_OFFSET)", () => {
  var deltaYAtCap = CairnLogic.PULL_MAX_OFFSET / CairnLogic.PULL_RESISTANCE;
  assert.equal(CairnLogic.pullIndicatorOffset(deltaYAtCap), CairnLogic.PULL_MAX_OFFSET);
});

test("pullIndicatorOffset: just below the cap boundary is NOT clamped -- confirms the cap is a min(), not an early floor", () => {
  var deltaYJustBelowCap = CairnLogic.PULL_MAX_OFFSET / CairnLogic.PULL_RESISTANCE - 10;
  var expected = deltaYJustBelowCap * CairnLogic.PULL_RESISTANCE;
  assert.equal(CairnLogic.pullIndicatorOffset(deltaYJustBelowCap), expected);
  assert.ok(expected < CairnLogic.PULL_MAX_OFFSET, "test sanity: this value must actually be under the cap");
});

// ---- 8. pullIndicatorLabel ----

test("pullIndicatorLabel: a distinct, non-empty string for each of the three phases with copy", () => {
  var pulling = CairnLogic.pullIndicatorLabel("pulling");
  var armed = CairnLogic.pullIndicatorLabel("armed");
  var refreshing = CairnLogic.pullIndicatorLabel("refreshing");

  [pulling, armed, refreshing].forEach((label, i) => {
    assert.equal(typeof label, "string", `phase ${["pulling", "armed", "refreshing"][i]} must return a string`);
    assert.notEqual(label.length, 0, `phase ${["pulling", "armed", "refreshing"][i]} must not be an empty string`);
  });

  assert.notEqual(pulling, armed);
  assert.notEqual(armed, refreshing);
  assert.notEqual(pulling, refreshing);
});

test("pullIndicatorLabel: matches the ruling's exact copy", () => {
  assert.equal(CairnLogic.pullIndicatorLabel("pulling"), "↓ Pull to refresh");
  assert.equal(CairnLogic.pullIndicatorLabel("armed"), "↑ Release to refresh");
  assert.equal(CairnLogic.pullIndicatorLabel("refreshing"), "↻ Refreshing…");
});

test("pullIndicatorLabel: does not throw and returns a string for an unknown/idle phase", () => {
  ["idle", "bogus", undefined, null].forEach((phase) => {
    var label;
    assert.doesNotThrow(() => { label = CairnLogic.pullIndicatorLabel(phase); }, `phase ${JSON.stringify(phase)} must not throw`);
    assert.equal(typeof label, "string", `phase ${JSON.stringify(phase)} must still return a string`);
  });
});

// ---- 9. shouldCancelPull: each flag cancels independently ----

function cancelFlags(overrides) {
  return Object.assign(
    { cardDragActive: false, drawerOpen: false, multiTouch: false, horizontalDominant: false, refreshing: false },
    overrides
  );
}

test("shouldCancelPull: false when every flag is absent/false", () => {
  assert.equal(CairnLogic.shouldCancelPull(cancelFlags({})), false);
});

test("shouldCancelPull: true when cardDragActive alone is true (AC3 -- no interference with drag)", () => {
  assert.equal(CairnLogic.shouldCancelPull(cancelFlags({ cardDragActive: true })), true);
});

test("shouldCancelPull: true when drawerOpen alone is true (the fixed-position drawer trap)", () => {
  assert.equal(CairnLogic.shouldCancelPull(cancelFlags({ drawerOpen: true })), true);
});

test("shouldCancelPull: true when multiTouch alone is true (pinch-zoom is not a pull)", () => {
  assert.equal(CairnLogic.shouldCancelPull(cancelFlags({ multiTouch: true })), true);
});

test("shouldCancelPull: true when horizontalDominant alone is true (a lane's horizontal swipe must not be stolen)", () => {
  assert.equal(CairnLogic.shouldCancelPull(cancelFlags({ horizontalDominant: true })), true);
});

test("shouldCancelPull: true when refreshing alone is true (no stacking repeated pulls)", () => {
  assert.equal(CairnLogic.shouldCancelPull(cancelFlags({ refreshing: true })), true);
});

// ---- 10. pullPhase's partiality is the contract ----

test("pullPhase never returns 'refreshing' for any input -- entering/leaving that phase is the async caller's business, not this function's", () => {
  var atScrollTopValues = [true, false];
  var cancelledValues = [true, false];
  var deltaYValues = [-100, -1, 0, 1, 30, CairnLogic.PULL_THRESHOLD, CairnLogic.PULL_THRESHOLD + 1, 1000];

  atScrollTopValues.forEach((atScrollTop) => {
    cancelledValues.forEach((cancelled) => {
      deltaYValues.forEach((deltaY) => {
        var phase = CairnLogic.pullPhase({ atScrollTop: atScrollTop, deltaY: deltaY, cancelled: cancelled });
        assert.notEqual(
          phase,
          "refreshing",
          `pullPhase({atScrollTop:${atScrollTop}, deltaY:${deltaY}, cancelled:${cancelled}}) must never be "refreshing"`
        );
        assert.ok(
          phase === "idle" || phase === "pulling" || phase === "armed",
          `pullPhase returned an unrecognized phase: ${JSON.stringify(phase)}`
        );
      });
    });
  });
});
