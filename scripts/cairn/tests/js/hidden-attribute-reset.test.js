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
//
// Architect's post-691e7ae review (2026-09-03): the checks above confirm
// A conforming bare `[hidden]` rule exists, but not that it's the ONLY
// one, and nothing constrained competing `!important` display
// declarations elsewhere in the file. Two filter-evasion constructions
// passed the original 11/11 while restoring the shipped bug in the
// browser -- both are same-origin, same-specificity `!important`-vs-
// `!important` ties, decided by source order, i.e. exactly the failure
// mode `!important` was supposed to make impossible:
//   (a) appending a SECOND bare `[hidden] { display: flex !important; }`
//       rule anywhere in the file -- every hidden element re-renders.
//   (b) appending `.new-issue-form { display: flex !important; }` (or
//       any other selector) -- recreates PT-76's original bug verbatim.
// Two more assertions close this, using the same eachRule/
// stripCssComments machinery:
//   5. EVERY bare `[hidden]` rule (not just the first found) declares
//      `display: none !important` -- catches (a).
//   6. NO rule other than the generic `[hidden]` reset declares `display`
//      with `!important` anywhere in the file -- pins the file's
//      `!important`-on-`display` budget at exactly one, and that one
//      rule's selector list must be exactly `[hidden]` alone. Catches (b).

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

// (4) Every rule (not just the first) whose selector list contains the
// bare `[hidden]` token -- closes evasion (a): a second `[hidden]` rule
// with a competing `!important` declaration appended anywhere in the
// file would be invisible to extractGenericHiddenRuleDeclarations's
// "stop at first match" behaviour, but not to this.
function extractAllBareHiddenRuleDeclarations(cssSource) {
  var source = stripCssComments(cssSource);
  var found = [];
  eachRule(source, function (selectorList, declarations) {
    var selectors = selectorList.split(",").map(function (s) {
      return s.trim();
    });
    if (selectors.indexOf("[hidden]") !== -1) {
      found.push(declarations);
    }
  });
  if (found.length === 0) {
    throw new ExtractionError(
      "could not find any rule with a bare `[hidden]` selector anywhere in board.css -- " +
        "if the generic hidden-attribute reset was renamed or removed, this guard needs " +
        "to be updated, not silenced."
    );
  }
  return found;
}

// (5) Every rule anywhere in the file whose declarations set `display`
// with `!important` -- regardless of selector or value. Returns each
// such rule's trimmed, comma-split selector list. Closes evasion (b): a
// rule on a DIFFERENT selector (e.g. `.new-issue-form`) with its own
// `display: ... !important` recreates the original same-origin,
// same-specificity, source-order-decided tie PT-76 exists to kill --
// `!important` is only a fix while it stays a monopoly.
function extractImportantDisplayRules(cssSource) {
  var source = stripCssComments(cssSource);
  var found = [];
  eachRule(source, function (selectorList, declarations) {
    if (/display\s*:\s*[^;]*!important/.test(declarations)) {
      found.push(
        selectorList.split(",").map(function (s) {
          return s.trim();
        })
      );
    }
  });
  if (found.length === 0) {
    throw new ExtractionError(
      "could not find any rule anywhere in board.css that sets `display` with `!important` -- " +
        "if the generic hidden-attribute reset's !important was dropped, this guard needs to " +
        "be updated, not silenced."
    );
  }
  return found;
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

test("PT-76: EVERY bare [hidden] rule declares display:none !important, not just the first found", () => {
  var cssSource = readBoardCss();
  var allDeclarations = extractAllBareHiddenRuleDeclarations(cssSource);
  allDeclarations.forEach(function (declarations, i) {
    assert.match(
      declarations,
      /display\s*:\s*none\s*!important/,
      "bare `[hidden]` rule #" + i + " does not declare `display: none !important` -- got " +
        JSON.stringify(declarations) + ". A second [hidden] rule with a competing " +
        "!important declaration would re-render every hidden element (same-origin, " +
        "same-specificity, source-order-decided tie -- architect's post-691e7ae review)"
    );
  });
});

test("PT-76: no rule other than the generic [hidden] reset declares display with !important", () => {
  var cssSource = readBoardCss();
  var importantRules = extractImportantDisplayRules(cssSource);
  assert.equal(
    importantRules.length,
    1,
    "expected exactly ONE rule in board.css to declare `display` with `!important` -- found " +
      importantRules.length + ": " + JSON.stringify(importantRules) + ". Any other rule " +
      "with `display: ... !important` recreates PT-76's original bug against that selector " +
      "(!important-vs-!important is decided by source order, same as the un-important case " +
      "PT-76 was filed to fix)"
  );
  assert.deepEqual(
    importantRules[0],
    ["[hidden]"],
    "the one `!important`-on-`display` rule in board.css must be the bare `[hidden]` " +
      "selector alone -- got " + JSON.stringify(importantRules[0])
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

test("negative control: extractAllBareHiddenRuleDeclarations returns EVERY bare [hidden] rule, not just the first", () => {
  var fakeCss = "[hidden] { display: none !important; }\n[hidden] { display: flex !important; }\n";
  var all = extractAllBareHiddenRuleDeclarations(fakeCss);
  assert.equal(all.length, 2);
  assert.match(all[0], /none/);
  assert.match(all[1], /flex/);
});

test("negative control: extractAllBareHiddenRuleDeclarations throws ExtractionError when no bare [hidden] rule exists", () => {
  var fakeCss = ".foo[hidden] { display: none; }\n";
  assert.throws(() => extractAllBareHiddenRuleDeclarations(fakeCss), ExtractionError);
});

test("regression guard: evasion (a) -- a second [hidden] rule with a competing !important is caught by the ALL-rules check", () => {
  // Reproduces the architect's exact filter-evasion construction: appending
  // `[hidden] { display: flex !important; }` anywhere in the file. The
  // single-rule extractor (extractGenericHiddenRuleDeclarations) would
  // still see only the FIRST bare [hidden] rule and stay green; the
  // all-rules extractor must not.
  var fakeCss = "[hidden] { display: none !important; }\n[hidden] { display: flex !important; }\n";
  var all = extractAllBareHiddenRuleDeclarations(fakeCss);
  var offender = all.find(function (d) {
    return !/display\s*:\s*none\s*!important/.test(d);
  });
  assert.ok(offender, "the evasion construction must produce at least one bare [hidden] rule whose declarations are NOT display:none!important");
});

test("negative control: extractImportantDisplayRules returns every rule with display:!important, and the exact selector list for each", () => {
  var fakeCss =
    "[hidden] { display: none !important; }\n" +
    ".new-issue-form { display: flex !important; }\n" +
    ".unrelated { color: red !important; }\n";
  var found = extractImportantDisplayRules(fakeCss);
  assert.deepEqual(found, [["[hidden]"], [".new-issue-form"]], ".unrelated's color:!important must not be counted -- only display matters");
});

test("negative control: extractImportantDisplayRules throws ExtractionError when nothing declares display with !important", () => {
  var fakeCss = "[hidden] { display: none; }\n.foo { color: red !important; }\n";
  assert.throws(() => extractImportantDisplayRules(fakeCss), ExtractionError);
});

test("regression guard: evasion (b) -- a competing !important display on ANY other selector is caught by the budget check", () => {
  // Reproduces the architect's second filter-evasion construction:
  // appending `.new-issue-form { display: flex !important; }`. This is
  // PT-76's original bug recreated verbatim (author-origin !important vs
  // author-origin !important, decided by source order).
  var fakeCss =
    "[hidden] { display: none !important; }\n" +
    ".new-issue-form { display: flex !important; }\n";
  var found = extractImportantDisplayRules(fakeCss);
  assert.equal(found.length, 2, "the evasion construction must produce a SECOND !important-on-display rule");
  assert.notDeepEqual(
    found,
    [["[hidden]"]],
    "the budget check (found.length === 1 && found[0] deepEqual ['[hidden]']) must fail against this fixture"
  );
});
