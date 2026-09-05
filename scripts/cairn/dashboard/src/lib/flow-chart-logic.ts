// PT-85: the pure period-aggregation/scope-selection/caption seam for
// the issue-flow throughput block (architect's ruling 409d310, payload
// pinned at 2f8eba0). Deliberately has NO svelte/DOM/fetch dependency --
// tested via `node --test scripts/cairn/tests/js/flow-chart-logic.test.js`,
// no browser, mirroring token-chart-logic.ts's own split from
// TokenCostChart.svelte. IssueFlowChart.svelte imports this and does
// rendering only.

export type Period = 'day' | 'week';

export type FlowMilestoneBreakdown = {
	opened: number;
	closed: number;
	cancelled: number;
	wip: number;
};

export type FlowPoint = {
	date: string;
	opened: number;
	closed: number;
	cancelled: number;
	wip: number;
	by_milestone: Record<string, FlowMilestoneBreakdown>;
};

export type FlowMilestone = {
	id: string;
	name: string | null;
	status: string | null;
};

export type FlowPayload = {
	period: 'day';
	series: FlowPoint[];
	milestones: FlowMilestone[];
	default_milestone: string | null;
	as_of: string | null;
	scope: string;
	warning: string | null;
};

// The scoped, flat point shape the chart actually renders -- either the
// payload's own overall numbers, or one milestone's `by_milestone` entry,
// projected onto the same four-field shape so the rendering code never
// branches on which scope is active.
export type ScopedPoint = {
	date: string;
	opened: number;
	closed: number;
	cancelled: number;
	wip: number;
};

export const ALL_MILESTONES_SCOPE = 'all';

const ZERO_BREAKDOWN: FlowMilestoneBreakdown = { opened: 0, closed: 0, cancelled: 0, wip: 0 };

// §5 (day granularity server-side) + the scope control: pick out either
// the OVERALL numbers already sitting on each point, or one milestone's
// `by_milestone` entry -- a missing entry (a milestone that had not yet
// appeared as of this point, `by_milestone` being dense only from FIRST
// appearance onward) degrades to all-zero, never a crash or `undefined`
// leaking into a chart axis.
export function scopedSeries(series: FlowPoint[], scope: string): ScopedPoint[] {
	if (scope === ALL_MILESTONES_SCOPE) {
		return series.map((p) => ({ date: p.date, opened: p.opened, closed: p.closed, cancelled: p.cancelled, wip: p.wip }));
	}
	return series.map((p) => {
		const m = p.by_milestone[scope] ?? ZERO_BREAKDOWN;
		return { date: p.date, opened: m.opened, closed: m.closed, cancelled: m.cancelled, wip: m.wip };
	});
}

// ISO week start (Monday) of the UTC calendar day `dateStr` names --
// architect's ruling §3/addendum: week buckets group UTC days, week
// start pinned to ISO Monday (never the locale-dependent Sunday start).
export function isoWeekStartUtc(dateStr: string): string {
	const d = new Date(`${dateStr}T00:00:00Z`);
	const weekday = d.getUTCDay(); // 0 = Sunday .. 6 = Saturday
	const daysSinceMonday = weekday === 0 ? 6 : weekday - 1;
	d.setUTCDate(d.getUTCDate() - daysSinceMonday);
	return d.toISOString().slice(0, 10);
}

// The one rule stated explicitly so nobody reaches for `reduce` by
// reflex (architect's ruling, addendum): a week point SUMS the deltas
// (opened/closed/cancelled) across its days, but takes the LAST day's
// `wip` in the week -- summing or averaging a point-in-time count is
// the exact category error PT-85 exists to remove; `wip` unchanged on a
// day with no events is not "zero WIP that day", it is "still whatever
// it last was". `series` must already be chronological (the server's
// own contract) -- this never re-sorts.
export function aggregateToWeeks(series: ScopedPoint[]): ScopedPoint[] {
	const weeks = new Map<string, ScopedPoint[]>();
	for (const point of series) {
		const weekStart = isoWeekStartUtc(point.date);
		const bucket = weeks.get(weekStart);
		if (bucket) {
			bucket.push(point);
		} else {
			weeks.set(weekStart, [point]);
		}
	}
	return Array.from(weeks.entries())
		.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
		.map(([weekStart, points]) => {
			const last = points[points.length - 1];
			return {
				date: weekStart,
				opened: points.reduce((sum, p) => sum + p.opened, 0),
				closed: points.reduce((sum, p) => sum + p.closed, 0),
				cancelled: points.reduce((sum, p) => sum + p.cancelled, 0),
				wip: last.wip,
			};
		});
}

export function aggregateByPeriod(series: ScopedPoint[], period: Period): ScopedPoint[] {
	return period === 'week' ? aggregateToWeeks(series) : series;
}

// Ruling §3 (Milestone scope): default to the milestone with the most
// recent activity, else 'all' -- `default_milestone` is already server-
// resolved (addendum change 3: a TRANSITION day, never standing WIP).
export function defaultScope(payload: FlowPayload): string {
	return payload.default_milestone ?? ALL_MILESTONES_SCOPE;
}

function scopeLabel(payload: FlowPayload, scope: string): string {
	if (scope === ALL_MILESTONES_SCOPE) return 'all milestones';
	const milestone = payload.milestones.find((m) => m.id === scope);
	return milestone?.name ?? scope;
}

// AC 2: caption names the period, the scope, and that WIP is end-of-
// period -- one clause each, composed here (never inlined in the
// component) so the exact wording is unit-testable without a browser.
export function formatFlowCaption(payload: FlowPayload, period: Period, scope: string): string {
	const periodWord = period === 'week' ? 'week' : 'day';
	const parts = [
		`Bars show issues opened and closed per ${periodWord}, scoped to ${scopeLabel(payload, scope)}.`,
		`The WIP line is a point-in-time count (in-progress + in-review) at the END of each ${periodWord}, not an activity count.`,
	];
	if (period === 'week') {
		parts.push('Week totals sum daily opens/closes; WIP is the last day of the week, never a sum.');
	}
	return parts.join(' ');
}
