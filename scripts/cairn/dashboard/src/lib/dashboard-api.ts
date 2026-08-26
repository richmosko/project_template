// PT-54: typed client for GET /api/dashboard (scripts/cairn/cairn.py) and
// the freshness contract the architect ruled on -- SSE refetch (the
// existing /api/events channel, coarse: any frame -> refetch) PLUS a 15s
// poll, because the data-dir watcher backing /api/events only scans
// process/cairn/, so a branch switch / new tag / dirty working tree is
// invisible to it. This module owns both triggers; callers just get an
// `onUpdate` callback.

export type GitState = {
	branch: string | null;
	dirty: boolean | null;
	head: string | null;
	latest_tag: string | null;
	warning: string | null;
};

export type TrackerCounts = Record<string, number>;

export type CheckResult = {
	ok: boolean;
	errors: string[];
};

// Matches build_dashboard_payload's `_find_release_milestone` join exactly
// (scripts/cairn/cairn.py) -- `id`/`name`/`status`/`ga` are the matched
// milestone's own fields, not a `tag` (the tag lives on `git.latest_tag`,
// which is what produced this join in the first place). `null` whole-object
// when nothing matches (including "no tags at all").
export type ReleaseRow = {
	id: string | null;
	name: string | null;
	status: string | null;
	ga: boolean | null;
} | null;

export type DashboardPayload = {
	git: GitState;
	tracker: { counts_by_status: TrackerCounts };
	check: CheckResult;
	release: ReleaseRow;
	generated_at: string;
};

const POLL_INTERVAL_MS = 15_000;

export async function fetchDashboard(
	etag?: string,
): Promise<{ payload: DashboardPayload | null; etag: string | null; notModified: boolean }> {
	const headers: Record<string, string> = {};
	if (etag) headers['If-None-Match'] = etag;
	const res = await fetch('/api/dashboard', { headers });
	if (res.status === 304) {
		return { payload: null, etag: etag ?? null, notModified: true };
	}
	if (!res.ok) {
		throw new Error(`GET /api/dashboard -> ${res.status}`);
	}
	const payload = (await res.json()) as DashboardPayload;
	return { payload, etag: res.headers.get('ETag'), notModified: false };
}

/**
 * Subscribes to both freshness triggers and calls `onUpdate` with every
 * successfully fetched payload (never with a 304 -- the caller only cares
 * about actual data, the ETag dance is this module's own concern).
 * Returns a teardown function.
 */
export function subscribeDashboard(
	onUpdate: (payload: DashboardPayload) => void,
	onError: (err: unknown) => void = () => {},
): () => void {
	let etag: string | undefined;
	let stopped = false;

	const refresh = async () => {
		try {
			const result = await fetchDashboard(etag);
			if (stopped) return;
			if (result.etag) etag = result.etag;
			if (result.payload) onUpdate(result.payload);
		} catch (err) {
			if (!stopped) onError(err);
		}
	};

	// Initial load.
	void refresh();

	// Slow poll -- the only trigger for git-state changes (branch/tag/dirty),
	// which the SSE watcher never sees (it scans process/cairn/ only).
	const pollId = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);

	// SSE -- coarse contract shared with the board: any frame means
	// refetch, never a targeted diff.
	const source = new EventSource('/api/events');
	source.onmessage = () => void refresh();
	source.onerror = (err) => {
		// EventSource auto-reconnects on its own; this is informational,
		// not fatal -- the poll above keeps the dashboard fresh regardless.
		onError(err);
	};

	return () => {
		stopped = true;
		window.clearInterval(pollId);
		source.close();
	};
}
