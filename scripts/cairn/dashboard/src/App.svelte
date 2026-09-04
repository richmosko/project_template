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
	// PT-69: theme/color settings popover -- top-right header placement,
	// alongside Refresh (ux-designer's ruling, 2026-08-29, supersedes the
	// original Sidebar.Footer plan -- it wasn't discovered there in
	// Mosko's live test). One reactive state instance at app root;
	// ThemeSettings.svelte reads/writes it.
	import ThemeSettings from '$lib/components/ThemeSettings.svelte';
	import { ThemeSettingsState } from '$lib/theme-settings.svelte.js';
	// PT-71 (Mosko's live-test finding #3 + ux's icon picks, 2026-08-30):
	// the collapsed icon rail had no icons at all -- Dashboard =
	// LayoutDashboard, Board = Kanban ("better rail-size silhouette than
	// ListTodo, distinct from LayoutDashboard's grid shape").
	import LayoutDashboard from '@lucide/svelte/icons/layout-dashboard';
	import Kanban from '@lucide/svelte/icons/kanban';
	// PT-73 (Mosko's finding + ux's ruling, 2026-08-30/31): the repo
	// header (PT-68) adopts the same icon-left menu-item pattern as the
	// nav items above -- FolderGit2 over Box/Package: "specifically
	// represents which git repo you're looking at... the more distinct
	// silhouette next to the rail's other two icons" (a folder outline
	// reads as a different shape class than LayoutDashboard's grid or
	// Kanban's columns, avoiding "three flavors of boxes").
	import FolderGit2 from '@lucide/svelte/icons/folder-git-2';
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

	// PT-69: constructed once -- the inline bootstrap script (index.html's
	// <head>) already applied the stored/system preference before this
	// component ever mounts, so this just picks up that same localStorage
	// state, not a fresh resolve.
	const themeSettings = new ThemeSettingsState();

	// PT-72 (architect ruling): PT-61's no-router convention held for two
	// links with no shared-chrome persistence requirement; the unified
	// shell introduces exactly that requirement (Dashboard <-> Issue
	// Tracking must swap content without remounting the sidebar/header),
	// so the conclusion changes with the premise. Soft nav in ~15 lines,
	// not a router library: `$state`-backed route pieces, intercepted
	// anchor clicks -> `history.pushState`, a `popstate` listener below.
	// The anchors keep real `href` values, so a hard load still works
	// through PT-54's existing SPA fallback -- soft nav is pure
	// enhancement, not the only path in.
	let currentPath = $state(window.location.pathname);
	let currentSearch = $state(window.location.search);

	function navigate(event: MouseEvent, path: string) {
		// Let modified/non-plain clicks (new tab, etc.) behave natively.
		if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
			return;
		}
		event.preventDefault();
		if (path === currentPath + currentSearch) return;
		history.pushState({}, '', path);
		const url = new URL(path, window.location.origin);
		currentPath = url.pathname;
		currentSearch = url.search;
	}

	// Curried, not an inline arrow function at each call site -- an
	// inline `(e) => navigate(e, path)` written directly inside a tag's
	// opening `<a ...>` puts a literal `=>` between the tag's `<` and
	// `>`, which broke a source-text `[^>]*` guard reading the compiled
	// markup as plain text (caught while wiring this up: the guard's
	// `<a href="...">...</a>` match terminated at the arrow's `>` instead
	// of the tag's own, swallowing the label). Keeping `=>` out of the
	// markup itself sidesteps that class of guard entirely.
	function navigateTo(path: string) {
		return (event: MouseEvent) => navigate(event, path);
	}

	function handlePopState() {
		currentPath = window.location.pathname;
		currentSearch = window.location.search;
	}
	window.addEventListener('popstate', handlePopState);
	onDestroy(() => window.removeEventListener('popstate', handlePopState));

	// PT-72: the Issue Tracking route's embed reads its own `open=<id>`
	// param, derived here from the shell's OWN `?issue=<id>` query --
	// architect's ruling §4: "two params in two layers... the shell must
	// pass it down." No issue param (or a bare Dashboard-route visit)
	// yields an empty suffix -- the iframe still gets plain `/?embed=1`.
	let issueTrackingOpenSuffix = $derived.by(() => {
		const issueId = new URLSearchParams(currentSearch).get('issue');
		return issueId ? `&open=${encodeURIComponent(issueId)}` : '';
	});
	let onIssueTracking = $derived(currentPath === '/dashboard/issues');

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

	// PT-79 (architect ruling § 3): same lazy dynamic-import pattern as
	// IssueFlowChart immediately above -- a second eager chart import
	// would undo the point of the first.
	let TokenCostChart = $state<typeof import('$lib/components/TokenCostChart.svelte')['default'] | null>(null);
	import('$lib/components/TokenCostChart.svelte').then((mod) => {
		TokenCostChart = mod.default;
	});

	// PT-56: separate state, separate poll -- the roster rides no SSE
	// (the watcher never sees .claude/agents/ changes), matching the
	// architect's ruling that this is a genuinely independent data source
	// from the rest of the dashboard, not a variant of it.
	let roster = $state<RosterAgent[] | null>(null);
	let rosterError = $state<string | null>(null);

	// PT-69 (architect's ruling 1db6053): idle moved off --chart-2 -- same
	// "status affordance must not depend on the user's Chart Color choice"
	// reasoning as the board's paused chip and the "accent" badge variant.
	const PRESENCE_DOT_CLASS: Record<RosterAgent['presence'], string> = {
		working: 'bg-primary',
		idle: 'bg-accent',
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

	// PT-65: the roster's work line is now client-composed from the
	// structured {id, title, status, kind} payload -- the framing that
	// used to be server-composed English (re-parsed by the component with
	// .split(':')) is derived here instead. Team-lead's ruling folds
	// cancelled-only into kind: 'history' alongside done (same terminal-
	// status principle), but "Last shipped" only fits a shipped (done)
	// issue -- a cancelled one gets its status named instead, same text
	// the server used to compose for that cell. Staleness is NOT
	// re-stated inline here -- that's stale_since's own line below,
	// unchanged, avoiding the old double mention (once inline in the
	// sentence, once in its own line).
	function formatWorkLine(work: NonNullable<RosterAgent['work']>): string {
		if (work.kind === 'history') {
			return work.status === 'done'
				? `Last shipped ${work.id}: ${work.title}`
				: `${work.id}: ${work.title} (${work.status})`;
		}
		if (work.kind === 'stale') return `${work.id}: ${work.title}`;
		const isActive = work.status === 'in-progress' || work.status === 'in-review';
		return isActive ? `${work.id}: ${work.title}` : `${work.id}: ${work.title} (${work.status})`;
	}

	// design-system-spec.md § Project extensions: record-status vocabulary,
	// expressed as badge variants against existing preset tokens (never a
	// per-category hue). "in-review" maps to the accent tier
	// ("Paused / In Review" -- PT-69: moved off --chart-2, see badge.svelte);
	// "done" to the inverted foreground tier.
	const STATUS_BADGE_VARIANT: Record<string, 'outline' | 'secondary' | 'default' | 'accent' | 'inverted' | 'destructive'> = {
		backlog: 'outline',
		todo: 'secondary',
		'in-progress': 'default',
		'in-review': 'accent',
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
     Footer` -- Footer landed PT-69 (the theme/color settings dropdown;
     previously omitted, "nothing to put there yet"). -->
<Sidebar.Provider>
	<Sidebar.Root collapsible="icon">
		<Sidebar.Header>
			<!-- PT-68 (Mosko's scope): every template clone showed the same
			     hardcoded "Cairn" label here -- now the repo's own name,
			     server-derived (git.repo_name, /api/dashboard) so each
			     project's dashboard identifies itself. `data` is null only
			     during the initial fetch; repo_name itself is never null
			     once loaded (read_git_state's one field that survives a
			     git-unavailable degrade -- a directory basename needs no
			     git subprocess to exist).
			     PT-73: this row now follows the same collapse-aware
			     icon-left pattern as the nav items below it -- icon-only
			     when the rail collapses, name beside it expanded. The
			     label's `group-data-[collapsible=icon]:hidden` is the
			     same class family every other collapse-aware element in
			     this sidebar component family already uses (sidebar-
			     menu-badge.svelte, sidebar-group-label.svelte, ...); this
			     row simply never adopted it before. -->
			<div class="flex items-center gap-2 px-2 py-1.5">
				<FolderGit2 class="size-4 shrink-0 text-sidebar-foreground" />
				<span class="font-heading text-sm font-semibold text-sidebar-foreground group-data-[collapsible=icon]:hidden">
					{data?.git.repo_name ?? '…'}
				</span>
			</div>
		</Sidebar.Header>
		<Sidebar.Content>
			<Sidebar.Group>
				<Sidebar.GroupLabel>Navigate</Sidebar.GroupLabel>
				<Sidebar.GroupContent>
					<Sidebar.Menu>
						<Sidebar.MenuItem>
							<Sidebar.MenuButton isActive={currentPath === '/dashboard'}>
								{#snippet child({ props })}
									<a href="/dashboard" {...props} onclick={navigateTo('/dashboard')}>
										<LayoutDashboard />
										<span>Dashboard</span>
									</a>
								{/snippet}
							</Sidebar.MenuButton>
						</Sidebar.MenuItem>
						<!-- PT-72 (team-lead/architect/ux ruling): "Board" (href="/") ->
						     "Issue Tracking" (href="/dashboard/issues") -- the old href
						     navigated the user OUT of the shell entirely, which was
						     Mosko's actual complaint. The standalone board at bare `/`
						     still exists unchanged (architect's ruling §5); this link
						     just no longer points at it. -->
						<Sidebar.MenuItem>
							<Sidebar.MenuButton isActive={onIssueTracking}>
								{#snippet child({ props })}
									<a href="/dashboard/issues" {...props} onclick={navigateTo('/dashboard/issues')}>
										<Kanban />
										<span>Issue Tracking</span>
									</a>
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
	<!-- PT-74 (Mosko's finding, 2026-08-31): this wrapper kept the old
	     max-w-6xl inset when PT-73 unified the sections below it -- match
	     the same rule the content wrapper already uses (no cap), on both
	     routes (this header renders before the route switch, so it's
	     already shared chrome -- no per-route duplication to fix). -->
	<div class="mx-auto flex w-full flex-col gap-6">
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
			<!-- PT-69 (ux-designer's ruling, 2026-08-29): top-right header,
			     same position as the board's trigger -- supersedes the
			     original Sidebar.Footer placement. -->
			<ThemeSettings themeState={themeSettings} />
		</div>
	</header>
	</div>

	<!-- PT-72 (architect ruling §1): chrome above (Sidebar.Root + this
	     header) mounts once and never remounts across Dashboard <->
	     Issue Tracking navigation -- only the content below swaps. The
	     Issue Tracking branch gets the full viewport width (outside the
	     max-w-6xl cap, same full-bleed treatment PT-62 already gave the
	     home preview's board section) and full remaining height (no
	     h-[70vh] cap -- architect's ruling §2, ux's spec). -->
	<!-- PT-73 (Mosko's finding + ux's ruling, 2026-08-30/31): the
	     max-w-6xl cap on this wrapper is a deliberate SUPERSESSION of
	     PT-62's own hotfix, not a silent drift from it -- PT-62 kept the
	     cap when the Board card was the one section escaping it; PT-72
	     moved the Board card itself full-bleed, and ux's ruling confirms
	     the rest widen to match it ("the widest existing section... sets
	     the standard rather than the Board card shrinking to match its
	     narrower siblings"), not the reverse. No cap here anymore --
	     status cards/tracker/chart/agents now share the same full-bleed
	     container the Board section already had. -->
	{#if !onIssueTracking}
	<div class="mx-auto flex w-full flex-col gap-6">
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

	<!-- PT-79: token/cost block, directly below the flow chart -- own
	     standalone section (IssueFlowChart's own pattern above, not the
	     4-column grid section elsewhere on this page), lazy-imported for
	     the same reason. -->
	{#if TokenCostChart}
		<TokenCostChart />
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
											{agent.work.id}
										</summary>
										<p class="mt-1">{formatWorkLine(agent.work)}</p>
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
	<!-- PT-55 (architect ruling): same-origin iframe of the real board.
	     PT-72 (architect ruling §2, §3, ux spec): this preview is now
	     read-only (`readonly=1`, additive to `embed=1`) -- filters, view
	     tabs, create-issue, drag, per-lane/column toggles all suppressed
	     board-side (single point in board.js's `init()`, never render-
	     function branching -- PT-55's original "would mean forking new
	     state to deliver LESS" objection still binds the implementation,
	     it just no longer forecloses a SECOND surface). Full editing now
	     lives only on the Issue Tracking page (branch above). Card click
	     navigates the shell to that page with the drawer pre-opened
	     (architect's ruling §4) -- not a second inline/modal editor. No
	     sandbox (breaks same-origin storage), no postMessage auto-height
	     (the board owns its own scrolling/sticky chrome), fixed height. -->
	<section aria-label="Board">
		<Card.Root class="[--card-spacing:1.5rem]">
			<Card.Header>
				<Card.Title class="text-lg">Board</Card.Title>
				<Card.Action>
					<!-- ux spec: explicit "View full board" escape hatch,
					     independent of card-click -- the standing lesson
					     from the Sidebar.Footer placement miss is not to
					     rely on users guessing that cards are click-through. -->
					<Button variant="secondary" size="sm" href="/dashboard/issues" onclick={navigateTo('/dashboard/issues')}>
						View full board
					</Button>
				</Card.Action>
			</Card.Header>
			<Card.Content class="flex flex-col gap-3">
				<p class="text-xs text-muted-foreground">
					A live, read-only glance at the board (click a card to open it on the full
					Issue Tracking page) -- editing lives there, not here.
				</p>
				<iframe
					src="/?embed=1&readonly=1"
					title="Cairn board"
					class="h-[70vh] w-full rounded-md border border-border"
				></iframe>
			</Card.Content>
		</Card.Root>
	</section>
	{:else}
		<section aria-label="Issue Tracking" class="flex min-h-0 flex-1 flex-col">
			<iframe
				src="/?embed=1{issueTrackingOpenSuffix}"
				title="Cairn board"
				class="w-full flex-1 rounded-md border border-border"
			></iframe>
		</section>
	{/if}
	</div>
	</Sidebar.Inset>
</Sidebar.Provider>
