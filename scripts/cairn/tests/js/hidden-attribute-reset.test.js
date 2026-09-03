"use strict";

// PT-76 (architect's ruling, 2026-09-03, "one generic reset, retiring the
// per-element fixes"): the automated leg of the `[hidden]` cascade-origin
// fix, in the same shape as embed-visibility-scope.test.js (PT-55) --
// source-text guards over board.css, because this suite has no jsdom and
// no `document` (confirmed against 8+ existing test files that already
// document the same limit; see embed-visibility-scope.test.js lines 3-9).
// The browser leg -- getComputedStyle + getBoundingClientRect +
// elementFromPoint across all three placements -- is the load-bearing
// acceptance check (PT-76's own acceptance criteria say so explicitly);
// this file proves only what source text CAN prove:
//
//   1. board.css declares a generic `[hidden]` rule (selector EXACTLY
//      `[hidden]`, not `X[hidden]`) whose `display` is `none` AND carries
//      `!important` -- the architect's ruling is explicit that dropping
//      `!important` silently reintroduces the bug for any future
//      id-based `display` rule (author-origin beats UA-origin regardless
//      of specificity or source order; only `!important` is both origin-
//      and specificity-independent).
//   2. The body.readonly hide-list selector set (board.css ~181-187) is
//      extracted independently and asserted to contain BOTH
//      #new-issue-form and #new-issue-btn -- PT-76's ruling (b): the
//      read-only surface carries no create affordance, and the policy
//      list must say so even though the generic [hidden] rule makes it
//      redundant while the attribute happens to be set.
//   3. No element-specific `X[hidden] { display: none }` rule remains --
//      their return would mean the generic rule was lost and the
//      per-element band-aids crept back (PT-69's two rules,
//      `.theme-settings-menu[hidden]` and `.theme-settings-row-flyout[hidden]`,
//      are the ones this ruling retires).
//   4. Every extractor below raises a named ExtractionError when its
//      pattern matches nothing -- never a silent empty list, never a
//      vacuously-green pass. Same contract as PT-36 / PT-45 / PT-55.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_CSS_PATH = path.join(__dirname, "..", "..", "board", "board.css");

class ExtractionError extends Error {}

// Same comment-stripping principle as embed-visibility-scope.test.js's
// stripCssComments (PT-55's diff-review catch): a comment mentioning
// `[hidden]` or `body.readonly #new-issue-form` in prose must never be
// read as a real rule. This file's own PT-69 comment block above
// `.theme-settings-menu[hidden]` is exactly that hazard -- it says
// "the `hidden` attribute" in prose right next to real rules.
function stripCssComments(cssSource) {
  return cssSource.replace(/\/\*[\s\S]*?\*\//g, "");
}

function readBoardCss() {
  return fs.readFileSync(BOARD_CSS_PATH, "utf8");
}

// Walks every top-level `selectorList { declarations }` rule in the
// (comment-stripped) source. Does not attempt to handle nested at-rules
// (@media etc.) -- board.css has none wrapping these rules today, and if
// that changes this extractor's blind spot should be revisited, not
// silently trusted.
function eachRule(cssSource, callback) {
  var ruleRe = /([^{}]+)\{([^{}]*)\}/g;
  var match;
  while ((match = ruleRe.exec(cssSource))) {
    callback(match[1], match[2]);
  }
}

// (1) The generic `[hidden]` reset. Selector list is split on commas and
// each piece trimmed -- the match requires one of those pieces to be the
// BARE token `[hidden]`, not `.foo[hidden]` or `[hidden].bar`, so this
// extractor cannot be fooled by a per-element rule that merely contains
// the substring "[hidden]".
function extractGenericHiddenRuleDeclarations(cssSource) {
  var source = stripCssComments(cssSource);
  var found = null;
  eachRule(source, function (selectorList, declarations) {
    if (found) return;
    var selectors = selectorList.split(",").map(function (s) {
      return s.trim();
    });
    if (selectors.indexOf("[hidden]") !== -1) {
      found = declarations;
    }
  });
  if (found === null) {
    throw new ExtractionError(
      "could not find a rule with a bare `[hidden]` selector anywhere in board.css -- " +
        "if the generic hidden-attribute reset was renamed or removed, this guard needs " +
        "to be updated, not silenced."
    );
  }
  return found;
}

// (2) Every element-specific `X[hidden]` rule -- i.e. a selector token
// that ends in `[hidden]` but is NOT the bare `[hidden]` token itself
// (compound selectors like `.foo.bar[hidden]` or descendant selectors
// like `.foo [hidden]` both count as "element-specific": the point is
// that a *different* selector was chosen instead of relying on the one
// generic reset).
function extractElementSpecificHiddenSelectors(cssSource) {
  var source = stripCssComments(cssSource);
  var offenders = [];
  eachRule(source, function (selectorList) {
    var selectors = selectorList.split(",").map(function (s) {
      return s.trim();
    });
    selectors.forEach(function (sel) {
      if (sel.length && sel !== "[hidden]" && /\[hidden\]$/.test(sel)) {
        offenders.push(sel);
      }
    });
  });
  return offenders;
}

// (3) The body.readonly hide-list. Finds the rule whose ENTIRE selector
// list is made of `body.readonly <something>` pieces (so this can't be
// fooled by an unrelated rule that merely mentions body.readonly once
// among other selectors) and whose declarations hide the element.
// Returns the bare selector for each piece (the part after
// "body.readonly ").
function extractReadonlyHiddenSelectors(cssSource) {
  var source = stripCssComments(cssSource);
  var found = null;
  eachRule(source, function (selectorList, declarations) {
    if (found) return;
    var pieces = selectorList.split(",").map(function (s) {
      return s.trim();
    });
    if (pieces.length === 0) return;
    var allReadonly = pieces.every(function (p) {
      return /^body\.readonly\s+\S/.test(p);
    });
    if (!allReadonly) return;
    if (!/display\s*:\s*none/.test(declarations)) return;
    found = pieces.map(function (p) {
      return p.replace(/^body\.readonly\s+/, "");
    });
  });
  if (found === null) {
    throw new ExtractionError(
      "could not find a rule whose selector list is entirely `body.readonly <selector>` " +
        "pieces hiding via `display: none` in board.css -- if the read-only hide-list was " +
        "renamed, restructured, or removed, this guard needs to be updated, not silenced."
    );
  }
  return new Set(found);
}

test("PT-76: board.css declares a generic [hidden] rule with display:none and !important", () => {
  var cssSource = readBoardCss();
  var declarations = extractGenericHiddenRuleDeclarations(cssSource);
  assert.match(
    declarations,
    /display\s*:\s*none\s*!important/,
    "the bare `[hidden]` rule must set `display: none !important` -- author-origin " +
      "declarations unconditionally outrank UA-origin declarations regardless of " +
      "specificity or source order, so only !important is both origin- and " +
      "specificity-independent (architect's PT-76 cascade-origin correction to PT-69's " +
      "specificity-tie model)"
  );
});

test("PT-76: the body.readonly hide list contains both #new-issue-form and #new-issue-btn", () => {
  var cssSource = readBoardCss();
  var hidden = extractReadonlyHiddenSelectors(cssSource);
  assert.ok(
    hidden.has("#new-issue-btn"),
    "expected #new-issue-btn in the body.readonly hide list -- got " +
      JSON.stringify(Array.from(hidden).sort())
  );
  assert.ok(
    hidden.has("#new-issue-form"),
    "expected #new-issue-form in the body.readonly hide list -- the read-only surface " +
      "must carry no create affordance even though the generic [hidden] rule makes this " +
      "redundant while the hidden attribute happens to be set (architect's PT-76 ruling (b): " +
      "the read-only rule is the POLICY statement and must hold on its own) -- got " +
      JSON.stringify(Array.from(hidden).sort())
  );
});

test("PT-76: no element-specific X[hidden] rule remains -- the generic reset subsumes them", () => {
  var cssSource = readBoardCss();
  var offenders = extractElementSpecificHiddenSelectors(cssSource);
  assert.deepEqual(
    offenders,
    [],
    "found element-specific [hidden] rule(s) that should have been retired in favour of " +
      "the single generic `[hidden]` reset: " + JSON.stringify(offenders) + " -- their " +
      "return signals the generic rule was lost or a per-element band-aid crept back in " +
      "(PT-69's .theme-settings-menu[hidden] and .theme-settings-row-flyout[hidden] are " +
      "exactly the two this ruling retires)"
  );
});

test("negative control: extractGenericHiddenRuleDeclarations matches a bare [hidden] rule and ignores a compound one", () => {
  var fakeCss = ".foo[hidden] { display: none; }\n[hidden] { display: none !important; }\n";
  var declarations = extractGenericHiddenRuleDeclarations(fakeCss);
  assert.match(declarations, /!important/);
});

test("negative control: extractGenericHiddenRuleDeclarations throws ExtractionError when no bare [hidden] rule exists", () => {
  var fakeCss = ".foo[hidden] { display: none; }\n.bar { color: red; }\n";
  assert.throws(() => extractGenericHiddenRuleDeclarations(fakeCss), ExtractionError);
});

test("negative control: extractElementSpecificHiddenSelectors finds compound [hidden] selectors and ignores the bare one", () => {
  var fakeCss =
    "[hidden] { display: none !important; }\n" +
    ".theme-settings-menu[hidden] { display: none; }\n" +
    ".foo .theme-settings-row-flyout[hidden] { display: none; }\n";
  var offenders = extractElementSpecificHiddenSelectors(fakeCss);
  assert.deepEqual(offenders.sort(), [
    ".foo .theme-settings-row-flyout[hidden]",
    ".theme-settings-menu[hidden]",
  ]);
});

test("negative control: extractElementSpecificHiddenSelectors returns empty when only the bare rule exists", () => {
  var fakeCss = "[hidden] { display: none !important; }\n";
  assert.deepEqual(extractElementSpecificHiddenSelectors(fakeCss), []);
});

test("negative control: extractReadonlyHiddenSelectors matches a body.readonly hide-list and returns bare selectors", () => {
  var fakeCss =
    "body.readonly .filters,\nbody.readonly #new-issue-btn,\nbody.readonly #new-issue-form {\n  display: none;\n}\n";
  var hidden = extractReadonlyHiddenSelectors(fakeCss);
  assert.deepEqual(Array.from(hidden).sort(), [".filters", "#new-issue-btn", "#new-issue-form"].sort());
});

test("negative control: extractReadonlyHiddenSelectors ignores a rule that only PARTLY mentions body.readonly", () => {
  var fakeCss = "body.readonly .filters, .always-visible {\n  display: none;\n}\n";
  assert.throws(() => extractReadonlyHiddenSelectors(fakeCss), ExtractionError);
});

test("negative control: extractReadonlyHiddenSelectors throws ExtractionError when no body.readonly hide rule exists", () => {
  var fakeCss = ".foo { color: red; }\n";
  assert.throws(() => extractReadonlyHiddenSelectors(fakeCss), ExtractionError);
});

test("regression guard: a comment mentioning '[hidden]' or 'body.readonly #new-issue-form' in prose must NOT be read as a real rule", () => {
  var fakeCss =
    "/* note: the [hidden] attribute and body.readonly #new-issue-form policy are related */\n" +
    ".foo { color: red; }\n";
  assert.throws(() => extractGenericHiddenRuleDeclarations(fakeCss), ExtractionError);
  assert.throws(() => extractReadonlyHiddenSelectors(fakeCss), ExtractionError);
  assert.deepEqual(extractElementSpecificHiddenSelectors(fakeCss), []);
});
