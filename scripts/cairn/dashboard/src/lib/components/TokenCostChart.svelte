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
		tickEveryNth,
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
	// Browser-verified defect (team-lead's pass on 3aa09e8): the original
	// placeholder reused four ADJACENT steps of PT-61's ordinal flow ramp
	// -- deliberately near-identical golds by design, which is exactly why
	// it read as one indistinguishable swatch and made three of the four
	// series invisible against cache read. A follow-up stopgap borrowed
	// four widely-spaced hues from the categorical role palette instead,
	// but ux-designer's ruling (f9c6417) rejected that reuse too: those
	// hues already carry a fixed per-role meaning in the cost view (AC1's
	// role stack), and reusing them here for an unrelated axis (token
	// type, in the tokens-mode toggle) is a semantic-meaning collision --
	// the same class of issue as PT-69's Paused-badge fix. Uses the
	// dedicated counter-type palette shipped for exactly this purpose
	// instead (see app.css's PT-79 counter-token block): a muted
	// cyan/teal family, distinct in character from both the golden
	// ordinal ramp and the 8-hue role rainbow, so a reader can't mistake
	// a token-type swatch for a role swatch.
	const TOKEN_TYPE_COLOR: Record<(typeof TOKEN_TYPE_KEYS)[number], string> = {
		input: 'var(--chart-counter-input)',
		cache_write: 'var(--chart-counter-cache-write)',
		cache_read: 'var(--chart-counter-cache-read)',
		output: 'var(--chart-counter-output)',
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

	// Browser-verified defect (team-lead's narrow-width re-check on
	// 078ad9e, delta N1): a FIXED row-count reservation (3 rows, 92px)
	// cannot hold -- the cost view's role legend wraps to 4 rows at a
	// 500px viewport, exceeding it and overlapping the plot again, the
	// same failure mode as the original padding regression just at a
	// different width. There is no bar-count/series-count formula that
	// predicts row count without knowing the actual rendered width (the
	// same information the browser's own flex-wrap layout already has),
	// so this measures it directly instead of guessing: a ResizeObserver
	// on the container watches BOTH the container's own width (also
	// feeds the x-axis label thinning below, delta N2) and, via a
	// MutationObserver locating it (layerchart mounts/replaces it after
	// this element exists), the actually-rendered `.lc-legend-container`
	// element's height. `legendHeight`'s initial value matches the old
	// 3-row constant so there's no layout jump before the first
	// measurement lands (typically within a frame of mount).
	let containerWidth = $state(600);
	let legendHeight = $state(92);

	function measureChart(node: HTMLElement) {
		const ro = new ResizeObserver((entries) => {
			for (const entry of entries) {
				if (entry.target === node) {
					containerWidth = entry.contentRect.width;
				} else {
					const h = entry.contentRect.height;
					if (h > 0) legendHeight = Math.ceil(h);
				}
			}
		});
		ro.observe(node);

		let observedLegend: Element | null = null;
		function syncLegendObservation() {
			const el = node.querySelector('.lc-legend-container');
			if (el && el !== observedLegend) {
				if (observedLegend) ro.unobserve(observedLegend);
				observedLegend = el;
				ro.observe(el);
			}
		}
		syncLegendObservation();
		const mo = new MutationObserver(syncLegendObservation);
		mo.observe(node, { childList: true, subtree: true });

		return {
			destroy() {
				ro.disconnect();
				mo.disconnect();
			},
		};
	}

	// Browser-verified regression (team-lead's re-check on b934262): once the
	// y-axis-clipping fix below supplied an explicit `padding` object,
	// layerchart's own default padding computation (states/chart.svelte.js's
	// `padding` getter, node_modules/layerchart/dist/states/chart.svelte.js:816
	// -- only calls `defaultChartPadding({ axis, legend, ... })` when the
	// caller's padding prop is null) was bypassed entirely; any explicit
	// padding object merges against a bare `{top:0,right:0,bottom:0,left:0}`
	// instead. `defaultChartPadding` normally reserves bottom: 20 (x-axis
	// labels) + 32 (one legend row) -- dropping that same reservation to 0 is
	// exactly why the legend (position: absolute; bottom: 0, per layerchart's
	// own Legend.svelte) ended up drawn on top of the bars and x-axis instead
	// of in its own row below them. Reproduces the rest of the library's
	// default here (top/right unchanged, left overridden as before); the
	// bottom reservation now tracks the MEASURED legend height (see
	// measureChart above) rather than a guessed row count.
	const CHART_PADDING = $derived({
		top: 4,
		right: 4,
		left: 64,
		bottom: 20 + legendHeight,
	});

	// Browser-verified defect: Show-all's 69 x-axis labels overlapped into
	// an unreadable smear -- layerchart's default band-axis tick generator
	// renders one label per bar with no density awareness. team-lead's
	// narrow-width re-check (delta N2) found the original fix's fixed
	// 20-bar-count threshold was itself the wrong axis to thin on: 13 bars
	// already overlap at a 500px viewport, well under 20, because what
	// actually determines overlap is PIXELS PER BAR vs. LABEL WIDTH, not
	// bar count -- the same count fits fine at 1553px. Measures both:
	// `containerWidth` (measureChart's ResizeObserver, above) divided by
	// bar count gives the real per-bar pixel budget, and each label's
	// actual rendered width via canvas measureText (close enough to the
	// real SVG text width for a spacing decision -- exact font metrics
	// aren't load-bearing here, only "does the next label collide").
	// Thins to the smallest step that gives every visible label its own
	// width plus a breathing gap, always keeping `main` (the last bar).
	// The step MATH is token-chart-logic.ts's tickEveryNth (pure, unit-
	// tested without a browser/DOM) -- this only measures the two real
	// numbers it needs: the actual plot width (measureChart's
	// ResizeObserver, above) and each label's actual rendered width via
	// canvas measureText (close enough to the real SVG text width for a
	// spacing decision -- exact font metrics aren't load-bearing here,
	// only "does the next label collide").
	const X_AXIS_LABEL_FONT = '12px ui-sans-serif, system-ui, sans-serif';
	let measureCanvasCtx: CanvasRenderingContext2D | null | undefined;
	function measureLabelWidth(text: string): number {
		if (measureCanvasCtx === undefined) {
			measureCanvasCtx = typeof document === 'undefined' ? null : (document.createElement('canvas').getContext('2d') ?? null);
		}
		if (!measureCanvasCtx) return text.length * 7;
		measureCanvasCtx.font = X_AXIS_LABEL_FONT;
		return measureCanvasCtx.measureText(text).width;
	}
	const xAxisTicks = $derived.by(() => {
		const ids = chartData.map((d) => d.issue as string);
		if (ids.length === 0) return undefined;
		const plotWidth = Math.max(containerWidth - CHART_PADDING.left - CHART_PADDING.right, 0);
		const maxLabelWidth = Math.max(...ids.map(measureLabelWidth));
		const step = tickEveryNth(ids.length, plotWidth, maxLabelWidth);
		if (step <= 1) return undefined;
		return ids.filter((id, i) => i % step === 0 || id === 'main');
	});

	function onBarClick(_event: MouseEvent, detail: { data: Record<string, string | number> }): void {
		const issue = detail.data.issue as string;
		// Ruling § 4: main "must not look clickable" -- no drawer link.
		if (issue === 'main') return;
		// Browser-verified defect (team-lead's re-check on b934262): the
		// drawer never opened. Root cause -- App.svelte (PT-72) reads its
		// OWN shell-level `?issue=<id>` query param and translates THAT
		// into `&open=<id>` for the embedded Issue Tracking board's own
		// iframe src (see App.svelte's `issueTrackingOpenSuffix`); a link
		// carrying `?open=` directly is a key the shell never reads, so
		// it's silently ignored. board.js's own equivalent navigation
		// (Kanban card -> full board) already uses the shell's real param
		// name -- match it exactly.
		window.location.href = `/dashboard/issues?issue=${encodeURIComponent(issue)}`;
	}

	// Browser-verified defect: a real click on a bar did nothing.
	// layerchart's BarChart renders an invisible hit-detection overlay
	// (TooltipContext, tooltipContext="band" by default) ON TOP of the
	// actual <rect> bars to drive the hover tooltip -- that overlay
	// intercepts the pointer event before it ever reaches Bars' own
	// onclick, so wiring only `onBarClick` (which attaches to the bars
	// themselves) is a real click handler nothing can actually reach.
	// The tooltip layer has its OWN onclick, fed the currently-hovered
	// datum -- that is the one guaranteed to receive the click.
	function onTooltipClick(event: MouseEvent, detail: { data: Record<string, string | number> | null }): void {
		if (!detail.data) return;
		onBarClick(event, { data: detail.data });
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
				<div use:measureChart class="relative">
				<Chart.Container config={chartConfig} class="aspect-auto h-[300px] w-full">
					<BarChart
						data={chartData}
						x="issue"
						xScale={scaleBand()}
						{series}
						seriesLayout="stack"
						legend
						{onBarClick}
						tooltipContext={{ onclick: onTooltipClick }}
						padding={CHART_PADDING}
						props={{
							xAxis: {
								ticks: xAxisTicks,
							},
							yAxis: {
								format: (v: number) => (mode === 'cost' ? formatUsd(v) : formatTokens(v)),
							},
							bars: {
								// Browser-verified defect (team-lead's re-check on
								// b934262): a top-level fillOpacity prop directly on
								// BarChart is not a real prop of the component --
								// BarChart.base.svelte spreads unrecognized props onto
								// Chart via restProps, never down into Bars/Bar, so it
								// never reached a rendered rect (every computed
								// fillOpacity read back as 1). This props.bars nesting
								// IS spread onto each Bars instance by
								// BarChart.base.svelte's marks snippet, which forwards
								// unrecognized props straight through to Bar via
								// extractLayerProps -- see Bars.base.svelte -- and Bar
								// explicitly supports fillOpacity as a per-datum
								// accessor via resolveStyleProp -- this is the layer
								// that actually reaches the rect.
								fillOpacity: (d: Record<string, string | number>) => (d.issue === 'main' ? 0.55 : 1),
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
				</div>
				<p class="mt-3 text-xs text-muted-foreground">{captionText}</p>
			{/if}
		</Card.Content>
	</Card.Root>
</section>

<style>
	/* Browser-verified defect (team-lead's 570px-viewport pass): layerchart's
	   own Legend renders its swatch row as `display: flex` with no
	   `flex-wrap` (see node_modules/layerchart/dist/components/Legend.svelte
	   -- `.lc-legend-swatch-group`), so at narrow widths the first/last
	   entries (e.g. architect, Other) clip out of view entirely rather than
	   reflowing -- both the counter legend (tokens view) and the role
	   legend (cost view) use this same element. layerchart's own rule is
	   wrapped in `:where(...)` (zero specificity), so a plain :global
	   class selector here overrides it cleanly with no specificity fight. */
	:global(.lc-legend-swatch-group) {
		flex-wrap: wrap;
	}
</style>
