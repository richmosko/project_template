// PT-69 (architect's theme-variant ruling §3): the theme/color settings
// dropdown's persisted-preference schema + reactive runtime state.
// Deliberately origin-global, NOT repo-scoped -- a theme is a fact about
// the person looking, not the project being viewed. One key, shared
// verbatim by the board (scripts/cairn/board/board-logic.js's
// parseThemePrefs/resolveDarkMode -- kept in lockstep with the functions
// below, same schema, same defaults) and the dashboard (this file).

export const THEME_STORAGE_KEY = 'cairn.theme';
const THEME_STORAGE_VERSION = 1;

export const THEME_DEFAULTS = { mode: 'system', base: 'stone', theme: 'sky', chart: 'yellow' } as const;

export const THEME_MODE_IDS = ['system', 'light', 'dark'] as const;
export type ThemeMode = (typeof THEME_MODE_IDS)[number];

export type ThemePrefs = {
	mode: ThemeMode;
	base: string;
	theme: string;
	chart: string;
};

export type ThemeOption = { id: string; label: string };

// Option catalogs -- id (matches variants.json's variant keys / the
// data-cairn-* attribute values the generated CSS selects on) + display
// label. Kept in sync BY HAND with scripts/cairn/design/variants.json
// (same "presentation copy" tradeoff board.js's own catalog makes) -- the
// CSS token VALUES those ids resolve to are fully generated
// (gen_variants.py) and byte-compared against variants.json, so drift
// here can only ever mean "wrong menu label/order", never "wrong color".
export const THEME_MODE_OPTIONS: ThemeOption[] = [
	{ id: 'system', label: 'System' },
	{ id: 'light', label: 'Light' },
	{ id: 'dark', label: 'Dark' },
];
export const THEME_BASE_OPTIONS: ThemeOption[] = [
	{ id: 'stone', label: 'Stone' },
	{ id: 'neutral', label: 'Neutral' },
	{ id: 'zinc', label: 'Zinc' },
	{ id: 'mauve', label: 'Mauve' },
	{ id: 'olive', label: 'Olive' },
	{ id: 'mist', label: 'Mist' },
	{ id: 'taupe', label: 'Taupe' },
];
// PT-69 (Mosko's live-test feedback, 2026-08-29): the curated caps are
// lifted -- full reference sets from the live generator (all 24
// PRESET_THEME_KEYS/PRESET_CHART_COLORS names, minus each dimension's
// own default), enumerated on the PT-69 issue thread.
export const THEME_THEME_OPTIONS: ThemeOption[] = [
	{ id: 'sky', label: 'Sky' },
	{ id: 'amber', label: 'Amber' },
	{ id: 'blue', label: 'Blue' },
	{ id: 'cyan', label: 'Cyan' },
	{ id: 'emerald', label: 'Emerald' },
	{ id: 'fuchsia', label: 'Fuchsia' },
	{ id: 'green', label: 'Green' },
	{ id: 'indigo', label: 'Indigo' },
	// PT-69 (qa's contrast gate, 2026-08-29): 'lime' dropped -- Theme's
	// drop-don't-rederive fence, per-variant defect (4.4612:1 dark,
	// below the 4.5:1 floor; every other Theme variant clears the same
	// pair fine). Chart Color's own 'lime' below is unaffected -- a
	// different pair, different gate.
	{ id: 'mauve', label: 'Mauve' },
	{ id: 'mist', label: 'Mist' },
	{ id: 'neutral', label: 'Neutral' },
	{ id: 'olive', label: 'Olive' },
	{ id: 'orange', label: 'Orange' },
	{ id: 'pink', label: 'Pink' },
	{ id: 'purple', label: 'Purple' },
	{ id: 'red', label: 'Red' },
	{ id: 'rose', label: 'Rose' },
	{ id: 'stone', label: 'Stone' },
	{ id: 'taupe', label: 'Taupe' },
	{ id: 'teal', label: 'Teal' },
	{ id: 'violet', label: 'Violet' },
	{ id: 'yellow', label: 'Yellow' },
	{ id: 'zinc', label: 'Zinc' },
];
export const THEME_CHART_OPTIONS: ThemeOption[] = [
	{ id: 'yellow', label: 'Yellow' },
	{ id: 'amber', label: 'Amber' },
	{ id: 'blue', label: 'Blue' },
	{ id: 'cyan', label: 'Cyan' },
	{ id: 'emerald', label: 'Emerald' },
	{ id: 'fuchsia', label: 'Fuchsia' },
	{ id: 'green', label: 'Green' },
	{ id: 'indigo', label: 'Indigo' },
	{ id: 'lime', label: 'Lime' },
	{ id: 'mauve', label: 'Mauve' },
	{ id: 'mist', label: 'Mist' },
	{ id: 'neutral', label: 'Neutral' },
	{ id: 'olive', label: 'Olive' },
	{ id: 'orange', label: 'Orange' },
	{ id: 'pink', label: 'Pink' },
	{ id: 'purple', label: 'Purple' },
	{ id: 'red', label: 'Red' },
	{ id: 'rose', label: 'Rose' },
	{ id: 'sky', label: 'Sky' },
	{ id: 'stone', label: 'Stone' },
	{ id: 'taupe', label: 'Taupe' },
	{ id: 'teal', label: 'Teal' },
	{ id: 'violet', label: 'Violet' },
	{ id: 'zinc', label: 'Zinc' },
];

const VALID_IDS = {
	base: THEME_BASE_OPTIONS.map((o) => o.id),
	theme: THEME_THEME_OPTIONS.map((o) => o.id),
	chart: THEME_CHART_OPTIONS.map((o) => o.id),
};

// PT-69 (architect's ruling §3): per-DIMENSION fallback, not whole-blob
// rejection -- an unrecognized or absent `base` falls back to the default
// base while leaving a valid `chart` choice intact. A `v` this function
// doesn't recognize is treated as absent. Never throws.
export function parseThemePrefs(raw: string | null): ThemePrefs {
	let parsed: Record<string, unknown> = {};
	if (typeof raw === 'string' && raw !== '') {
		try {
			const candidate = JSON.parse(raw);
			if (candidate && typeof candidate === 'object' && candidate.v === THEME_STORAGE_VERSION) {
				parsed = candidate;
			}
		} catch {
			parsed = {};
		}
	}
	function pick<T extends string>(value: unknown, validList: readonly T[], fallback: T): T {
		return typeof value === 'string' && (validList as readonly string[]).includes(value)
			? (value as T)
			: fallback;
	}
	return {
		mode: pick(parsed.mode, THEME_MODE_IDS, THEME_DEFAULTS.mode),
		base: pick(parsed.base, VALID_IDS.base as string[], THEME_DEFAULTS.base),
		theme: pick(parsed.theme, VALID_IDS.theme as string[], THEME_DEFAULTS.theme),
		chart: pick(parsed.chart, VALID_IDS.chart as string[], THEME_DEFAULTS.chart),
	};
}

// PT-69 (architect's ruling §3 + ux-designer's Mode addendum): mode=system
// (the default) follows systemPrefersDark, re-evaluated live by the
// caller on every prefers-color-scheme `change` event, not just once.
export function resolveDarkMode(mode: ThemeMode, systemPrefersDark: boolean): boolean {
	return mode === 'dark' || (mode === 'system' && systemPrefersDark);
}

function readStoredPrefs(): ThemePrefs {
	let raw: string | null = null;
	try {
		raw = localStorage.getItem(THEME_STORAGE_KEY);
	} catch {
		// Private mode / blocked storage -- degrade to defaults, same PT-30
		// contract as the board's readViewState.
	}
	return parseThemePrefs(raw);
}

function writeStoredPrefs(prefs: ThemePrefs): void {
	try {
		localStorage.setItem(
			THEME_STORAGE_KEY,
			JSON.stringify({ v: THEME_STORAGE_VERSION, mode: prefs.mode, base: prefs.base, theme: prefs.theme, chart: prefs.chart }),
		);
	} catch {
		// Degrade silently -- already applied to <html>; only the NEXT load
		// fails to remember it.
	}
}

function systemPrefersDarkNow(): boolean {
	try {
		return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
	} catch {
		return false;
	}
}

// Applies `prefs` to <html> -- mirrors the inline bootstrap script's own
// logic (index.html's <head>) so a post-load selection change and the
// pre-paint bootstrap never disagree on how a given prefs object maps to
// DOM state.
function applyPrefsToDocument(prefs: ThemePrefs): void {
	const root = document.documentElement;
	root.classList.toggle('dark', resolveDarkMode(prefs.mode, systemPrefersDarkNow()));
	if (prefs.base !== THEME_DEFAULTS.base) root.setAttribute('data-cairn-base', prefs.base);
	else root.removeAttribute('data-cairn-base');
	if (prefs.theme !== THEME_DEFAULTS.theme) root.setAttribute('data-cairn-theme', prefs.theme);
	else root.removeAttribute('data-cairn-theme');
	if (prefs.chart !== THEME_DEFAULTS.chart) root.setAttribute('data-cairn-chart', prefs.chart);
	else root.removeAttribute('data-cairn-chart');
}

// Reactive runtime state for the settings dropdown -- one instance,
// constructed once at app root (App.svelte), read by ThemeSettings.svelte.
export class ThemeSettingsState {
	prefs = $state<ThemePrefs>(readStoredPrefs());

	constructor() {
		// PT-69 (architect's ruling §3): cross-tab propagation -- `storage`
		// fires in OTHER tabs on write, so a same-origin board+dashboard pair
		// open side by side stays in sync without a reload.
		window.addEventListener('storage', (e) => {
			if (e.key !== null && e.key !== THEME_STORAGE_KEY) return;
			this.prefs = readStoredPrefs();
			applyPrefsToDocument(this.prefs);
		});

		// PT-69 (architect's addendum item 3 + ux-designer's Mode addendum):
		// mode=system must keep tracking the OS LIVE while the page stays
		// open, not just resolve once at load -- distinct from the storage
		// listener above (cross-tab; this one is cross-OS-setting, same tab).
		try {
			window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
				if (this.prefs.mode === 'system') applyPrefsToDocument(this.prefs);
			});
		} catch {
			// matchMedia unavailable -- system mode simply won't live-follow;
			// the synchronous bootstrap/load-time resolution still applies.
		}
	}

	select(dimension: keyof ThemePrefs, id: string): void {
		const next = { ...this.prefs, [dimension]: id } as ThemePrefs;
		this.prefs = next;
		writeStoredPrefs(next);
		applyPrefsToDocument(next);
	}
}
