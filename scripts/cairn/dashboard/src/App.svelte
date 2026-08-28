<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import * as Card from '$lib/components/ui/card/index.js';
	import * as Table from '$lib/components/ui/table/index.js';
	import StatusCard from '$lib/components/StatusCard.svelte';
	import { fetchDashboard, subscribeDashboard, type DashboardPayload } from '$lib/dashboard-api';

	let data = $state<DashboardPayload | null>(null);
	let loadError = $state<string | null>(null);
	let refreshing = $state(false);

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

	async function refreshNow() {
		refreshing = true;
		try {
			// Deliberately no ETag here -- "refresh now" means "give me
			// whatever's current right now," not "tell me if it changed."
			const result = await fetchDashboard();
			if (result.payload) {
				data = result.payload;
				loadError = null;
			}
		} catch (err) {
			loadError = err instanceof Error ? err.message : String(err);
		} finally {
			refreshing = false;
		}
	}

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

	// design-system-spec.md § Project extensions: record-status vocabulary,
	// expressed as badge variants against existing preset tokens (never a
	// per-category hue). "in-review" maps to the chart-2 tier
	// ("Paused / In Review"); "done" to the inverted foreground tier.
	const STATUS_BADGE_VARIANT: Record<string, 'outline' | 'secondary' | 'default' | 'chart' | 'inverted' | 'destructive'> = {
		backlog: 'outline',
		todo: 'secondary',
		'in-progress': 'default',
		'in-review': 'chart',
		done: 'inverted',
		cancelled: 'destructive',
	};
</script>

<!-- PT-62 (hotfix, team-lead ruling): design-system-spec.md's Dashboard
     scale defines 28px page MARGINS, not a max-width -- the preset's own
     preview is full-bleed. The previous `max-w-6xl` cap here was an
     implementation artifact, not a spec requirement, and it strangled the
     embedded board (PT-55): six kanban columns with Show-cancelled on
     don't fit inside a 1152px-capped page. Full-bleed root (28px margins
     via px-7/py-7 only); the Board section below gets the whole viewport.
     Everything ABOVE the board (header, status cards, tracker table,
     agent roster) stays inside its own `max-w-6xl` wrapper -- capping
     four stat cards at nothing would stretch them across an ultrawide
     monitor with mostly empty padding, which is the "spec's card scale
     holds" judgment call this issue's AC leaves to implementation. -->
<div class="flex min-h-screen flex-col gap-6 bg-muted px-7 py-7">
	<div class="mx-auto flex w-full max-w-6xl flex-col gap-6">
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
				<Badge variant={data.release?.ga ? 'default' : 'outline'}>
					{data.git.latest_tag ?? 'no tags yet'}
				</Badge>
			{:else if loadError}
				<Badge variant="destructive">/api/dashboard unreachable</Badge>
			{:else}
				<Badge variant="outline">Loading…</Badge>
			{/if}
			<Button variant="outline" size="sm" onclick={refreshNow} disabled={refreshing}>
				{refreshing ? 'Refreshing…' : 'Refresh'}
			</Button>
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
			value={data?.git.latest_tag ?? '—'}
			badgeLabel={data?.release?.status ?? (data && !data.release ? 'unreleased' : undefined)}
			badgeVariant={data?.release?.ga ? 'default' : 'outline'}
			detail={data?.release?.name ? `${data.release.id} — ${data.release.name}` : undefined}
		/>
		<StatusCard
			eyebrow="Active Feature"
			value={data ? activeFeatureLabel(data.git.branch) : '—'}
			detail={data ? 'from the current branch' : undefined}
		/>
		<StatusCard
			eyebrow="Tracker"
			value={data ? String(trackerTotal(data.tracker.counts_by_status)) : '—'}
			badgeLabel={data ? (data.check.ok ? 'Lint clean' : `${data.check.errors.length} lint error(s)`) : undefined}
			badgeVariant={data?.check.ok ? 'secondary' : 'destructive'}
			detail={data ? 'issues, live tree' : undefined}
		/>
	</section>

	{#if data}
		<section aria-label="Tracker breakdown">
			<Card.Root class="[--card-spacing:1.5rem]">
				<Card.Content>
					<Table.Root>
						<Table.Header>
							<Table.Row>
								<Table.Head>Status</Table.Head>
								<Table.Head class="text-right">Count</Table.Head>
							</Table.Row>
						</Table.Header>
						<Table.Body>
							{#each Object.entries(data.tracker.counts_by_status) as [status, count] (status)}
								<Table.Row>
									<Table.Cell>
										<Badge variant={STATUS_BADGE_VARIANT[status] ?? 'outline'}>{status}</Badge>
									</Table.Cell>
									<Table.Cell class="text-right font-mono">{count}</Table.Cell>
								</Table.Row>
							{/each}
						</Table.Body>
					</Table.Root>
				</Card.Content>
			</Card.Root>
		</section>
	{/if}

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
	</div>

	<!-- PT-62 (hotfix): the Board section is deliberately OUTSIDE the
	     max-w-6xl wrapper above -- it's the one section this hotfix exists
	     to give the full viewport to (28px margins only, via the outer
	     div's px-7). -->
	<!-- PT-55 (architect ruling): same-origin iframe of the real board at
	     `/?embed=1` -- maximal reuse (same files, same fetch, same PT-36
	     column list), not a rewrite. `embed=1` suppresses only the
	     wordmark and the Dashboard tab (board-logic.js's `isEmbedMode`,
	     board.js/board.css). Full read-write: drag/drawer/inline-edit/
	     +New all work because it IS the board -- a read-only mode would
	     mean forking new state into board.js to deliver LESS. Kanban⇄List
	     and lane collapse come free (the board's own <a> tabs navigate the
	     frame; PT-30's localStorage view state is shared across the
	     origin). No sandbox (breaks same-origin storage), no postMessage
	     auto-height (the board owns its own scrolling/sticky chrome --
	     auto-height would fight that and grow unboundedly), fixed height. -->
	<section aria-label="Board">
		<Card.Root class="[--card-spacing:1.5rem]">
			<Card.Header>
				<Card.Title class="text-lg">Board</Card.Title>
				<Card.Action>
					<Button variant="secondary" size="sm" href="/">Open full board</Button>
				</Card.Action>
			</Card.Header>
			<Card.Content class="flex flex-col gap-3">
				<p class="text-xs text-muted-foreground">
					This is the real, live board (drag, drawer, filters, + New all work) — not a
					lookalike. Its legacy pre-shadcn styling holds inside this panel until PT-57's
					board migration.
				</p>
				<iframe
					src="/?embed=1"
					title="Cairn board"
					class="h-[70vh] w-full rounded-md border border-border"
				></iframe>
			</Card.Content>
		</Card.Root>
	</section>
</div>
