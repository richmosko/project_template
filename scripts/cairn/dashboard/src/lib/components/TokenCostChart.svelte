<script lang="ts">
	import { onDestroy } from 'svelte';
	import { scaleBand } from 'd3-scale';
	import { BarChart } from 'layerchart';
	import * as Card from '$lib/components/ui/card/index.js';
	import * as Chart from '$lib/components/ui/chart/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { subscribeTokens, type TokensPayload, type TokenIssueTotal } from '$lib/dashboard-api';
	import {
		DEFAULT_BAR_LIMIT,
		selectBars,
		formatCaption,
		ROLE_TOKEN_ORDER,
		roleTokenSeries,
		type Metric,
	} from '$lib/token-chart-logic';

	// PT-79 (architect ruling): /api/tokens is a SEPARATE data source from
	// /api/dashboard and /api/flow -- own poll, own three-state error/
	// skeleton/content shape, IssueFlowChart's established pattern repeated
	// here rather than threaded through the parent (this whole component is
	// dynamically imported for the same reason IssueFlowChart is: keep the
	// chart library out of the main bundle).
	let tokens = $state<TokensPayload | null>(null);
	let tokensError = $state<string | null>(null);
	let mode = $state<Metric>('tokens');
	let showAll = $state(false);

	const unsubscribe = subscribeTokens(
		(payload) => {
			tokens = payload;
			tokensError = null;
		},
		(err) => {
			tokensError = err instanceof Error ? err.message : String(err);
		},
	);
	onDestroy(unsubscribe);

	// Tokens-mode series: the four counters, ALWAYS this fixed set,
	// regardless of which roles contributed -- ruling § 4: "role is the
	// stack (AC1) and token type is the toggle's tokens mode," the two
	// stacks never share an axis.
	const TOKEN_TYPE_KEYS = ['input', 'cache_write', 'cache_read', 'output'] as const;
	const TOKEN_TYPE_LABEL: Record<(typeof TOKEN_TYPE_KEYS)[number], string> = {
		input: 'Input',
		cache_write: 'Cache write',
		cache_read: 'Cache read',
		output: 'Output',
	};
	// TODO(ux-designer, blocked on architect amendment ad940d3 §2): app.css
	// carries no PT-79-specific color tokens yet, per that amendment's
	// explicit "implementation-lead should not touch app.css" instruction
	// -- the categorical role/token-type palette is an escalated
	// design-system decision (hue values AND, for roles, list membership),
	// not settled here. Built against EXISTING, already-validated tokens
	// in the meantime ("TODO marker, palette swapped in afterwards"):
	// four of PT-61's own six --chart-flow-* steps (the ordinal ramp
	// already cleared the light/dark contrast floor against this card
	// surface) -- deliberately NOT --chart-1/--chart-2, which PT-61's own
	// finding measured failing that floor (1.33:1 / 1.91:1 vs. the 2:1
	// gate). Reused as a stand-in only; token type has no real ordinal
	// relationship to status, so this is NOT a claim these are the right
	// long-term colors, only that they are already-safe ones.
	const TOKEN_TYPE_COLOR: Record<(typeof TOKEN_TYPE_KEYS)[number], string> = {
		input: 'var(--chart-flow-todo)',
		cache_write: 'var(--chart-flow-in-progress)',
		cache_read: 'var(--chart-flow-in-review)',
		output: 'var(--chart-flow-done)',
	};
	// The real, designed categorical role palette (ux-designer's proposal,
	// commit fd6df5c, docs/DESIGN/design-system-spec.md § Categorical role
	// palette (PT-79); unblocked by architect's mechanism amendment,
	// 962f3e9). 8 role hues, index-matched to ROLE_TOKEN_ORDER exactly
	// (position 0 -> --chart-role-1, etc.), PLUS three separate neutral
	// fold/guard tokens -- never one shared grey -- so `auxiliary`
	// (routine cheap-model overhead) and `subagent-unattributed` (the
	// role-resolution failure guard) stay visually distinct from each
	// other and from a role simply outside the 8-slot budget.
	const ROLE_SLOT_COLOR = [
		'var(--chart-role-1)',
		'var(--chart-role-2)',
		'var(--chart-role-3)',
		'var(--chart-role-4)',
		'var(--chart-role-5)',
		'var(--chart-role-6)',
		'var(--chart-role-7)',
		'var(--chart-role-8)',
	];
	const GUARD_COLOR: Record<string, string> = {
		auxiliary: 'var(--chart-role-guard-aux)',
		'subagent-unattributed': 'var(--chart-role-guard-unattributed)',
		other: 'var(--chart-role-other)',
	};
	const SERIES_LABEL: Record<string, string> = {
		auxiliary: 'Auxiliary',
		'subagent-unattributed': 'Unattributed',
		other: 'Other',
	};
	function roleColor(role: string): string {
		const series = roleTokenSeries(role);
		if (series in GUARD_COLOR) return GUARD_COLOR[series];
		const idx = ROLE_TOKEN_ORDER.indexOf(role);
		return ROLE_SLOT_COLOR[idx];
	}

	// Selection AND order follow the CURRENTLY DISPLAYED metric
	// (token-chart-logic.ts's selectBars -- team-lead's ruling: order
	// follows the toggle; architect's ruling: selection is the necessary
	// consequence). `main` is always appended last by selectBars itself,
	// never part of the ranked cut, never subject to "Show all".
	const allIssues = $derived(tokens?.issues ?? []);
	const realCount = $derived(allIssues.filter((i) => i.issue !== 'main').length);
	const displayedIssues = $derived(selectBars(allIssues, mode, DEFAULT_BAR_LIMIT, showAll));
	const shownCount = $derived(displayedIssues.filter((i) => i.issue !== 'main').length);

	// Cost view's role set is open-ended -- folded through roleTokenSeries
	// so a role outside the 8-slot budget (or one of the two synthetic
	// pseudo-roles) never gets its own hue, it merges into its named
	// guard/fold series (ad940d3 §2's fold rule; design-system-spec's
	// three-way guard split). The three fold series always sort last,
	// `other` last of the three -- role hues stay primary reading order.
	const series = $derived(
		mode === 'cost'
			? Array.from(new Set(displayedIssues.flatMap((i) => i.roles.map((r) => roleTokenSeries(r.role)))))
					.sort((a, b) => {
						const aFold = a in GUARD_COLOR;
						const bFold = b in GUARD_COLOR;
						if (aFold !== bFold) return aFold ? 1 : -1;
						return a.localeCompare(b);
					})
					.map((key) => ({
						key,
						label: SERIES_LABEL[key] ?? key,
						color: key in GUARD_COLOR ? GUARD_COLOR[key] : roleColor(key),
					}))
			: TOKEN_TYPE_KEYS.map((key) => ({ key, label: TOKEN_TYPE_LABEL[key], color: TOKEN_TYPE_COLOR[key] })),
	);

	const chartConfig = $derived(
		Object.fromEntries(series.map((s) => [s.key, { label: s.label, color: s.color }])) satisfies Chart.ChartConfig,
	);

	function rowFor(issue: TokenIssueTotal): Record<string, string | number> {
		const row: Record<string, string | number> = { issue: issue.issue };
		if (mode === 'cost') {
			for (const r of issue.roles) {
				const key = roleTokenSeries(r.role);
				row[key] = (row[key] as number | undefined ?? 0) + (r.cost_usd ?? 0);
			}
		} else {
			for (const key of TOKEN_TYPE_KEYS) {
				row[key] = issue.total[key];
			}
		}
		return row;
	}

	const chartData = $derived(displayedIssues.map(rowFor));

	function onBarClick(_event: MouseEvent, detail: { data: Record<string, string | number> }): void {
		const issue = detail.data.issue as string;
		// Ruling § 4: main "must not look clickable" -- no drawer link.
		if (issue === 'main') return;
		// AC4's drawer lives in board.js, a different page entirely --
		// a real navigation (App.svelte's own anchors carry real hrefs
		// for the identical reason: a hard load still works through
		// PT-54's SPA fallback).
		window.location.href = `/dashboard/issues?open=${encodeURIComponent(issue)}`;
	}

	function formatTokens(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return String(n);
	}

	function formatUsd(n: number): string {
		return `$${n.toFixed(2)}`;
	}

	const captionText = $derived.by(() => {
		if (!tokens) return '';
		return formatCaption(tokens, mode, shownCount, realCount);
	});
</script>

<!-- PT-79: the token/cost block named in the AC -- one bar per issue (plus
     main), stacked by role (cost view) or by token type (tokens view).
     Architect's amendment (ad940d3 §1, correcting the original ruling's
     §3): follows IssueFlowChart's LITERAL pattern -- own <section>, own
     Card.Root, no grid/col-span classes -- a full-width panel sitting
     beside the flow chart, not a member of the 4-column status grid. -->
<section aria-label="Token usage and estimated cost">
	<Card.Root class="[--card-spacing:1.5rem]">
		<Card.Header class="flex flex-wrap items-center justify-between gap-2 space-y-0">
			<div class="grid gap-1">
				<Card.Title class="text-lg">Token usage and estimated cost</Card.Title>
			</div>
			{#if tokens && tokens.issues.length > 0 && !tokens.warning}
				<div class="flex items-center gap-2">
					<Button variant={mode === 'tokens' ? 'default' : 'outline'} size="sm" onclick={() => (mode = 'tokens')}>
						Tokens
					</Button>
					<Button variant={mode === 'cost' ? 'default' : 'outline'} size="sm" onclick={() => (mode = 'cost')}>
						Estimated cost
					</Button>
					{#if realCount > DEFAULT_BAR_LIMIT}
						<Button variant="outline" size="sm" onclick={() => (showAll = !showAll)}>
							{showAll ? `Show top ${DEFAULT_BAR_LIMIT}` : 'Show all'}
						</Button>
					{/if}
				</div>
			{/if}
		</Card.Header>
		<Card.Content>
			{#if tokensError && !tokens}
				<p class="text-sm text-destructive">
					Couldn't load token usage: {tokensError}
				</p>
			{:else if tokens === null}
				<Skeleton class="h-[300px] w-full" />
			{:else if tokens.warning}
				<!-- Degraded-but-200 case -- no metrics file written yet
				     (PT-77/PT-78 haven't run). build_tokens_payload's own
				     warning text, not a fabricated one. -->
				<p class="text-sm text-muted-foreground">{tokens.warning}</p>
			{:else if tokens.issues.length === 0}
				<p class="text-sm text-muted-foreground">
					No token usage recorded yet — this fills in once the backfill or the live receiver writes data.
				</p>
			{:else}
				<Chart.Container config={chartConfig} class="aspect-auto h-[300px] w-full">
					<BarChart
						data={chartData}
						x="issue"
						xScale={scaleBand()}
						{series}
						seriesLayout="stack"
						legend
						{onBarClick}
						props={{
							yAxis: {
								format: (v: number) => (mode === 'cost' ? formatUsd(v) : formatTokens(v)),
							},
						}}
					>
						{#snippet tooltip()}
							<Chart.Tooltip
								indicator="line"
								class="z-50 bg-popover text-popover-foreground ring-1 ring-border"
								formatter={(v: number) => (mode === 'cost' ? formatUsd(v) : formatTokens(v))}
							/>
						{/snippet}
					</BarChart>
				</Chart.Container>
				<p class="mt-3 text-xs text-muted-foreground">{captionText}</p>
			{/if}
		</Card.Content>
	</Card.Root>
</section>
