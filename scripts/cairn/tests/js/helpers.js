"use strict";

// Shared test scaffolding for the board-logic.js JS suite -- mirrors
// scripts/cairn/tests/helpers.py's role for the Python suite. Every test
// file requires this first so loadCairnLogic() is the one place that
// knows how board-logic.js gets evaluated.
//
// board-logic.js is a plain <script> (no module system -- see
// INTERFACE.md's "Loading contract"), so it can't be `require()`d
// directly (no module.exports, and top-level `window.CairnLogic = ...`
// would throw ReferenceError under Node's CommonJS loader, which has no
// `window`). node:vm evaluates the file's source in a fresh sandbox
// object with `window` aliased to that same sandbox -- so
// `window.CairnLogic = {...}` in the file lands as a plain property of
// the sandbox, readable back out as `sandbox.CairnLogic` afterward.

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
  sandbox.window = sandbox;
  sandbox.console = console;
  vm.createContext(sandbox);

  try {
    vm.runInContext(source, sandbox, { filename: BOARD_LOGIC_PATH });
  } catch (err) {
    throw new Error(`board-logic.js threw while loading: ${err.message}`);
  }

  if (!sandbox.CairnLogic || typeof sandbox.CairnLogic !== "object") {
    throw new Error(
      "board-logic.js did not expose a global CairnLogic object " +
        '(expected "window.CairnLogic = {...}" at top level -- see ' +
        "INTERFACE.md's Loading contract)"
    );
  }
  return wrapForRealm(sandbox.CairnLogic);
}

// vm.createContext() gives board-logic.js's code its OWN JS realm -- a
// separate Object.prototype/Array.prototype from this file's. A plain
// object literal `{done: 2, total: 3}` returned from inside the sandbox
// is therefore NOT deepStrictEqual to an identically-shaped literal
// written in a test file: Node's assert/strict correctly (if
// surprisingly) treats cross-realm object identity as a real
// distinction, not a false positive to paper over -- and rightly so in
// general, but it's a pure loader artifact here, not a bug in the
// function under test. Every CairnLogic function returns plain
// JSON-shaped data (strings, null, arrays of plain objects, or plain
// objects) -- round-tripping through JSON.stringify/parse rehomes the
// value into THIS realm cheaply and safely, since none of these
// functions ever return Dates/Maps/RegExps/etc. that JSON can't
// round-trip. Fixed once here rather than in every test file.
function rehome(value) {
  if (value === null || typeof value !== "object") return value;
  return JSON.parse(JSON.stringify(value));
}

function wrapForRealm(cairnLogic) {
  var wrapped = {};
  Object.keys(cairnLogic).forEach(function (name) {
    var fn = cairnLogic[name];
    wrapped[name] = function () {
      return rehome(fn.apply(null, arguments));
    };
  });
  return wrapped;
}

module.exports = { loadCairnLogic, BOARD_LOGIC_PATH };
