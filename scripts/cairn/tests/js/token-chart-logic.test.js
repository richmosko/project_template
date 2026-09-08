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

// PT-102's amended, re-issued gate-1 ruling (process/cairn/issues/
// PT-102.md @ ccd4f48, item (a)): `closed_at` is a new sibling key on
// each issues_out entry (ISO date | null -- null for an issue not yet
// done), server-computed by reusing the throughput chart's own
// status->done transition detection, never re-derived client-side. A
// separate helper rather than a new sampleIssue() parameter -- every
// PRE-EXISTING sampleIssue() call site stays untouched (closed_at simply
// absent, i.e. undefined, which the ordering/caption logic must treat
// the same as an explicit null -- "open").
function withClosedAt(issue, closedAt) {
  return { ...issue, closed_at: closedAt };
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

// --------------------------------------------------------------------------
// PT-88 gate-1 ruling (architect, process/cairn/issues/PT-88.md @ c66be43,
// item (a)/(c)/(e)): `selectBars` gains a fifth optional positional,
// `order: 'ranked' | 'chronological' = 'ranked'` -- every test above stays
// valid unmodified on the default. Chronological: `kind: 'issue'` bars
// ONLY, in PAYLOAD order (server already sorts id-ascending -- no
// client-side re-sort), no limit, `main` and milestone bars omitted
// entirely (neither has a position in the issue sequence).
// --------------------------------------------------------------------------

test("chronological mode returns issue bars in payload order, never re-ranked by the displayed metric", () => {
  const mod = loadTokenChartLogic();
  // Payload order deliberately NOT sorted by tokens (PT-1 has the most
  // tokens but is NOT first) -- proves this is payload order, not a
  // client-side re-sort that happens to look chronological on tidy input.
  const issues = [
    sampleIssue("PT-3", 100, 1.0),
    sampleIssue("PT-1", 300, 3.0),
    sampleIssue("PT-2", 200, 2.0),
  ];
  const selected = mod.selectBars(issues, "tokens", 12, false, "chronological").map((e) => e.issue);
  assert.deepEqual(
    selected, ["PT-3", "PT-1", "PT-2"],
    `chronological mode must preserve payload order exactly, never re-sort by the displayed metric -- got ${JSON.stringify(selected)}`,
  );
});

test("chronological mode applies no limit at all, even with showAll false", () => {
  const mod = loadTokenChartLogic();
  const issues = Array.from({ length: 20 }, (_, i) => sampleIssue(`PT-${i + 1}`, 10, 0.1));
  const selected = mod.selectBars(issues, "tokens", 12, false, "chronological");
  assert.equal(
    selected.length, 20,
    `chronological mode must show every issue bar regardless of limit -- there is no cut to lift -- got ${selected.length}`,
  );
});

test("chronological mode omits main and milestone bars; ranked mode on the same payload still includes them", () => {
  const mod = loadTokenChartLogic();
  const issues = [
    sampleIssue("PT-1", 300, 3.0),
    sampleIssue("PT-2", 200, 2.0),
    sampleIssue("milestone:PT-0.4", 50, 0.5, "milestone"),
    sampleIssue("main", 999, 9.0),
  ];
  const chrono = mod.selectBars(issues, "tokens", 12, false, "chronological").map((e) => e.issue);
  const ranked = mod.selectBars(issues, "tokens", 12, false, "ranked").map((e) => e.issue);
  assert.deepEqual(
    chrono, ["PT-1", "PT-2"],
    `chronological mode must omit main and milestone bars entirely -- neither has a position in the issue sequence -- got ${JSON.stringify(chrono)}`,
  );
  assert.deepEqual(
    ranked, ["PT-1", "PT-2", "milestone:PT-0.4", "main"],
    `ranked mode on the SAME payload must still include both -- got ${JSON.stringify(ranked)}`,
  );
});

test("metric orthogonality: chronological output is identical across metrics even when ranked output differs", () => {
  const mod = loadTokenChartLogic();
  // PT-1 has the most tokens but the LEAST cost; PT-2 the reverse -- the
  // two metrics rank these issues in opposite order in ranked mode.
  const issues = [
    sampleIssue("PT-1", 300, 1.0),
    sampleIssue("PT-2", 100, 30.0),
  ];
  const chronoTokens = mod.selectBars(issues, "tokens", 12, false, "chronological").map((e) => e.issue);
  const chronoCost = mod.selectBars(issues, "cost", 12, false, "chronological").map((e) => e.issue);
  const rankedTokens = mod.selectBars(issues, "tokens", 12, false, "ranked").map((e) => e.issue);
  const rankedCost = mod.selectBars(issues, "cost", 12, false, "ranked").map((e) => e.issue);
  assert.deepEqual(
    chronoTokens, chronoCost,
    `chronological order must be identical regardless of the displayed metric -- got tokens=${JSON.stringify(chronoTokens)} cost=${JSON.stringify(chronoCost)}`,
  );
  assert.notDeepEqual(
    rankedTokens, rankedCost,
    "sanity check on this test's own fixture: the two metrics must actually rank differently in ranked mode, or this test proves nothing about orthogonality",
  );
});

test("formatCaption's ranked branch is byte-identical whether or not order is passed explicitly", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([sampleIssue("PT-1", 300, 3.0)]);
  const implicitDefault = mod.formatCaption(payload, "tokens", 12, 68);
  const explicitRanked = mod.formatCaption(payload, "tokens", 12, 68, "ranked");
  assert.equal(
    explicitRanked, implicitDefault,
    "passing order='ranked' explicitly must produce byte-identical output to the default (no 5th argument at all)",
  );
});

test("formatCaption for chronological mode states 'in the order closed' and never appends milestone_caption verbatim", () => {
  // PT-102's amended, re-issued ruling (process/cairn/issues/PT-102.md
  // @ ccd4f48, item (d)) SUPERSEDES PT-88's "in the order opened"
  // phrasing a second time -- ordering is now by close date, not by
  // filing date, and the caption says so. PT-1 is given an explicit
  // closed_at so this test (about milestone/main omission, not the
  // still-open clause) doesn't spuriously trip it.
  const mod = loadTokenChartLogic();
  const payload = samplePayload([
    withClosedAt(sampleIssue("PT-1", 300, 3.0), "2026-09-01"),
    sampleIssue("milestone:PT-0.4", 50, 0.5, "milestone"),
    sampleIssue("main", 999, 9.0),
  ]);
  payload.milestone_caption = "Milestone bars are main-branch work attributed to whichever milestone was active at the time.";
  const caption = mod.formatCaption(payload, "tokens", 68, 68, "chronological");
  assert.match(
    caption, /Showing all 68 issues in the order closed, by tokens\./,
    `expected the ruled chronological middle sentence -- got ${JSON.stringify(caption)}`,
  );
  assert.match(
    caption, /Milestone and main buckets are omitted here — neither has a place in the issue sequence\./,
    `expected the omission sentence when the payload carries a non-issue bucket -- got ${JSON.stringify(caption)}`,
  );
  assert.ok(
    !caption.includes(payload.milestone_caption),
    `chronological caption must never append milestone_caption verbatim (no milestone bars are shown in this mode) -- got ${JSON.stringify(caption)}`,
  );
});

test("formatCaption for chronological mode omits the omission sentence when the payload has no non-issue buckets", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([withClosedAt(sampleIssue("PT-1", 300, 3.0), "2026-09-01")]);
  const caption = mod.formatCaption(payload, "tokens", 1, 1, "chronological");
  assert.doesNotMatch(
    caption, /omitted here/,
    `no non-issue bucket in this payload -- the omission sentence must not appear -- got ${JSON.stringify(caption)}`,
  );
});

// --------------------------------------------------------------------------
// PT-102's amended, re-issued gate-1 ruling (process/cairn/issues/
// PT-102.md @ ccd4f48): chronological mode's sort key is `closed_at`
// (the status->done transition date), NOT `first_active` (my superseded
// draft against the retired @14cc804 ruling was discarded, never
// committed). Closed issues sort by `closed_at` ascending; open issues
// (no `closed_at`) sort after every closed one, in payload order (the
// id tie-break, obtained for free from a stable sort over an
// id-ascending payload -- the client never parses an id, which PT-88
// forbade).
// --------------------------------------------------------------------------

test("chronological mode orders closed issues by closed_at ascending", () => {
  const mod = loadTokenChartLogic();
  const issues = [
    withClosedAt(sampleIssue("PT-3", 10, 0.1), "2026-09-03"),
    withClosedAt(sampleIssue("PT-1", 10, 0.1), "2026-09-01"),
    withClosedAt(sampleIssue("PT-2", 10, 0.1), "2026-09-02"),
  ];
  const selected = mod.selectBars(issues, "tokens", 12, false, "chronological").map((e) => e.issue);
  assert.deepEqual(
    selected, ["PT-1", "PT-2", "PT-3"],
    `expected closed_at-ascending order -- got ${JSON.stringify(selected)}`,
  );
});

test("open issues (no closed_at) sort after every closed issue, regardless of id", () => {
  const mod = loadTokenChartLogic();
  // Deliberately reversed relative to id order: PT-1 (lowest id) is
  // OPEN and must land LAST; PT-9 (highest id) closed LATER than PT-2
  // but must still precede PT-1.
  const issues = [
    sampleIssue("PT-1", 10, 0.1), // open -- no closed_at at all
    withClosedAt(sampleIssue("PT-9", 10, 0.1), "2026-09-05"),
    withClosedAt(sampleIssue("PT-2", 10, 0.1), "2026-09-01"),
  ];
  const selected = mod.selectBars(issues, "tokens", 12, false, "chronological").map((e) => e.issue);
  assert.deepEqual(
    selected, ["PT-2", "PT-9", "PT-1"],
    `closed issues (by closed_at ascending) must come first, the open issue (PT-1, lowest id) `
    + `must be LAST -- got ${JSON.stringify(selected)}`,
  );
});

test("chronological mode is a stable sort: same-closed-date issues and open issues each keep payload order", () => {
  const mod = loadTokenChartLogic();
  // Payload order deliberately NOT id-ascending within either group, so
  // "payload order" and "id order" can't be confused for one another.
  const issues = [
    withClosedAt(sampleIssue("PT-9", 10, 0.1), "2026-09-01"),
    withClosedAt(sampleIssue("PT-3", 10, 0.1), "2026-09-01"),
    withClosedAt(sampleIssue("PT-5", 10, 0.1), "2026-09-01"),
    sampleIssue("PT-7", 10, 0.1), // open
    sampleIssue("PT-2", 10, 0.1), // open
  ];
  const selected = mod.selectBars(issues, "tokens", 12, false, "chronological").map((e) => e.issue);
  assert.deepEqual(
    selected, ["PT-9", "PT-3", "PT-5", "PT-7", "PT-2"],
    `same-closed-date issues must keep payload order among themselves, and open issues must `
    + `keep payload order among themselves (both groups, after the closed block) -- got `
    + `${JSON.stringify(selected)}`,
  );
});

test("formatCaption chronological has no still-open clause when every issue is closed", () => {
  const mod = loadTokenChartLogic();
  const payload = samplePayload([
    withClosedAt(sampleIssue("PT-1", 10, 0.1), "2026-09-01"),
    withClosedAt(sampleIssue("PT-2", 10, 0.1), "2026-09-02"),
  ]);
  const caption = mod.formatCaption(payload, "tokens", 2, 2, "chronological");
  assert.match(
    caption, /Showing all 2 issues in the order closed, by tokens\./,
    `got ${JSON.stringify(caption)}`,
  );
  assert.doesNotMatch(caption, /still open/, `got ${JSON.stringify(caption)}`);
});

test("formatCaption chronological names the still-open issue count (plural control) when more than one issue is open", () => {
  // Control for the singular test below -- the PLURAL branch was
  // already correct in the merged build (verdict delta 1, PT-102.md @
  // 663eb0a: only the singular case pluralized wrongly), so this stays
  // green throughout and proves the fix didn't break the plural case
  // while adding the singular one.
  const mod = loadTokenChartLogic();
  const payload = samplePayload([
    withClosedAt(sampleIssue("PT-1", 10, 0.1), "2026-09-01"),
    sampleIssue("PT-2", 10, 0.1), // open
    sampleIssue("PT-3", 10, 0.1), // open
  ]);
  const caption = mod.formatCaption(payload, "tokens", 3, 3, "chronological");
  assert.match(
    caption, /2 issues are still open and are shown last\./,
    `got ${JSON.stringify(caption)}`,
  );
});

test("formatCaption chronological singularizes the still-open sentence when exactly one issue is open", () => {
  // Verdict delta 1 (PT-102.md @ 663eb0a): the live board showed "1
  // issues are still open and are shown last." -- the architect's own
  // ruling supplied that unpluralized string verbatim, so this is a
  // ruling fix, not a build defect. Red at HEAD: the merged
  // implementation still emits the unpluralized `${openCount} issues
  // ... are shown last.` for every count including 1.
  const mod = loadTokenChartLogic();
  const payload = samplePayload([
    withClosedAt(sampleIssue("PT-1", 10, 0.1), "2026-09-01"),
    sampleIssue("PT-2", 10, 0.1), // the one open issue
  ]);
  const caption = mod.formatCaption(payload, "tokens", 2, 2, "chronological");
  assert.match(
    caption, /\b1 issue is still open and is shown last\./,
    `expected the SINGULAR form ("1 issue is ... is shown") -- got ${JSON.stringify(caption)}`,
  );
  assert.doesNotMatch(
    caption, /1 issues are still open/,
    `must not still emit the unpluralized plural form -- got ${JSON.stringify(caption)}`,
  );
});

// --------------------------------------------------------------------------
// PT-101 gate-1 ruling, RE-ISSUED WHOLE (architect, process/cairn/issues/
// PT-101.md @ d7f7d3a, superseding @3b42f3c per the builder's measured
// objection -- my earlier floorRowForRender/trueTotalFor draft is
// discarded here, never a subject of any commit past this one). A
// sub-pixel column (0.712 px, 0.114 px, ...) renders present but
// invisible in chronological mode. The mechanism is now an OVERLAY, not
// a value floor: nothing floors a row's data -- `TokenCostChart.svelte`
// overrides layerchart's `marks` snippet with a verbatim copy of its
// default body plus one extra layer drawing a `MIN_BAR_PX`-tall Rect at
// the baseline for each sub-pixel column. The y-scale, the stack and the
// tooltip are untouched by construction, so there is no floored row to
// assert against and no `trueTotalFor` -- do not resurrect either.
//
// `subPixelColumns(rows, seriesKeys, yMax, plotHeightPx, minPx =
// MIN_BAR_PX): Array<{ issue, heightPx, topSeriesKey }>` REPORTS which
// columns need the overlay; `heightPx` is the TRUE (auditable) height,
// `topSeriesKey` the stack-top series with a non-zero value (the
// overlay borrows that column's own colour). Row shape unchanged from
// PT-88/PT-102: `{ issue, kind, <seriesKey>: number, ... }`.
// --------------------------------------------------------------------------

const SERIES_KEYS = ["input", "cache_write", "cache_read", "output"];

test("subPixelColumns returns only columns rendering below the floor", () => {
  const mod = loadTokenChartLogic();
  const rows = [
    { issue: "PT-1", kind: "issue", input: 1, cache_write: 0, cache_read: 0, output: 0 }, // total 1 -> 0.25px, below floor
    { issue: "PT-2", kind: "issue", input: 100, cache_write: 0, cache_read: 0, output: 0 }, // total 100 -> 25px, at/above floor
  ];
  // yMax=1000, plotHeightPx=250, default minPx (1).
  const result = mod.subPixelColumns(rows, SERIES_KEYS, 1000, 250);
  const ids = result.map((c) => c.issue);
  assert.deepEqual(ids, ["PT-1"], `expected only the below-floor column (PT-1) -- got ${JSON.stringify(ids)}`);
});

test("subPixelColumns excludes a zero-total column even though it renders below the floor", () => {
  const mod = loadTokenChartLogic();
  const rows = [{ issue: "PT-1", kind: "issue", input: 0, cache_write: 0, cache_read: 0, output: 0 }];
  const result = mod.subPixelColumns(rows, SERIES_KEYS, 1000, 250);
  assert.deepEqual(
    result, [],
    `a zero-total column renders at a true 0px by design and must never be reported as `
    + `sub-pixel -- got ${JSON.stringify(result)}`,
  );
});

test("subPixelColumns returns [] (never divides) when yMax or plotHeightPx is non-positive", () => {
  const mod = loadTokenChartLogic();
  const rows = [{ issue: "PT-1", kind: "issue", input: 1, cache_write: 0, cache_read: 0, output: 0 }];
  assert.deepEqual(mod.subPixelColumns(rows, SERIES_KEYS, 0, 250), [], "yMax = 0 must return []");
  assert.deepEqual(mod.subPixelColumns(rows, SERIES_KEYS, 1000, 0), [], "plotHeightPx = 0 must return []");
});

test("subPixelColumns' topSeriesKey is the stack-top series with a non-zero value, skipping a zero-valued last series", () => {
  const mod = loadTokenChartLogic();
  // SERIES_KEYS' LAST entry ("output", the stack-top POSITION) is
  // deliberately zero here -- "cache_read" is the true topmost
  // non-zero segment. Distinguishes "stack-top position" from
  // "stack-top position with a non-zero value": a mutation that
  // unconditionally returns the last key would report "output".
  const rows = [{ issue: "PT-1", kind: "issue", input: 1, cache_write: 1, cache_read: 1, output: 0 }];
  const result = mod.subPixelColumns(rows, SERIES_KEYS, 1000, 250);
  assert.equal(result.length, 1, `expected exactly one sub-pixel column -- got ${JSON.stringify(result)}`);
  assert.equal(
    result[0].topSeriesKey, "cache_read",
    `expected the stack-top NON-ZERO series (cache_read), not the last seriesKeys entry `
    + `(output, zero here) -- got ${JSON.stringify(result[0])}`,
  );
});

test("subPixelColumns' heightPx is the true, auditable sub-pixel height -- not the floor value", () => {
  const mod = loadTokenChartLogic();
  // total = 1, yMax = 1000, plotHeightPx = 250 -> true heightPx = 0.25.
  const rows = [{ issue: "PT-1", kind: "issue", input: 1, cache_write: 0, cache_read: 0, output: 0 }];
  const result = mod.subPixelColumns(rows, SERIES_KEYS, 1000, 250);
  assert.equal(result.length, 1);
  assert.equal(
    result[0].heightPx, 0.25,
    `expected the TRUE sub-pixel height (0.25), not MIN_BAR_PX (1) -- the overlay's own audit `
    + `trail depends on this being the real number -- got ${result[0].heightPx}`,
  );
});

// --------------------------------------------------------------------------
// Fork guard (ruling item (e)6): TokenCostChart.svelte carries a
// VERBATIM COPY of layerchart's default `marks` body (there is no
// children/aboveMarks/belowMarks snippet to layer onto instead --
// measured, BarChart.base.svelte exposes only `marks`). A minor bump can
// change that body under an unchanged copy with NO rendering symptom --
// the bars keep drawing, just silently missing whatever upstream
// changed. This guard is the only thing that would catch that drift.
// --------------------------------------------------------------------------

const fs = require("node:fs");

const LAYERCHART_PACKAGE_JSON = path.join(__dirname, "..", "..", "dashboard", "node_modules", "layerchart", "package.json");
const LAYERCHART_BARCHART_BASE = path.join(
  __dirname, "..", "..", "dashboard", "node_modules", "layerchart", "dist", "components", "charts", "BarChart", "BarChart.base.svelte",
);

// Pinned at the moment TokenCostChart.svelte's marks override copied
// this body verbatim (architect's ruling, PT-101.md @ d7f7d3a).
const PINNED_LAYERCHART_VERSION = "2.3.1";
const PINNED_DEFAULT_MARKS_BODY = `      {#each context.series.visibleSeries as s, i (s.key)}
        <Bars
          seriesKey={s.key}
          x1={valueAxis === 'y' && isGroupSeries && restProps.x1 == null
            ? (d: any) => s.value ?? s.key
            : undefined}
          y1={valueAxis === 'x' && isGroupSeries && restProps.y1 == null
            ? (d: any) => s.value ?? s.key
            : undefined}
          rounded={context.series.stackLayout != null
            ? // Per row rather than per series: a sub-band or a gap in the data can leave the
              // later series out, making an earlier one the top of *that* stack
              (d: any) => (context.series.isStackTop(s.key, d) ? 'edge' : 'none')
            : Array.isArray(xProp) || Array.isArray(yProp)
              ? 'all'
              : 'edge'}
          radius={4}
          strokeWidth={1}
          {stackPadding}
          opacity={(d: any) =>
            context.series.isHighlighted(context.cKey(d) ?? s.key, true) ? 1 : 0.1}
          onBarClick={(e: MouseEvent, detail: any) => onBarClick(e, { ...detail, series: s })}
          {...props.bars}
          {...s.props}
        />
      {/each}`;

test("layerchart is still the pinned version our copied marks body was taken from", () => {
  const pkg = JSON.parse(fs.readFileSync(LAYERCHART_PACKAGE_JSON, "utf8"));
  assert.equal(
    pkg.version, PINNED_LAYERCHART_VERSION,
    `layerchart's installed version (${pkg.version}) no longer matches the version our copied `
    + `marks body was taken from (${PINNED_LAYERCHART_VERSION}) -- re-verify (and if needed `
    + `re-copy) TokenCostChart.svelte's marks override against the new upstream body before `
    + `trusting it still renders the same as the library's own default`,
  );
});

test("layerchart's upstream default marks body still matches the text copied into TokenCostChart.svelte", () => {
  const source = fs.readFileSync(LAYERCHART_BARCHART_BASE, "utf8");
  assert.ok(
    source.includes(PINNED_DEFAULT_MARKS_BODY),
    "layerchart's BarChart.base.svelte default marks body (the {#each context.series."
    + "visibleSeries...}{/each} block) no longer matches the text pinned in this test -- the "
    + "vendored library changed its default rendering under an unchanged version pin (or the "
    + "version-pin test above already caught a bump); TokenCostChart.svelte's copied marks "
    + "override must be re-verified against the new upstream body before merging any dependency "
    + "update, or the overlay silently renders on top of a body missing whatever changed.",
  );
});
