<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as Card from '$lib/components/ui/card/index.js';
	import StatusCard from '$lib/components/StatusCard.svelte';
	import { subscribeDashboard, type DashboardPayload } from '$lib/dashboard-api';

	let data = $state<DashboardPayload | null>(null);
	let loadError = $state<string | null>(null);

	const unsubscribe = subscribeDashboard(
		(payload) => {
			data = payload;
			loadError = null;
		},
		(err) => {
			// Non-fatal by design (architect ruling: SSE + poll, either can
			// hiccup without the other) -- surface it, keep showing the
			// last-known-good payload rather than blanking the dashboard.
			loadError = err instanceof Error ? err.message : String(err);
		},
	);
	onDestroy(unsubscribe);

	// "Active feature" isn't a payload field (architect's /api/dashboard
	// contract has no such key) -- it's honestly derived client-side from
	// the real branch name, never fabricated. `main`/`master` or anything
	// that isn't a feature/* branch renders as an honest empty state.
	function activeFeatureLabel(branch: string | null): string {
		if (!branch) return '—';
		const match = /^feature\/(.+)$/.exec(branch);
		if (!match) return 'None (on ' + branch + ')';
		return match[1];
	}

	function trackerTotal(counts: Record<string, number>): number {
		return Object.values(counts).reduce((sum, n) => sum + n, 0);
	}

	function trackerBreakdown(counts: Record<string, number>): string {
		const entries = Object.entries(counts).filter(([, n]) => n > 0);
		if (entries.length === 0) return 'no issues';
		return entries.map(([status, n]) => `${status} ${n}`).join(' · ');
	}
</script>

<div class="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 bg-muted px-7 py-7">
	<header class="flex flex-wrap items-center justify-between gap-4">
		<div class="flex flex-col gap-1">
			<h1 class="font-heading text-2xl font-bold text-foreground">Project Dashboard</h1>
			<p class="text-sm text-muted-foreground">
				Real-time repo, tracker, and release state.
			</p>
		</div>
		<div class="flex items-center gap-2">
			{#if data}
				<Badge variant={data.git.dirty ? 'outline' : 'secondary'}>
					{data.git.branch ?? 'unknown branch'} · {data.git.dirty ? 'dirty' : 'clean'}
				</Badge>
				<Badge variant={data.release.ga ? 'default' : 'outline'}>
					{data.release.tag ?? data.git.latest_tag ?? 'no tags yet'}
				</Badge>
			{:else if loadError}
				<Badge variant="destructive">/api/dashboard unreachable</Badge>
			{:else}
				<Badge variant="outline">Loading…</Badge>
			{/if}
		</div>
	</header>

	{#if loadError && !data}
		<Card.Root>
			<Card.Content>
				<p class="text-sm text-destructive">
					Couldn't load dashboard data: {loadError}
				</p>
			</Card.Content>
		</Card.Root>
	{/if}

	<section class="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
		<StatusCard
			eyebrow="Build"
			value={data?.git.branch ?? '—'}
			badgeLabel={data ? (data.git.dirty ? 'Dirty' : 'Clean') : undefined}
			badgeVariant={data?.git.dirty ? 'outline' : 'secondary'}
			detail={data?.git.head ? `@ ${data.git.head}` : (data?.git.warning ?? undefined)}
		/>
		<StatusCard
			eyebrow="Release"
			value={data?.release.tag ?? data?.git.latest_tag ?? '—'}
			badgeLabel={data?.release.status ?? (data && !data.release.tag ? 'unreleased' : undefined)}
			badgeVariant={data?.release.ga ? 'default' : 'outline'}
			detail={data?.release.milestone ? `Milestone ${data.release.milestone}` : undefined}
		/>
		<StatusCard
			eyebrow="Active Feature"
			value={data ? activeFeatureLabel(data.git.branch) : '—'}
			detail={data ? 'from the current branch' : undefined}
		/>
		<StatusCard
			eyebrow="Tracker"
			value={data ? String(trackerTotal(data.tracker.counts)) : '—'}
			badgeLabel={data ? (data.check.ok ? 'Lint clean' : `${data.check.errors.length} lint error(s)`) : undefined}
			badgeVariant={data?.check.ok ? 'secondary' : 'destructive'}
			detail={data ? trackerBreakdown(data.tracker.counts) : undefined}
		/>
	</section>

	<!-- PT-56: agent-roster panel. Honest empty state -- no fabricated
	     agents until the presence-source ruling lands and the panel is
	     actually wired up. -->
	<section aria-label="Agent roster">
		<h2 class="font-heading mb-3 text-lg font-semibold text-foreground">Agents</h2>
		<Card.Root>
			<Card.Content class="py-8 text-center text-sm text-muted-foreground">
				Agent roster not wired up yet (PT-56).
			</Card.Content>
		</Card.Root>
	</section>

	<!-- PT-55: embedded kanban/list board. Honest empty state -- no forked
	     board rendering here until the real embed lands. -->
	<section aria-label="Board">
		<h2 class="font-heading mb-3 text-lg font-semibold text-foreground">Board</h2>
		<Card.Root>
			<Card.Content class="py-8 text-center text-sm text-muted-foreground">
				Board embed not wired up yet (PT-55) — see the
				<a href="/" class="text-primary underline underline-offset-4">full board</a>.
			</Card.Content>
		</Card.Root>
	</section>
</div>
