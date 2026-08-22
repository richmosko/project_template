"use strict";

// PT-31 item 5 (architect's ruling): direct self-tests of helpers.js's own
// rehome/wrapForRealm -- test infrastructure, authored by QA, no
// implementation hand-off. These two functions have shipped a REAL,
// escaped gap in two consecutive loops, both times caught only by
// incidental product-test coverage (a CairnLogic function that happened to
// exercise the gap), never by a test of the harness itself:
//   - PT-29: wrapForRealm treated every export as a function, so
//     BOARD_COLUMNS (a data array) read back as `[Function (anonymous)]`.
//   - PT-30: rehome's original JSON.stringify/parse round-trip silently
//     restored `Object.prototype` on a null-proto value.
//
// THE decisive instruction (architect, quoted verbatim in the ruling):
// "the fixture must be evaluated in a vm context, not defined as a
// literal in the test file -- a same-realm fixture passes every assertion
// trivially, and the suite would report coverage that doesn't exist."
// rehome/wrapForRealm exist ENTIRELY to fix cross-realm identity; a
// fixture built with `{}`/`[]` literals in THIS file is already same-realm
// before rehome ever touches it, so every assertion below would pass
// whether or not rehome/wrapForRealm did anything at all -- exactly the
// "looks thorough, tests nothing" failure the instruction names.
//
// So: the fixture (a synthetic CairnLogic-alike, deliberately independent
// of what board-logic.js actually exports -- this suite must keep passing
// even if CairnLogic's real export list changes shape entirely) is built
// by evaluating a source string via vm.runInNewContext, exactly the same
// mechanism loadCairnLogic() itself uses to load board-logic.js. Every
// object literal inside FIXTURE_SOURCE is constructed in that foreign
// realm -- a DIFFERENT Object.prototype/Array.prototype than this file's --
// which is what makes a cross-realm bug in rehome/wrapForRealm actually
// observable here.

const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const { rehome, wrapForRealm } = require("./helpers.js");

// The seven cases from the ruling's fixture-shape table, each exported as
// a top-level `var` (lands on the vm context object, same convention
// board-logic.js itself uses) so wrapForRealm sees them as CairnLogic-alike
// exports -- a mix of function-valued (called-and-rehomed) and data-valued
// (rehomed directly) entries, on purpose, since that mix is exactly what
// PT-29's gap was about.
const FIXTURE_SOURCE = `
"use strict";

// 1. Base case: a function returning a plain object.
function plainObjectFn() { return { a: 1, b: "two" }; }

// 2. PT-29's gap: a DATA ARRAY export, not a function.
var dataArray = ["x", "y", "z"];

// 3. PT-30's gap: a DATA export with a NULL PROTOTYPE, not a function.
var nullProtoData = (function () {
  var o = Object.create(null);
  o.k1 = "v1";
  o.k2 = "v2";
  return o;
})();

// 4. Recursion: a function returning a nested mix -- an array of objects,
//    an object containing an array, and a null-proto object nested inside
//    a normal one. A per-case (non-recursive) fix would pass 1-3 above and
//    still miss this.
function nestedMixFn() {
  var innerNullProto = Object.create(null);
  innerNullProto.deep = "value";
  return {
    arrayOfObjects: [{ id: 1 }, { id: 2 }],
    objectWithArray: { list: [1, 2, 3] },
    nullProtoNested: innerNullProto,
  };
}

// 5. The non-object short-circuit: primitive, null, undefined.
function primitiveFn() { return 42; }
function nullFn() { return null; }
function undefinedFn() { return undefined; }

// 6. Non-object DATA exports -- must pass through untouched.
var stringData = "hello";
var numberData = 7;

// 7. The prototype-collision class this codebase keeps meeting: an object
//    whose OWN keys are named "constructor" and "__proto__". Plain
//    assignment is enough for "constructor" (an ordinary writable/
//    configurable data property on Object.prototype, shadowed normally),
//    but "__proto__" needs defineProperty -- bracket/dot assignment to
//    "__proto__" invokes Object.prototype's special accessor instead of
//    creating an own data property (and silently no-ops here, since a
//    string isn't a valid prototype value), which would make the fixture
//    itself fail to reproduce the exact hazard it exists to test.
function collisionObjFn() {
  var o = { constructor: "not-the-real-constructor" };
  Object.defineProperty(o, "__proto__", {
    value: "also-just-a-string-value",
    enumerable: true,
    writable: true,
    configurable: true,
  });
  return o;
}
`;

function loadFixture() {
  const sandbox = {};
  vm.runInNewContext(FIXTURE_SOURCE, sandbox, { filename: "pt31-helpers-realm-fixture.js" });
  return sandbox;
}

// Sanity check on the fixture-loading mechanism itself, run first: if this
// fails, every test below is meaningless (it would mean FIXTURE_SOURCE
// isn't actually landing in a foreign realm at all).
test("fixture sanity: the loaded fixture's objects are NOT same-realm as this file's literals", () => {
  const fixture = loadFixture();
  const foreignObj = fixture.plainObjectFn();
  assert.notEqual(
    Object.getPrototypeOf(foreignObj),
    Object.prototype,
    "the fixture must be foreign-realm -- its plain objects' prototype must NOT be THIS file's Object.prototype"
  );
  const foreignArr = fixture.dataArray;
  assert.equal(
    foreignArr instanceof Array,
    false,
    "the fixture must be foreign-realm -- its arrays must NOT be instances of THIS file's Array"
  );
});

// ---- 1. base case: function returning a plain object ----

test("wrapForRealm: a function export is called-and-rehomed, returns a same-realm deepStrictEqual object", () => {
  const wrapped = wrapForRealm(loadFixture());
  const result = wrapped.plainObjectFn();
  assert.deepStrictEqual(result, { a: 1, b: "two" });
  assert.equal(Object.getPrototypeOf(result), Object.prototype);
});

// ---- 2. PT-29's gap: data array export ----

test("wrapForRealm: a DATA ARRAY export is rehomed directly, not wrapped in a callable (PT-29's escaped gap)", () => {
  const wrapped = wrapForRealm(loadFixture());
  assert.equal(typeof wrapped.dataArray, "object", "must stay a value, not become a Function");
  assert.deepStrictEqual(wrapped.dataArray, ["x", "y", "z"]);
  assert.equal(Array.isArray(wrapped.dataArray), true);
  assert.equal(wrapped.dataArray instanceof Array, true, "instanceof is the half that fails for a foreign-realm array");
});

// ---- 3. PT-30's gap: null-prototype data export ----

test("wrapForRealm: a null-prototype DATA export keeps its null prototype (PT-30's escaped gap)", () => {
  const wrapped = wrapForRealm(loadFixture());
  // NOT `assert.deepStrictEqual(wrapped.nullProtoData, { k1: "v1", k2: "v2" })`
  // -- a bare `{...}` literal's prototype is THIS file's Object.prototype,
  // so deepStrictEqual would fail on the prototype mismatch even though
  // rehome did exactly the right thing (that failure mode was caught
  // writing this test: see helpers.js's comment on the same subtlety).
  // Compare structure and null-ness as two separate, precise assertions.
  assert.deepStrictEqual(Object.keys(wrapped.nullProtoData).sort(), ["k1", "k2"]);
  assert.equal(wrapped.nullProtoData.k1, "v1");
  assert.equal(wrapped.nullProtoData.k2, "v2");
  assert.equal(Object.getPrototypeOf(wrapped.nullProtoData), null, "a JSON round-trip would have restored Object.prototype here -- this is PT-30's exact bug");
});

// ---- 4. recursion: nested mix ----

test("rehome: recurses through a nested mix -- array of objects, object containing an array, null-proto nested inside a normal object", () => {
  const wrapped = wrapForRealm(loadFixture());
  const result = wrapped.nestedMixFn();

  assert.deepStrictEqual(result.arrayOfObjects, [{ id: 1 }, { id: 2 }]);
  assert.equal(Array.isArray(result.arrayOfObjects), true);
  assert.equal(result.arrayOfObjects instanceof Array, true);
  result.arrayOfObjects.forEach((entry) => {
    assert.equal(Object.getPrototypeOf(entry), Object.prototype, "each object INSIDE the array must also be rehomed, not just the array itself");
  });

  assert.deepStrictEqual(result.objectWithArray, { list: [1, 2, 3] });
  assert.equal(Array.isArray(result.objectWithArray.list), true);
  assert.equal(result.objectWithArray.list instanceof Array, true, "an array NESTED inside an object must also pass the instanceof half");

  // Same prototype-mismatch subtlety as the top-level null-proto test above
  // -- compare structure/values and null-ness separately, not via
  // deepStrictEqual against a bare (Object.prototype) literal.
  assert.deepStrictEqual(Object.keys(result.nullProtoNested), ["deep"]);
  assert.equal(result.nullProtoNested.deep, "value");
  assert.equal(Object.getPrototypeOf(result.nullProtoNested), null, "a null-proto object NESTED inside a normal one must keep its null prototype at that nesting level");
  assert.equal(Object.getPrototypeOf(result), Object.prototype, "the OUTER object itself is a normal (non-null-proto) object");
});

// ---- 5. non-object short-circuit ----

test("rehome: a primitive return value passes through unchanged, not wrapped or copied", () => {
  const wrapped = wrapForRealm(loadFixture());
  assert.equal(wrapped.primitiveFn(), 42);
});

test("rehome: null passes through unchanged", () => {
  const wrapped = wrapForRealm(loadFixture());
  assert.equal(wrapped.nullFn(), null);
});

test("rehome: undefined passes through unchanged", () => {
  const wrapped = wrapForRealm(loadFixture());
  assert.equal(wrapped.undefinedFn(), undefined);
});

// ---- 6. non-object data exports ----

test("wrapForRealm: a string DATA export passes through untouched", () => {
  const wrapped = wrapForRealm(loadFixture());
  assert.equal(wrapped.stringData, "hello");
});

test("wrapForRealm: a number DATA export passes through untouched", () => {
  const wrapped = wrapForRealm(loadFixture());
  assert.equal(wrapped.numberData, 7);
});

// ---- 7. prototype-collision class ----

test("rehome: an object with OWN keys named constructor/__proto__ survives intact -- the prototype-collision class this codebase keeps meeting", () => {
  const wrapped = wrapForRealm(loadFixture());
  const result = wrapped.collisionObjFn();

  assert.equal(
    Object.prototype.hasOwnProperty.call(result, "constructor"),
    true,
    "the OWN 'constructor' key must survive as a real property, not be masked by the inherited Object.prototype.constructor function"
  );
  assert.equal(result.constructor, "not-the-real-constructor");

  assert.equal(
    Object.prototype.hasOwnProperty.call(result, "__proto__"),
    true,
    "the OWN '__proto__' key must survive as a real property -- Object.keys/hasOwnProperty must see it as data, not have it silently reassign the object's actual prototype"
  );
  assert.equal(result["__proto__"], "also-just-a-string-value");

  // And the object's ACTUAL prototype must be unaffected by any of this --
  // rehome always builds its copy via `{}`/`Object.create(null)`, never by
  // interpreting a source object's own "__proto__" key as a real
  // prototype assignment.
  assert.equal(Object.getPrototypeOf(result), Object.prototype);
});

// ---- rehome() called directly (not just through wrapForRealm) ----

test("rehome: called directly on a foreign-realm value (not routed through wrapForRealm) produces the same same-realm result", () => {
  const fixture = loadFixture();
  const foreignArray = fixture.dataArray;
  const result = rehome(foreignArray);
  assert.deepStrictEqual(result, ["x", "y", "z"]);
  assert.equal(Array.isArray(result), true);
  assert.equal(result instanceof Array, true);
});
