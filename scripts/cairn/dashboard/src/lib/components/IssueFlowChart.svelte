<script lang="ts">
	import { onDestroy } from 'svelte';
	import { scaleBand } from 'd3-scale';
	import { BarChart, Bars, Spline } from 'layerchart';
	import * as Card from '$lib/components/ui/card/index.js';
	import * as Chart from '$lib/components/ui/chart/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { subscribeFlow, type FlowPayload } from '$lib/dashboard-api';
	import {
		ALL_MILESTONES_SCOPE,
		aggregateByPeriod,
		defaultScope,
		formatFlowCaption,
		scopedSeries,
		type Period,
	} from '$lib/flow-chart-logic';

	// PT-85 (architect ruling 409d310, shape pinned 2f8eba0): replaces
	// PT-61's cumulative status-stack area chart with a throughput view --
	// opened/closed bars plus a WIP line, day/week toggle, milestone scope
	// control. Same /api/flow data source, own poll, own three-state
	// error/skeleton/content shape (PT-61's own precedent, unchanged).
	let flow = $state<FlowPayload | null>(null);
	let flowError = $state<string | null>(null);
	let tableView = $state(false);
	let period = $state<Period>('day');
	// 'all' or a milestone id -- initialised once the first payload
	// arrives (architect's ruling §3: default to the milestone with the
	// most recent activity); a later poll never resets a scope the user
	// already picked.
	let scope = $state<string | null>(null);

	const unsubscribe = subscribeFlow(
		(payload) => {
			flow = payload;
			flowError = null;
			if (scope === null) {
				scope = defaultScope(payload);
			}
		},
		(err) => {
			flowError = err instanceof Error ? err.message : String(err);
		},
	);
	onDestroy(unsubscribe);

	// §9 (architect ruling 586af1f -- supersedes an earlier ramp-reuse
	// proposal of mine, rejected: three ramp steps are three shades of
	// one hue, the wrong encoding for a contrast a reader must make at a
	// glance). PT-85's 3 series are CATEGORICAL, not ordinal -- the old
	// 6-token --chart-flow-* ramp is retired entirely (all six, both
	// app.css and variants.css). Three NEW dedicated tokens, sourced
	// from the dataviz skill's validated categorical palette, chosen so
	// all three are mutually distinguishable and none lands on a
	// --chart-role-* hue on this same page (team-lead's decision; full
	// picks + validate_palette.js output recorded on PT-85 and in
	// app.css's own comment). Interim, not final -- PT-92 is filed for
	// a ux-designer eye on the specific hex values.
	const SERIES_COLOR = {
		opened: 'var(--chart-flow-opened)',
		closed: 'var(--chart-flow-closed)',
		wip: 'var(--chart-flow-wip)',
	};
	const SERIES_LABEL = { opened: 'Opened', closed: 'Closed', wip: 'WIP (end of period)' };

	const chartConfig = {
		opened: { label: SERIES_LABEL.opened, color: SERIES_COLOR.opened },
		closed: { label: SERIES_LABEL.closed, color: SERIES_COLOR.closed },
		wip: { label: SERIES_LABEL.wip, color: SERIES_COLOR.wip },
	} satisfies Chart.ChartConfig;

	const barSeries = [
		{ key: 'opened', label: SERIES_LABEL.opened, color: SERIES_COLOR.opened },
		{ key: 'closed', label: SERIES_LABEL.closed, color: SERIES_COLOR.closed },
	];

	// Selection order: scope first (server-native, per-point), THEN period
	// aggregation (client-side, pure -- flow-chart-logic.ts's own
	// contract: sum the deltas, take the LAST wip of the week, never a
	// sum/mean of a point-in-time value).
	const displayedSeries = $derived(
		flow ? aggregateByPeriod(scopedSeries(flow.series, scope ?? ALL_MILESTONES_SCOPE), period) : [],
	);

	const captionText = $derived(flow ? formatFlowCaption(flow, period, scope ?? ALL_MILESTONES_SCOPE) : '');

	// yDomain must cover all three plotted values -- BarChart's own
	// auto-domain only considers the declared bar series (opened/closed);
	// the WIP line, drawn as an extra Spline mark sharing the same scale,
	// would clip silently at the bars' own max otherwise.
	const yMax = $derived(
		displayedSeries.reduce((max, p) => Math.max(max, p.opened, p.closed, p.wip), 0),
	);
	const yDomain = $derived([0, yMax === 0 ? 1 : yMax] as [number, number]);
</script>

<!-- PT-85: throughput view -- issues opened/closed per period (bars),
     issues in flight at period end (WIP line), scoped to one milestone
     or all. Replaces PT-61's cumulative status-stack chart entirely
     (architect's ruling §7: retired, not toggled). -->
<section aria-label="Issue throughput over time">
	<Card.Root class="[--card-spacing:1.5rem]">
		<Card.Header class="flex flex-wrap items-center justify-between gap-2 space-y-0">
			<div class="grid gap-1">
				<Card.Title class="text-lg">Issue throughput</Card.Title>
				{#if flow}
					<Card.Description class="text-xs">{captionText} {flow.scope}</Card.Description>
				{/if}
			</div>
			{#if flow && flow.series.length > 0 && !flow.warning}
				<div class="flex flex-wrap items-center gap-2">
					{#if flow.milestones.length > 0}
						<!-- Milestone scope control (ruling §3): a plain native
						     select -- this control has no other requirement
						     (styling, search, etc.) named in the ruling, and a
						     native element is free accessibility. Archived
						     milestones are selectable: `flow.milestones` already
						     includes them (server-side, no client-side filter). -->
						<label class="flex items-center gap-1 text-xs text-muted-foreground">
							Milestone
							<select
								class="h-8 rounded-md border border-input bg-background px-2 text-xs"
								bind:value={scope}
								aria-label="Scope to one milestone, or all"
							>
								<option value={ALL_MILESTONES_SCOPE}>All milestones</option>
								{#each flow.milestones as m (m.id)}
									<option value={m.id}>{m.name ?? m.id}</option>
								{/each}
							</select>
						</label>
					{/if}
					<div class="flex items-center gap-1" role="group" aria-label="Period">
						<Button variant={period === 'day' ? 'default' : 'outline'} size="sm" onclick={() => (period = 'day')}>
							Day
						</Button>
						<Button variant={period === 'week' ? 'default' : 'outline'} size="sm" onclick={() => (period = 'week')}>
							Week
						</Button>
					</div>
					<!-- dataviz skill (components.md): every chart carries a
					     table-view toggle, the WCAG-clean accessibility twin. -->
					<Button variant="outline" size="sm" onclick={() => (tableView = !tableView)}>
						{tableView ? 'Show chart' : 'Show table'}
					</Button>
				</div>
			{/if}
		</Card.Header>
		<Card.Content>
			{#if flowError && !flow}
				<p class="text-sm text-destructive">
					Couldn't load issue throughput history: {flowError}
				</p>
			{:else if flow === null}
				<Skeleton class="h-[250px] w-full" />
			{:else if flow.warning}
				<p class="text-sm text-muted-foreground">{flow.warning}</p>
			{:else if flow.series.length === 0}
				<p class="text-sm text-muted-foreground">
					No committed issue history yet — this fills in as issues open, close, or change status
					over time.
				</p>
			{:else if displayedSeries.length < 2 || tableView}
				{#if displayedSeries.length < 2}
					<p class="mb-3 text-sm text-muted-foreground">
						Only {displayedSeries.length} {period}{displayedSeries.length === 1 ? '' : 's'} of committed
						history so far — not enough to plot a trend yet.
					</p>
				{/if}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<caption class="sr-only">Issue throughput, one row per {period}</caption>
						<thead>
							<tr class="border-b border-border">
								<th class="py-2 pr-4 text-left font-medium text-muted-foreground">
									{period === 'week' ? 'Week of' : 'Date'}
								</th>
								<th class="py-2 pr-4 text-right font-medium text-muted-foreground">Opened</th>
								<th class="py-2 pr-4 text-right font-medium text-muted-foreground">Closed</th>
								<th class="py-2 pr-4 text-right font-medium text-muted-foreground">WIP</th>
								<th class="py-2 pr-4 text-right font-medium text-muted-foreground">Cancelled</th>
							</tr>
						</thead>
						<tbody>
							{#each displayedSeries as point (point.date)}
								<tr class="border-b border-border last:border-0">
									<td class="py-2 pr-4 font-mono">{point.date}</td>
									<td class="py-2 pr-4 text-right font-mono">{point.opened}</td>
									<td class="py-2 pr-4 text-right font-mono">{point.closed}</td>
									<td class="py-2 pr-4 text-right font-mono">{point.wip}</td>
									<td class="py-2 pr-4 text-right font-mono">{point.cancelled}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<Chart.Container config={chartConfig} class="aspect-auto h-[280px] w-full">
					<BarChart
						data={displayedSeries}
						x="date"
						xScale={scaleBand()}
						series={barSeries}
						seriesLayout="group"
						legend
						{yDomain}
						props={{
							yAxis: { format: (v: number) => String(v) },
						}}
					>
						{#snippet marks({ context })}
							{#each context.series.visibleSeries as s (s.key)}
								<Bars seriesKey={s.key} radius={2} {...s.props} />
							{/each}
							<!-- WIP overlaid as a line on the SAME shared scale
							     (yDomain above forces it to cover the line too) --
							     point-in-time, deliberately never a bar (a bar
							     would visually read as another delta, exactly the
							     "two gap semantics in one shape" defect PT-85
							     exists to remove). -->
							<Spline
								data={displayedSeries}
								x={(d: { date: string }) => d.date}
								y={(d: { wip: number }) => d.wip}
								stroke={SERIES_COLOR.wip}
								class="stroke-2"
							/>
						{/snippet}
						{#snippet tooltip()}
							<Chart.Tooltip
								indicator="line"
								class="z-50 bg-popover text-popover-foreground ring-1 ring-border"
							/>
						{/snippet}
					</BarChart>
				</Chart.Container>
			{/if}
		</Card.Content>
	</Card.Root>
</section>
