// PT-79: the pure selection/sort/caption seam for the token/cost
// dashboard block (architect's addendum, a375ff7, "token-chart-logic.ts
// -- the pure seam"; role-palette mechanism amended, ad940d3 §2).
// Deliberately has NO svelte/DOM/fetch dependency -- every selection,
// ordering, and caption-string assertion belongs here, tested via
// `node --test scripts/cairn/tests/js/token-chart-logic.test.js`, no
// browser, mirroring how board-logic.js is already split from board.js.
// TokenCostChart.svelte imports this and does rendering only.

export const DEFAULT_BAR_LIMIT = 12;

export type Metric = 'tokens' | 'cost';

export type TokenCounters = {
	input: number;
	cache_write: number;
	cache_read: number;
	output: number;
	cost_usd: number | null;
};

export type TokenIssueTotal = {
	issue: string;
	total: TokenCounters;
	roles: Array<TokenCounters & { role: string }>;
};

export type TokensPayload = {
	issues: TokenIssueTotal[];
	window_start: string | null;
	window_end: string | null;
	generated: string | null;
	sources: string[];
	prices: {
		retrieved: string | null;
		source: string | null;
		unpriced_models: string[];
	};
	warning: string | null;
};

// The raw value one issue contributes on the currently displayed axis --
// summed tokens (all four counters) for 'tokens', cost_usd (0 when
// unpriced/null -- a bar chart has no way to draw "unknown height") for
// 'cost'.
export function barValue(issue: TokenIssueTotal, metric: Metric): number {
	if (metric === 'cost') {
		return issue.total.cost_usd ?? 0;
	}
	return issue.total.input + issue.total.cache_write + issue.total.cache_read + issue.total.output;
}

// Top-N by the DISPLAYED metric, `main` always appended LAST regardless
// of its own rank or value -- never subject to the top-N cut, never
// sorted in among the ranked real issues. Selection AND order both
// follow `metric` (architect's ruling, PT-79 §4): the top-12-by-tokens
// and top-12-by-cost sets differ on the real corpus, so pinning
// selection to one metric would make the other view silently omit real
// contenders while still calling itself complete.
// team-lead's narrow-width re-check on 078ad9e (delta N2): the ORIGINAL
// x-axis label-thinning fix used a fixed 20-bar-count threshold, so 13
// bars never thinned regardless of viewport width -- but 13 bars already
// overlap at a 500px plot, and the same 13 fit fine at 1200px. What
// actually determines overlap is pixels-per-bar vs. label width, not bar
// count, so this takes both as inputs (extracted here, not left inline
// in TokenCostChart.svelte, so it's unit-testable without a browser/DOM
// -- the component's own job is only to MEASURE the real plot width and
// label width via a ResizeObserver/canvas measureText and hand both
// numbers to this pure function). `X_AXIS_LABEL_GAP` is a small breathing
// margin between adjacent visible labels, baked in here rather than a
// 4th parameter -- this function's whole contract is "given these three
// numbers, what step", not a place to grow a second knob.
const X_AXIS_LABEL_GAP = 8;

export function tickEveryNth(barCount: number, plotWidthPx: number, labelWidthPx: number): number {
	if (barCount <= 0) return 1;
	const perBarWidth = plotWidthPx / barCount;
	const neededWidth = labelWidthPx + X_AXIS_LABEL_GAP;
	if (perBarWidth >= neededWidth) return 1;
	return Math.max(1, Math.ceil(neededWidth / perBarWidth));
}

export function selectBars(
	issues: TokenIssueTotal[],
	metric: Metric,
	limit: number = DEFAULT_BAR_LIMIT,
	showAll: boolean = false,
): TokenIssueTotal[] {
	const real = issues.filter((i) => i.issue !== 'main');
	const main = issues.find((i) => i.issue === 'main');
	const ranked = [...real].sort((a, b) => barValue(b, metric) - barValue(a, metric));
	const visible = showAll ? ranked : ranked.slice(0, limit);
	return main ? [...visible, main] : visible;
}

// Addendum's exact caption string shapes (verbatim sentence order):
// tokens view leads "Tokens are exact.", cost view leads with the
// "estimated" dollar caveat naming prices.retrieved; both then state
// what's shown (top-N-of-total, or "all N" when nothing was cut) and the
// retention-window caveat; the unpriced-models suffix is appended only
// when non-empty. Every value interpolated from `payload` -- no literal
// dates or counts hardcoded in the component that calls this.
export function formatCaption(payload: TokensPayload, metric: Metric, shown: number, total: number): string {
	const parts: string[] = [];
	if (metric === 'cost') {
		parts.push(
			`Dollars are estimated from published list prices retrieved ${payload.prices.retrieved ?? 'unknown'} — standard speed, global inference, no discounts.`,
		);
	} else {
		parts.push('Tokens are exact.');
	}

	const basis = metric === 'cost' ? 'estimated cost' : 'tokens';
	if (shown >= total) {
		parts.push(`Showing all ${total} issues, ordered by ${basis}.`);
	} else {
		parts.push(`Showing the top ${shown} of ${total} issues by ${basis}, plus main.`);
	}

	parts.push(
		`History begins ${payload.window_start ?? 'unknown'}; earlier work predates the local transcript retention window and was never recorded.`,
	);

	const unpriced = payload.prices.unpriced_models ?? [];
	if (unpriced.length > 0) {
		parts.push(`${unpriced.length} model(s) have no published rate and are excluded from cost: ${unpriced.join(', ')}.`);
	}

	return parts.join(' ');
}

// PT-79 amendment (ad940d3 §2): the role-color ASSIGNMENT MECHANISM is
// ruled here (a pure function of role name, via this explicit append-only
// list -- never roster directory order, never rank in the current
// payload, so a role keeps its colour across reloads AND across data
// changes). The 8 hue values AND this membership list were an escalated
// design-system decision (ux-designer's token proposal, commit fd6df5c;
// mechanism amendment 962f3e9 unblocked applying it) -- see
// docs/DESIGN/design-system-spec.md § Categorical role palette (PT-79)
// for the full derivation/evidence. Order here matches app.css's
// --chart-role-1..8 index exactly (position 0 -> --chart-role-1, etc.).
// `frontend-lead`/`backend-lead` were considered and explicitly folded
// into `other` (both are Implement-phase specialist variants
// `implementation-lead` already covers as the generalist case, and were
// the two lowest-volume roles in the real corpus at decision time) --
// promoting either later is a pure append to this list, never a
// reshuffle of the existing 8. `mcp-broker` was already outside the
// 10-role enumeration this decision was made against.
export const ROLE_TOKEN_ORDER: string[] = [
	'team-lead',
	'product-manager',
	'architect',
	'ux-designer',
	'seceng',
	'devops-engineer',
	'implementation-lead',
	'qa-engineer',
];

// Three distinct fold buckets, not one shared grey (design-system-spec's
// "Guard series and the 'other' fold" section, ad940d3 §2's "a grouped
// bucket must announce itself"): `auxiliary` (cheap-model overhead) and
// `subagent-unattributed` (the role-resolution failure guard -- "guards
// should be visible") each get their OWN neutral, distinct from the
// generic `other` fold for any role simply outside ROLE_TOKEN_ORDER.
// Collapsing all three into one grey would make it impossible to tell,
// at a glance, routine overhead from an attribution failure worth
// investigating. The caller maps these three series keys to
// --chart-role-guard-aux / --chart-role-guard-unattributed /
// --chart-role-other respectively -- this function only answers "which
// of the (up to) 11 series does this one role belong to".
export function roleTokenSeries(role: string): string {
	if (ROLE_TOKEN_ORDER.includes(role)) return role;
	if (role === 'auxiliary') return 'auxiliary';
	if (role === 'subagent-unattributed') return 'subagent-unattributed';
	return 'other';
}
