"use strict";

// PT-85 failing acceptance tests: `flow-chart-logic.ts`, the pure
// period-aggregation/scope-selection/caption seam named in the
// architect's ruling (process/cairn/issues/PT-85.md, 409d310, payload
// pinned at 2f8eba0, week-aggregation rule stated in the addendum
// following 2f8eba0). Mirrors token-chart-logic.test.js's own
// established shape for this suite: `node --test` against the .ts file
// directly (Node's native type-stripping, no build step, no browser).
//
// Contract (flow-chart-logic.ts, verbatim):
//   export const ALL_MILESTONES_SCOPE = 'all';
//   export function scopedSeries(series, scope): ScopedPoint[]
//   export function isoWeekStartUtc(dateStr): string
//   export function aggregateToWeeks(series): ScopedPoint[]
//   export function aggregateByPeriod(series, period): ScopedPoint[]
//   export function defaultScope(payload): string
//   export function formatFlowCaption(payload, period, scope): string
//
// The one rule this file exists to pin, stated so nobody reaches for
// `reduce` by reflex on WIP: a week aggregates opened/closed/cancelled
// by SUM, but takes the LAST day's wip in the week -- summing or
// averaging a point-in-time count is the exact category error PT-85
// exists to remove.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const MODULE_PATH = path.join(__dirname, "..", "..", "dashboard", "src", "lib", "flow-chart-logic.ts");

function loadFlowChartLogic() {
  try {
    return require(MODULE_PATH);
  } catch (err) {
    throw new Error(
      `flow-chart-logic.ts not found or failed to load at ${MODULE_PATH} -- PT-85's ruled ` +
        `pure seam is unimplemented (${err.message})`
    );
  }
}

function breakdown(opened, closed, cancelled, wip) {
  return { opened, closed, cancelled, wip };
}

function point(date, opened, closed, cancelled, wip, byMilestone) {
  return { date, opened, closed, cancelled, wip, by_milestone: byMilestone || {} };
}

function samplePayload(series, milestones, defaultMilestone) {
  return {
    period: "day",
    series: series,
    milestones: milestones || [],
    default_milestone: defaultMilestone === undefined ? null : defaultMilestone,
    as_of: "deadbeef",
    scope: "some scope note",
    warning: null,
  };
}

// --------------------------------------------------------------------------
// Period aggregation: day passthrough; week sums deltas, takes LAST wip.
// --------------------------------------------------------------------------

test("aggregateByPeriod('day') returns the series unchanged (passthrough)", () => {
  const { aggregateByPeriod } = loadFlowChartLogic();
  const series = [point("2026-08-10", 1, 0, 0, 1), point("2026-08-11", 0, 1, 0, 0)];
  const result = aggregateByPeriod(series, "day");
  assert.deepEqual(result, series);
});

test("aggregateByPeriod('week') sums opened/closed/cancelled across the week", () => {
  const { aggregateByPeriod } = loadFlowChartLogic();
  // 2026-08-10 is a Monday (ISO week start) -- both days fall in the same ISO week.
  const series = [
    point("2026-08-10", 2, 1, 0, 3),
    point("2026-08-11", 1, 0, 1, 5),
  ];
  const [week] = aggregateByPeriod(series, "week");
  assert.equal(week.opened, 3, "opened must SUM across the week (2+1)");
  assert.equal(week.closed, 1, "closed must SUM across the week (1+0)");
  assert.equal(week.cancelled, 1, "cancelled must SUM across the week (0+1)");
});

test("aggregateByPeriod('week') takes the LAST day's wip, never a sum or a mean", () => {
  const { aggregateByPeriod } = loadFlowChartLogic();
  const series = [
    point("2026-08-10", 0, 0, 0, 10),
    point("2026-08-11", 0, 0, 0, 3),
  ];
  const [week] = aggregateByPeriod(series, "week");
  assert.equal(
    week.wip, 3,
    "wip must be the week's LAST day (3), not the sum (13) or the mean (6.5) -- summing/" +
      "averaging a point-in-time count is the exact category error PT-85 removes"
  );
});

test("aggregateByPeriod('week') carries an unchanged WIP forward on a day with no events, never zeroing it", () => {
  const { aggregateByPeriod } = loadFlowChartLogic();
  // A day with zero deltas still has a REAL (carried) wip value -- this
  // is the server's own by_milestone density guarantee reflected in the
  // client's week-aggregation: a quiet day is "unchanged", not "empty".
  const series = [
    point("2026-08-10", 1, 0, 0, 4),
    point("2026-08-11", 0, 0, 0, 4),
  ];
  const [week] = aggregateByPeriod(series, "week");
  assert.equal(week.wip, 4, "the last day's wip (carried, unchanged) must be used verbatim");
});

test("aggregateByPeriod('week') buckets multiple weeks separately, sorted chronologically", () => {
  const { aggregateByPeriod } = loadFlowChartLogic();
  const series = [
    point("2026-08-10", 1, 0, 0, 1), // week of 2026-08-10
    point("2026-08-18", 2, 0, 0, 2), // week of 2026-08-17 (next week)
  ];
  const weeks = aggregateByPeriod(series, "week");
  assert.equal(weeks.length, 2, `expected two distinct weeks -- got ${JSON.stringify(weeks)}`);
  assert.ok(weeks[0].date < weeks[1].date, "weeks must be sorted chronologically");
});

test("isoWeekStartUtc anchors to the ISO Monday of the UTC week, never a locale Sunday start", () => {
  const { isoWeekStartUtc } = loadFlowChartLogic();
  // 2026-08-13 is a Thursday; its ISO week starts Monday 2026-08-10.
  assert.equal(isoWeekStartUtc("2026-08-13"), "2026-08-10");
  // A Monday maps to itself.
  assert.equal(isoWeekStartUtc("2026-08-10"), "2026-08-10");
  // A Sunday belongs to the PRECEDING Monday's week (ISO, not a new week).
  assert.equal(isoWeekStartUtc("2026-08-16"), "2026-08-10");
});

// --------------------------------------------------------------------------
// Milestone-scope selection.
// --------------------------------------------------------------------------

test("scopedSeries('all') returns the overall opened/closed/cancelled/wip, dropping by_milestone", () => {
  const { scopedSeries, ALL_MILESTONES_SCOPE } = loadFlowChartLogic();
  const series = [point("2026-08-10", 5, 2, 1, 3, { "PT-0.1": breakdown(1, 0, 0, 1) })];
  const [scoped] = scopedSeries(series, ALL_MILESTONES_SCOPE);
  assert.deepEqual(scoped, { date: "2026-08-10", opened: 5, closed: 2, cancelled: 1, wip: 3 });
});

test("scopedSeries(milestoneId) projects that milestone's by_milestone entry onto the flat shape", () => {
  const { scopedSeries } = loadFlowChartLogic();
  const series = [point("2026-08-10", 5, 2, 1, 3, { "PT-0.1": breakdown(1, 0, 0, 1) })];
  const [scoped] = scopedSeries(series, "PT-0.1");
  assert.deepEqual(scoped, { date: "2026-08-10", opened: 1, closed: 0, cancelled: 0, wip: 1 });
});

test("scopedSeries(milestoneId) degrades a missing entry to all-zero, never undefined/crash", () => {
  const { scopedSeries } = loadFlowChartLogic();
  // PT-0.2 has not appeared as of this point at all (by_milestone is
  // dense only from a milestone's FIRST appearance onward).
  const series = [point("2026-08-10", 5, 2, 1, 3, { "PT-0.1": breakdown(1, 0, 0, 1) })];
  const [scoped] = scopedSeries(series, "PT-0.2");
  assert.deepEqual(scoped, { date: "2026-08-10", opened: 0, closed: 0, cancelled: 0, wip: 0 });
});

test("defaultScope honours the server's default_milestone when present", () => {
  const { defaultScope } = loadFlowChartLogic();
  const payload = samplePayload([], [{ id: "PT-0.12", name: "Telemetry", status: "in-progress" }], "PT-0.12");
  assert.equal(defaultScope(payload), "PT-0.12");
});

test("defaultScope falls back to 'all' when the server has no default (no milestone data at all)", () => {
  const { defaultScope, ALL_MILESTONES_SCOPE } = loadFlowChartLogic();
  const payload = samplePayload([], [], null);
  assert.equal(defaultScope(payload), ALL_MILESTONES_SCOPE);
});

// --------------------------------------------------------------------------
// Caption composition.
// --------------------------------------------------------------------------

test("formatFlowCaption names the period, the scope, and that WIP is end-of-period", () => {
  const { formatFlowCaption, ALL_MILESTONES_SCOPE } = loadFlowChartLogic();
  const payload = samplePayload([], []);
  const caption = formatFlowCaption(payload, "day", ALL_MILESTONES_SCOPE);
  assert.match(caption, /\bday\b/, `caption must name the period -- got ${JSON.stringify(caption)}`);
  assert.match(caption, /all milestones/, `caption must name the scope -- got ${JSON.stringify(caption)}`);
  assert.match(
    caption, /end of each day|point-in-time/,
    `caption must state WIP is end-of-period, point-in-time -- got ${JSON.stringify(caption)}`
  );
});

test("formatFlowCaption names a specific milestone's own name, not its bare id", () => {
  const { formatFlowCaption } = loadFlowChartLogic();
  const payload = samplePayload([], [{ id: "PT-0.12", name: "Telemetry attribution", status: "in-progress" }]);
  const caption = formatFlowCaption(payload, "day", "PT-0.12");
  assert.match(
    caption, /Telemetry attribution/,
    `caption must use the milestone's own name for the scope, not the bare id -- got ${JSON.stringify(caption)}`
  );
});

test("formatFlowCaption falls back to the bare id when the milestone has no current name (a historical ghost)", () => {
  const { formatFlowCaption } = loadFlowChartLogic();
  const payload = samplePayload([], [{ id: "0.6.1", name: null, status: null }]);
  const caption = formatFlowCaption(payload, "day", "0.6.1");
  assert.match(caption, /0\.6\.1/, `caption must fall back to the bare id -- got ${JSON.stringify(caption)}`);
});

test("formatFlowCaption states the week-summing/last-wip rule only in week mode", () => {
  const { formatFlowCaption, ALL_MILESTONES_SCOPE } = loadFlowChartLogic();
  const payload = samplePayload([], []);
  const dayCaption = formatFlowCaption(payload, "day", ALL_MILESTONES_SCOPE);
  const weekCaption = formatFlowCaption(payload, "week", ALL_MILESTONES_SCOPE);
  assert.doesNotMatch(
    dayCaption, /never a sum/i,
    `the week-specific rule clause must not appear in day mode -- got ${JSON.stringify(dayCaption)}`
  );
  assert.match(
    weekCaption, /never a sum/i,
    `week mode must state WIP is never summed across the week -- got ${JSON.stringify(weekCaption)}`
  );
});

// --------------------------------------------------------------------------
// `cancelled` survives the pipeline (tooltip-only data, per the ruling --
// never rendered as its own bar/line, but must not be dropped either).
// --------------------------------------------------------------------------

test("cancelled survives scopedSeries and week aggregation, ready for a tooltip to read", () => {
  const { scopedSeries, aggregateByPeriod, ALL_MILESTONES_SCOPE } = loadFlowChartLogic();
  const series = [point("2026-08-10", 1, 0, 2, 0), point("2026-08-11", 0, 0, 3, 0)];
  const scoped = scopedSeries(series, ALL_MILESTONES_SCOPE);
  const weeks = aggregateByPeriod(scoped, "week");
  assert.equal(scoped[0].cancelled, 2, "cancelled must survive scopedSeries");
  assert.equal(weeks[0].cancelled, 5, "cancelled must survive week aggregation, summed like opened/closed");
});

// --------------------------------------------------------------------------
// The retired cumulative series (backlog/todo/in-progress/in-review/done/
// cancelled status-stack counts) must not resurface in this seam's output.
// --------------------------------------------------------------------------

test("scopedSeries' output never carries a retired 'counts' field", () => {
  const { scopedSeries, ALL_MILESTONES_SCOPE } = loadFlowChartLogic();
  const series = [point("2026-08-10", 1, 0, 0, 1)];
  const [scoped] = scopedSeries(series, ALL_MILESTONES_SCOPE);
  assert.deepEqual(
    Object.keys(scoped).sort(), ["cancelled", "closed", "date", "opened", "wip"],
    `scopedSeries must project exactly the throughput fields -- no retired 'counts' key -- got ${JSON.stringify(scoped)}`
  );
});
