# Design System Spec

> The written companion to `tokens.css` + `screen.css`. The CSS files are the machine-readable source of truth; this doc explains the *why* and the usage rules. Owned by the `ux-designer` agent. Generate/refine with `/generate-designdoc`.

## What governs this system

**Direction pivot (2026-08-26):** this project's UI direction is now Svelte dashboard applications built on **shadcn-svelte**. The canonical token source is a specific shadcn-svelte theme preset — [`shadcn-svelte.com/create/preview?preset=b6XadDxmQS`](https://www.shadcn-svelte.com/create/preview?preset=b6XadDxmQS) — a JS-rendered page; every value in this doc was extracted from its live `:root`/`.dark` output on **2026-08-26** and is treated as authoritative for that date. If the preset changes upstream, re-extract and diff before trusting this doc blindly.

The preset's own creator-sidebar metadata (read from the live page, not inferred): **Style "Mira"**, Base "Stone", Theme "Sky", Chart "Yellow", Heading face "Space Grotesk", Body face "Merriweather", Icon library **Lucide**, Radius "Medium". Use `lucide-svelte` for all iconography — it's the preset's stated icon set, not an independent choice this doc is making.

shadcn-svelte's CSS-custom-property convention **is** our token architecture now — this supersedes the Atlassian dotted `color.background.*` naming grammar this doc previously used (that section governed the cairn board's `board.css` only; see **Legacy/migration** below for where it now lives).

`tokens.css` (per the artifacts table in `CLAUDE.md`) is the **downstream, machine-readable deliverable** `frontend-lead` consumes — for this system it is, verbatim, the `:root` and `.dark` blocks reproduced in **Foundations → Color**, dropped into a Svelte app's `app.css` per shadcn-svelte's standard Tailwind-v4 `@theme inline` wiring (`bunx shadcn-svelte@latest init` scaffolds this; this doc doesn't re-derive that plumbing, only the values). `screen.css` in this system is whatever component-level overrides a given dashboard needs on top of shadcn-svelte's shipped component CSS — expected to be thin, since shadcn owns most of it.

---

## Foundations

### Color

All values are `oklch()`. Where a role has no dark-mode override listed, dark mode is presumed to reuse the light value (chart ramp) — confirmed against the extracted payload, not assumed.

**Dashboard canvas convention: cards-on-muted, not cards-on-background.** `--background` (`oklch(1 0 0)`, pure white in light mode) is a real token, but the preset's own live preview does not paint the page canvas with it — the visible dashboard canvas in the preview is `--muted` (`oklch(0.97 0.001 106.424)`), with `--card` (white) surfaces sitting on top for actual content panels. Adopt this as the stated convention for this system: page/canvas root = `bg-muted`, content cards/panels = `bg-card`, reserving bare `--background` for chrome that intentionally sits flush with card color (e.g. a toolbar meant to blend into the content plane). This mirrors most shadcn-svelte dashboard block templates and gives the white cards something to visually separate from.

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
| `--muted-foreground` | `oklch(0.5485 0.013 58.071)` | Muted/meta text — **darkened from the preset's own `oklch(0.553 0.013 58.071)` (PT-69, "darken the ink," see Accessibility)**; every other Base Color variant carries its own equivalently-derived ink |
| `--accent` | `oklch(0.97 0.001 106.424)` | Hover/active surface accent |
| `--accent-foreground` | `oklch(0.216 0.006 56.043)` | Text on accent surface |
| `--destructive` | `oklch(0.577 0.245 27.325)` | Destructive fill (delete, danger) |
| `--destructive-foreground` | `oklch(1 0 0)` | Text on destructive fill — **resolved (PT-69, 2026-08-29, ux-designer's design call on architect's ruling, see Accessibility):** the preset's own `oklch(0.97 0.01 17)` fails AA at 4.35:1 float / 4.37:1 quantized against this palette's actual `--destructive` fill (both models agree it fails — see the **two-model rule** in Accessibility); pure white clears both with room (4.76:1 float / 4.77:1 quantized). Accepted — costs the preset's slight warm-pink tint on destructive-chip text, chosen over the alternative of darkening the `--destructive` fill itself (which would change the brand danger hue, a bigger visible change) |
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
| `--destructive-foreground` | `oklch(0.31 0.01 17.0)` | Text on destructive fill — **split from `:root`'s value, PT-69 (2026-08-29, f26dbad; re-derived under the two-model rule, see Accessibility)**: dark mode's `--destructive` is unusually a *lighter* red than light mode's own, so a shared ink can never clear both. `L 0.3145` cleared the floor under one contrast model but not the other (4.4955:1 float / 4.5268:1 quantized — the floor sat inside that gap); `L 0.31` clears both with real margin (4.5694:1 float / 4.5970:1 quantized) |
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
| `--font-sans` | `'Merriweather Variable', Georgia, 'Times New Roman', serif` | Despite the `--font-sans` name (shadcn's slot naming, not a description), the preset assigns a **serif** to this slot — a deliberate editorial choice, not a typo. Fallback added here since the preset payload didn't specify one. |
| `--font-heading` | `'Space Grotesk Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` | **Corrected 2026-08-26 — missed in the initial extraction.** A second, distinct face used for headings and card titles — **not** for big display/stat numbers (see correction below); confirmed by measuring actual rendered output in the preset's live preview, not just reading declared variables. Fallback added here since the preset payload didn't specify one. |
| `--font-mono` | `'Geist Mono Variable', ui-monospace, SFMono-Regular, Menlo, monospace` | For IDs, code, tabular/numeric dashboard values |

**This is a serif-body/sans-heading pairing, not serif-everywhere** — the initial extraction of this doc missed `--font-heading` and wrongly implied Merriweather covered the whole UI. Measured usage in the live preview: **Space Grotesk** (`--font-heading`) renders on headings and card titles only (20px+ — `text-xl`/`text-2xl`); **Merriweather** (`--font-sans`) renders on body copy, buttons, inputs, form labels, and table cells — i.e. `--font-sans` is still the base/default face applied everywhere that isn't explicitly a heading/title.

**Correction (2026-08-26, from a screenshot of the live preview):** big display/stat values (e.g. dashboard money figures) do **not** take the heading face — they render in **Merriweather bold** (`--font-sans`, bold weight), while card titles/labels use `--font-heading` (Space Grotesk). Don't infer "large text = heading face" from size alone; the face split is by *role* (title vs. stat/display number), not by size tier. A dashboard-stat component should set `font-family: var(--font-sans); font-weight: 700;` at whatever size the metric calls for, not reach for `--font-heading`.

All three are Google Fonts variable families — none ship as a system stack, so all three cost a network font request (a reversal of the previous system's "zero font requests" stance; see the pushback note at the end of this doc).

Type scale — shadcn-svelte dashboard norms (Tailwind `text-*` steps actually used across shadcn block templates, not a generated modular scale):

**Face is by role, not by size tier** — don't infer the face from pixel size alone (see the display-value correction below, where a large number is body-face bold, not heading-face).

| Token | Size | Line-height | Weight | Face | Used for |
|---|---|---|---|---|---|
| `text-xs` | 12px | 16px | 400 / 500 (badge) | `--font-sans` (Merriweather) | Badge/chip text, table meta, timestamps |
| `text-sm` | 14px | 20px | 400 | `--font-sans` (Merriweather) | **Base UI size** — buttons, inputs, table cells, card body, nav items |
| `text-base` | 16px | 24px | 400 | `--font-sans` (Merriweather) | Prose body copy inside cards/dialogs |
| `text-lg` | 18px | 28px | 600 | `--font-heading` (Space Grotesk) | Card title, dialog title |
| `text-xl` | 20px | 28px | 600 | `--font-heading` (Space Grotesk) | Section heading |
| `text-2xl` | 24px | 32px | 700 | `--font-heading` (Space Grotesk) | Page/dashboard title |
| `text-2xl`/`text-3xl` as a **stat/display value** | 24–30px | tight (1.1–1.2) | 700 | `--font-sans` **bold** (Merriweather), *not* `--font-heading` | Big dashboard metric numbers (e.g. money figures) — role-based exception, confirmed from a screenshot of the live preview: display numbers stay on the body face at bold weight, only titles/headings switch face |

Unlike the previous system, shadcn's base UI size is **14px**, not 13px — close enough that it isn't a meaningful regression, but don't silently reuse the old 13px assumption in hand-rolled CSS.

### Dashboard scale

**Approved (2026-08-26)** as the standard density for dashboard screens — future screens should inherit these values rather than re-deriving spacing/type sizing per screen. Validated against the preset's own live preview at its actual rendered proportions, not picked independently of it.

| Element | Value |
|---|---|
| Page margins | 28px |
| Gap between cards | 24px |
| Card padding | 24px (nested/kanban cards 16px; wells 14px) |
| Display/stat values | 28px, `--font-sans` (Merriweather) bold, line-height 1.15 |
| Card/section titles | 17–18px, `--font-heading` (Space Grotesk) 600 |
| Eyebrow labels | 12px, `--font-heading` 600, uppercase, letter-spacing 0.08em, `--muted-foreground` |
| Base UI text | 14–15px |
| Meta/secondary text | 13px |
| Mono (IDs) | 12–13px |
| Badges | 12px text, `3px 11px` padding, pill radius |
| Buttons | 14px text, `8px 16px` padding, 8px radius — this is `--radius-md` per this doc's own Radius scale table below, not `--radius-sm` (6px); flagging the mismatch rather than silently relabeling the token |
| Table rows | 13px text, `16px` cell padding |

Two figures here refine, rather than duplicate, the generic type scale above: the 28px stat-value size is a specific instance of the `text-2xl`/`text-3xl`-as-display-value row (Merriweather bold, not `--font-heading`); the 17–18px title size sits inside the `text-lg` step already mapped to `--font-heading`. Where this table and the generic type scale disagree on a specific pixel value, this table wins for dashboard-screen work — it's the number Mosko actually approved against the rendered preview.

### Radius scale

The preset sets one base, `--radius: 0.625rem` (10px); shadcn-svelte's standard convention derives the rest from it. **Corrected 2026-08-26** against the live scaffold (`scripts/cairn/dashboard`'s `shadcn-svelte init --preset b6XadDxmQS` output, in its generated `@theme inline` block) — an earlier revision of this table reproduced a *subtractive* formula (`radius - 4px`, etc.) that had only ever been derived on paper from shadcn's general documented convention, never checked against what the CLI actually generates for this preset. The real formula is *multiplicative*; the computed px values below are unchanged at this project's `--radius: 0.625rem` (both formulas agree numerically at this one base value — they diverge the moment `--radius` is customized, which is why the distinction matters):

| Token | Formula | Value | Used for |
|---|---|---|---|
| `--radius-sm` | `radius * 0.6` | 6px | Small controls: badge, checkbox |
| `--radius-md` | `radius * 0.8` | 8px | Button, input, select |
| `--radius-lg` | `radius` | 10px | Card, dialog, popover |
| `--radius-xl` | `radius * 1.4` | 14px | Large surfaces: sheet panel, drawer |
| `--radius-2xl` | `radius * 1.8` | 18px | (scaffold-generated step beyond this system's named usage list) |
| `--radius-3xl` | `radius * 2.2` | 22px | (scaffold-generated step beyond this system's named usage list) |
| `--radius-4xl` | `radius * 2.6` | 26px | (scaffold-generated step beyond this system's named usage list) |

### Chart ramp

`--chart-1`…`--chart-5` is a **single-hue sequential ramp** (hue stays in the 61–98° golden band; only lightness/chroma step down). This is correct and good for **sequential/quantitative data** (a heat scale, a single-metric magnitude series) — it reads badly for **categorical data** (5 distinct series that need to be told apart by hue, e.g. "issues by assignee" or "issues by repo"). With the record-status/badge vocabulary now also token-only and hue-flat by design (see **Project extensions**), there is genuinely **no multi-hue categorical palette anywhere in this system** — flag this at chart-spec time, not before: if a real need for 3+ unrelated categorical series (or a positive/negative financial-style delta pair) surfaces, that is the point to bring a token proposal to the team, decided against a concrete use case rather than pre-emptively invented here.

### Chart-local ramp (PT-61 — issue flow over time)

**Re-stepped 2026-08-28 (Mosko's ruling, "re-step the chart ramp").** The base `--chart-1`…`--chart-5` ramp above fails the dataviz skill's *ordinal* light-end contrast floor (a discrete ordered-category ramp — see `choosing-a-form.md` — needs its lightest step to clear 2:1 against the chart surface): measured against this app's own `--card` (`oklch(1 0 0)`, pure white in light mode), `--chart-1` is **1.33:1** and `--chart-2` is **1.91:1**, both below the 2:1 hard gate (`--chart-3`…`--chart-5`, and all five steps in dark mode, pass). `--chart-1`…`--chart-5` are **left untouched** — every other consumer already using them is unaffected.

Resolution: **6 new chart-local tokens**, one per `STATUS_ORDER` status (`backlog`/`todo`/`in-progress`/`in-review`/`done`/`cancelled` — the same taxonomy the flow chart's server payload is keyed by), within the same golden hue family, snapped to clear every check the dataviz skill's ordinal validator runs (`validate_ordinal`: monotone lightness, ≥0.06 adjacent ΔL, ≤40° hue spread, ≥2:1 light-end contrast) — validated in **both modes**, against each mode's own real `--card` surface, not assumed identical because one mode happened to pass:

| Token | OKLCH (identical in `:root` / `.dark`) | Status |
|---|---|---|
| `--chart-flow-backlog` | `oklch(0.77 0.17 95)` | backlog (lightest) |
| `--chart-flow-todo` | `oklch(0.702 0.168 88.4)` | todo |
| `--chart-flow-in-progress` | `oklch(0.634 0.16 81.8)` | in-progress |
| `--chart-flow-in-review` | `oklch(0.566 0.145 75.2)` | in-review |
| `--chart-flow-done` | `oklch(0.498 0.125 68.6)` | done |
| `--chart-flow-cancelled` | `oklch(0.43 0.1 62)` | cancelled (darkest) |

**Validator evidence** (`dataviz` skill's `scripts/validate_palette.py`, `validate_ordinal`, run against this exact 6-hex palette): light mode — lightness monotone ✓, adjacent ΔL all ≥0.06 ✓, light-end contrast `#d6b100` (backlog) **2.07:1** vs `#ffffff` ✓, hue spread **32°** ✓, all checks pass. Dark mode — same palette (not re-derived; verified to independently clear the dark check rather than assumed), light-end-equivalent (darkest step, the one nearest the dark surface) `#764100` (cancelled) **2.10:1** vs the `.dark` `--card` surface (`oklch(0.216 0.006 56.043)` ≈ `#1c1917`) ✓, hue spread **32°** ✓, all checks pass. One identical set of 6 values serves both modes (unlike the sequential-ramp guidance's general "dark mode gets its own steps" default — this particular palette happened to already clear both surfaces at once, confirmed by running the validator twice, not assumed).

Guarded mechanically by `scripts/cairn/tests/test_dashboard_chart_ramp.py`, which re-runs this same validator against whatever 6 values actually sit in `app.css` on every test run (not a snapshot of today's numbers) — a future edit to these specific tokens that drops back below the floor goes red the same way the original `--chart-1`/`--chart-2` finding did.

### Sidebar tokens

Dashboards are assumed to ship a persistent nav sidebar as a first-class surface, not an afterthought — the preset gives it its own token group (`--sidebar`, `--sidebar-foreground`, `--sidebar-primary(-foreground)`, `--sidebar-accent(-foreground)`, `--sidebar-border`, `--sidebar-ring`) distinct from `--card`/`--popover`, so a sidebar can be tinted independently (here: barely — `--sidebar` in light mode is `oklch(0.985 …)` vs. page `--background` `oklch(1 …)`, a near-imperceptible 1.5% lightness step, just enough to read as a distinct plane without a visible seam).

**`--sidebar-primary`/`--sidebar-primary-foreground` are dead tokens.** Declared in all three token files (`app.css`, `board/tokens.css`, this doc's Foundations table above) but rendered by nothing — the vendored shadcn `ui/sidebar/` component styles active nav items off `--sidebar-accent` instead (found while correcting PT-69's contrast-gate pair list, 2026-08-29, which had wrongly gated this pair). Not a bug to fix here — the parity test faithfully keeps them in sync across files, they're just decoration nobody consumes. Flagging so a future audit doesn't assume "declared" means "used."

### Shadows

The extracted payload did not include custom `--shadow-*` overrides, meaning this preset does **not** re-tune shadows — it inherits shadcn-svelte's default `shadow-xs`/`shadow-sm`/`shadow-md` Tailwind scale (subtle, low-opacity black, 1–3px offsets). Treat the shadow scale as **shadcn's stock default, not preset-specific** — this is the one token group in this doc not independently re-verified against the live page today; if a future audit needs exact shadow values, pull them from the generated `app.css` shadcn-svelte writes on `init`, not from this doc.

Usage: `shadow-xs` on inputs/buttons (barely-there depth cue), `shadow-sm` on cards/popovers, reserve anything heavier for a modal/sheet that floats over the whole page — mirrors the old system's "one subtle shadow + one heavier overlay shadow" split.

---

## Project extensions — preset tokens only (no invented hues)

**Direction refinement (2026-08-26):** no blending with the legacy system. This design system uses **only** the preset's own tokens and settings — nothing hue-invented, nothing carried forward from the retired Atlassian-modeled palette. The record-status and badge/chip vocabularies the cairn tracker UI needs are expressed entirely as **shadcn badge variants against existing preset tokens**. Meaning is carried by **variant weight** (filled vs. secondary vs. outline, and which existing token fills it) rather than by a dedicated hue per category. The old green/violet/amber extension palette from the previous revision of this doc is **retired, not migrated** — none of those hues exist anywhere in this system now.

### Record-status vocabulary (preset tokens only)

| Status | Badge variant | Fill | Text | Dot/accent |
|---|---|---|---|---|
| Backlog / Planned | `outline` | transparent, `--border` outline | `--muted-foreground` | `--ring` |
| Todo | `secondary` | `--secondary` | `--secondary-foreground` | `--secondary-foreground` |
| In Progress | `default` | `--primary` | `--primary-foreground` | `--primary` |
| Paused / In Review | custom (accent-tier) | `--accent` | `--accent-foreground` | `--accent` |
| Done | custom (inverted) | `--foreground` | `--background` | `--foreground` |
| Cancelled / Blocked | `destructive` | `--destructive` | `--destructive-foreground` | `--destructive` |

**Moved off `--chart-2`, corrected 2026-08-29 (architect's ruling, PT-69).** Paused/In Review originally drew its surface from `--chart-2`, sound reasoning when the chart ramp was fixed — PT-69 makes Chart Color user-selectable, which turns that reasoning over: a status chip's appearance and legibility would become a function of the user's chart-palette choice, which have no product relationship (someone picking a chart hue for a better-reading burndown shouldn't thereby restyle the Paused chip). The measured symptom was worse than a simple miss, too — `--chart-1..5` is declared identically in `:root`/`.dark` (chart ramps are checked against `--card`, so they don't invert with mode), while `--foreground` does invert, so `--foreground`-on-`--chart-2` swung from 10.32:1 in light mode to **1.83:1 in dark** for every Base × Chart combination. Re-deriving the ramp to keep an 11px chip readable was ruled out too — that's the tail wagging the dog, and would need redoing per chart variant.

Replacement: **`--accent`/`--accent-foreground`** — a Base-Color-owned pairing (inverts correctly with mode, tracks Base like everything else in this row's family), not yet used anywhere else in the badge vocabulary, and a clean, trivial contrast pass in both modes (see **Accessibility**) — notably *not* `--muted`/`--muted-foreground`, which this doc's Accessibility section separately records as **failing** AA at 4.39:1 on its own canvas; routing a new badge through a pairing already flagged as broken would have been the wrong direction to reach for. Judgment call worth flagging: `--accent` doubles as this system's hover/active surface elsewhere (interactive menu/option rows, incl. the theme-settings Popover's own rows, corrected from an earlier "DropdownMenu items" description once that component changed — see **Theme & color variants**) — reusing it here for a static badge fill is a role overload I'm accepting rather than inventing a token, since badges live on cards, not inside interactive menus, so the two contexts shouldn't actually collide for a user. This affects three sites: `board.css`'s `.chip.status[data-status="paused"]`, `badge.svelte`'s custom accent-tier variant (**rename the variant from its old `chart` name** — keeping "chart" in the name after moving off the Chart dimension would mislead the next reader), and `App.svelte`'s idle state.

**Verified 2026-08-26 → 2026-08-29 (architect):** contrast checked across all 7 Base variants × both modes (14 blocks, not just the Stone default) — worst case 13.79:1 (Olive dark), best 16.42:1, comfortably clearing the 11px chip size where the old `--chart-2` pairing was the one that failed. The hover-collision this role overload could in theory cause was also checked directly: `--accent` renders as a surface in exactly three places (a table row hover, and the theme dropdown's own option-row hover/selected states), and neither renders a chip today — the list view's status column is plain text, the dropdown has no chips — so the overlap is real in principle but has zero collision site right now.

**Structural guard, not decoration: the Paused/In Review chip keeps its `1px solid var(--border)` outline** rather than following the other filled badge variants' `border-color: transparent` pattern (`.chip.assignee`/`.chip.release` on `--secondary` do go transparent). This is a deliberate one-off exception, cheap insurance against the accepted role-overload above: if a future change ever puts status chips into a hoverable row (plausible — the list currently renders status as plain text, not a chip), the border keeps the chip visible against an accent-colored hover background instead of it silently disappearing into an identical fill. The cost is a border that's barely visible against most fills today; the payoff is not needing anyone to remember this section exists before making that future change.

**Explicitly unaffected — stays on Chart Color, by design:** non-text graphical objects that are *supposed* to track the Chart dimension, e.g. `board.css`'s `.major-status-dot` and the theme-settings dropdown's own Chart Color indicator swatch (`bg-chart-3`) — those are 3:1-floor graphical indicators, not text-bearing status surfaces, and the whole point of the Chart Color indicator dot is to show the current chart hue. Only text-bearing surfaces moved.

"Paused / In Review" and "Done" aren't stock shadcn badge variants (`default`/`secondary`/`destructive`/`outline`) — they're two additional `badgeVariants` entries this system defines, each pointed at an existing preset token (`--accent`, `--foreground`) rather than a new color. That's the one place this vocabulary adds anything beyond wiring up stock variants, and it's still zero new hues.

### Badge/chip vocabulary (preset tokens only)

| Category | Example uses | Variant | Notes |
|---|---|---|---|
| Person (assignee) / release | `.badge-assignee`, `.badge-release` | `secondary` | No per-category hue — a person chip and a release chip look the same weight, distinguished by label/icon, not color |
| Milestone / neutral (default) | `.badge-milestone`, base `.badge` | `outline` | |
| Archived | `.badge-archived` | `outline` + italic + reduced opacity (reuse the existing `opacity-*` disabled/muted treatment shadcn ships, not an invented token) | Muted-but-present, same intent as the old system's archived rule, no new color needed to express it |
| Blocked / cancelled | `.badge-blocked` | `destructive` | |

**The rule going forward: variant weight encodes meaning, not hue.** `default` (primary-filled) = the one thing that should visually dominate on a card (active/live status); `secondary` = present but not urgent; `outline` = lowest-weight, informational; `destructive` = the one danger signal in the system. Don't add a new badge color for a new category — pick the variant whose weight matches how urgently it should draw the eye, and if none of the four stock variants plus the two accent/foreground-tier additions above fit, that's a signal to bring the question to the team rather than inventing a token unilaterally.

---

## Theme & color variants (PT-69)

**What this is:** a user-selectable settings dropdown — **Mode, Base Color, Theme, Chart Color** — that lets a person pick their own point in a small, curated variant space, while preset b6XadDxmQS stays the **default**. This relaxes the 2026-08-26 preset-pure ruling (see **What governs this system** above) into "preset-as-default, shadcn-native variants on top." Full design rationale — the counting logic behind each option set, and a state-by-state behavior spec — lives in the PT-69 issue comment thread (`process/cairn/issues/PT-69.md`); this section is the settled summary other agents should build from, not the working record.

**Architecture (ruled by architect, PT-69, 2026-08-29):** four dimensions. Three are CSS `data-cairn-*` attributes on `<html>` (Base Color → `data-cairn-base`, Theme → `data-cairn-theme`, Chart Color → `data-cairn-chart`); the fourth (Mode) reuses the existing `.dark` class. The three attribute dimensions **partition** the token set — no token belongs to more than one dimension, mechanically enforced by a test. Values are vendored, not fetched at runtime, from shadcn-svelte's own generator (browser-extracted, same method as the 2026-08-26 preset extraction) into `scripts/cairn/design/variants.json`; a generator script emits three CSS copies — `scripts/cairn/board/variants.css`, `scripts/cairn/dashboard/src/variants.css`, and `docs/DESIGN/variants.css` (this system's copy). Persistence is one origin-global `localStorage` key, `cairn.theme`, shared by the dashboard and the board — a theme is a fact about the person looking, not the project being viewed, so it is deliberately not repo-scoped.

### Dimensions, token ownership, and option sets

| Dimension | Attribute | Owns (tokens) | Default | Offered options |
|---|---|---|---|---|
| **Mode** | `.dark` class | selects the light/dark half of every block below | `system` | System, Light, Dark |
| **Base Color** | `data-cairn-base` | neutrals: `--background --foreground --card(-foreground) --popover(-foreground) --secondary(-foreground) --muted(-foreground) --accent(-foreground) --border --input --ring --destructive(-foreground) --sidebar --sidebar-foreground --sidebar-accent(-foreground) --sidebar-border --sidebar-ring` | `stone` | **Stone** (default), Neutral, Zinc, Mauve, Olive, Mist, Taupe |
| **Theme** | `data-cairn-theme` | brand hue: `--primary --primary-foreground --sidebar-primary --sidebar-primary-foreground` | `sky` | **Sky** (default) + **the full reference set** — expanded 2026-08-29 (Mosko), see note below; superseded my earlier curated 7 |
| **Chart Color** | `data-cairn-chart` | `--chart-1..5` + `--chart-flow-*` (the PT-61 ordinal ramp, re-derived per variant — see **Chart-local ramp** above) | `yellow` | **Yellow** (default) + **the full reference set** — expanded 2026-08-29 (Mosko), the ≤5 cap is lifted; superseded my earlier curated 3 |

Note the Theme row still *owns* `--sidebar-primary`/`--sidebar-primary-foreground` even though the contrast gate below excludes them — ownership (which block declares the token) and gating (which pairs get contrast-checked) are separate questions. They're declared per Theme variant so they track the accent hue if anything ever consumes them; they're ungated because nothing does today (see **Sidebar tokens** above). Don't prune them from the Theme block as "dead" — that would leave every non-Sky theme with a sky-blue `sidebar-primary`, unguarded by any test.

Sizing logic: **Base** ships shadcn's complete, closed 7-way neutral set — nothing to trim, nothing to add. (**Corrected 2026-08-29:** the classic 5-name shadcn/ui vocabulary — Stone/Neutral/Zinc/Gray/Slate — does not exist in the OKLCH preset system this app is actually built on; `implementation-lead`'s live-generator verification found the real, complete set is Stone/Neutral/Zinc/Mauve/Olive/Mist/Taupe. "Gray"/"Slate" only exist in a separate legacy HSL system that also redefines Theme/Chart-owned tokens per base color — a partition violation, not usable. Shipping the full 7 rather than trimming to a picked 5 follows the same "closed set, ship all of it" logic used for Base originally; the per-variant contrast gate below covers all 7 at no new cost class, per architect.)

**Superseded 2026-08-29 (Mosko, live-test feedback): Theme and Chart Color both expand to their full reference sets, not a curated subset.** My earlier counts — Theme sized at 7 (Sky default + Blue/Violet/Rose/Orange/Green/Amber, deliberately excluding "Yellow" to avoid colliding with Chart Color's default name) and Chart Color capped at 3 (Yellow default + Blue/Violet), reasoned against architect's original ≤5 chart-variant ceiling — are retired along with that ceiling; Mosko lifted the cap directly. implementation-lead enumerates the real full lists from the live generator (same method as the Base Color correction: a browser/endpoint pass, not domain recall), and both option-set columns above get filled in once that lands. Two pieces of my original reasoning still apply and should carry forward into the real enumeration rather than being silently dropped: **(1)** if the full Theme list also contains "Yellow," the same Theme/Chart name-collision concern I raised holds and is worth a second look (my working fix was Amber-instead-of-Yellow for a curated *subset* — with the *full* set, dropping a real shadcn-named option to dodge a collision is a different, worse trade, so this may just need to be accepted rather than solved); **(2)** the per-variant contrast gate (Base/Theme) and the per-variant dual-ramp validator (Chart Color, ≥2:1 light-end + the PT-61 two-model dark-mode discipline) apply to **every** newly-enumerated option, not just the 10 named above — "full reference set" is not a smaller-diligence path, it's the same gate run more times. Chart Color's validator cost, previously the reason for capping at 3, is now real and larger — that's Mosko's explicit call to make (cap lifted), not a design objection, but implementation-lead should budget for it accordingly.

Chart Color's validation surface (unchanged by the expansion): every variant costs its own validator-passing derivation of *two* ramps (`--chart-1..5` sequential + the 6-step ordinal `--chart-flow-*`), checked against the **extremes of `--card` across every Base Color × Mode combination**, not just the default Stone card: each ramp's light end is validated against the maximum-luminance `--card` in that set, its dark end against the minimum-luminance one, with both extremes computed from `variants.json` rather than hardcoded. Contrast against a surface is monotone in that surface's luminance on each side, so clearing the two extremes clears every base — which is what collapses the obligation from 15 validator runs per ramp to 2 **per variant** (now potentially many more variants than 3).

**Base and Theme variants carry their own contrast gate — pairs derived from actual source usage, not from token-name symmetry.** (**Corrected 2026-08-29:** the first version of this paragraph listed `--sidebar-primary-foreground`/`--sidebar-primary` by assuming `X-foreground` renders on `X` for every declared pair; it doesn't — that specific pair has zero references anywhere in `board.css`/`board.js`/`board.html`/`dashboard/src`, including the vendored shadcn `ui/sidebar/` component, which styles active items off `--sidebar-accent` instead. Both tokens are declared in all three token files and rendered by nothing — see **Sidebar tokens** above.) The gated pairs: every Base variant's `--foreground`/`--background`, `--card-foreground`/`--card`, `--muted-foreground`/`--muted`, and `--muted-foreground`/`--card` (the codebase's most common meta-text combination, missed by the original pairing's token-symmetry approach); every Theme variant's `--primary-foreground`/`--primary`. One test walks every (dimension, variant, mode, pair) tuple from `variants.json`, reusing the OKLCH→hex bridge the chart-ramp tests already carry — and the pair list itself must be **derived from source usage and re-derived each run, never hand-maintained**, which is how the dead `--sidebar-primary` pair got in in the first place.

The floor is role-dependent, not one global number: **normal text 4.5:1** (WCAG 1.4.3), **large text 3:1** (≥24px, or ≥18.66px bold — WCAG 1.4.3), **non-text/graphical objects 3:1** (WCAG 1.4.11, e.g. a status dot fill). `--muted-foreground` is gated at 4.5:1 where it renders as normal-size text (e.g. `.column-header`) but only 3:1 where the same token fills a non-text swatch (e.g. this dropdown's Base Color indicator dot, see **Dropdown UI spec** below).

Not a rubber stamp: PT-61's finding was that a *published* shadcn palette failed a floor nobody had checked. **If a Base or Theme variant fails, drop it from the option set — do not re-derive it.** We are not in the business of repairing shadcn's published neutrals, and a re-derived "Zinc" that isn't shadcn's Zinc is worse than four base colors. Chart Color is the deliberate exception: `--chart-flow-*` is this project's own token, so a failing chart hue gets re-stepped per PT-61 rather than dropped. With the corrected pair list, **all 7 Theme options pass** — the dimension was never actually at risk; the `--sidebar-primary-foreground`/`--sidebar-primary` pair that would have gated it doesn't render anywhere.

### Dropdown UI spec

All four rows share one anatomy: label + current-value text + a right-side indicator — a colored dot for Base/Theme/Chart rows, or a `Monitor`/`Sun`/`Moon` icon (Lucide) for the Mode row, reflecting the user's *selection* rather than the OS-resolved effective appearance (so the row never silently disagrees with what's stored). Mode's option order is System, Light, Dark (System first, matching its default).

Dot fill per row, **corrected 2026-08-29** (architect flagged the original Base Color choice as perceptually indiscriminate): Theme dot = current `--primary`; Chart Color dot = current `--chart-3` (a representative mid-ramp step); Base Color dot = current `--muted-foreground`, **not** `--foreground`. All seven Base Color options are near-black-on-white neutrals at `--foreground`'s lightness (L≈0.147) — the hue differences between Stone/Neutral/Zinc/Mauve/Olive/Mist/Taupe are a fraction of a chroma unit and don't survive down to an 8px dot at that lightness. `--muted-foreground` sits at mid-lightness (L≈0.55), where hue/chroma differences are most perceptually discriminable — same principle as why this doc's own contrast tables flag mid-lightness pairs as the ones worth actually measuring. If `--muted-foreground` still reads too similar across all seven once real values land in `variants.json`, the fallback is a two-tone chip (`--muted` fill, `--border` ring) rather than reaching back for `--foreground`.

**Placement, corrected 2026-08-29 (Mosko's live-test feedback, supersedes the original `Sidebar.Footer` call):** the dashboard trigger sitting in `Sidebar.Footer` was never discovered in actual use — a natural-seeming information-architecture choice that failed the only test that matters, someone actually looking for it. **Both surfaces now place the trigger in the same position: the top-right header area** — dashboard: the header row, alongside the existing Refresh control; board: where its own trigger already sits (no change needed there, it was already top-right). Same icon button both places (Lucide `Settings2`), icon-only with an `aria-label`/tooltip ("Appearance") rather than a visible text label, since header real estate is tighter than a sidebar footer and — per this same feedback loop — consistency of *position* matters more than a label explaining what's already a recognizable settings-gear affordance. This is a discoverability-over-theory correction: my original "sidebar is the natural home for persistent dashboard chrome" reasoning wasn't wrong as a general design-system principle, it was wrong for a control a user needs to *find*, not just tolerate being present. **This placement now covers the whole unified shell, not just the dashboard home** — see **Unified shell** below: the shell header (and its trigger) persists across every route, including the Issue Tracking page.

**Row interaction, corrected 2026-08-29 (Mosko's live-test feedback): Popover, not DropdownMenu.Sub, cascading left.** Two of Mosko's five findings point at the same root cause — the board's per-dimension groups couldn't be closed (no outside-click/Escape dismissal) *and* rendered as flat always-visible blocks instead of flyouts — which is what happens when a settings surface is hand-built without a real floating-panel primitive underneath it, on either surface. Ruling: **the whole thing — the top-level trigger's panel, and each of the four rows' option lists — uses the Popover interaction model** (shadcn-svelte's `Popover.Root`/`Trigger`/`Content` on the dashboard; a hand-rolled equivalent on the board, same as the trigger button already is), not `DropdownMenu.Sub`. Structure: clicking the top-right trigger opens a Popover panel listing the four rows (label + value + indicator, as above); clicking a row opens a **second, nested Popover anchored to that row**, `side="left"` (flying out further left, since the trigger already sits at the right edge and rightward flyouts would run off-screen) — this is Mosko's explicit reference, [shadcn-svelte's Popover docs](https://www.shadcn-svelte.com/docs/components/popover), and it's the better-fitting primitive for the board too: Popover's contract (trigger + anchored content + outside-click/Escape dismissal) is small enough to hand-roll consistently in vanilla JS, where reproducing `DropdownMenu`'s fuller menu semantics (hover-intent, roving keyboard focus, submenu timing) would not be. Selecting an option in a row's nested Popover applies it immediately and closes *that* Popover only — the top-level panel stays open, so a user can set two or three dimensions in one visit without re-opening the trigger. Each Popover — top-level and every row's — must support toggle-close-on-trigger, outside-click close, and Escape, on **both** surfaces; this is what was missing on the board and is now a stated requirement, not an implementation detail assumed to come for free.

Placement is otherwise unchanged from the anatomy above: same label+value+indicator row content, same "no cycle-on-click, full option set visible on open, native checkmark on current selection" rule — only the container changed from menu-submenu to popover-popover.

**Reset is out of scope** for this dropdown — it isn't one of the four named controls, and hand-resetting four settings is cheap enough not to warrant one. Revisit if a future ticket grows this dropdown past roughly four knobs.

**Embed dedup — ruled and confirmed already implemented (PT-69/PT-72).** When the board renders embedded (`embed=1`), its own trigger is removed from the DOM entirely (`wireThemeSettings()`'s embed branch, `(wrapper||trigger).remove()`) — not `display:none`, which would leave a hidden-but-present control in the keyboard tab order. Both surfaces already read/write the same origin-global `cairn.theme` key, so the embedded trigger would be fully redundant — same state, same control, same visual position, on screen twice. **This must stay conditional on `embed=1`, not become unconditional** — the standalone board at `/` and `/list` (see **Unified shell**) is not embedded, must keep its own trigger, and has no other surface to defer to.

**Mode's `system` state needs live-follow, not just a one-time read:** when `mode="system"`, the effective `.dark` class must track `prefers-color-scheme` while the page stays open (a `change` listener on the media query), in addition to architect's cross-tab `storage` event listener — two different triggers for the same "the visible mode can change without a click" requirement. The inline FOUC-avoidance bootstrap script must evaluate `matchMedia('(prefers-color-scheme: dark)').matches` synchronously on first paint for `system`, not fall through to the light default.

---

## Unified shell (PT-72)

**What this is:** the dashboard's Sidebar + Header (see **Sidebar tokens**, and the theme-settings trigger placement above) now persist across every route in the app, including a full-page view of the board — not just the dashboard home. Paired with architect's routing/embed-variant ruling (PT-72 issue); this section is the UX contract, not the mechanism.

**Persistent chrome.** Sidebar + Header mount once and never remount across navigation between Dashboard (`/dashboard`) and Issue Tracking (`/dashboard/issues`) — soft client-side nav swaps only the content area. The board iframe mounts on arrival at Issue Tracking and unmounts on leaving; the chrome around it does not flash or repaint on either transition.

**Nav rename: "Issue Tracking"** (`/dashboard/issues`), replacing "Board" — confirmed as Mosko proposed. Label length is bound only by the expanded sidebar's single-line width (14 characters, comfortably next to "Dashboard"'s 9); the collapsed rail is icon-only with a hover tooltip, so rail width was never actually the constraint. Icons (PT-71): Dashboard = Lucide `LayoutDashboard`, Issue Tracking = Lucide `Kanban`.

**Issue Tracking page — full board, `/?embed=1` at full height (not the dashboard-home card's capped height).** All board functionality is unchanged: drag/drop, create/filter bar, Kanban/List tabs, card click opens the real editable drawer, connection-state indicator. It has **no theme-settings trigger of its own** — the shell header's trigger is the only one on this route, via the existing embed-conditional suppression (see **Embed dedup**, above). It also has no wordmark/repo-name masthead to suppress — `board.html`'s "cairn" wordmark is already hidden under `embed=1`, and the board never carried a repo-name display of its own (PT-68 touched only the dashboard sidebar).

**Dashboard-home preview — read-only, `/?embed=1&readonly=1`.** A glance surface, not a second workspace; strip list is complete, not illustrative:

| | Hidden | Kept |
|---|---|---|
| Controls | Filter row; Kanban/List view tabs (fixed to Kanban); create-issue button; per-column add buttons; `#expand-all-btn`/`#collapse-all-btn`; per-lane `.swimlane-toggle`/`.repo-group-toggle` | — |
| Interaction | Drag affordances (no `dragstart`/`drop` handlers, `draggable=false`) | Cards remain click-through only |
| Chrome | Wordmark/masthead + the board's own Dashboard tab (already covered by `embed=1`) | Column headers with titles + counts; the connection-state indicator (informational, not a control) |

**Lane collapse state is deliberately ignored, not read.** The read-only preview always renders fully expanded, regardless of `cairn.board.expandedLanes` (persisted, origin-shared with the workspace page). Reading that shared state would let a user collapse lanes on the Issue Tracking page and return to a near-empty preview with no visible cause and no on-screen affordance to fix it, since the toggles that would fix it are hidden here — a glance surface should look identical on every visit. No new storage key: this is one more suppression, same class as the rest of the strip list above. The panel is fixed-height with internal scroll regardless of lane count — ordinary containment for one section among several on a busy dashboard home.

**Card click navigates the shell, deep-linked — not an inline edit, not a read-only modal.** Clicking a card moves the top-level window (`window.top.location`, same-origin) to `/dashboard/issues?issue=<id>`; the shell derives `/?embed=1&open=<id>` for the iframe `src`, and that issue's drawer opens automatically on arrival. Avoids a second detail-view implementation — the exact thing PT-55 rejected read-only over. A plain **"View full board" link/button** at the top of the section is the non-card escape hatch — discovery should not depend on a user guessing that cards are click-through, the standing lesson from the `Sidebar.Footer` placement miss above.

**Standalone board is unaffected.** `/` and `/list` keep working exactly as today — no params, full chrome, their own theme-settings trigger. This is the zero-build fallback (a fresh clone with no `dist/` has no dashboard to defer to) and must not depend on the shell existing.

---

## Components

Map to shadcn-svelte's shipped components — install via `bunx shadcn-svelte@latest add <name>`, don't hand-roll. Anatomy follows shadcn's documented structure; the right column is what the cairn board specifically needs from each.

| shadcn-svelte component | Anatomy (shadcn norm) | Cairn board usage |
|---|---|---|
| **Button** | `<Button variant={default\|secondary\|destructive\|outline\|ghost\|link} size={default\|sm\|lg\|icon}>` | `default` = primary actions (new issue submit); `outline` = cancel/secondary; `ghost` = icon-only (drawer close); `destructive` = delete/archive confirm |
| **Badge** | `<Badge variant={default\|secondary\|destructive\|outline}>`, plus two accent/foreground-tier `badgeVariants` additions (see **Project extensions**) | Status chips, assignee/milestone/release/blocked/archived chips — all mapped to stock variants + preset tokens, no per-category hues |
| **Card** | `Card.Root > Card.Header > Card.Title/Card.Description, Card.Content, Card.Footer` | Issue card, containment-card nesting (repo-group → swimlane → column) — same depth-alternation principle as before, now expressed via `bg-card` vs. `bg-muted` instead of hand-picked hex |
| **Table** | `Table.Root > Table.Header/Body > Table.Row > Table.Head/Cell` | List view — shadcn's table ships sortable-header patterns and row hover as CSS, closing the old "no sort indicator" gap only if the sort-icon slot is actually used, not just the markup |
| **Sheet / Dialog** | `Sheet.Root > Sheet.Trigger, Sheet.Content > Sheet.Header, Sheet.Footer` (Dialog is the centered variant; Sheet is the edge-anchored drawer) | Sheet = the right-side issue drawer (direct replacement for the old bespoke `.drawer`); Dialog = new-issue modal, confirm-delete |
| **Sidebar** | `Sidebar.Provider > Sidebar.Root > Sidebar.Header, Sidebar.Content (Sidebar.Group×n), Sidebar.Footer`, collapsible via `Sidebar.Trigger` | Primary nav — majors/milestones tree, view switcher; replaces the old flat `.majors-tabs` row with a real collapsible nav surface. **Landed (PT-61):** the dashboard's Dashboard/Board nav entries — the fuller majors/milestones tree is still forward-looking, not yet built |
| **Chart** | `Chart.Container config={ChartConfig}` wrapping a `layerchart` primitive (`AreaChart`/`Area` etc.), `Chart.Tooltip` for hover | **Landed (PT-61):** the dashboard's issue-flow-over-time stacked area chart — see **Chart-local ramp** above for the color tokens it uses. Pulls in `layerchart` + `d3-scale`/`d3-shape` as real new dependencies (dynamically imported so they land in their own bundle chunk, not the main one) |
| **Sonner (toast)** | `<Toaster />` mounted once at app root, imperative `toast.success()/toast.error()` calls | Direct replacement for the old bespoke `.toast`/`.toast.error` — ships enter/exit animation and stacking for free |
| **Skeleton** | `<Skeleton class="h-4 w-full" />` composed to match real layout | New capability — the old system had **no loading state at all** (documented gap). Every list/board fetch should render a skeleton shaped like the real card/row/table it's replacing, per the "no decorative loading states" working principle |
| **Popover** | `Popover.Root > Popover.Trigger, Popover.Content` (nested: a row's `Popover.Trigger` lives inside the top-level `Popover.Content`, its own `Popover.Content` set to `side="left"`) | **Landed (PT-69), corrected from an earlier `DropdownMenu.Sub` design:** the theme/color settings panel — top-level trigger opens a Popover listing Mode/Base Color/Theme/Chart Color rows, each row opens its own nested Popover flying left with that dimension's option list — see **Theme & color variants** above for the full spec. Chosen over `DropdownMenu.Sub` specifically because its trigger+anchored-content+dismiss contract is reproducible in vanilla JS for the board, where `DropdownMenu`'s fuller menu semantics wouldn't be |

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
| Chip pairs (`.chip.assignee`, `.chip.milestone`, `.chip.repo`, `.chip.subissues`, `.chip.ga`, etc. — the old green/purple/amber taxonomy) | Badge variants, see **Project extensions** | **Retired, not migrated.** The old per-category-hue rule (person=blue, taxonomy=green, warning=amber, danger=red, neutral=grey) does not carry forward — the new system has no invented hues at all. Chips map to stock `secondary`/`outline`/`destructive` badge variants (plus two accent/foreground-tier additions) and distinguish category by label/icon and variant weight, not by a dedicated color per category |
| `border-radius: 6px` (`--radius` old) | `--radius-md` (8px) or `--radius-lg` (10px) depending on component | Not a 1:1 value match — pick per new scale, don't hardcode 6px forward |
| `elevation.shadow.raised` / `.overlay` | `shadow-sm` / `shadow-md`+ (shadcn default scale) | |
| System-UI type stack | `--font-sans` (Merriweather, body/UI) / `--font-heading` (Space Grotesk, headings) / `--font-mono` (Geist Mono) | Full stack replacement, now a three-face system (was one), see typography section and pushback note below |

---

## Accessibility

**Target: WCAG AA**, unchanged from the previous system. Contrast below is computed from OKLCH lightness deltas as an engineering estimate, not a colorimetrically verified measurement (recommend running the final `tokens.css` through a proper OKLCH-aware contrast checker before ship — flagging the method, not asserting precision).

**Two-model rule (PT-69, 2026-08-29, architect's ruling).** A bare contrast figure in this doc is now ambiguous on its own — two defensible, independently-correct OKLCH→contrast bridges exist in this project (continuous-sRGB float math, and the 8-bit-hex-quantized math `gen_variants.py`'s derivation shares with its own guarding test), and they can disagree by enough to matter right at the 4.5:1 floor: `derive_muted_foreground()`/`derive_destructive_foreground()` each stop at the first value that clears *by their own model*, which by construction parks every derived ink a hair above the floor — sometimes below it under the other model. Found because ux-designer's re-implementation was independent of the generator's, so it didn't share the generator's blind spot; a guard can't see its own bias. **Rule going forward: any derived ink must clear the floor under both models, with ε = 0.05 of margin** — figures below are labeled with which model produced them where the distinction matters.

| Pair | Light-mode estimate | AA (4.5:1 normal text)? |
|---|---|---|
| `--foreground` on `--background` | L 0.147 vs L 1.0 — very large delta | Pass, trivially (comparable to the old system's 12.6:1 near-black-on-white) |
| `--muted-foreground` on `--background` | L 0.553 vs L 1.0 | **Passes, but narrowly** — comparable band to the old system's `#5E6C84`/white pair (5.6:1); don't assume headroom to go lighter |
| `--primary-foreground` on `--primary` | L 0.977 vs L 0.5, but `--primary` carries chroma 0.134 (fairly saturated blue) | Likely passes (comparable to the old white-on-`#0052CC` at 5.1:1) but chroma at this level measurably eats into perceived contrast versus a chroma-0 gray of the same lightness — worth an actual check, not an assumption |
| `--destructive-foreground` on `--destructive` | L 0.97 vs L 0.577, chroma 0.245 — the **highest-chroma color in the whole palette** | **Failed for real, not just borderline — measured (not estimated) at 4.35:1 float / 4.37:1 quantized light, 2.65:1 dark, all below floor.** This flag's own prediction ("high chroma reds are where lightness-only math is least reliable") held; it's also, in hindsight, the doc's first accidental demonstration of the **two-model rule** below (two people independently measured this exact pair and got 4.35 vs 4.37 — both correct, just different models). **Both modes now resolved and re-verified under both models** — see the PT-69 write-up below: dark mode re-derived to `L 0.31` (4.5694:1 float / 4.5970:1 quantized, both clearing ε = 0.05 margin — the first derivation at `L 0.3145` passed one model and missed the other by a hair); light mode moved to pure white (4.7647:1 float / 4.7699:1 quantized, comfortably clearing both, ux-designer's call) |
| `--sidebar-foreground` on `--sidebar` | L 0.147 vs L 0.985 | Pass, trivially |
| `--accent-foreground` on `--accent` (Paused/In Review badge, **corrected 2026-08-29 — moved off `--chart-2` per PT-69**, see **Project extensions**) | Light: L 0.216 vs L 0.97; Dark: L 0.985 vs L 0.268 — large delta both modes, low chroma (~0.006–0.007) | Pass, trivially, in both modes — a clean improvement over the pairing it replaced (which ranged 10.32:1 light down to a failing 1.83:1 dark because `--chart-2` doesn't invert with mode and `--foreground` does); still worth a real colorimetric check before lock, same standing caveat as every estimate in this table |
| `--background` on `--foreground` (Done badge, new — see **Project extensions**) | L 1.0 vs L 0.147 — same magnitude delta as the `--foreground`/`--background` pair above, inverted | Pass, trivially |

**New flag this palette introduces that the old one didn't have:** the old type stack was a system-UI sans at all sizes; this one is a **serif-body/sans-heading pairing**, and the serif (Merriweather, `--font-sans`) is the one carrying the base UI slot, including down at `text-xs` (12px badge/chip text — the system's smallest, highest-density text). Section/page headings (`text-xl`/`text-2xl`) render in Space Grotesk, a sans, so that end of the scale is unaffected — but per the measured preview output, form **labels** also render in Merriweather (they're grouped with body/buttons/inputs/table cells, not with headings), so labels don't get the sans benefit either. Serifs carry finer stroke contrast and are demonstrably harder to read at small sizes than a humanist sans, independent of color contrast. Recommend not shipping `text-xs` badge/chip labels (or small-size form labels) in the serif family even if the rest of the UI stays on-brand — either bump that text to `text-sm`+ or scope `--font-sans` out of the smallest components. This is a real, new accessibility-adjacent risk, not inherited from the old spec.

**Resolved (PT-64, Mosko's final ruling 2026-08-28) — full face floor:** option (a) chosen, scope widened from an initial "form labels only" cut to **every sub-13px selector in `board.css`**, per the AC's literal wording ("the sub-13px selector set ... enumerated mechanically, every selector under 13px"). Sequence: the ruling started narrow (`.filters label`, `.drawer-field label` only, chips assumed already-sans from a spot check); a follow-up computed-style read (team-lead, live browser) found `.chip` had **no font-family override at all** — its face was placement-dependent, sans inside `.swimlane-header`, serif inside `.card-meta` (the bulk of board chips) — which corrected the original "chips already sans" assumption and reopened scope. Mosko then ruled the full floor rather than patching `.chip` alone.

Final state: every sub-13px selector in `board.css` now resolves to `var(--font-heading)` (Space Grotesk) or, for `.chip.repo`, the pre-existing `var(--font-mono)` (monospace is exempted — it isn't the serif-legibility risk this rule targets). That covers the two form-label selectors, the full `.chip` family (base rule fixed once; `.assignee`/`.release`/`.blocked`/`.ga`/`.archived`/`.status[...]` variants inherit it), `.connection-state` (+ `.live`), `.comment-meta`, `table.issue-list th`, `.pr-link`/`.file-link`/`.parent-link`, `.drawer-progress`, `.record-readonly-note`, and two UA-default-font buttons (`.major-tab-open`, `.view-state-btn`) that needed an explicit face for the first time since browsers don't inherit page font-family into form controls by default. `.swimlane-toggle`/`.repo-group-toggle` had `font-family: inherit` (already computing sans by placement) swapped for an explicit `var(--font-heading)` — deliberately, so the guard doesn't depend on where in the DOM those toggles happen to sit, the same placement-dependence gap the `.chip` finding exposed. Guarded mechanically by `scripts/cairn/tests/test_board_small_label_face.py`, which re-derives the sub-13px selector set from source on every run rather than pinning today's list, so a future selector added under 13px without a face override goes red automatically.

**Resolved (Mosko's ruling, 2026-08-29, "darken the ink"; final numbers under architect's "two-model rule," implementation-lead's re-run):** measured (not estimated) contrast put `--muted-foreground` on the `--muted` canvas at **4.39:1 — fails the 4.5:1 AA floor for normal text**, on the shipped Stone default (live since 2026-08-26) and every alternate Base Color option, Mauve included (its apparent single-model pass at 4.54:1 didn't survive the two-model re-check either). The *identical text token* on `--card` passed at 4.79:1 — the defect was the canvas surface, not the ink itself.

Chosen resolution: **derive `--muted-foreground` per Base Color variant** — darken it by the minimum amount that clears 4.5:1 under BOTH the quantized-hex and float contrast models against that variant's own `--muted`, in both modes, chroma/hue held fixed. Precedent: this feature's own chart-flow ramp already deviates from the preset with recorded rationale (PT-61); one derived ink token per base is the same class of departure. Implementation: `scripts/cairn/design/gen_variants.py`'s `derive_muted_foreground()` — stdlib OKLCH math, re-run on every generation so a future re-vendor of the raw base colors (or a future change to the two-model epsilon) recomputes automatically; `variants.json` still carries the vendored (undarkened) value for provenance.

Before/after (light mode only — every base's dark-mode `--muted-foreground`/`--muted` pair already clears 4.5:1 under both models, so the derivation is a no-op there). Contrast columns are quantized-hex / float, both required to clear 4.55:1 (floor + the 0.05 two-model epsilon):

| Base | Before | After | Contrast (quantized / float) |
|---|---|---|---|
| Stone (default) | `oklch(0.553 0.013 58.071)` | `oklch(0.5450 0.013 58.071)` | 4.39:1 → 4.58:1 / 4.56:1 |
| Neutral | `oklch(0.556 0 0)` | `oklch(0.5430 0 0)` | 4.35:1 → 4.61:1 / 4.58:1 |
| Zinc | `oklch(0.552 0.016 285.938)` | `oklch(0.5430 0.016 285.938)` | 4.39:1 → 4.58:1 / 4.56:1 |
| Mauve | `oklch(0.542 0.034 322.5)` | `oklch(0.5405 0.034 322.5)` | 4.54:1 (single-model) → 4.58:1 / 4.56:1 |
| Olive | `oklch(0.580 0.031 107.3)` | `oklch(0.5405 0.031 107.3)` | 3.86:1 → 4.58:1 / 4.55:1 |
| Mist | `oklch(0.560 0.021 213.5)` | `oklch(0.5375 0.021 213.5)` | 4.14:1 → 4.57:1 / 4.56:1 |
| Taupe | `oklch(0.547 0.021 43.1)` | `oklch(0.5380 0.021 43.1)` | 4.40:1 → 4.59:1 / 4.58:1 |

With this change, the Base contrast gate holds at zero exemptions — the drop-don't-rederive fence now governs only genuine per-variant defects, not this token.

**`--destructive-foreground`/`--destructive` — dark mode resolved, light mode open (architect's ruling, 2026-08-29, f26dbad).** Measured contrast: **4.37:1 quantized light (4.35:1 float — see the two-model rule above) / 2.65:1 dark**, both below the 4.5:1 floor — reachable for the first time via PT-69's board dark-mode wiring, not a pre-existing visible defect the way `--muted-foreground` was. Investigation found this pair can't take the same "darken the ink" treatment as `--muted-foreground`: light mode's `--destructive` is a *dark* red (L 0.577, wants lighter ink) while dark mode's is unusually a *lighter* red than its own light-mode counterpart (L 0.704, wants darker ink) — opposite directions, so a single shared ink value can never clear both (max achievable with white ink in dark mode is 2.89:1). `--destructive-foreground` never needed to be identical across modes — nothing in the system requires it, and `--destructive` itself already differs per mode.

**Dark mode: resolved — root-caused and re-derived under the two-model rule (architect, 2026-08-29).** The float/quantized disagreement ux-designer flagged was real, not rounding noise: `oklch(0.3145 0.01 17.0)` measures **4.4955:1 float / 4.5268:1 quantized** — the 4.5 floor sits *inside* that ~0.03 gap, so which bridge you trust decides pass/fail. Root cause: `derive_destructive_foreground()` (like `derive_muted_foreground()`) stops at the first value that clears the floor *by its own model*, which by construction parks every derived ink a hair above zero margin on that one model — sometimes below the floor on the other. Re-derived to `L 0.3145 → 0.3100` (chroma/hue unchanged), which clears **both** models with real margin: **4.5694:1 float / 4.5970:1 quantized**. Also fixes `.engine-stale-banner` (board.css), which pairs the same two tokens. Implementation: `gen_variants.py`'s `derive_destructive_foreground()` — direction-aware (unlike `derive_muted_foreground`, which only ever darkens), takes an explicit `"lighten"`/`"darken"` argument rather than inferring it, specifically so a future clone of this pattern can't silently search the wrong direction and fail as "no value found" instead of "wrong direction." Now additionally required to clear ε = 0.05 margin under both models, not just its own.

**Light mode: resolved (ux-designer's design call, 2026-08-29).** Accepted the direction-correct fix: ink moves to pure white, `oklch(0.97 0.01 17)` → `oklch(1 0 0)`, **4.35:1 float / 4.37:1 quantized → 4.7647:1 float / 4.7699:1 quantized**, dropping the preset's slight warm-pink tint entirely. Rejected the alternative (darkening the light-mode `--destructive` fill to preserve the tinted ink) — that changes the brand danger hue itself, a bigger and more visible departure than losing a chroma-0.01 tint on the text sitting on top of it, and it also runs against this doc's broader "preset tokens only" discipline better than moving the ink does. A whisper of tint was viable — `oklch(0.99 0.01 17)` clears **both** models (4.5833:1 float / 4.5814:1 quantized, 0.083 of margin past ε — checked by architect after the fact, and comfortably past, not a near-miss as an earlier version of this paragraph incorrectly claimed). Pure white was chosen anyway, on its own merits: more headroom, one less special value to carry and explain, no tint story needed. `:root`'s value is now the single source; nothing left open on this pair.

**Correction, 2026-08-29 (architect caught it):** the sentence above previously claimed the `oklch(0.99 0.01 17)` alternative was "a near-miss of the same [two-model] bug" — that was a single-model number (mine) asserted as fact inside the very paragraph warning against doing that, and it was wrong: checked properly, that value clears both models with real margin. Left visible rather than quietly rewritten, since it's the cleanest example in this doc of why the two-model rule exists — a plausible-sounding claim about margin, unverified against the second model, sitting right next to the rule that says not to do that.

**Open items carried forward, still true:**
- Reduced-motion policy is still ours to set (see Components) — shadcn doesn't solve this by default.
- The two accent/foreground-tier badge additions (Paused/In Review on `--accent`, Done on inverted `--foreground`) are new pairings of existing preset tokens, not measured yet — verify contrast on those two before locking `tokens.css`. (The "invented hues need sign-off" item from the previous revision of this doc is resolved — there are no invented hues anymore.)

---

## Pushback (UX owner notes on the preset, not fixes)

Flagging for the team's awareness — not blocking adoption of the preset, but worth a conscious yes/no:

1. **Merriweather-as-body-face is still an unusual, opinionated choice for a data-dense dashboard, even with Space Grotesk covering headings.** The pairing is more defensible than "serif everywhere" — headings get a clean sans — but Merriweather is still what actually renders on tables, forms, buttons, and badges, which is the majority of a tracker/dashboard's actual surface area, not the minority of it covered by headings. Worth a quick internal design review before this ships broadly, not just accepting the preset default because it's the preset default.
2. **Three Google Fonts now load (Merriweather Variable + Space Grotesk Variable + Geist Mono Variable), not two** — reverses the old system's zero-network-font-request stance more than initially scoped. That was a deliberate old-system choice for perf/offline-resilience reasons — if those constraints still matter for this project, self-host all three variable fonts rather than trusting Google Fonts' CDN at runtime, and preload them to avoid FOUC on a data-heavy first paint.
3. **This system now has no multi-hue categorical palette anywhere, by explicit decision (2026-08-26: preset tokens only, no invented hues).** The previous revision of this doc proposed inventing a green and a violet to cover this; that proposal is retired. The status/badge vocabulary is now fully expressible with existing tokens (see **Project extensions**), so the gap doesn't block anything today — but it means **positive/negative financial-style deltas and any true multi-series categorical chart (3+ unrelated series that need to be told apart by hue) currently have no palette to draw from.** This is the one place a future token addition may be genuinely needed — decide it against a concrete chart/metric spec when one actually comes up, not speculatively now.
4. **The chart ramp is sequential-only by construction** (see also #3 — this is the same underlying gap, chart-specific). Fine if this project's charts stay single-metric; if roadmap plans include any categorical chart (status breakdown, assignee distribution) or a positive/negative delta indicator, that need should be scoped and resolved as a deliberate token decision when it comes up, not bolted on ad hoc.
