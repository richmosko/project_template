"use strict";

// PT-79 failing acceptance tests: `token-chart-logic.ts`, the pure
// selection/sort/caption seam named in the architect's addendum
// (process/cairn/issues/PT-79.md, a375ff7, "token-chart-logic.ts -- the
// pure seam") and amended (ad940d3 §2, ROLE_TOKEN_ORDER + the "other"
// fold).
//
// Node 26 supports importing/requiring .ts files with native type
// stripping (verified by hand before writing this file) -- no build
// step, no ts-node/tsx dependency needed, matching the addendum's own
// "node --test against scripts/cairn/tests/js/, no browser" instruction.
//
// Contract (addendum, verbatim):
//   export const DEFAULT_BAR_LIMIT = 12;
//   export type Metric = 'tokens' | 'cost';
//   export function barValue(issue, metric): number
//   export function selectBars(issues, metric, limit = DEFAULT_BAR_LIMIT, showAll = false)
//     // top-N by metric, `main` always appended last, main NEVER subject to the cut
//   export function formatCaption(payload, metric, shown, total): string
//
// Amendment ad940d3 §2 adds:
//   export const ROLE_TOKEN_ORDER = [...]; // append-only, explicit, 8 slots
//   // folding an unlisted role yields the "other" series
//
// Nothing under test exists yet: no
// scripts/cairn/dashboard/src/lib/token-chart-logic.ts file at all.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const MODULE_PATH = path.join(__dirname, "..", "..", "dashboard", "src", "lib", "token-chart-logic.ts");

function loadTokenChartLogic() {
  try {
    return require(MODULE_PATH);
  } catch (err) {
    throw new Error(
      `token-chart-logic.ts not found or failed to load at ${MODULE_PATH} -- PT-79's ` +
        `ruled pure seam (addendum a375ff7) is unimplemented (${err.message})`
    );
  }
}

function sampleIssue(issue, tokensTotal, costTotal, kind) {
  return {
    issue: issue,
    // PT-84 §7: kind defaults to "issue" so every PRE-EXISTING call site
    // above (none of which pass a 4th argument) keeps behaving exactly
    // as it did before this field existed -- "main" is the one
    // pre-existing exception, matching build_tokens_payload's own
    // server-side derivation (issue === "main" -> kind: "main").
    kind: kind || (issue === "main" ? "main" : "issue"),
    total: { input: tokensTotal, cache_write: 0, cache_read: 0, output: 0, cost_usd: costTotal },
    roles: [],
  };
}

function samplePayload(issueList) {
  return {
    issues: issueList,
    window_start: "2026-08-18",
    window_end: "2026-09-04",
    generated: "2026-09-04T02:18:03Z",
    sources: ["transcript-backfill"],
    prices: { retrieved: "2026-09-04", source: "https://example.invalid", unpriced_models: [] },
    warning: null,
    // PT-84 §7: null when the payload has no milestone bucket -- the
    // committed server behaviour (implementation-lead, 775576e).
    milestone_caption: null,
  };
}

test("token-chart-logic.ts exists and is importable", () => {
  assert.doesNotThrow(() => loadTokenChartLogic());
});

test("DEFAULT_BAR_LIMIT is exactly 12", () => {
  const mod = loadTokenChartLogic();
  assert.equal(mod.DEFAULT_BAR_LIMIT, 12);
});

test("selectBars returns the top-N issues by the displayed metric, main appended last regardless of rank", () => {
  const mod = loadTokenChartLogic();
  // 3 real issues + main. Rank by tokens: PT-1 (300) > PT-2 (200) > PT-3
  // (100). main has the LOWEST raw token total (50) but must still be
  // appended LAST, never subject to the top-N cut or its own ranking.
  const issues = [
    sampleIssue("PT-1", 300, 3.0),
    sampleIssue("PT-2", 200, 30.0), // higher COST than PT-1 despite fewer tokens
    sampleIssue("PT-3", 100, 1.0),
    sampleIssue("main", 50, 0.5),
  ];
  const selected = mod.selectBars(issues, "tokens", 2, false);
  const ids = selected.map((e) => e.issue);
  assert.deepEqual(ids, ["PT-1", "PT-2", "main"], "top 2 by tokens (PT-1, PT-2) plus main, appended last");
});

test("selection AND order follow the displayed metric -- cost view can select a different top-N than tokens view", () => {
  const mod = loadTokenChartLogic();
  const issues = [
    sampleIssue("PT-1", 300, 3.0),   // top by tokens, LOW cost
    sampleIssue("PT-2", 200, 30.0),  // top by cost, mid tokens
    sampleIssue("PT-3", 100, 1.0),
    sampleIssue("main", 50, 0.5),
  ];
  const byTokens = mod.selectBars(issues, "tokens", 2, false).map((e) => e.issue);
  const byCost = mod.selectBars(issues, "cost", 2, false).map((e) => e.issue);
  assert.deepEqual(byTokens, ["PT-1", "PT-2", "main"]);
  assert.deepEqual(byCost, ["PT-2", "PT-1", "main"], "cost view must reorder to PT-2 first (highest cost), not preserve the tokens-view order");
});

test("main is never subject to the top-N cut even when it would rank in the top N by raw value", () => {
  const mod = loadTokenChartLogic();
  // main has the HIGHEST value here -- must still be appended LAST, not
  // sorted to the front as if it were a normal contender.
  const issues = [
    sampleIssue("PT-1", 100, 1.0),
    sampleIssue("PT-2", 50, 0.5),
    sampleIssue("main", 999, 99.0),
  ];
  const selected = mod.selectBars(issues, "tokens", 2, false).map((e) => e.issue);
  assert.deepEqual(selected, ["PT-1", "PT-2", "main"], "main must be LAST regardless of its own rank");
});

test("showAll returns every issue plus main, not just the top-N", () => {
  const mod = loadTokenChartLogic();
  const issues = [
    sampleIssue("PT-1", 300, 3.0),
    sampleIssue("PT-2", 200, 2.0),
    sampleIssue("PT-3", 100, 1.0),
    sampleIssue("main", 50, 0.5),
  ];
  const selected = mod.selectBars(issues, "tokens", 2, true).map((e) => e.issue);
  assert.deepEqual(selected, ["PT-1", "PT-2", "PT-3", "main"]);
});

test("barValue reads tokens total for metric 'tokens'", () => {
  const mod = loadTokenChartLogic();
  const issue = sampleIssue("PT-1", 300, 3.0);
  assert.equal(mod.barValue(issue, "tokens"), 300);
});

test("barValue reads cost_usd total for metric 'cost'", () => {
  const mod = loadTokenChartLogic();
  const issue = sampleIssue("PT-1", 300, 3.0);
  assert.equal(mod.barValue(issue, "cost"), 3.0);
});

test("formatCaption for tokens view matches the addendum's exact string shape", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([sampleIssue("PT-1", 300, 3.0)]);
  const caption = mod.formatCaption(payload, "tokens", 12, 68);
  assert.match(caption, /Tokens are exact/);
  assert.match(caption, /Showing the top 12 of 68 issues by tokens, plus main/);
  assert.match(caption, /History begins 2026-08-18/);
});

test("formatCaption for cost view matches the addendum's exact string shape, including 'estimated'", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([sampleIssue("PT-1", 300, 3.0)]);
  const caption = mod.formatCaption(payload, "cost", 12, 68);
  assert.match(caption, /estimated/);
  assert.match(caption, /retrieved 2026-09-04/);
  assert.match(caption, /Showing the top 12 of 68 issues by estimated cost, plus main/);
});

test("formatCaption with Show-all active uses the 'Showing all {total}' phrasing, not 'top N of'", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([sampleIssue("PT-1", 300, 3.0)]);
  const caption = mod.formatCaption(payload, "tokens", 68, 68);
  assert.match(caption, /Showing all 68 issues, ordered by/);
  assert.doesNotMatch(caption, /top \d+ of/);
});

test("formatCaption appends the unpriced-models suffix when prices.unpriced_models is non-empty", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([sampleIssue("PT-1", 300, 3.0)]);
  payload.prices.unpriced_models = ["claude-unreleased-model-x"];
  const caption = mod.formatCaption(payload, "cost", 12, 68);
  assert.match(caption, /1 model\(s\) have no published rate and are excluded from cost: claude-unreleased-model-x/);
});

test("formatCaption omits the unpriced-models suffix when the list is empty", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([sampleIssue("PT-1", 300, 3.0)]);
  const caption = mod.formatCaption(payload, "cost", 12, 68);
  assert.doesNotMatch(caption, /have no published rate/);
});

test("ROLE_TOKEN_ORDER is exported as an array with at most 8 entries", () => {
  const mod = loadTokenChartLogic();
  assert.ok(Array.isArray(mod.ROLE_TOKEN_ORDER), "ROLE_TOKEN_ORDER must be an array");
  assert.ok(mod.ROLE_TOKEN_ORDER.length <= 8, `expected at most 8 role slots (amendment ad940d3 §2's distinguishability limit), got ${mod.ROLE_TOKEN_ORDER.length}`);
});

test("a role not present in ROLE_TOKEN_ORDER folds into an 'other' series", () => {
  const mod = loadTokenChartLogic();
  assert.equal(
    typeof mod.roleTokenSeries,
    "function",
    "expected a roleTokenSeries(roleName) -> token-name helper (or equivalently-purposed export) " +
      "implementing the fold rule -- see amendment ad940d3 §2: 'roles not in ROLE_TOKEN_ORDER " +
      "aggregate into a single other series'"
  );
  const unlistedRole = "some-role-that-will-never-be-in-the-list-xyz";
  assert.ok(
    !mod.ROLE_TOKEN_ORDER.includes(unlistedRole),
    "sanity check on this test's own fixture: the probe role must not already be in the list",
  );
  const series = mod.roleTokenSeries(unlistedRole);
  assert.equal(series, "other", `an unlisted role must fold to 'other', got ${JSON.stringify(series)}`);
});

// team-lead's browser-verified delta on 078ad9e (narrow width, 500px):
// 13 x-axis labels overlapped -- the current thinning rule
// (TokenCostChart.svelte's X_AXIS_DENSITY_THRESHOLD = 20) keys on a
// FIXED bar count, not available pixel width, so it never engages until
// 21+ bars regardless of how narrow the plot actually is. Proposed pure
// function (negotiable), extracted to token-chart-logic.ts so it's
// unit-testable and width-aware:
//
//   export function tickEveryNth(barCount, plotWidthPx, labelWidthPx): number
//     // returns the step N such that "show every Nth bar's label" keeps
//     // labels from overlapping at the given plot width -- 1 means "show
//     // every label, no thinning needed."
//
// team-lead's own worked example: 13 bars at 300px thin, 13 bars at
// 1200px do not -- the two tests below pin exactly that pair.

test("tickEveryNth exists on token-chart-logic.ts", () => {
  const mod = loadTokenChartLogic();
  assert.equal(
    typeof mod.tickEveryNth,
    "function",
    "expected a tickEveryNth(barCount, plotWidthPx, labelWidthPx) -> number pure function -- " +
      "team-lead's instruction: label thinning must take available pixel width per bar into " +
      "account, not a fixed bar-count threshold (the current X_AXIS_DENSITY_THRESHOLD = 20 in " +
      "TokenCostChart.svelte is exactly the bug: 13 bars never thins regardless of width)"
  );
});

test("13 bars at a narrow 300px plot width must thin (step > 1)", () => {
  const mod = loadTokenChartLogic();
  const step = mod.tickEveryNth(13, 300, 40);
  assert.ok(step > 1, `expected thinning (step > 1) for 13 bars at 300px with ~40px labels, got step=${step}`);
});

test("the SAME 13 bars at a wide 1200px plot width must NOT thin (step === 1)", () => {
  const mod = loadTokenChartLogic();
  const step = mod.tickEveryNth(13, 1200, 40);
  assert.equal(step, 1, `expected no thinning (step === 1) for 13 bars at 1200px with ~40px labels, got step=${step} -- this is the width-awareness team-lead's diagnosis requires: the SAME bar count must behave differently at different widths`);
});

test("thinning is decisive: it must differ between the narrow and wide case for the same bar count", () => {
  // The single most important property here -- a function that returns
  // the SAME step regardless of plotWidthPx would technically satisfy
  // the two tests above independently if both happened to want step 1
  // or both wanted step > 1, but wouldn't actually be width-aware. This
  // test makes that failure mode impossible to pass accidentally.
  const mod = loadTokenChartLogic();
  const narrowStep = mod.tickEveryNth(13, 300, 40);
  const wideStep = mod.tickEveryNth(13, 1200, 40);
  assert.notEqual(narrowStep, wideStep, `tickEveryNth(13, 300, 40)=${narrowStep} and tickEveryNth(13, 1200, 40)=${wideStep} must differ -- a width-blind implementation could accidentally return the same step for both`);
});

test("more bars than fit even at the widest plausible width still thins sensibly (step is a positive integer)", () => {
  const mod = loadTokenChartLogic();
  const step = mod.tickEveryNth(69, 1200, 40);
  assert.ok(Number.isInteger(step) && step >= 1, `expected a positive integer step, got ${step}`);
});

test("zero bars does not throw and returns a sane step", () => {
  const mod = loadTokenChartLogic();
  const step = mod.tickEveryNth(0, 300, 40);
  assert.ok(Number.isInteger(step) && step >= 1, `expected a positive integer step for zero bars, got ${step}`);
});

// --------------------------------------------------------------------------
// PT-84 AC 4: milestone-overhead bars (process/cairn/issues/PT-84.md, §7,
// team-lead's decision that milestone_caption stays server-side and the
// chart appends it verbatim). Written after the ruling landed, same
// discipline as everything else in PT-84.
// --------------------------------------------------------------------------

test("selectBars excludes kind:'milestone' bars from the top-N ranking cut, like main", () => {
  const mod = loadTokenChartLogic();
  // 3 real issues ranked PT-1 > PT-2 > PT-3 by tokens; 2 milestone bars
  // with token totals that WOULD outrank everything if they competed for
  // the cut (200, matching PT-2) -- must never be cut regardless of value.
  const issues = [
    sampleIssue("PT-1", 300, 3.0),
    sampleIssue("PT-2", 200, 30.0),
    sampleIssue("PT-3", 100, 1.0),
    sampleIssue("milestone:PT-0.4", 200, 2.0, "milestone"),
    sampleIssue("milestone:PT-0.12", 50, 0.5, "milestone"),
    sampleIssue("main", 999, 9.0),
  ];
  const selected = mod.selectBars(issues, "tokens", 1, false);
  const ids = selected.map((e) => e.issue);
  assert.deepEqual(
    ids,
    ["PT-1", "milestone:PT-0.4", "milestone:PT-0.12", "main"],
    `top 1 real issue (PT-1) + both milestone bars (never cut, never re-ranked among themselves -- payload order) + main last, got ${JSON.stringify(ids)}`,
  );
});

test("selectBars milestone bars are never counted toward the real-issues top-N limit", () => {
  const mod = loadTokenChartLogic();
  // limit=2: exactly 2 real issues must survive regardless of how many
  // milestone bars sit alongside them -- a milestone bar consuming a
  // slot in the cut would be the same bug as main being rankable.
  const issues = [
    sampleIssue("PT-1", 300, 3.0),
    sampleIssue("PT-2", 200, 2.0),
    sampleIssue("PT-3", 100, 1.0),
    sampleIssue("milestone:PT-0.4", 500, 5.0, "milestone"),
  ];
  const selected = mod.selectBars(issues, "tokens", 2, false);
  const realIds = selected.filter((e) => e.kind === "issue").map((e) => e.issue);
  assert.deepEqual(realIds, ["PT-1", "PT-2"], `exactly 2 real issues must survive the limit=2 cut regardless of milestone bars present, got ${JSON.stringify(realIds)}`);
});

test("selectBars keeps milestone bars ordered exactly as the payload orders them (creation-time order, server-side)", () => {
  const mod = loadTokenChartLogic();
  // §6: milestone bars are already creation-time-ordered by the server
  // (cairn.milestone_rank_map) -- selectBars must NOT re-sort them by
  // their own token/cost value, only preserve payload order among them.
  const issues = [
    sampleIssue("PT-1", 300, 3.0),
    sampleIssue("milestone:PT-0.4", 10, 0.1, "milestone"), // smaller value, but created FIRST
    sampleIssue("milestone:PT-0.12", 900, 9.0, "milestone"), // larger value, but created LATER
    sampleIssue("main", 5, 0.05),
  ];
  const selected = mod.selectBars(issues, "tokens", 12, false);
  const milestoneIds = selected.filter((e) => e.kind === "milestone").map((e) => e.issue);
  assert.deepEqual(
    milestoneIds,
    ["milestone:PT-0.4", "milestone:PT-0.12"],
    `milestone bars must stay in the server's payload order (creation time), never re-ranked by value -- got ${JSON.stringify(milestoneIds)}`,
  );
});

test("formatCaption appends milestone_caption verbatim when the payload has a milestone bucket", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([sampleIssue("milestone:PT-0.4", 10, 0.1, "milestone")]);
  payload.milestone_caption = "Milestone bars are main-branch work attributed to whichever milestone was active at the time.";
  const caption = mod.formatCaption(payload, "tokens", 1, 1);
  assert.ok(
    caption.includes(payload.milestone_caption),
    `caption must include milestone_caption verbatim when present -- got ${JSON.stringify(caption)}`,
  );
});

test("formatCaption does not mention milestones at all when milestone_caption is null", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([sampleIssue("PT-1", 10, 0.1)]);
  // milestone_caption stays null (samplePayload's own default) -- no
  // milestone bucket in this payload.
  const caption = mod.formatCaption(payload, "tokens", 1, 1);
  assert.ok(
    !/milestone/i.test(caption),
    `caption must not mention milestones at all when milestone_caption is null -- got ${JSON.stringify(caption)}`,
  );
});
