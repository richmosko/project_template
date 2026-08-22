"use strict";

// Shared test scaffolding for the board-logic.js JS suite -- mirrors
// scripts/cairn/tests/helpers.py's role for the Python suite. Every test
// file requires this first so loadCairnLogic() is the one place that
// knows how board-logic.js gets evaluated.
//
// board-logic.js is a plain <script> (no module system -- see
// INTERFACE.md's "Loading contract"): a top-level `var CairnLogic = ...`,
// no `window.` prefix, no module.exports. A top-level `var` lands on the
// global object in both environments this file runs in -- `window` in a
// real browser, the vm context's global object here -- so the one file
// serves both with no dual-mode branching (architect's ruling,
// 2026-08-21, settling a convention question that had qa-engineer and
// implementation-lead each waiting on the other).
//
// vm.runInNewContext gives each call its own fresh context/global object
// and evaluates the source directly against it -- `var CairnLogic = ...`
// at the top of that source becomes a property of the context object
// itself, read back out here as `sandbox.CairnLogic`. Deliberately a
// FRESH context per loadCairnLogic() call (matches "fresh context per
// test file" -- every test file calls this once at module load) rather
// than a shared/cached one: every bug this suite exists to catch was
// about stale or accidentally-shared lookup state, so the harness itself
// shouldn't introduce a shared-state footgun of its own.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const BOARD_LOGIC_PATH = path.join(__dirname, "..", "..", "board", "board-logic.js");

function loadCairnLogic() {
  let source;
  try {
    source = fs.readFileSync(BOARD_LOGIC_PATH, "utf8");
  } catch (err) {
    throw new Error(
      `board-logic.js not found at ${BOARD_LOGIC_PATH} -- has the PT-22 ` +
        `extraction landed yet? (${err.message})`
    );
  }

  const sandbox = {};
  try {
    vm.runInNewContext(source, sandbox, { filename: BOARD_LOGIC_PATH });
  } catch (err) {
    throw new Error(`board-logic.js threw while loading: ${err.message}`);
  }

  if (!sandbox.CairnLogic || typeof sandbox.CairnLogic !== "object") {
    throw new Error(
      "board-logic.js did not expose a global CairnLogic object " +
        '(expected a top-level "var CairnLogic = {...}" -- see ' +
        "INTERFACE.md's Loading contract)"
    );
  }
  return wrapForRealm(sandbox.CairnLogic);
}

// vm.runInNewContext() gives board-logic.js's code its OWN JS realm -- a
// separate Object.prototype/Array.prototype from this file's. A plain
// object literal `{done: 2, total: 3}` returned from inside the sandbox
// is therefore NOT deepStrictEqual to an identically-shaped literal
// written in a test file: Node's assert/strict correctly (if
// surprisingly) treats cross-realm object identity as a real
// distinction, not a false positive to paper over -- and rightly so in
// general, but it's a pure loader artifact here, not a bug in the
// function under test. Every CairnLogic function returns plain
// JSON-shaped data (strings, null, arrays of plain objects, or plain
// objects) -- rehoming the value into THIS realm cheaply and safely
// closes it, since none of these functions ever return Dates/Maps/
// RegExps/etc. that a structural copy can't reproduce. Fixed once here
// rather than in every test file.
//
// PT-30 (view-state.test.js's "returns an Object.create(null) map"
// case): NOT a JSON.stringify/parse round-trip -- that recreates every
// object using THIS realm's normal Object.prototype regardless of the
// sandbox value's own prototype, so a null-prototype map (parseExpandedLanes,
// laneExpanded's/nextExpandedLanes' maps) silently grew a prototype chain
// crossing the wrapper, the same class of gap PT-29's wrapForRealm fix
// (below) closed for data-vs-function exports. Recursing by hand and
// preserving "was this object's own prototype null" at each level closes
// it structurally instead of case-by-case.
function rehome(value) {
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) {
    // NOT `value.map(rehome)` -- `.map` resolves through the FOREIGN
    // realm's own Array.prototype (that's whose object `value` is), and
    // per spec uses `this`'s species constructor to build the result, so
    // the "rehomed" array would still be a foreign-realm Array and fail
    // assert.deepStrictEqual against a same-shaped current-realm literal
    // exactly like the object case this function exists to fix. A `[]`
    // literal + push, evaluated in THIS file's realm, sidesteps it.
    var arr = [];
    for (var i = 0; i < value.length; i++) arr.push(rehome(value[i]));
    return arr;
  }
  var copy = Object.getPrototypeOf(value) === null ? Object.create(null) : {};
  Object.keys(value).forEach(function (key) { copy[key] = rehome(value[key]); });
  return copy;
}

function wrapForRealm(cairnLogic) {
  var wrapped = {};
  Object.keys(cairnLogic).forEach(function (name) {
    var value = cairnLogic[name];
    // PT-29: not every CairnLogic export is a function -- BOARD_COLUMNS
    // (architect's ruling § 4) is a plain data array. Wrapping it in a
    // callable the way every prior export was (this function pre-dates
    // PT-29) silently replaced the array with a Function value, so
    // `CairnLogic.BOARD_COLUMNS` read back here as `[Function (anonymous)]`
    // instead of the list of strings. Data exports are rehomed directly;
    // only functions get the call-and-rehome wrapper.
    if (typeof value === "function") {
      wrapped[name] = function () {
        return rehome(value.apply(null, arguments));
      };
    } else {
      wrapped[name] = rehome(value);
    }
  });
  return wrapped;
}

module.exports = { loadCairnLogic, BOARD_LOGIC_PATH };
