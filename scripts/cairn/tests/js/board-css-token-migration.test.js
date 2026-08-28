"use strict";

// PT-57 (Board: migrate board.css to preset tokens) -- guard written
// BEFORE the architect's token-delivery ruling lands (link vs inline
// tokens.css, font hosting location for the board's own document, and
// interplay with embed-visibility-scope.test.js's CSS extractors are all
// still open). Same posture as PT-55/PT-56's own pending-ruling tests:
// don't guess at the delivery mechanism ahead of an open architectural
// decision.
//
// What IS testable regardless of which mechanism wins is the literal, AC-
// stated claim "legacy hexes gone" -- docs/DESIGN/design-system-spec.md's
// own Legacy/migration table names the exact seven hex values board.css
// must stop hardcoding, independent of how the replacement tokens get
// delivered. RED today (board.css still carries every one of them); goes
// green the moment the migration actually removes them, regardless of
// link-vs-inline or where the fonts end up.
//
// NOT covered here (deliberately, pending the ruling): the badge-variant
// re-expression of the chip taxonomy, and the regression pass ("board
// remains functional in both views + drawer") -- both depend on shapes
// the ruling hasn't decided yet.

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

function findLegacyHexes(cssSource) {
  const upper = cssSource.toUpperCase();
  return LEGACY_HEXES.filter((hex) => {
    // Whole-token match: not preceded/followed by a hex digit, so a
    // legitimate DIFFERENT color that happens to end in the same six
    // characters (extremely unlikely for 6-hex-digit codes, but the
    // discipline costs nothing) isn't miscounted.
    const re = new RegExp("(?<![0-9A-F])" + hex.slice(1) + "(?![0-9A-F])", "i");
    return re.test(upper);
  });
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
