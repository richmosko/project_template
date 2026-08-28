<script lang="ts">
	import { onDestroy } from 'svelte';
	import { scaleUtc } from 'd3-scale';
	import { Area, AreaChart } from 'layerchart';
	import * as Card from '$lib/components/ui/card/index.js';
	import * as Chart from '$lib/components/ui/chart/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { subscribeFlow, type FlowPayload } from '$lib/dashboard-api';

	// PT-61 (architect ruling): /api/flow is a SEPARATE data source from
	// /api/dashboard (own poll, own three-state error/skeleton/content
	// shape -- roster's established pattern in App.svelte, repeated here
	// rather than threaded through the parent, since this whole component
	// is dynamically imported specifically so layerchart lands in its own
	// bundle chunk).
	let flow = $state<FlowPayload | null>(null);
	let flowError = $state<string | null>(null);
	let tableView = $state(false);

	const unsubscribe = subscribeFlow(
		(payload) => {
			flow = payload;
			flowError = null;
		},
		(err) => {
			flowError = err instanceof Error ? err.message : String(err);
		},
	);
	onDestroy(unsubscribe);

	// Same STATUS_ORDER the server's counts keys come from (App.svelte's
	// STATUS_BADGE_VARIANT uses the identical key set) -- this is only the
	// chart's display label + color map, never a second taxonomy: the
	// series actually plotted are driven by whatever keys the server sent,
	// this just supplies text/color for the ones it recognizes.
	const STATUS_LABEL: Record<string, string> = {
		backlog: 'Backlog',
		todo: 'Todo',
		'in-progress': 'In Progress',
		'in-review': 'In Review',
		done: 'Done',
		cancelled: 'Cancelled',
	};

	// PT-61 (Mosko's ruling, "re-step the chart ramp"): chart-LOCAL tokens,
	// one per status, validated via the dataviz skill's ordinal check in
	// both modes (design-system-spec.md § Accessibility carries the
	// evidence) -- never the base --chart-1..5 ramp, whose two lightest
	// steps fail the light-end contrast floor on this app's white card.
	const STATUS_COLOR: Record<string, string> = {
		backlog: 'var(--chart-flow-backlog)',
		todo: 'var(--chart-flow-todo)',
		'in-progress': 'var(--chart-flow-in-progress)',
		'in-review': 'var(--chart-flow-in-review)',
		done: 'var(--chart-flow-done)',
		cancelled: 'var(--chart-flow-cancelled)',
	};

	const STATUS_KEYS = ['backlog', 'todo', 'in-progress', 'in-review', 'done', 'cancelled'];

	const chartConfig = {
		backlog: { label: STATUS_LABEL.backlog, color: STATUS_COLOR.backlog },
		todo: { label: STATUS_LABEL.todo, color: STATUS_COLOR.todo },
		'in-progress': { label: STATUS_LABEL['in-progress'], color: STATUS_COLOR['in-progress'] },
		'in-review': { label: STATUS_LABEL['in-review'], color: STATUS_COLOR['in-review'] },
		done: { label: STATUS_LABEL.done, color: STATUS_COLOR.done },
		cancelled: { label: STATUS_LABEL.cancelled, color: STATUS_COLOR.cancelled },
	} satisfies Chart.ChartConfig;

	const series = STATUS_KEYS.map((key) => ({
		key,
		label: STATUS_LABEL[key],
		color: STATUS_COLOR[key],
	}));

	// Stacked-area composition-over-time (dataviz skill's choosing-a-form:
	// "trend over time" + "part-to-whole" together -> stacked area), one
	// point per day the server already folded same-day commits into.
	const chartData = $derived(
		(flow?.series ?? []).map((point) => {
			const row: Record<string, number | Date> = { date: new Date(`${point.date}T00:00:00Z`) };
			for (const key of STATUS_KEYS) {
				row[key] = point.counts[key] ?? 0;
			}
			return row;
		}),
	);

	// PT-61 (team-lead's browser-pass finding): layerchart's default tick
	// generator picks a "nice" sub-day interval for a scaleUtc() domain
	// spanning several days, and every sub-day tick formats to the same
	// day string (formatDay has no time component) -- every date rendered
	// twice. Passing the exact array of UTC-midnight Dates we actually
	// have data for pins one tick per real data point, never a generated
	// in-between one.
	const chartTickDates = $derived(chartData.map((row) => row.date as Date));

	function formatDay(d: Date): string {
		return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
	}
</script>

<!-- PT-61: the chart panel named in the AC -- issue flow over time, one
     stacked area per status, on the re-stepped chart-local ramp. -->
<section aria-label="Issue flow over time">
	<Card.Root class="[--card-spacing:1.5rem]">
		<Card.Header class="flex flex-wrap items-center justify-between gap-2 space-y-0">
			<div class="grid gap-1">
				<Card.Title class="text-lg">Issue flow over time</Card.Title>
				{#if flow}
					<!-- Architect's ruling: the two divergences from the status
					     cards (archived issues included; last point is
					     committed-only, may lag an uncommitted edit) must be
					     surfaced in the UI, not silently reconciled. -->
					<Card.Description class="text-xs">{flow.scope}</Card.Description>
				{/if}
			</div>
			{#if flow && flow.series.length > 0 && !flow.warning}
				<!-- dataviz skill (components.md): every chart carries a
				     table-view toggle, the WCAG-clean accessibility twin. -->
				<Button variant="outline" size="sm" onclick={() => (tableView = !tableView)}>
					{tableView ? 'Show chart' : 'Show table'}
				</Button>
			{/if}
		</Card.Header>
		<Card.Content>
			{#if flowError && !flow}
				<p class="text-sm text-destructive">
					Couldn't load issue flow history: {flowError}
				</p>
			{:else if flow === null}
				<!-- design-system-spec.md: skeleton shaped like the real
				     content it's replacing -- a chart-height bar, matching the
				     ChartContainer's own h-[250px] below. -->
				<Skeleton class="h-[250px] w-full" />
			{:else if flow.warning}
				<!-- Degraded-but-200 case (git unavailable, non-worktree
				     data_dir) -- build_flow_payload's own warning text, not a
				     fabricated one. -->
				<p class="text-sm text-muted-foreground">{flow.warning}</p>
			{:else if flow.series.length === 0}
				<!-- Honest empty state -- a fresh template instance has no
				     issue-history commits yet (ruling: "required, not
				     optional"). -->
				<p class="text-sm text-muted-foreground">
					No committed issue history yet — this fills in as issues change status over time.
				</p>
			{:else if flow.series.length < 2 || tableView}
				{#if flow.series.length < 2}
					<!-- Few-points state (ruling: "required, not optional") --
					     an area chart can't show a trend from one point; the
					     table is the honest presentation, not a degraded one. -->
					<p class="mb-3 text-sm text-muted-foreground">
						Only {flow.series.length} day{flow.series.length === 1 ? '' : 's'} of committed history
						so far — not enough to plot a trend yet.
					</p>
				{/if}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<caption class="sr-only">Issue counts by status, one row per day</caption>
						<thead>
							<tr class="border-b border-border">
								<th class="py-2 pr-4 text-left font-medium text-muted-foreground">Date</th>
								{#each STATUS_KEYS as key (key)}
									<th class="py-2 pr-4 text-right font-medium text-muted-foreground">
										{STATUS_LABEL[key]}
									</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each flow.series as point (point.date)}
								<tr class="border-b border-border last:border-0">
									<td class="py-2 pr-4 font-mono">{point.date}</td>
									{#each STATUS_KEYS as key (key)}
										<td class="py-2 pr-4 text-right font-mono">{point.counts[key] ?? 0}</td>
									{/each}
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<Chart.Container config={chartConfig} class="aspect-auto h-[250px] w-full">
					<AreaChart
						legend
						data={chartData}
						x="date"
						xScale={scaleUtc()}
						{series}
						seriesLayout="stack"
						props={{
							xAxis: { ticks: chartTickDates, format: (v: Date) => formatDay(v) },
							yAxis: { format: (v: number) => String(v) },
						}}
					>
						{#snippet marks({ context })}
							<!-- marks-and-anatomy.md: ~10% opacity wash on the
							     fill (never a saturated block), 2px stroke lines. -->
							{#each context.series.visibleSeries as s (s.key)}
								<Area seriesKey={s.key} fillOpacity={0.1} line={{ class: 'stroke-2' }} {...s.props} />
							{/each}
						{/snippet}
						{#snippet tooltip()}
							<!-- interaction.md: crosshair + one tooltip listing
							     every series at that X -- Chart.Tooltip's default
							     shape, not a per-mark hover. PT-61 (team-lead's
							     browser-pass finding): explicit bg-popover +
							     ring + z-50 -- the vendored default (bg-background,
							     no explicit stacking) read translucent in light
							     mode where the tooltip overhangs the plot edge
							     near the legend; forcing an opaque popover
							     surface above everything else can't make that
							     worse regardless of the underlying cause. -->
							<Chart.Tooltip
								labelFormatter={(v: Date) => formatDay(v)}
								indicator="line"
								class="z-50 bg-popover text-popover-foreground ring-1 ring-border"
							/>
						{/snippet}
					</AreaChart>
				</Chart.Container>
			{/if}
		</Card.Content>
	</Card.Root>
</section>
