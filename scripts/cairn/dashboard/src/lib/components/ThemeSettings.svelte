<script lang="ts">
	// PT-69 (ux-designer's ruling, 2026-08-29): top-right header placement
	// (icon-only, "Appearance" label via aria-label/tooltip -- supersedes
	// the retired Sidebar.Footer plan) + Popover row interaction (not
	// DropdownMenu.Sub): the top-level trigger opens a Popover listing the
	// four rows; each row opens a NESTED Popover, side="left", with that
	// dimension's options. Selecting an option closes only its own row
	// Popover, not the top-level panel -- consumed from App.svelte's
	// header row, alongside Refresh.
	import * as Popover from '$lib/components/ui/popover/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import Settings2 from '@lucide/svelte/icons/settings-2';
	import Monitor from '@lucide/svelte/icons/monitor';
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import CheckIcon from '@lucide/svelte/icons/check';
	import {
		THEME_MODE_OPTIONS,
		THEME_BASE_OPTIONS,
		THEME_THEME_OPTIONS,
		THEME_CHART_OPTIONS,
		type ThemeSettingsState,
		type ThemeOption,
	} from '$lib/theme-settings.svelte.js';

	let { themeState }: { themeState: ThemeSettingsState } = $props();

	// Top-level panel open state + one per row -- a row's Popover closing
	// on selection must not touch the top-level panel's own open state,
	// so each needs its own bindable boolean, not a single shared one.
	let topOpen = $state(false);
	let modeOpen = $state(false);
	let baseOpen = $state(false);
	let themeOpen = $state(false);
	let chartOpen = $state(false);

	const MODE_ICONS = { system: Monitor, light: Sun, dark: Moon } as const;

	function labelFor(options: ThemeOption[], id: string): string {
		return options.find((o) => o.id === id)?.label ?? id;
	}

	function select(dimension: 'mode' | 'base' | 'theme' | 'chart', id: string, closeRow: () => void): void {
		themeState.select(dimension, id);
		closeRow();
	}
</script>

<Popover.Root bind:open={topOpen}>
	<Popover.Trigger>
		{#snippet child({ props })}
			<Button {...props} variant="ghost" size="icon" aria-label="Appearance" title="Appearance">
				<Settings2 class="size-4" />
			</Button>
		{/snippet}
	</Popover.Trigger>
	<Popover.Content align="end" class="w-56 gap-1 p-1">
		<!-- Mode -->
		<Popover.Root bind:open={modeOpen}>
			<Popover.Trigger class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground">
				{@const ModeIcon = MODE_ICONS[themeState.prefs.mode]}
				<ModeIcon class="size-3.5 shrink-0" />
				<span>Mode: {labelFor(THEME_MODE_OPTIONS, themeState.prefs.mode)}</span>
			</Popover.Trigger>
			<Popover.Content side="left" align="start" class="w-40 gap-0.5 p-1">
				{#each THEME_MODE_OPTIONS as option (option.id)}
					{@const selected = option.id === themeState.prefs.mode}
					<button
						type="button"
						class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground"
						onclick={() => select('mode', option.id, () => (modeOpen = false))}
					>
						<span class="flex size-3.5 shrink-0 items-center justify-center">
							{#if selected}<CheckIcon class="size-3.5" />{/if}
						</span>
						{option.label}
					</button>
				{/each}
			</Popover.Content>
		</Popover.Root>

		<!-- Base Color -->
		<Popover.Root bind:open={baseOpen}>
			<Popover.Trigger class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground">
				<span class="inline-block size-2 shrink-0 rounded-full bg-muted-foreground" aria-hidden="true"></span>
				<span>Base Color: {labelFor(THEME_BASE_OPTIONS, themeState.prefs.base)}</span>
			</Popover.Trigger>
			<Popover.Content side="left" align="start" class="max-h-80 w-40 gap-0.5 overflow-y-auto p-1">
				{#each THEME_BASE_OPTIONS as option (option.id)}
					{@const selected = option.id === themeState.prefs.base}
					<button
						type="button"
						class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground"
						onclick={() => select('base', option.id, () => (baseOpen = false))}
					>
						<span class="flex size-3.5 shrink-0 items-center justify-center">
							{#if selected}<CheckIcon class="size-3.5" />{/if}
						</span>
						{option.label}
					</button>
				{/each}
			</Popover.Content>
		</Popover.Root>

		<!-- Theme -->
		<Popover.Root bind:open={themeOpen}>
			<Popover.Trigger class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground">
				<span class="inline-block size-2 shrink-0 rounded-full bg-primary" aria-hidden="true"></span>
				<span>Theme: {labelFor(THEME_THEME_OPTIONS, themeState.prefs.theme)}</span>
			</Popover.Trigger>
			<Popover.Content side="left" align="start" class="max-h-80 w-40 gap-0.5 overflow-y-auto p-1">
				{#each THEME_THEME_OPTIONS as option (option.id)}
					{@const selected = option.id === themeState.prefs.theme}
					<button
						type="button"
						class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground"
						onclick={() => select('theme', option.id, () => (themeOpen = false))}
					>
						<span class="flex size-3.5 shrink-0 items-center justify-center">
							{#if selected}<CheckIcon class="size-3.5" />{/if}
						</span>
						{option.label}
					</button>
				{/each}
			</Popover.Content>
		</Popover.Root>

		<!-- Chart Color -->
		<Popover.Root bind:open={chartOpen}>
			<Popover.Trigger class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground">
				<span class="inline-block size-2 shrink-0 rounded-full bg-chart-3" aria-hidden="true"></span>
				<span>Chart Color: {labelFor(THEME_CHART_OPTIONS, themeState.prefs.chart)}</span>
			</Popover.Trigger>
			<Popover.Content side="left" align="start" class="max-h-80 w-40 gap-0.5 overflow-y-auto p-1">
				{#each THEME_CHART_OPTIONS as option (option.id)}
					{@const selected = option.id === themeState.prefs.chart}
					<button
						type="button"
						class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground"
						onclick={() => select('chart', option.id, () => (chartOpen = false))}
					>
						<span class="flex size-3.5 shrink-0 items-center justify-center">
							{#if selected}<CheckIcon class="size-3.5" />{/if}
						</span>
						{option.label}
					</button>
				{/each}
			</Popover.Content>
		</Popover.Root>
	</Popover.Content>
</Popover.Root>
