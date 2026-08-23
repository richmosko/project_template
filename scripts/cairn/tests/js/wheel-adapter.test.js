"use strict";

// PT-33 (architect's ruling @ e319208, on PT-32's foundation @ 052d7de): the
// pure, input-agnostic wheel adapter feeding PT-32's `pullPhase` machine a
// synthesized deltaY. `wheel` has no start/end marker the way touch does, so
// this reducer infers gesture-open from a quiet gap (`WHEEL_PULL_IDLE_MS`)
// rather than a velocity/decay model -- momentum is never preceded by
// stillness; a deliberate pull is. The flick-to-top false positive (the case
// that deferred this from PT-32) is D15/D17 below.
//
// None of wheelPullInitialState/wheelPullDistance/wheelPullReduce/
// wheelPullShouldFire/WHEEL_PULL_IDLE_MS/WHEEL_PULL_BURST_MAX/
// WHEEL_LINE_HEIGHT exist in board-logic.js as of this commit -- every test
// below is expected to fail with "not a function" / undefined-constant
// errors until implementation-lead's PT-33 slice lands.
//
// AC4 is enforced structurally, not by a test in this file: `pullPhase` and
// friends are NOT modified by this issue (the ruling's ground truth,
// measured at 052d7de) and `pull-refresh.test.js` is NOT edited here -- that
// suite passing byte-for-byte unchanged alongside this one *is* the touch-
// path regression check. Do not add wheel assertions to that file.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

// ---- shared fixture helpers ----

// A wheel event with sane defaults; override only what a case cares about.
function ev(overrides) {
  return Object.assign(
    {
      deltaY: 0,
      deltaX: 0,
      deltaMode: 0,
      timeStamp: 0,
      atScrollTop: true,
      horizontalDominant: false,
    },
    overrides
  );
}

// Deterministic PRNG (mulberry32) -- D17's "randomize the decay curve" needs
// reproducible sequences, not real randomness a flaky run could blame.
function mulberry32(seed) {
  var s = seed >>> 0;
  return function () {
    s = (s + 0x6d2b79f5) | 0;
    var t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const IDLE = () => CairnLogic.WHEEL_PULL_IDLE_MS;
const BURST = () => CairnLogic.WHEEL_PULL_BURST_MAX;
const LINE = () => CairnLogic.WHEEL_LINE_HEIGHT;

// ================= A. wheelPullDistance =================

test("A1: wheelPullDistance -- deltaMode 0 (pixels), sign-flipped: up is positive pull", () => {
  assert.equal(CairnLogic.wheelPullDistance({ deltaY: -12, deltaMode: 0 }), 12);
  assert.equal(CairnLogic.wheelPullDistance({ deltaY: 12, deltaMode: 0 }), -12);
});

test("A2: wheelPullDistance -- deltaMode 1 (lines) normalizes by WHEEL_LINE_HEIGHT", () => {
  assert.equal(CairnLogic.wheelPullDistance({ deltaY: -3, deltaMode: 1 }), 3 * LINE());
});

test("A3: wheelPullDistance -- deltaMode 2 (pages) and any unknown mode return 0", () => {
  [2, 3, 99, undefined, null].forEach((mode) => {
    assert.equal(
      CairnLogic.wheelPullDistance({ deltaY: -50, deltaMode: mode }),
      0,
      `deltaMode=${JSON.stringify(mode)} must normalize to 0, never a fabricated pixel value`
    );
  });
});

// ================= B. Opening gates (evaluated ONLY on an opening event) =================

test("B4: first-ever event (lastTs === -Infinity), at top, small upward delta -> pulling, distance = normalized magnitude", () => {
  var initial = CairnLogic.wheelPullInitialState();
  assert.equal(initial.lastTs, -Infinity, "sanity: initial lastTs must be -Infinity so the very first event always opens");

  var next = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -20, timeStamp: 1000 }));
  assert.equal(next.status, "pulling");
  assert.equal(next.distance, 20);
  assert.equal(next.lastTs, 1000);
});

test("B5: opening event with atScrollTop:false -> blocked", () => {
  var initial = CairnLogic.wheelPullInitialState();
  var next = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -20, atScrollTop: false, timeStamp: 1000 }));
  assert.equal(next.status, "blocked");
});

test("B6: opening event with distance <= 0 (downward or zero) -> blocked", () => {
  var initial = CairnLogic.wheelPullInitialState();
  [0, 20].forEach((deltaY) => {
    var next = CairnLogic.wheelPullReduce(initial, ev({ deltaY: deltaY, timeStamp: 1000 }));
    assert.equal(next.status, "blocked", `deltaY=${deltaY} (distance <= 0) must block an opening event`);
  });
});

test("B7: opening event with distance > WHEEL_PULL_BURST_MAX -> blocked", () => {
  var initial = CairnLogic.wheelPullInitialState();
  var next = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -(BURST() + 10), timeStamp: 1000 }));
  assert.equal(next.status, "blocked");
});

test("B8: opening event with horizontalDominant:true -> blocked", () => {
  var initial = CairnLogic.wheelPullInitialState();
  var next = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -20, horizontalDominant: true, timeStamp: 1000 }));
  assert.equal(next.status, "blocked");
});

test("B9: boundary -- distance EXACTLY WHEEL_PULL_BURST_MAX opens (inclusive)", () => {
  var initial = CairnLogic.wheelPullInitialState();
  var next = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -BURST(), timeStamp: 1000 }));
  assert.equal(next.status, "pulling", "the burst gate boundary is inclusive, matching PULL_THRESHOLD's convention");
  assert.equal(next.distance, BURST());
});

// ================= C. Continuation =================

test("C10: gap < WHEEL_PULL_IDLE_MS while prev.status !== 'pulling' -> stays blocked, never opens", () => {
  var initial = CairnLogic.wheelPullInitialState();
  var blocked = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -20, atScrollTop: false, timeStamp: 1000 }));
  assert.equal(blocked.status, "blocked", "sanity: first event must be blocked (not at scroll top)");

  var still = CairnLogic.wheelPullReduce(blocked, ev({ deltaY: -20, atScrollTop: true, timeStamp: 1000 + IDLE() - 1 }));
  assert.equal(still.status, "blocked", "a small gap must not re-evaluate opening gates even with otherwise-valid params");
});

test("C11: successive in-gesture events accumulate distance", () => {
  var initial = CairnLogic.wheelPullInitialState();
  var opened = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -10, timeStamp: 1000 }));
  assert.equal(opened.status, "pulling");
  assert.equal(opened.distance, 10);

  var again = CairnLogic.wheelPullReduce(opened, ev({ deltaY: -10, timeStamp: 1016 }));
  assert.equal(again.status, "pulling");
  assert.equal(again.distance, 20);

  var third = CairnLogic.wheelPullReduce(again, ev({ deltaY: -15, timeStamp: 1032 }));
  assert.equal(third.status, "pulling");
  assert.equal(third.distance, 35);
});

test("C12: a delta > WHEEL_PULL_BURST_MAX mid-gesture does NOT block -- gates are open-only", () => {
  var initial = CairnLogic.wheelPullInitialState();
  var opened = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -10, timeStamp: 1000 }));
  assert.equal(opened.status, "pulling");

  var accelerated = CairnLogic.wheelPullReduce(opened, ev({ deltaY: -(BURST() + 200), timeStamp: 1016 }));
  assert.equal(accelerated.status, "pulling", "the burst gate must not re-apply mid-gesture; fast finishes are legal");
  assert.equal(accelerated.distance, 10 + BURST() + 200);
});

test("C13: retreat -- a downward delta decrements; decrementing to <= 0 ends the gesture (idle, distance 0)", () => {
  // Opening magnitude deliberately <= WHEEL_PULL_BURST_MAX (30, not 50) --
  // an opening event's distance is gated by the burst max (B7/B9/D21 pin it
  // at 40, inclusive) with no first-event exception. A 50px opener would be
  // refused at open (blocked, distance 0), never reaching "pulling" at all,
  // which would make this fixture test nothing about retreat. Caught by
  // implementation-lead cross-checking this case against its own siblings.
  var initial = CairnLogic.wheelPullInitialState();
  var opened = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -30, timeStamp: 1000 }));
  assert.equal(opened.status, "pulling");
  assert.equal(opened.distance, 30);

  var partialRetreat = CairnLogic.wheelPullReduce(opened, ev({ deltaY: 10, timeStamp: 1016 }));
  assert.equal(partialRetreat.status, "pulling", "a retreat that doesn't cross zero stays pulling -- the no-latch rule");
  assert.equal(partialRetreat.distance, 20);

  var fullRetreat = CairnLogic.wheelPullReduce(partialRetreat, ev({ deltaY: 25, timeStamp: 1032 }));
  assert.equal(fullRetreat.status, "idle", "a retreat past zero must end the gesture, not just zero the distance");
  assert.equal(fullRetreat.distance, 0);
});

test("C14: lastTs advances on EVERY event, including blocked and downward ones -- the load-bearing line", () => {
  // If the reducer only recorded timestamps for events it liked, a momentum
  // tail's first at-top event would see a stale lastTs, read as "preceded by
  // silence", and open a gesture -- exactly the false positive this issue
  // exists to prevent. An early-return optimization that skips the reducer
  // for events it can cheaply reject reopens this hole (§6 JC2 in the
  // ruling) -- this is why the handler must route every event through here.
  var initial = CairnLogic.wheelPullInitialState();

  var blockedByScroll = CairnLogic.wheelPullReduce(initial, ev({ deltaY: -20, atScrollTop: false, timeStamp: 500 }));
  assert.equal(blockedByScroll.status, "blocked");
  assert.equal(blockedByScroll.lastTs, 500, "lastTs must advance even on a blocked (not-at-top) event");

  var blockedByDownward = CairnLogic.wheelPullReduce(blockedByScroll, ev({ deltaY: 20, atScrollTop: true, timeStamp: 500 + IDLE() + 5 }));
  // This event's gap (IDLE()+5) IS >= WHEEL_PULL_IDLE_MS, so it IS an opening
  // evaluation -- and it fails the distance<=0 gate (downward), so it must
  // still land on "blocked", with lastTs advanced to ITS OWN timeStamp again.
  assert.equal(blockedByDownward.status, "blocked");
  assert.equal(blockedByDownward.lastTs, 500 + IDLE() + 5, "lastTs must advance on a blocked downward event too");

  // Now prove the consequence directly: a SMALL gap after that downward
  // event must NOT be treated as an opening -- which is only true if lastTs
  // really did move to the downward event's own timeStamp.
  var next = CairnLogic.wheelPullReduce(blockedByDownward, ev({ deltaY: -20, atScrollTop: true, timeStamp: blockedByDownward.lastTs + IDLE() - 1 }));
  assert.equal(next.status, "blocked", "a stale (un-advanced) lastTs would make this gap read as an opening and wrongly arm the gesture");
});

// ================= D. The momentum property =================

// ~15 events, 16ms apart, magnitudes decaying 140 -> 4, atScrollTop false for
// the first few then true (the scroll-to-top animation catching up before
// momentum continues past it), the whole window preceded by only a 16ms gap
// (this window's first event is itself a continuation of an already-running
// flick, per the ruling's D15 fixture spec).
function flickToTopEvents(t0) {
  var magnitudes = [140, 118, 98, 82, 68, 56, 46, 37, 30, 24, 19, 15, 11, 8, 4];
  var atScrollTopFlags = [false, false, false, false, false, true, true, true, true, true, true, true, true, true, true];
  return magnitudes.map(function (mag, i) {
    return ev({
      deltaY: -mag,
      timeStamp: t0 + i * 16,
      atScrollTop: atScrollTopFlags[i],
    });
  });
}

test("D15: flick-to-top fixture -- status never 'pulling' at any prefix, distance stays 0, shouldFire false throughout and after quiescence (the reason this issue exists)", () => {
  var t0 = 100000;
  // Seeded so the fixture's first event is a continuation (gap 16ms < IDLE),
  // not a true first-ever event -- see the fixture comment above.
  var state = { status: "idle", distance: 0, lastTs: t0 - 16 };

  flickToTopEvents(t0).forEach(function (e, i) {
    state = CairnLogic.wheelPullReduce(state, e);
    assert.notEqual(state.status, "pulling", `prefix ${i}: momentum tail must never read as pulling`);
    assert.equal(state.distance, 0, `prefix ${i}: distance must stay 0 through the whole momentum tail`);
    assert.equal(CairnLogic.wheelPullShouldFire(state, false), false, `prefix ${i}: must never be armed to fire`);
  });

  // "After quiescence" -- a long gap with no further events changes nothing;
  // the last computed state is what board.js would still be holding.
  assert.equal(CairnLogic.wheelPullShouldFire(state, false), false);
});

test("D16: deliberate-pull fixture -- opens after the idle gap, accumulates past threshold, fires", () => {
  var t0 = 200000;
  var state = { status: "idle", distance: 0, lastTs: t0 - IDLE() - 50 }; // preceded by real silence

  for (var i = 0; i < 20; i++) {
    state = CairnLogic.wheelPullReduce(state, ev({ deltaY: -6, timeStamp: t0 + i * 16 }));
  }

  assert.equal(state.status, "pulling");
  assert.ok(state.distance >= CairnLogic.PULL_THRESHOLD, `distance ${state.distance} must reach PULL_THRESHOLD (${CairnLogic.PULL_THRESHOLD})`);
  assert.equal(CairnLogic.wheelPullShouldFire(state, false), true);
});

test("D17: invariant -- for ANY sequence with no gap >= WHEEL_PULL_IDLE_MS and a first-event magnitude > WHEEL_PULL_BURST_MAX, wheelPullShouldFire is false at every prefix (randomized decay curves)", () => {
  for (var trial = 0; trial < 20; trial++) {
    var rand = mulberry32(trial + 1);
    var t0 = 1000 + trial * 100000;
    var length = 10 + Math.floor(rand() * 20); // 10..29 events
    var mag = BURST() + 1 + Math.floor(rand() * 200); // first magnitude always > burst max

    var state = { status: "idle", distance: 0, lastTs: t0 - 16 }; // no gap before the window either
    for (var i = 0; i < length; i++) {
      state = CairnLogic.wheelPullReduce(state, ev({ deltaY: -mag, timeStamp: t0 + i * 16, atScrollTop: true }));
      assert.equal(
        CairnLogic.wheelPullShouldFire(state, false),
        false,
        `trial ${trial}, event ${i}: no-gap decaying-magnitude stream must never be armed to fire (mag=${mag})`
      );
      // Decay by a random factor in [0.6, 0.95), floored, never below 1 --
      // a plateau-tolerant decay curve, not strict monotonic decrease.
      mag = Math.max(1, Math.floor(mag * (0.6 + rand() * 0.35)));
    }
  }
});

test("D18: recovery -- momentum rejection is temporary; a real gap after a blocked stream opens a fresh gesture", () => {
  var t0 = 300000;
  var state = { status: "idle", distance: 0, lastTs: t0 - 16 };
  flickToTopEvents(t0).forEach(function (e) {
    state = CairnLogic.wheelPullReduce(state, e);
  });
  assert.notEqual(state.status, "pulling", "sanity: the flick tail must have left the gesture unarmed");

  var recovered = CairnLogic.wheelPullReduce(
    state,
    ev({ deltaY: -10, atScrollTop: true, timeStamp: state.lastTs + IDLE() })
  );
  assert.equal(recovered.status, "pulling", "a real quiet gap after a blocked/momentum stream must open a fresh gesture");
  assert.equal(recovered.distance, 10);
});

test("D19: wheelPullShouldFire is false when cancelled is true, even at distance far past threshold (delegation to pullPhase)", () => {
  var state = { status: "pulling", distance: CairnLogic.PULL_THRESHOLD + 500, lastTs: 0 };
  assert.equal(CairnLogic.wheelPullShouldFire(state, true), false);
});

test("D20: wheelPullShouldFire is false for 'blocked' or 'idle' status whatever the distance", () => {
  ["blocked", "idle"].forEach((status) => {
    [0, 1, CairnLogic.PULL_THRESHOLD, CairnLogic.PULL_THRESHOLD + 1000].forEach((distance) => {
      var state = { status: status, distance: distance, lastTs: 0 };
      assert.equal(
        CairnLogic.wheelPullShouldFire(state, false),
        false,
        `status=${status} distance=${distance} must never be armed to fire`
      );
    });
  });
});

test("D21: constants export exactly 120 / 40 / 16", () => {
  assert.equal(CairnLogic.WHEEL_PULL_IDLE_MS, 120);
  assert.equal(CairnLogic.WHEEL_PULL_BURST_MAX, 40);
  assert.equal(CairnLogic.WHEEL_LINE_HEIGHT, 16);
});

test("D22: wheelPullReduce does not mutate prev; wheelPullInitialState returns a fresh object each call", () => {
  var prev = { status: "pulling", distance: 30, lastTs: 1000 };
  var prevCopy = { status: "pulling", distance: 30, lastTs: 1000 };
  CairnLogic.wheelPullReduce(prev, ev({ deltaY: -10, timeStamp: 1016 }));
  assert.deepEqual(prev, prevCopy, "wheelPullReduce must not mutate the state object passed in");

  var a = CairnLogic.wheelPullInitialState();
  var b = CairnLogic.wheelPullInitialState();
  assert.deepEqual(a, b, "two calls must be structurally equal");
  a.distance = 999;
  assert.notEqual(b.distance, 999, "mutating one call's result must not affect another -- each call must return a FRESH object, not a shared one");
});
