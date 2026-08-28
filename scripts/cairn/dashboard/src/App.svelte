<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import * as Card from '$lib/components/ui/card/index.js';
	import * as Table from '$lib/components/ui/table/index.js';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	// PT-61 (architect ruling): dashboard-01 Block anatomy's Sidebar --
	// Sidebar.Provider/Sidebar.Inset own page-level layout, so the existing
	// padded root moves INSIDE Inset below. No client router (there is no
	// router in this app) -- nav items are plain <a> tags, active state
	// derived from location.pathname, styled via Sidebar.MenuButton's
	// `child` snippet.
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import StatusCard from '$lib/components/StatusCard.svelte';
	import {
		fetchDashboard,
		subscribeDashboard,
		subscribeRoster,
		type DashboardPayload,
		type RosterAgent,
	} from '$lib/dashboard-api';

	let data = $state<DashboardPayload | null>(null);
	let loadError = $state<string | null>(null);
	let refreshing = $state(false);

	// PT-61: no client router in this app -- the sidebar's active-item
	// state is derived once from the real location, matching board.js's
	// own no-router convention rather than introducing one for two links.
	const currentPath = window.location.pathname;

	// PT-61 (architect ruling): dynamic-import the chart panel so
	// layerchart (a real dependency step-up: bits-ui/Sheet/Tooltip for the
	// sidebar, layerchart+d3 for this) lands in its own chunk instead of
	// inflating the main bundle every visitor downloads. IssueFlowChart
	// owns its own /api/flow fetch entirely -- this is only a lazy
	// component reference, not a lazy data load.
	let IssueFlowChart = $state<typeof import('$lib/components/IssueFlowChart.svelte')['default'] | null>(null);
	import('$lib/components/IssueFlowChart.svelte').then((mod) => {
		IssueFlowChart = mod.default;
	});

	// PT-56: separate state, separate poll -- the roster rides no SSE
	// (the watcher never sees .claude/agents/ changes), matching the
	// architect's ruling that this is a genuinely independent data source
	// from the rest of the dashboard, not a variant of it.
	let roster = $state<RosterAgent[] | null>(null);
	let rosterError = $state<string | null>(null);

	const PRESENCE_DOT_CLASS: Record<RosterAgent['presence'], string> = {
		working: 'bg-primary',
		idle: 'bg-chart-2',
		unknown: 'bg-muted-foreground/30',
	};

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

	const unsubscribeRoster = subscribeRoster(
		(payload) => {
			roster = payload.agents;
			rosterError = null;
		},
		(err) => {
			rosterError = err instanceof Error ? err.message : String(err);
		},
	);
	onDestroy(unsubscribeRoster);

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

<!-- PT-61 (architect ruling): dashboard-01 Block anatomy. Sidebar.Provider
     owns the page-level flex shell; Sidebar.Root is the nav rail (Dashboard
     + Board today, "future surfaces" per the AC go here as more Sidebar.Menu
     entries, not as further top-nav links); Sidebar.Inset is the main
     content plane. design-system-spec.md's Sidebar row: `Sidebar.Provider >
     Sidebar.Root > Sidebar.Header, Sidebar.Content (Sidebar.Group), Sidebar.
     Footer` -- Footer omitted for now, nothing to put there yet (no
     account/user surface exists). -->
<Sidebar.Provider>
	<Sidebar.Root collapsible="icon">
		<Sidebar.Header>
			<div class="flex items-center gap-2 px-2 py-1.5">
				<span class="font-heading text-sm font-semibold text-sidebar-foreground">Cairn</span>
			</div>
		</Sidebar.Header>
		<Sidebar.Content>
			<Sidebar.Group>
				<Sidebar.GroupLabel>Navigate</Sidebar.GroupLabel>
				<Sidebar.GroupContent>
					<Sidebar.Menu>
						<Sidebar.MenuItem>
							<Sidebar.MenuButton isActive={currentPath.startsWith('/dashboard')}>
								{#snippet child({ props })}
									<a href="/dashboard" {...props}>Dashboard</a>
								{/snippet}
							</Sidebar.MenuButton>
						</Sidebar.MenuItem>
						<Sidebar.MenuItem>
							<Sidebar.MenuButton isActive={currentPath === '/'}>
								{#snippet child({ props })}
									<a href="/" {...props}>Board</a>
								{/snippet}
							</Sidebar.MenuButton>
						</Sidebar.MenuItem>
					</Sidebar.Menu>
				</Sidebar.GroupContent>
			</Sidebar.Group>
		</Sidebar.Content>
	</Sidebar.Root>
	<Sidebar.Inset>
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
	     holds" judgment call this issue's AC leaves to implementation.
	     PT-61: this root + its inner max-w-6xl wrapper moved inside
	     Sidebar.Inset (architect's landmine note) -- Inset owns page-level
	     layout/peer-margins now, this div no longer wraps a bare <body>. -->
	<div class="flex min-h-screen flex-col gap-6 bg-muted px-7 py-7">
	<div class="mx-auto flex w-full max-w-6xl flex-col gap-6">
	<header class="flex flex-wrap items-center justify-between gap-4">
		<div class="flex items-center gap-3">
			<Sidebar.Trigger />
			<Sidebar.Separator orientation="vertical" class="h-4" />
			<div class="flex flex-col gap-1">
				<h1 class="font-heading text-2xl font-bold text-foreground">Project Dashboard</h1>
				<p class="text-sm text-muted-foreground">
					Real-time repo, tracker, and release state.
				</p>
			</div>
		</div>
		<div class="flex items-center gap-2">
			<!-- PT-60 (architect's PT-54 forward note): this cluster cycles
			     through Loading… / branch-state / unreachable text as the
			     payload resolves -- a Badge isn't a live region by default,
			     so without aria-live a screen reader never announces the
			     transition at all. Scoped to just this cluster (not the
			     Refresh button beside it); "polite" so the announcement
			     waits for a pause rather than interrupting. -->
			<div aria-live="polite" class="flex items-center gap-2">
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
			</div>
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
		{#if loadError && !data}
			<!-- PT-67: mirrors the roster panel's three-state shape -- a
			     failed initial load must switch this section to an error
			     message, not leave the skeleton below pulsing forever
			     underneath the separate top-level error card above. -->
			<Card.Root class="sm:col-span-2 lg:col-span-4">
				<Card.Content>
					<p class="text-sm text-destructive">
						Couldn't load dashboard data: {loadError}
					</p>
				</Card.Content>
			</Card.Root>
		{:else if data === null}
			<!-- design-system-spec.md: every list/board fetch renders a
			     skeleton shaped like the real card/row/table it's replacing --
			     four bars matching StatusCard's own eyebrow/value/badge
			     stack, not one decorative block standing in for the section. -->
			{#each [0, 1, 2, 3] as i (i)}
				<Card.Root class="[--card-spacing:1.5rem] gap-3">
					<Card.Content class="flex flex-col gap-2">
						<Skeleton class="h-3 w-20" />
						<Skeleton class="h-7 w-16" />
						<Skeleton class="h-5 w-14" />
					</Card.Content>
				</Card.Root>
			{/each}
		{:else}
			<StatusCard
				eyebrow="Build"
				value={data.git.branch ?? '—'}
				badgeLabel={data.git.dirty ? 'Dirty' : 'Clean'}
				badgeVariant={data.git.dirty ? 'outline' : 'secondary'}
				detail={data.git.head ? `@ ${data.git.head}` : (data.git.warning ?? undefined)}
			/>
			<StatusCard
				eyebrow="Release"
				value={data.git.latest_tag ?? '—'}
				badgeLabel={data.release?.status ?? (!data.release ? 'unreleased' : undefined)}
				badgeVariant={data.release?.ga ? 'default' : 'outline'}
				detail={data.release?.name ? `${data.release.id} — ${data.release.name}` : undefined}
			/>
			<StatusCard
				eyebrow="Active Feature"
				value={activeFeatureLabel(data.git.branch)}
				detail="from the current branch"
			/>
			<StatusCard
				eyebrow="Tracker"
				value={String(trackerTotal(data.tracker.counts_by_status))}
				badgeLabel={data.check.ok ? 'Lint clean' : `${data.check.errors.length} lint error(s)`}
				badgeVariant={data.check.ok ? 'secondary' : 'destructive'}
				detail="issues, live tree"
			/>
		{/if}
	</section>

	{#if loadError && !data}
		<!-- PT-67: mirrors the roster panel's three-state shape -- a
		     failed initial load must switch this section to an error
		     message, not leave the skeleton below pulsing forever
		     underneath the separate top-level error card above. -->
		<section aria-label="Tracker breakdown">
			<Card.Root class="[--card-spacing:1.5rem]">
				<Card.Content>
					<p class="text-sm text-destructive">
						Couldn't load the tracker breakdown: {loadError}
					</p>
				</Card.Content>
			</Card.Root>
		</section>
	{:else if data === null}
		<!-- PT-60: same fetch boundary as the status cards above -- a
		     skeleton shaped like the real table (header + STATUS_ORDER-
		     length rows), not a blank gap while /api/dashboard is in flight. -->
		<section aria-label="Tracker breakdown">
			<Card.Root class="[--card-spacing:1.5rem]">
				<Card.Content class="flex flex-col gap-2">
					{#each [0, 1, 2, 3, 4, 5] as i (i)}
						<Skeleton class="h-6 w-full" />
					{/each}
				</Card.Content>
			</Card.Root>
		</section>
	{:else}
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

	<!-- PT-61: chart panel, dashboard-01 Block anatomy's other named
	     surface (Sidebar above, Chart here) -- dynamically imported so
	     the component (and layerchart) doesn't block first paint on
	     everything above it. -->
	{#if IssueFlowChart}
		<IssueFlowChart />
	{/if}

	<!-- PT-56: agent-roster panel. Honest empty state -- no fabricated
	     agents until the presence-source ruling lands and the panel is
	     actually wired up. -->
	<!-- PT-56 (architect ruling): identity from .claude/agents/*.md +
	     .claude/roles/team-lead.md, work attribution from the tracker's
	     assignee field on live issues, presence strictly working/idle/
	     unknown -- never "active"/"online"/"live", which would claim an
	     observation this system cannot make. The legend line is part of
	     the ruling, not decoration: it's what keeps the color-coded dot
	     from silently implying real-time presence. -->
	<section aria-label="Agent roster">
		<h2 class="font-heading mb-3 text-lg font-semibold text-foreground">Agents</h2>
		<Card.Root>
			<Card.Content class="flex flex-col gap-3">
				<p class="text-xs text-muted-foreground">
					Derived from tracker assignments, not live presence — nobody is being pinged.
				</p>
				{#if rosterError && !roster}
					<p class="text-sm text-destructive">Couldn't load the roster: {rosterError}</p>
				{:else if roster === null}
					<!-- PT-60: skeleton shaped like the real roster cards below
					     (dot + name row, then a role-line bar) -- honest loading,
					     not a spinner or a bare "Loading…" string. -->
					<ul class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
						{#each [0, 1, 2] as i (i)}
							<li class="rounded-md border border-border p-3">
								<div class="flex items-center gap-2">
									<Skeleton class="size-2.5 shrink-0 rounded-full" />
									<Skeleton class="h-4 w-24" />
								</div>
								<Skeleton class="mt-2 h-3 w-32" />
							</li>
						{/each}
					</ul>
				{:else if roster.length === 0}
					<p class="text-sm text-muted-foreground">
						No agent identities found under .claude/agents/.
					</p>
				{:else}
					<ul class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
						{#each roster as agent (agent.id)}
							<li class="rounded-md border border-border p-3">
								<div class="flex items-center gap-2">
									<span
										class={`inline-block size-2.5 shrink-0 rounded-full ${PRESENCE_DOT_CLASS[agent.presence]}`}
										aria-hidden="true"
									></span>
									<span class="font-heading text-sm font-semibold text-foreground">{agent.name}</span>
									<Badge variant="outline" class="ml-auto">{agent.presence}</Badge>
								</div>
								<p class="mt-1 text-xs text-muted-foreground">{agent.role}</p>
								{#if agent.work}
									<details class="mt-2 text-xs text-muted-foreground">
										<summary class="cursor-pointer select-none">
											{agent.work.split(':')[0]}
										</summary>
										<p class="mt-1">{agent.work}</p>
										{#if agent.stale_since}
											<p class="mt-1">Last tracker update: {agent.stale_since}</p>
										{/if}
									</details>
								{:else}
									<!-- PT-56 (team-lead's browser-pass finding, architect's
									     recommendation 58f6fc1): an `unknown` card previously
									     stopped after role with no line at all -- ambiguous
									     between "nothing to report" and "failed to load".
									     One muted line makes the honest empty state explicit. -->
									<p class="mt-2 text-xs text-muted-foreground">No tracked work.</p>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
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
					lookalike.
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
	</Sidebar.Inset>
</Sidebar.Provider>
