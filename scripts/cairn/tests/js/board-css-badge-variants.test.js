"use strict";

// PT-57 (architect's token-delivery ruling, 4785853): the chip/status/dot
// re-expression, pinned structurally -- board.css's rule DECLARATIONS
// must reference the ruled preset tokens (var(--x)), not a hardcoded
// color and not just "some token or other". Same "extracted rule, not
// whole-file text" discipline as every other CSS guard in this suite
// (board-css-token-migration.test.js's --accent guard, embed-visibility-
// scope.test.js's hidden-selector extraction): comments in this exact
// area of board.css quote the ruling's own vocabulary ("outline",
// "secondary", "--muted-foreground"), so a naive substring search would
// be unusually prone to matching prose instead of code.
//
// Deliberately STRUCTURAL/BEHAVIORAL, not visual (team-lead's framing):
// asserts which CSS custom property a rule references, never a resolved
// color or a corner radius -- the visual half (does it actually look
// right) is the browser pass's job. selectors/`opacity`/`font-style` on
// the archived/repo chips are asserted because the ruling explicitly says
// those must NOT migrate (structure preserved), not because they're
// visual.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_CSS_PATH = path.join(__dirname, "..", "..", "board", "board.css");

class ExtractionError extends Error {}

function readBoardCss() {
  return fs.readFileSync(BOARD_CSS_PATH, "utf8");
}

function stripCssComments(cssSource) {
  return cssSource.replace(/\/\*[\s\S]*?\*\//g, "");
}

// The declaration-block text of the rule whose selector list contains
// EXACTLY `selector` (trimmed, comma-split) -- not a substring match
// against the raw selector text, so `.chip` doesn't accidentally match
// `.chip.blocked`. Comments stripped first. Raises loudly (never returns
// undefined/empty for a caller to silently treat as "no declarations",
// which could pass a should-fail assertion for the wrong reason) if the
// selector isn't found in ANY rule's selector list.
function findRuleDeclarations(cssSource, selector) {
  const stripped = stripCssComments(cssSource);
  const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
  let ruleMatch;
  while ((ruleMatch = ruleRe.exec(stripped))) {
    const selectors = ruleMatch[1].split(",").map((s) => s.trim());
    if (selectors.includes(selector)) {
      return ruleMatch[2].trim();
    }
  }
  throw new ExtractionError(
    `could not find a rule with "${selector}" in its selector list -- if this selector was ` +
      `renamed or restructured, this guard needs to be updated, not silenced.`
  );
}

function assertDeclarationsReference(declarations, expectedVars, label) {
  for (const v of expectedVars) {
    assert.match(
      declarations, new RegExp("var\\(\\s*" + v.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&")),
      `${label}: expected declarations to reference ${v}, got: ${declarations}`
    );
  }
}

const css = readBoardCss();

// ---------------------------------------------------------------------------
// Chips
// ---------------------------------------------------------------------------

test("PT-57: base .chip is the outline variant (transparent, --border, --muted-foreground)", () => {
  const decl = findRuleDeclarations(css, ".chip");
  assert.match(decl, /background:\s*transparent/);
  assertDeclarationsReference(decl, ["--border", "--muted-foreground"], ".chip");
});

test("PT-57: .chip.assignee/.chip.release are the secondary variant", () => {
  // findRuleDeclarations splits a rule's selector LIST and matches any
  // one member -- search on a single selector, not the joined
  // ".a, .b" string (which wouldn't equal either split, trimmed member).
  const decl = findRuleDeclarations(css, ".chip.assignee");
  assertDeclarationsReference(decl, ["--secondary", "--secondary-foreground"], ".chip.assignee");
  assert.equal(
    decl, findRuleDeclarations(css, ".chip.release"),
    ".chip.assignee and .chip.release must still share the SAME rule (same declarations), not drift apart"
  );
});

test("PT-57: .chip.blocked is the destructive variant", () => {
  const decl = findRuleDeclarations(css, ".chip.blocked");
  assertDeclarationsReference(decl, ["--destructive", "--destructive-foreground"], ".chip.blocked");
});

test("PT-57: .chip.ga is the default/primary variant, weight preserved", () => {
  const decl = findRuleDeclarations(css, ".chip.ga");
  assertDeclarationsReference(decl, ["--primary", "--primary-foreground"], ".chip.ga");
  assert.match(decl, /font-weight:\s*600/, ".chip.ga must keep font-weight: 600 (ruling: GA should dominate)");
});

test("PT-57 (must NOT migrate): .chip.archived keeps italic + opacity 0.6, no token override", () => {
  const decl = findRuleDeclarations(css, ".chip.archived");
  assert.match(decl, /font-style:\s*italic/);
  assert.match(decl, /opacity:\s*0\.6/);
});

test("PT-57/PT-63: .chip.repo keeps its monospace font-family (the label distinction, not a hue)", () => {
  // PT-57's own text: "family is a label distinction, not a hue" -- what
  // must survive is the MONOSPACE DISTINCTION, not any particular literal
  // stack. PT-63 (pre-decided, no ruling gate) replaced every hardcoded
  // `ui-monospace, SFMono-Regular, Menlo, monospace` stack in board.css --
  // including this one -- with `var(--font-mono)` (the vendored Geist
  // Mono Variable face). This is the anticipated evolution PT-57's own
  // "must NOT migrate" list didn't foresee (it predates PT-63 entirely),
  // not a violation of the constraint: the distinction this test guards
  // is intact, just delivered through the token now.
  const decl = findRuleDeclarations(css, ".chip.repo");
  assert.match(decl, /font-family:\s*var\(--font-mono\)/);
});

// ---------------------------------------------------------------------------
// Record status chips -- .chip.status[data-status="..."]
// ---------------------------------------------------------------------------

test("PT-57: .chip.status in-progress is --primary/--primary-foreground", () => {
  const decl = findRuleDeclarations(css, '.chip.status[data-status="in-progress"]');
  assertDeclarationsReference(decl, ["--primary", "--primary-foreground"], "status in-progress");
});

// PT-69 (architect's ruling 1db6053 + ux-designer's replacement): moved
// OFF --chart-2 -- a status chip's legibility can't depend on the user's
// (now user-selectable) Chart Color choice. --accent/--accent-foreground
// is Base-Color-owned, inverts correctly per mode. .major-status-dot's own
// paused fill (below) is a deliberate exception -- a non-text graphical
// object that's supposed to track Chart Color, not repointed.
test("PT-69: .chip.status paused is --accent fill / --accent-foreground text", () => {
  const decl = findRuleDeclarations(css, '.chip.status[data-status="paused"]');
  assertDeclarationsReference(decl, ["--accent", "--accent-foreground"], "status paused");
});

test("PT-57: .chip.status done is inverted (--foreground fill / --background text)", () => {
  const decl = findRuleDeclarations(css, '.chip.status[data-status="done"]');
  assertDeclarationsReference(decl, ["--foreground", "--background"], "status done");
});

test("PT-57: .chip.status cancelled is --destructive/--destructive-foreground", () => {
  const decl = findRuleDeclarations(css, '.chip.status[data-status="cancelled"]');
  assertDeclarationsReference(decl, ["--destructive", "--destructive-foreground"], "status cancelled");
});

test("PT-57: .chip.status planned has NO override rule -- it inherits the base outline chip", () => {
  // The ruling's table explicitly says planned "stays the base outline
  // chip (no override needed)" -- a rule existing here at all would be
  // the opposite of what was ruled, so this asserts ABSENCE.
  assert.throws(
    () => findRuleDeclarations(css, '.chip.status[data-status="planned"]'),
    ExtractionError,
    "a .chip.status[data-status=\"planned\"] override rule exists, but the ruling says planned " +
      "should inherit the base .chip (outline) styling with no override"
  );
});

// ---------------------------------------------------------------------------
// Major status dot -- .major-status-dot[data-status="..."]
// ---------------------------------------------------------------------------

test("PT-57: default/unknown .major-status-dot is --muted-foreground, distinct from planned's --ring", () => {
  const decl = findRuleDeclarations(css, ".major-status-dot");
  assertDeclarationsReference(decl, ["--muted-foreground"], ".major-status-dot (default)");
});

test("PT-57: .major-status-dot planned is --ring (not the same token as the default/unknown case)", () => {
  const decl = findRuleDeclarations(css, '.major-status-dot[data-status="planned"]');
  assertDeclarationsReference(decl, ["--ring"], "dot planned");
});

test("PT-57: .major-status-dot in-progress/paused/done/cancelled match the chip table's fill tokens", () => {
  assertDeclarationsReference(findRuleDeclarations(css, '.major-status-dot[data-status="in-progress"]'), ["--primary"], "dot in-progress");
  assertDeclarationsReference(findRuleDeclarations(css, '.major-status-dot[data-status="paused"]'), ["--chart-2"], "dot paused");
  assertDeclarationsReference(findRuleDeclarations(css, '.major-status-dot[data-status="done"]'), ["--foreground"], "dot done");
  assertDeclarationsReference(findRuleDeclarations(css, '.major-status-dot[data-status="cancelled"]'), ["--destructive"], "dot cancelled");
});

// ---------------------------------------------------------------------------
// Liveness indicator -- no green in this preset
// ---------------------------------------------------------------------------

test("PT-57: .connection-state.live maps to --primary (the preset has no green)", () => {
  const decl = findRuleDeclarations(css, ".connection-state.live");
  assertDeclarationsReference(decl, ["--primary"], ".connection-state.live");
});

// ---------------------------------------------------------------------------
// Extractor self-tests
// ---------------------------------------------------------------------------

test("negative control: findRuleDeclarations raises loudly for a selector that doesn't exist", () => {
  assert.throws(() => findRuleDeclarations(css, ".this-selector-does-not-exist-anywhere"), ExtractionError);
});

test("negative control: a comment mentioning a selector is not mistaken for the real rule", () => {
  const fakeCss = "/* .foo { background: var(--wrong); } */\n.foo { background: var(--right); }";
  const decl = findRuleDeclarations(fakeCss, ".foo");
  assert.match(decl, /--right/);
  assert.doesNotMatch(decl, /--wrong/);
});

test("negative control: .chip does not accidentally match .chip.blocked's declarations", () => {
  const fakeCss = ".chip { color: var(--muted-foreground); } .chip.blocked { color: var(--destructive); }";
  const decl = findRuleDeclarations(fakeCss, ".chip");
  assert.match(decl, /--muted-foreground/);
  assert.doesNotMatch(decl, /--destructive/);
});
