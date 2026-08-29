"use strict";

// PT-57 (Board: migrate board.css to preset tokens) -- the first test here
// was written before the architect's token-delivery ruling landed
// (committed 4785853: a new scripts/cairn/board/tokens.css, linked from
// board.html, colors+radius only). The legacy-hex guard held regardless
// of the ruling's outcome, per PT-55/PT-56's own pending-ruling-test
// posture.
//
// The second test (--accent collision) is the ruling's own explicit ask:
// board.css uses --accent as its PRIMARY BLUE (#0052cc historically), but
// the preset's --accent is a near-white hover/active surface. Once
// tokens.css is linked, every remaining `var(--accent)` call site that
// meant "primary blue" silently repaints near-white-on-white -- a bug the
// referenced-variable-closure guard (test_board_tokens_parity.py) CANNOT
// catch, because --accent still resolves to a real, defined value; it's
// just the WRONG one. The ruling names exactly one legitimate remaining
// use: table.issue-list tr:hover (the preset's hover-surface role really
// is what --accent means now).
//
// NOT covered here (deliberately, pending further migration work): the
// badge-variant re-expression of the chip taxonomy, and the regression
// pass ("board remains functional in both views + drawer") -- both
// depend on shapes/state the migration hasn't finished yet.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_CSS_PATH = path.join(__dirname, "..", "..", "board", "board.css");

// design-system-spec.md's Legacy/migration table, verbatim -- the exact
// hex values board.css must stop hardcoding. Matched case-insensitively;
// word-boundary-anchored (via a leading non-hex-digit lookbehind-free
// regex) so e.g. "#0052CC" doesn't accidentally get flagged as containing
// some OTHER, unrelated 6-digit hex that merely shares a substring --
// each of these seven is checked as its own complete token.
const LEGACY_HEXES = [
  "#F4F5F7", // page bg
  "#FFFFFF", // card/panel bg
  "#0052CC", // accent/primary
  "#DE350B", // danger/banner
  "#172B4D", // default text
  "#5E6C84", // subtle text
  "#DFE1E6", // border
];

function readBoardCss() {
  return fs.readFileSync(BOARD_CSS_PATH, "utf8");
}

function stripCssComments(cssSource) {
  return cssSource.replace(/\/\*[\s\S]*?\*\//g, "");
}

function findLegacyHexes(cssSource) {
  // Comments stripped first (hardening, added after a real near-miss:
  // implementation-lead's own PT-57 fix commit added a comment that
  // quotes "rgb(9, 30, 66)" in prose to EXPLAIN the fix -- a future
  // comment quoting one of these seven hexes the same way would have
  // false-positived against the un-hardened version of this check).
  const upper = stripCssComments(cssSource).toUpperCase();
  return LEGACY_HEXES.filter((hex) => {
    // Whole-token match: not preceded/followed by a hex digit, so a
    // legitimate DIFFERENT color that happens to end in the same six
    // characters (extremely unlikely for 6-hex-digit codes, but the
    // discipline costs nothing) isn't miscounted.
    const re = new RegExp("(?<![0-9A-F])" + hex.slice(1) + "(?![0-9A-F])", "i");
    return re.test(upper);
  });
}

// Architect's addendum (2026-08-27, after the main ruling): the
// Atlassian navy tint, rgb(9, 30, 66), hid inside THREE rgba() literals
// (--shadow, .drawer-overlay's scrim, .drawer's box-shadow) -- invisible
// to a bare "#" grep, and a hue the preset-pure direction forbids as
// much as any hex. implementation-lead fixed all three (07a0557); this
// guard exists so a regression (or a future rgba() literal that
// re-introduces the same tint) fails loudly.
// R,G,B components, matched with flexible whitespace so both "9, 30, 66"
// and "9,30,66" are caught.
const LEGACY_RGB_COMPONENTS = [9, 30, 66]; // Atlassian N800, the pre-migration --shadow/scrim tint

function findLegacyRgbTint(cssSource) {
  const stripped = stripCssComments(cssSource);
  const re = new RegExp(LEGACY_RGB_COMPONENTS.join("\\s*,\\s*"));
  return re.test(stripped);
}

test("PT-57: board.css no longer hardcodes any of design-system-spec.md's seven named legacy hex values", () => {
  const found = findLegacyHexes(readBoardCss());
  assert.deepEqual(
    found, [],
    `board.css still hardcodes legacy hex value(s) ${JSON.stringify(found)} -- per docs/DESIGN/` +
      `design-system-spec.md's Legacy/migration table, these must be replaced by the corresponding ` +
      `preset token (see that table for the old-hex -> new-token mapping)`
  );
});

test("negative control: the extractor actually catches a legacy hex when present (sanity)", () => {
  const found = findLegacyHexes(":root { --bg: #F4F5F7; }");
  assert.deepEqual(found, ["#F4F5F7"]);
});

test("negative control: a different, unrelated hex is not miscounted as a legacy one", () => {
  const found = findLegacyHexes(":root { --something: #123456; }");
  assert.deepEqual(found, []);
});

test("PT-57 (architect's addendum): board.css no longer hides the Atlassian navy tint inside an rgba() literal", () => {
  assert.equal(
    findLegacyRgbTint(readBoardCss()), false,
    `board.css still contains the legacy Atlassian navy RGB triplet (${LEGACY_RGB_COMPONENTS.join(", ")}) ` +
      `inside an rgb()/rgba() color value -- a carried-forward hue is exactly what the preset-pure ` +
      `direction forbids, hex or not (see 07a0557 for the original fix: drop the tint, keep the alpha)`
  );
});

test("negative control: the rgb-tint extractor catches the tint when present", () => {
  assert.equal(findLegacyRgbTint("--shadow: 0 1px 2px rgba(9, 30, 66, 0.12);"), true);
});

test("negative control: a comment mentioning the tint in prose is not read as a real usage", () => {
  assert.equal(
    findLegacyRgbTint("/* the old value was rgb(9, 30, 66) */\n--shadow: 0 1px 2px rgba(0, 0, 0, 0.12);"),
    false
  );
});

// ---------------------------------------------------------------------------
// The --accent collision guard (architect's explicit ruling ask)
// ---------------------------------------------------------------------------

// PT-69: three more legitimate uses landed alongside the theme/color
// settings dropdown. Two are the same "hover/active surface accent" role
// table.issue-list tr:hover already established (.theme-settings-option's
// selected/:hover states). The third is a deliberate, ux-designer-ruled
// role OVERLOAD, not a repeat of the old primary-blue meaning: the Paused/
// In Review status chip moved OFF --chart-2 (architect's ruling 1db6053 --
// a status chip's legibility can't depend on the user's Chart Color pick)
// onto --accent as a STATIC fill, reusing the hover-surface token for a
// second role ux-designer explicitly accepted rather than inventing a new
// token (design-system-spec.md's Project extensions section records the
// tradeoff).
const ACCENT_ALLOWED_SELECTORS = [
  "table.issue-list tr:hover",
  ".theme-settings-option.selected",
  ".theme-settings-option:hover",
  '.chip.status[data-status="paused"]',
  // PT-69 (ux-designer's Popover-row ruling): the row trigger itself
  // also takes the hover/active-surface accent treatment, same role,
  // now that rows are real Popover triggers rather than always-expanded
  // group headings.
  ".theme-settings-row-trigger:hover",
  '.theme-settings-row-trigger[aria-expanded="true"]',
];

function stripCssComments(cssSource) {
  return cssSource.replace(/\/\*[\s\S]*?\*\//g, "");
}

// Every rule (selector-list -> declaration body) whose declarations
// reference var(--accent), as {selector, declarations} pairs -- same
// rule-boundary technique as embed-visibility-scope.test.js's
// extractEmbedHiddenSelectors, comments stripped first for the same
// reason (a prose comment mentioning "--accent" must not be read as a
// real reference).
function findAccentUsingRules(cssSource) {
  const stripped = stripCssComments(cssSource);
  const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
  const matches = [];
  let ruleMatch;
  while ((ruleMatch = ruleRe.exec(stripped))) {
    const selector = ruleMatch[1].trim();
    const declarations = ruleMatch[2];
    if (/var\(\s*--accent\b/.test(declarations)) {
      matches.push({ selector, declarations: declarations.trim() });
    }
  }
  return matches;
}

test("PT-57/PT-69: var(--accent) is used in board.css ONLY at the known legitimate hover-surface rules", () => {
  const rules = findAccentUsingRules(readBoardCss());
  const selectors = rules.map((r) => r.selector).slice().sort();
  const allowed = ACCENT_ALLOWED_SELECTORS.slice().sort();
  assert.deepEqual(
    selectors, allowed,
    `var(--accent) must appear in exactly the known rules (${JSON.stringify(allowed)}, the preset's ` +
      `real hover-surface role) -- got ${JSON.stringify(selectors)}. Any OTHER selector using ` +
      `var(--accent) almost certainly meant the OLD --accent (primary blue, #0052cc) and will silently ` +
      `repaint near-white-on-white once tokens.css is linked -- it should reference var(--primary) instead.`
  );
});

test("negative control: the accent-usage extractor finds a real match", () => {
  const rules = findAccentUsingRules(".foo:hover { background: var(--accent); }");
  assert.deepEqual(rules.map((r) => r.selector), [".foo:hover"]);
});

test("negative control: a comment mentioning --accent is not read as a real reference", () => {
  const rules = findAccentUsingRules("/* uses var(--accent) in prose, not code */\n.foo { color: red; }");
  assert.deepEqual(rules, []);
});
