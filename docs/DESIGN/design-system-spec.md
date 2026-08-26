# Design System Spec

> The written companion to `tokens.css` + `screen.css`. The CSS files are the machine-readable source of truth; this doc explains the *why* and the usage rules. Owned by the `ux-designer` agent. Generate/refine with `/generate-designdoc`.

## What governs this system

**Direction pivot (2026-08-26):** this project's UI direction is now Svelte dashboard applications built on **shadcn-svelte**. The canonical token source is a specific shadcn-svelte theme preset — [`shadcn-svelte.com/create/preview?preset=b6XadDxmQS`](https://www.shadcn-svelte.com/create/preview?preset=b6XadDxmQS) — a JS-rendered page; every value in this doc was extracted from its live `:root`/`.dark` output on **2026-08-26** and is treated as authoritative for that date. If the preset changes upstream, re-extract and diff before trusting this doc blindly.

shadcn-svelte's CSS-custom-property convention **is** our token architecture now — this supersedes the Atlassian dotted `color.background.*` naming grammar this doc previously used (that section governed the cairn board's `board.css` only; see **Legacy/migration** below for where it now lives).

`tokens.css` (per the artifacts table in `CLAUDE.md`) is the **downstream, machine-readable deliverable** `frontend-lead` consumes — for this system it is, verbatim, the `:root` and `.dark` blocks reproduced in **Foundations → Color**, dropped into a Svelte app's `app.css` per shadcn-svelte's standard Tailwind-v4 `@theme inline` wiring (`bunx shadcn-svelte@latest init` scaffolds this; this doc doesn't re-derive that plumbing, only the values). `screen.css` in this system is whatever component-level overrides a given dashboard needs on top of shadcn-svelte's shipped component CSS — expected to be thin, since shadcn owns most of it.

---

## Foundations

### Color

All values are `oklch()`. Where a role has no dark-mode override listed, dark mode is presumed to reuse the light value (chart ramp) — confirmed against the extracted payload, not assumed.

#### Light (`:root`)

| Token | Value | Role |
|---|---|---|
| `--background` | `oklch(1 0 0)` | Page background |
| `--foreground` | `oklch(0.147 0.004 49.25)` | Default body text |
| `--card` | `oklch(1 0 0)` | Card surface |
| `--card-foreground` | `oklch(0.147 0.004 49.25)` | Text on card |
| `--popover` | `oklch(1 0 0)` | Popover/dropdown surface |
| `--popover-foreground` | `oklch(0.147 0.004 49.25)` | Text on popover |
| `--primary` | `oklch(0.5 0.134 242.749)` | Primary action fill (sky blue) |
| `--primary-foreground` | `oklch(0.977 0.013 236.62)` | Text on primary fill |
| `--secondary` | `oklch(0.967 0.001 286.375)` | Secondary button/surface |
| `--secondary-foreground` | `oklch(0.21 0.006 285.885)` | Text on secondary |
| `--muted` | `oklch(0.97 0.001 106.424)` | Muted background (subtle panels) |
| `--muted-foreground` | `oklch(0.553 0.013 58.071)` | Muted/meta text |
| `--accent` | `oklch(0.97 0.001 106.424)` | Hover/active surface accent |
| `--accent-foreground` | `oklch(0.216 0.006 56.043)` | Text on accent surface |
| `--destructive` | `oklch(0.577 0.245 27.325)` | Destructive fill (delete, danger) |
| `--destructive-foreground` | `oklch(0.97 0.01 17)` | Text on destructive fill |
| `--border` | `oklch(0.923 0.003 48.717)` | Default hairline border |
| `--input` | `oklch(0.923 0.003 48.717)` | Input border |
| `--ring` | `oklch(0.709 0.01 56.259)` | Focus ring |
| `--chart-1` | `oklch(0.905 0.182 98.111)` | Chart step 1 (lightest) |
| `--chart-2` | `oklch(0.795 0.184 86.047)` | Chart step 2 |
| `--chart-3` | `oklch(0.681 0.162 75.834)` | Chart step 3 |
| `--chart-4` | `oklch(0.554 0.135 66.442)` | Chart step 4 |
| `--chart-5` | `oklch(0.476 0.114 61.907)` | Chart step 5 (darkest) |
| `--sidebar` | `oklch(0.985 0.001 106.423)` | Sidebar background |
| `--sidebar-foreground` | `oklch(0.147 0.004 49.25)` | Sidebar text |
| `--sidebar-primary` | `oklch(0.588 0.158 241.966)` | Sidebar active/primary item |
| `--sidebar-primary-foreground` | `oklch(0.977 0.013 236.62)` | Text on sidebar-primary |
| `--sidebar-accent` | `oklch(0.97 0.001 106.424)` | Sidebar hover/accent |
| `--sidebar-accent-foreground` | `oklch(0.216 0.006 56.043)` | Text on sidebar-accent |
| `--sidebar-border` | `oklch(0.923 0.003 48.717)` | Sidebar hairline |
| `--sidebar-ring` | `oklch(0.709 0.01 56.259)` | Sidebar focus ring |

#### Dark (`.dark`)

| Token | Value | Role |
|---|---|---|
| `--background` | `oklch(0.147 0.004 49.25)` | Page background |
| `--foreground` | `oklch(0.985 0.001 106.423)` | Default body text |
| `--card` | `oklch(0.216 0.006 56.043)` | Card surface |
| `--card-foreground` | `oklch(0.985 0.001 106.423)` | Text on card |
| `--primary` | `oklch(0.443 0.11 240.79)` | Primary action fill (dimmer sky blue) |
| `--primary-foreground` | `oklch(0.977 0.013 236.62)` | Text on primary fill |
| `--secondary` | `oklch(0.274 0.006 286.033)` | Secondary button/surface |
| `--secondary-foreground` | `oklch(0.985 0 0)` | Text on secondary |
| `--muted` | `oklch(0.268 0.007 34.298)` | Muted background |
| `--muted-foreground` | `oklch(0.709 0.01 56.259)` | Muted/meta text |
| `--accent` | `oklch(0.268 0.007 34.298)` | Hover/active surface accent |
| `--accent-foreground` | `oklch(0.985 0.001 106.423)` | Text on accent surface |
| `--destructive` | `oklch(0.704 0.191 22.216)` | Destructive fill |
| `--border` | `oklch(1 0 0 / 10%)` | Default hairline border (translucent white) |
| `--input` | `oklch(1 0 0 / 15%)` | Input border |
| `--ring` | `oklch(0.553 0.013 58.071)` | Focus ring |
| `--chart-1`…`--chart-5` | same as light | Chart ramp is not re-tuned for dark mode |
| `--sidebar` | `oklch(0.216 0.006 56.043)` | Sidebar background |
| `--sidebar-primary` | `oklch(0.685 0.169 237.323)` | Sidebar active/primary item |

**Character read:** warm stone neutrals (hue ≈ 49–58, not a cool navy-grey), a single sky-blue accent hue (≈ 237–243) carried by both `--primary` and `--sidebar-primary`, and a single-hue golden chart ramp (hue ≈ 61–98). This is a materially different palette from the retired Atlassian-modeled one — do not cross-reference old hex values as if they still apply; see **Legacy/migration**.

### Typography

| Token | Stack | Notes |
|---|---|---|
| `--font-sans` | `'Merriweather Variable', Georgia, 'Times New Roman', serif` | The preset assigns a **serif** to the "sans" slot — not a typo in the preset, a deliberate editorial choice. Fallback added here since the preset payload didn't specify one. |
| `--font-mono` | `'Geist Mono Variable', ui-monospace, SFMono-Regular, Menlo, monospace` | For IDs, code, tabular/numeric dashboard values |

Both are Google Fonts variable families — neither ships as a system stack, so both cost a network font request (a reversal of the previous system's "zero font requests" stance; see the pushback note at the end of this doc).

Type scale — shadcn-svelte dashboard norms (Tailwind `text-*` steps actually used across shadcn block templates, not a generated modular scale):

| Token | Size | Line-height | Weight | Used for |
|---|---|---|---|---|
| `text-xs` | 12px | 16px | 400 / 500 (badge) | Badge/chip text, table meta, timestamps |
| `text-sm` | 14px | 20px | 400 | **Base UI size** — buttons, inputs, table cells, card body, nav items |
| `text-base` | 16px | 24px | 400 | Prose body copy inside cards/dialogs |
| `text-lg` | 18px | 28px | 600 | Card title, dialog title |
| `text-xl` | 20px | 28px | 600 | Section heading |
| `text-2xl` | 24px | 32px | 700 | Page/dashboard title |

Unlike the previous system, shadcn's base UI size is **14px**, not 13px — close enough that it isn't a meaningful regression, but don't silently reuse the old 13px assumption in hand-rolled CSS.

### Radius scale

The preset sets one base, `--radius: 0.625rem` (10px); shadcn-svelte's standard convention derives the rest from it (not present in the extracted payload verbatim — reproduced here per shadcn's documented `@theme inline` mapping, flagged as derived, not independently re-extracted):

| Token | Formula | Value | Used for |
|---|---|---|---|
| `--radius-sm` | `radius - 4px` | 6px | Small controls: badge, checkbox |
| `--radius-md` | `radius - 2px` | 8px | Button, input, select |
| `--radius-lg` | `radius` | 10px | Card, dialog, popover |
| `--radius-xl` | `radius + 4px` | 14px | Large surfaces: sheet panel, drawer |

### Chart ramp

`--chart-1`…`--chart-5` is a **single-hue sequential ramp** (hue stays in the 61–98° golden band; only lightness/chroma step down). This is correct and good for **sequential/quantitative data** (a heat scale, a single-metric magnitude series) — it reads badly for **categorical data** (5 distinct series that need to be told apart by hue, e.g. "issues by assignee" or "issues by repo"). Using this ramp categorically is a foreseeable misuse; flag it in review if a chart spec calls for 3+ unrelated categorical series and route those to the record-status/badge palette below instead, which does vary hue.

### Sidebar tokens

Dashboards are assumed to ship a persistent nav sidebar as a first-class surface, not an afterthought — the preset gives it its own token group (`--sidebar`, `--sidebar-foreground`, `--sidebar-primary(-foreground)`, `--sidebar-accent(-foreground)`, `--sidebar-border`, `--sidebar-ring`) distinct from `--card`/`--popover`, so a sidebar can be tinted independently (here: barely — `--sidebar` in light mode is `oklch(0.985 …)` vs. page `--background` `oklch(1 …)`, a near-imperceptible 1.5% lightness step, just enough to read as a distinct plane without a visible seam).

### Shadows

The extracted payload did not include custom `--shadow-*` overrides, meaning this preset does **not** re-tune shadows — it inherits shadcn-svelte's default `shadow-xs`/`shadow-sm`/`shadow-md` Tailwind scale (subtle, low-opacity black, 1–3px offsets). Treat the shadow scale as **shadcn's stock default, not preset-specific** — this is the one token group in this doc not independently re-verified against the live page today; if a future audit needs exact shadow values, pull them from the generated `app.css` shadcn-svelte writes on `init`, not from this doc.

Usage: `shadow-xs` on inputs/buttons (barely-there depth cue), `shadow-sm` on cards/popovers, reserve anything heavier for a modal/sheet that floats over the whole page — mirrors the old system's "one subtle shadow + one heavier overlay shadow" split.

---

## Project extensions (proposed — not in the shadcn-svelte preset)

shadcn-svelte defines UI primitives, not domain semantics. The cairn tracker UI needs a **record-status vocabulary** (five values) and a **badge/chip semantic vocabulary** (person/taxonomy/warning/danger/neutral) that don't exist in the preset. The values below are **proposed** by this doc, harmonized to the preset's hue system (warm neutral base at hue ≈ 49–58, sky-blue primary at hue ≈ 237–243, golden chart ramp at hue ≈ 61–98) — they are new judgment calls, not extracted from anything, and should be reviewed before `tokens.css` treats them as final.

Two hues had to be invented because the preset has **no green and no violet/purple** anywhere in its palette (a real gap for a status/taxonomy system — see pushback note). Green was placed at hue 145 (a standard "success" green, far enough from the sky-blue primary at 240 and the golden chart ramp at 61–98 to stay visually distinct) and violet at hue 300 (matching the low-chroma, high-lightness treatment `--secondary` already uses, so it reads as "another muted taxonomy tag," not a second accent).

### Record-status vocabulary (proposed)

| Status | Light dot/accent | Light bg (subtle) | Light fg | Dark dot/accent | Dark bg (subtle) | Dark fg | Reasoning |
|---|---|---|---|---|---|---|---|
| `planned` | `oklch(0.709 0.01 56.259)` (= dark `--muted-foreground`, reused) | `oklch(0.97 0.001 106.424)` (`--muted`) | `oklch(0.553 0.013 58.071)` (`--muted-foreground`) | `oklch(0.709 0.01 56.259)` | `oklch(0.268 0.007 34.298)` (`--muted` dark) | `oklch(0.709 0.01 56.259)` | Reuses `--muted*` verbatim — "not started" is the system's neutral default, shouldn't need a new hue |
| `in-progress` | `oklch(0.5 0.134 242.749)` (= `--primary`) | `oklch(0.94 0.03 240)` | `oklch(0.4 0.13 242.749)` | `oklch(0.443 0.11 240.79)` (= dark `--primary`) | `oklch(0.3 0.08 240)` | `oklch(0.85 0.05 240)` | Reuses `--primary` hue exactly — matches the old system's rule that the one accent = the active/live state |
| `paused` | `oklch(0.72 0.15 70)` | `oklch(0.96 0.05 80)` | `oklch(0.45 0.13 65)` | `oklch(0.75 0.16 70)` | `oklch(0.32 0.07 65)` | `oklch(0.85 0.1 75)` | Amber pulled from inside the existing chart-ramp hue band (61–98°) so it reads as "in-family," not a random new color |
| `done` | `oklch(0.6 0.14 145)` | `oklch(0.94 0.05 150)` | `oklch(0.4 0.13 145)` | `oklch(0.65 0.15 145)` | `oklch(0.3 0.08 150)` | `oklch(0.85 0.08 150)` | **Invented hue** — preset has no green; placed far from primary and chart hues |
| `cancelled` | `oklch(0.577 0.245 27.325)` (= `--destructive`) | `oklch(0.95 0.04 27)` | `oklch(0.45 0.2 27)` | `oklch(0.704 0.191 22.216)` (= dark `--destructive`) | `oklch(0.3 0.1 27)` | `oklch(0.85 0.1 25)` | Reuses `--destructive` exactly |

### Badge/chip semantic vocabulary (proposed)

Keeps the old system's category rule — **person = primary/sky, taxonomy = green, warning = amber, danger = destructive, neutral = muted** — re-expressed in the new hue system:

| Category | Example uses | Light bg | Light fg | Dark bg | Dark fg |
|---|---|---|---|---|---|
| Person (assignee) | `.badge-assignee` | `oklch(0.94 0.03 240)` | `oklch(0.4 0.13 242.749)` | `oklch(0.3 0.08 240)` | `oklch(0.85 0.05 240)` |
| Taxonomy (milestone) | `.badge-milestone` | `oklch(0.94 0.05 150)` | `oklch(0.4 0.13 145)` | `oklch(0.3 0.08 150)` | `oklch(0.85 0.08 150)` |
| Taxonomy (repo/release) | `.badge-repo`, `.badge-release` | `oklch(0.93 0.04 300)` | `oklch(0.45 0.14 300)` | `oklch(0.32 0.08 300)` | `oklch(0.85 0.06 300)` | 
| Warning (subissues, GA) | `.badge-subissues`, `.badge-ga` | `oklch(0.96 0.05 80)` | `oklch(0.45 0.13 65)` | `oklch(0.32 0.07 65)` | `oklch(0.85 0.1 75)` |
| Danger (blocked) | `.badge-blocked` | `oklch(0.95 0.04 27)` | `oklch(0.45 0.2 27)` | `oklch(0.3 0.1 27)` | `oklch(0.85 0.1 25)` |
| Neutral (default, archived) | `.badge`, `.badge-archived` | `oklch(0.97 0.001 106.424)` (`--muted`) | `oklch(0.553 0.013 58.071)` (`--muted-foreground`) | `oklch(0.268 0.007 34.298)` | `oklch(0.709 0.01 56.259)` |

**Note on repo/release sharing violet:** as with the old palette, `repo` and `release` share a tint deliberately (mutually exclusive on one card) — carried forward unchanged as a rule, just re-hued.

---

## Components

Map to shadcn-svelte's shipped components — install via `bunx shadcn-svelte@latest add <name>`, don't hand-roll. Anatomy follows shadcn's documented structure; the right column is what the cairn board specifically needs from each.

| shadcn-svelte component | Anatomy (shadcn norm) | Cairn board usage |
|---|---|---|
| **Button** | `<Button variant={default\|secondary\|destructive\|outline\|ghost\|link} size={default\|sm\|lg\|icon}>` | `default` = primary actions (new issue submit); `outline` = cancel/secondary; `ghost` = icon-only (drawer close); `destructive` = delete/archive confirm |
| **Badge** | `<Badge variant={default\|secondary\|destructive\|outline}>`, plus custom variants for the extension palette above | Status chips, assignee/milestone/repo/blocked/subissues chips — extend `badgeVariants` with the six categories from **Project extensions** rather than inlining colors per-usage |
| **Card** | `Card.Root > Card.Header > Card.Title/Card.Description, Card.Content, Card.Footer` | Issue card, containment-card nesting (repo-group → swimlane → column) — same depth-alternation principle as before, now expressed via `bg-card` vs. `bg-muted` instead of hand-picked hex |
| **Table** | `Table.Root > Table.Header/Body > Table.Row > Table.Head/Cell` | List view — shadcn's table ships sortable-header patterns and row hover as CSS, closing the old "no sort indicator" gap only if the sort-icon slot is actually used, not just the markup |
| **Sheet / Dialog** | `Sheet.Root > Sheet.Trigger, Sheet.Content > Sheet.Header, Sheet.Footer` (Dialog is the centered variant; Sheet is the edge-anchored drawer) | Sheet = the right-side issue drawer (direct replacement for the old bespoke `.drawer`); Dialog = new-issue modal, confirm-delete |
| **Sidebar** | `Sidebar.Provider > Sidebar.Root > Sidebar.Header, Sidebar.Content (Sidebar.Group×n), Sidebar.Footer`, collapsible via `Sidebar.Trigger` | Primary nav — majors/milestones tree, view switcher; replaces the old flat `.majors-tabs` row with a real collapsible nav surface |
| **Sonner (toast)** | `<Toaster />` mounted once at app root, imperative `toast.success()/toast.error()` calls | Direct replacement for the old bespoke `.toast`/`.toast.error` — ships enter/exit animation and stacking for free |
| **Skeleton** | `<Skeleton class="h-4 w-full" />` composed to match real layout | New capability — the old system had **no loading state at all** (documented gap). Every list/board fetch should render a skeleton shaped like the real card/row/table it's replacing, per the "no decorative loading states" working principle |

**shadcn closes the old spec's two biggest flagged gaps automatically:** every interactive shadcn-svelte primitive ships a `focus-visible:ring-ring` treatment and a `disabled:opacity-50 disabled:pointer-events-none` state out of the box — adopting the library, not just its tokens, is what fixes this, so don't reintroduce ad hoc unstyled buttons/inputs that bypass the primitives.

**What's still ours to set, because shadcn doesn't opine on it:**
- **Reduced-motion policy.** shadcn's own transitions (accordion, sheet slide, toast) don't universally respect `prefers-reduced-motion` out of the box. If motion sensitivity matters for this project, wrap `tailwind.config`/global CSS with a `@media (prefers-reduced-motion: reduce)` override — still an open item, not solved by adopting the library.
- **Loading-state authoring discipline.** Skeleton exists as a primitive; nothing forces every fetch boundary to actually use it. Still a per-feature implementation responsibility.

---

## Legacy/migration

`scripts/cairn/board/board.css` is now the **legacy implementation** — the Atlassian-modeled dotted-token system this doc previously specified. It is not being touched by this doc; migrating the board itself to shadcn-svelte tokens is **future implementation work**, tracked separately, not performed here. This table exists so a future migration PR has a starting map, not as a claim the migration is done:

| Old (`board.css`) | New token | Note |
|---|---|---|
| `#F4F5F7` (page bg) | `--background` (light) / consider `--muted` for the sunken-well cases | Old system used one grey for two roles (page bg *and* sunken well); new system should pick per-role, not carry the overload forward |
| `#FFFFFF` (card/panel bg) | `--card` / `--background` | |
| `#0052CC` (accent/primary) | `--primary` | Hue shifts from Atlassian B400 (≈ hue 258, more saturated) to the preset's sky blue (hue ≈ 243, lower chroma) — a visible re-brand, not a drop-in swap |
| `#DE350B` (danger/banner) | `--destructive` | |
| `#172B4D` (default text) | `--foreground` | |
| `#5E6C84` (subtle text) | `--muted-foreground` | |
| `#DFE1E6` (border) | `--border` | |
| Chip pairs (`.chip.assignee`, `.chip.milestone`, etc.) | Badge variants, see **Project extensions** | Category rule (person/taxonomy/warning/danger/neutral) carries forward unchanged; only the hex values and the delivery mechanism (Tailwind badge variants vs. hand-rolled `.chip.*` classes) change |
| `border-radius: 6px` (`--radius` old) | `--radius-md` (8px) or `--radius-lg` (10px) depending on component | Not a 1:1 value match — pick per new scale, don't hardcode 6px forward |
| `elevation.shadow.raised` / `.overlay` | `shadow-sm` / `shadow-md`+ (shadcn default scale) | |
| System-UI type stack | `--font-sans` (Merriweather) / `--font-mono` (Geist Mono) | Full stack replacement, see typography section and pushback note below |

---

## Accessibility

**Target: WCAG AA**, unchanged from the previous system. Contrast below is computed from OKLCH lightness deltas as an engineering estimate, not a colorimetrically verified measurement (recommend running the final `tokens.css` through a proper OKLCH-aware contrast checker before ship — flagging the method, not asserting precision).

| Pair | Light-mode estimate | AA (4.5:1 normal text)? |
|---|---|---|
| `--foreground` on `--background` | L 0.147 vs L 1.0 — very large delta | Pass, trivially (comparable to the old system's 12.6:1 near-black-on-white) |
| `--muted-foreground` on `--background` | L 0.553 vs L 1.0 | **Passes, but narrowly** — comparable band to the old system's `#5E6C84`/white pair (5.6:1); don't assume headroom to go lighter |
| `--primary-foreground` on `--primary` | L 0.977 vs L 0.5, but `--primary` carries chroma 0.134 (fairly saturated blue) | Likely passes (comparable to the old white-on-`#0052CC` at 5.1:1) but chroma at this level measurably eats into perceived contrast versus a chroma-0 gray of the same lightness — worth an actual check, not an assumption |
| `--destructive-foreground` on `--destructive` | L 0.97 vs L 0.577, chroma 0.245 — the **highest-chroma color in the whole palette** | **Borderline — the pair most likely to actually fail or sit right at the line.** High chroma reds are exactly where lightness-only contrast math is least reliable; this is the one pair to measure for real before shipping any destructive-filled button/badge text, same flag the old system raised for its red |
| `--sidebar-foreground` on `--sidebar` | L 0.147 vs L 0.985 | Pass, trivially |

**New flag this palette introduces that the old one didn't have:** the old type stack was a system-UI sans at all sizes; this one puts **Merriweather, a serif, in the base UI font slot**, including down at `text-xs` (12px badge/chip text — the system's smallest, highest-density text). Serifs carry finer stroke contrast and are demonstrably harder to read at small sizes than a humanist sans, independent of color contrast. Recommend not shipping `text-xs` badge/chip labels in the serif family even if the rest of the UI stays on-brand — either bump badge text to `text-sm` or scope `--font-sans` out of the smallest components. This is a real, new accessibility-adjacent risk, not inherited from the old spec.

**Open items carried forward, still true:**
- Reduced-motion policy is still ours to set (see Components) — shadcn doesn't solve this by default.
- The extension palette (status/badge colors) above is proposed, not measured — verify contrast on the actual proposed pairs before locking `tokens.css`, same caveat as the destructive pair.

---

## Pushback (UX owner notes on the preset, not fixes)

Flagging for the team's awareness — not blocking adoption of the preset, but worth a conscious yes/no:

1. **Merriweather-as-sans is an unusual, opinionated choice for a data-dense dashboard.** Serif body text is defensible for long-form reading; it is a less obvious fit for tables, forms, and badges — the majority of a tracker/dashboard's actual surface area. Worth a quick internal design review before this ships broadly, not just accepting the preset default because it's the preset default.
2. **Two Google Fonts loaded (Merriweather Variable + Geist Mono Variable) reverses the old system's zero-network-font-request stance.** That was a deliberate old-system choice for perf/offline-resilience reasons — if those constraints still matter for this project, self-host both variable fonts rather than trusting Google Fonts' CDN at runtime, and preload them to avoid FOUC on a data-heavy first paint.
3. **No green, no violet/purple anywhere in the extracted palette.** For a system whose primary consumer is a status-tracking dashboard, the total absence of a "done/success" hue and a distinct taxonomy hue is a real gap, not a style preference — the two hues proposed in **Project extensions** are inventions this doc had to make to cover it, and should get explicit sign-off rather than being treated as part of the "official" preset.
4. **The chart ramp is sequential-only by construction.** Fine if this project's charts stay single-metric; if roadmap plans include any categorical chart (status breakdown, assignee distribution), that need should be scoped now so it doesn't get bolted on as an afterthought with clashing hues later.
