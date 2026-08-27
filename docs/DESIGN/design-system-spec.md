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

### Sidebar tokens

Dashboards are assumed to ship a persistent nav sidebar as a first-class surface, not an afterthought — the preset gives it its own token group (`--sidebar`, `--sidebar-foreground`, `--sidebar-primary(-foreground)`, `--sidebar-accent(-foreground)`, `--sidebar-border`, `--sidebar-ring`) distinct from `--card`/`--popover`, so a sidebar can be tinted independently (here: barely — `--sidebar` in light mode is `oklch(0.985 …)` vs. page `--background` `oklch(1 …)`, a near-imperceptible 1.5% lightness step, just enough to read as a distinct plane without a visible seam).

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
| Paused / In Review | custom (chart-tier) | `--chart-2` | `--foreground` | `--chart-2` |
| Done | custom (inverted) | `--foreground` | `--background` | `--foreground` |
| Cancelled / Blocked | `destructive` | `--destructive` | `--destructive-foreground` | `--destructive` |

"Paused / In Review" and "Done" aren't stock shadcn badge variants (`default`/`secondary`/`destructive`/`outline`) — they're two additional `badgeVariants` entries this system defines, each pointed at an existing preset token (`--chart-2`, `--foreground`) rather than a new color. That's the one place this vocabulary adds anything beyond wiring up stock variants, and it's still zero new hues.

### Badge/chip vocabulary (preset tokens only)

| Category | Example uses | Variant | Notes |
|---|---|---|---|
| Person (assignee) / release | `.badge-assignee`, `.badge-release` | `secondary` | No per-category hue — a person chip and a release chip look the same weight, distinguished by label/icon, not color |
| Milestone / neutral (default) | `.badge-milestone`, base `.badge` | `outline` | |
| Archived | `.badge-archived` | `outline` + italic + reduced opacity (reuse the existing `opacity-*` disabled/muted treatment shadcn ships, not an invented token) | Muted-but-present, same intent as the old system's archived rule, no new color needed to express it |
| Blocked / cancelled | `.badge-blocked` | `destructive` | |

**The rule going forward: variant weight encodes meaning, not hue.** `default` (primary-filled) = the one thing that should visually dominate on a card (active/live status); `secondary` = present but not urgent; `outline` = lowest-weight, informational; `destructive` = the one danger signal in the system. Don't add a new badge color for a new category — pick the variant whose weight matches how urgently it should draw the eye, and if none of the four stock variants plus the two chart/foreground-tier additions above fit, that's a signal to bring the question to the team rather than inventing a token unilaterally.

---

## Components

Map to shadcn-svelte's shipped components — install via `bunx shadcn-svelte@latest add <name>`, don't hand-roll. Anatomy follows shadcn's documented structure; the right column is what the cairn board specifically needs from each.

| shadcn-svelte component | Anatomy (shadcn norm) | Cairn board usage |
|---|---|---|
| **Button** | `<Button variant={default\|secondary\|destructive\|outline\|ghost\|link} size={default\|sm\|lg\|icon}>` | `default` = primary actions (new issue submit); `outline` = cancel/secondary; `ghost` = icon-only (drawer close); `destructive` = delete/archive confirm |
| **Badge** | `<Badge variant={default\|secondary\|destructive\|outline}>`, plus two chart/foreground-tier `badgeVariants` additions (see **Project extensions**) | Status chips, assignee/milestone/release/blocked/archived chips — all mapped to stock variants + preset tokens, no per-category hues |
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
| Chip pairs (`.chip.assignee`, `.chip.milestone`, `.chip.repo`, `.chip.subissues`, `.chip.ga`, etc. — the old green/purple/amber taxonomy) | Badge variants, see **Project extensions** | **Retired, not migrated.** The old per-category-hue rule (person=blue, taxonomy=green, warning=amber, danger=red, neutral=grey) does not carry forward — the new system has no invented hues at all. Chips map to stock `secondary`/`outline`/`destructive` badge variants (plus two chart/foreground-tier additions) and distinguish category by label/icon and variant weight, not by a dedicated color per category |
| `border-radius: 6px` (`--radius` old) | `--radius-md` (8px) or `--radius-lg` (10px) depending on component | Not a 1:1 value match — pick per new scale, don't hardcode 6px forward |
| `elevation.shadow.raised` / `.overlay` | `shadow-sm` / `shadow-md`+ (shadcn default scale) | |
| System-UI type stack | `--font-sans` (Merriweather, body/UI) / `--font-heading` (Space Grotesk, headings) / `--font-mono` (Geist Mono) | Full stack replacement, now a three-face system (was one), see typography section and pushback note below |

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
| `--foreground` on `--chart-2` (Paused/In Review badge, new — see **Project extensions**) | L 0.147 vs L 0.795, but `--chart-2` carries chroma 0.184 (second-highest chroma in the palette after destructive) | Likely passes on lightness delta alone (comparable margin to the muted-foreground pair above), but chroma at this level is exactly the case flagged for destructive — measure for real before treating this badge as ship-ready, don't assume the lightness gap alone is enough |
| `--background` on `--foreground` (Done badge, new — see **Project extensions**) | L 1.0 vs L 0.147 — same magnitude delta as the `--foreground`/`--background` pair above, inverted | Pass, trivially |

**New flag this palette introduces that the old one didn't have:** the old type stack was a system-UI sans at all sizes; this one is a **serif-body/sans-heading pairing**, and the serif (Merriweather, `--font-sans`) is the one carrying the base UI slot, including down at `text-xs` (12px badge/chip text — the system's smallest, highest-density text). Section/page headings (`text-xl`/`text-2xl`) render in Space Grotesk, a sans, so that end of the scale is unaffected — but per the measured preview output, form **labels** also render in Merriweather (they're grouped with body/buttons/inputs/table cells, not with headings), so labels don't get the sans benefit either. Serifs carry finer stroke contrast and are demonstrably harder to read at small sizes than a humanist sans, independent of color contrast. Recommend not shipping `text-xs` badge/chip labels (or small-size form labels) in the serif family even if the rest of the UI stays on-brand — either bump that text to `text-sm`+ or scope `--font-sans` out of the smallest components. This is a real, new accessibility-adjacent risk, not inherited from the old spec.

**Open items carried forward, still true:**
- Reduced-motion policy is still ours to set (see Components) — shadcn doesn't solve this by default.
- The two chart/foreground-tier badge additions (Paused/In Review on `--chart-2`, Done on inverted `--foreground`) are new pairings of existing preset tokens, not measured yet — verify contrast on those two before locking `tokens.css`, same caveat as the destructive pair. (The "invented hues need sign-off" item from the previous revision of this doc is resolved — there are no invented hues anymore.)

---

## Pushback (UX owner notes on the preset, not fixes)

Flagging for the team's awareness — not blocking adoption of the preset, but worth a conscious yes/no:

1. **Merriweather-as-body-face is still an unusual, opinionated choice for a data-dense dashboard, even with Space Grotesk covering headings.** The pairing is more defensible than "serif everywhere" — headings get a clean sans — but Merriweather is still what actually renders on tables, forms, buttons, and badges, which is the majority of a tracker/dashboard's actual surface area, not the minority of it covered by headings. Worth a quick internal design review before this ships broadly, not just accepting the preset default because it's the preset default.
2. **Three Google Fonts now load (Merriweather Variable + Space Grotesk Variable + Geist Mono Variable), not two** — reverses the old system's zero-network-font-request stance more than initially scoped. That was a deliberate old-system choice for perf/offline-resilience reasons — if those constraints still matter for this project, self-host all three variable fonts rather than trusting Google Fonts' CDN at runtime, and preload them to avoid FOUC on a data-heavy first paint.
3. **This system now has no multi-hue categorical palette anywhere, by explicit decision (2026-08-26: preset tokens only, no invented hues).** The previous revision of this doc proposed inventing a green and a violet to cover this; that proposal is retired. The status/badge vocabulary is now fully expressible with existing tokens (see **Project extensions**), so the gap doesn't block anything today — but it means **positive/negative financial-style deltas and any true multi-series categorical chart (3+ unrelated series that need to be told apart by hue) currently have no palette to draw from.** This is the one place a future token addition may be genuinely needed — decide it against a concrete chart/metric spec when one actually comes up, not speculatively now.
4. **The chart ramp is sequential-only by construction** (see also #3 — this is the same underlying gap, chart-specific). Fine if this project's charts stay single-metric; if roadmap plans include any categorical chart (status breakdown, assignee distribution) or a positive/negative delta indicator, that need should be scoped and resolved as a deliberate token decision when it comes up, not bolted on ad hoc.
