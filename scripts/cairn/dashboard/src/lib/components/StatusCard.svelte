<script lang="ts">
	import * as Card from '$lib/components/ui/card/index.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import type { BadgeVariant } from '$lib/components/ui/badge/badge.svelte';

	type Props = {
		eyebrow: string;
		value: string;
		badgeLabel?: string;
		badgeVariant?: BadgeVariant;
		detail?: string;
	};

	let { eyebrow, value, badgeLabel, badgeVariant = 'outline', detail }: Props = $props();
</script>

<!--
  design-system-spec.md → Dashboard scale: 24px card padding, 28px bold
  Merriweather (--font-sans) display value at line-height 1.15, 12px
  Space Grotesk eyebrow (uppercase, letter-spacing 0.08em, --muted-foreground).
-->
<Card.Root class="[--card-spacing:1.5rem] gap-3">
	<Card.Content class="flex flex-col gap-2">
		<span class="font-heading text-xs font-semibold tracking-[0.08em] text-muted-foreground uppercase">
			{eyebrow}
		</span>
		<span class="font-sans text-[28px] leading-[1.15] font-bold text-foreground">
			{value}
		</span>
		{#if badgeLabel}
			<Badge variant={badgeVariant}>{badgeLabel}</Badge>
		{/if}
		{#if detail}
			<span class="text-sm text-muted-foreground">{detail}</span>
		{/if}
	</Card.Content>
</Card.Root>
