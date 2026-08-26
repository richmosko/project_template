# Design System Spec

> The written companion to `tokens.css` + `screen.css`. The CSS files are the machine-readable source of truth; this doc explains the *why* and the usage rules. Owned by the `ux-designer` agent. Generate/refine with `/generate-designdoc`.

## What governs this system

This project's one shipped UI today is the cairn issue board (`scripts/cairn/board/board.css`, `board.html`, `board.js`) — a vanilla-CSS Kanban/list app with no framework and no CDN dependency. Its palette already tracks Atlassian's public color palette (B400 blue, N-series greys/text, semantic reds/greens/oranges/purples) even though it predates this spec being written down.

This document formalizes that palette into a **semantic, dot-namespaced token architecture** modeled on the structure documented at [atlassian.design](https://atlassian.design) — `color.background.*`, `color.text.*`, `color.border.*`, `space.*`, `border.radius.*`, `elevation.shadow.*` — **not** a copy of Atlassian's token values, font, or brand assets. The naming grammar (Foundation → Property → Modifier, e.g. `color.text`, `color.icon.success`) was verified against the live page ["Design tokens explained"](https://atlassian.design/foundations/tokens/design-tokens) on 2026-08-26.

Two boundaries, deliberately:

1. **`board.css` is the ground truth for every value in this doc.** Every hex, size, and radius below was read directly out of `scripts/cairn/board/board.css` — none are recalled from Atlassian's canonical palette. Where a board.css value happens to be Atlassian's canonical value, this doc says so (e.g. `#0052CC` = Atlassian B400) as a cross-reference, not as the source.
2. **No Atlassian branded assets.** No Charlie Sans (or Atlassian's current type family), no Atlassian logos, no Atlassian product names borrowed as our own. Our type stack is the system-ui stack the board actually ships (`-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`) plus the monospace stack for IDs/code.

`tokens.css` and `screen.css` (per the artifacts table in `CLAUDE.md`) are the **downstream, machine-readable deliverables** that `frontend-lead` consumes for new project UI — they should be *generated from this spec*, not the reverse. As of this writing they do not yet exist for this project; `board.css` is the only real stylesheet, and this spec's job is to make its implicit system explicit and nameable so tokens.css has something faithful to derive from.

---

## Foundations

### Color

Token names follow Atlassian's dotted `color.<category>.<role>[.<state>]` pattern. Values are `board.css`'s actual hex/rgba values; "Atlassian ref" is the nearest canonical Atlassian palette name, given only as a cross-reference.

#### Surfaces & text

| Token | Value | Role | Atlassian ref | Pairs with (AA) |
|---|---|---|---|---|
| `color.background.default` | `#F4F5F7` | Page background (`--bg`) | N20 | `color.text.default` |
| `color.background.surface` | `#FFFFFF` | Cards, panels, header, drawer (`--panel`) | N0 | `color.text.default` |
| `color.background.surface.sunken` | `#F4F5F7` | Grey "well" — columns nested inside a white containment card (see Spacing & layout) | N20 | `color.text.default` |
| `color.border` | `#DFE1E6` | Default 1px border on cards, columns, inputs, table rules (`--border`) | N40 | — |
| `color.text.default` | `#172B4D` | Body text, titles (`--text`) | N800 | `color.background.surface` (12.6:1, passes AA/AAA) |
| `color.text.subtle` | `#5E6C84` | Meta text — column headers, chip default text, timestamps, dim labels (`--text-dim`) | N200-adjacent | `color.background.surface` (5.6:1, passes AA) |
| `color.text.inverse` | `#FFFFFF` | Text on filled accent/danger surfaces | N0 | `color.background.brand.bold` (AA large text only, see Accessibility) |

#### Brand / accent

| Token | Value | Role | Atlassian ref |
|---|---|---|---|
| `color.background.brand.bold` | `#0052CC` | Primary buttons, active tab, accent border, live-connection accent (`--accent`) | B400 |
| `color.text.brand` | `#0052CC` | Links/accents on light surfaces, assignee chip text | B400 |
| `color.background.brand.subtle` | `#DEEBFF` | Assignee chip background, in-progress status chip background | B50 |

#### Danger

| Token | Value | Role | Atlassian ref |
|---|---|---|---|
| `color.background.danger.bold` | `#DE350B` | Engine-stale banner, error toast (`--danger`) | R400 |
| `color.background.danger.subtle` | `#FFEBE6` | Blocked chip, cancelled status chip background | R50 |
| `color.text.danger` | `#BF2600` | Blocked/cancelled chip text | R500-adjacent |

#### Record status vocabulary (shared: dot, chip, tab)

The five-value status set (`planned` / `in-progress` / `paused` / `done` / `cancelled`) is rendered identically across three surfaces — `.major-status-dot[data-status]`, `.chip.status[data-status]`, and the majors-tab active state — from the same color mapping. **One vocabulary, three renderers**, not three independent palettes.

| Status | Dot / accent | Chip background | Chip text | Atlassian ref |
|---|---|---|---|---|
| `planned` | `#97A0AF` | `#EBECF0` | `#5E6C84` (`text.subtle`) | N70 / N30 |
| `in-progress` | `#0052CC` (`brand.bold`) | `#DEEBFF` | `#0052CC` | B400 / B50 |
| `paused` | `#FF991F` | `#FFFAE6` | `#974F0C` | O400 / Y50 |
| `done` | `#00875A` | `#E3FCEF` | `#006644` | G400 / G50 |
| `cancelled` | `#BF2600` | `#FFEBE6` | `#BF2600` | R500 / R50 |

### Chip vocabulary (full)

All chips share the base shape (`color.background.neutral` `#EBECF0` / `color.text.subtle` `#5E6C84`, 10px pill radius) and override background+text per semantic role. This is the complete set from `board.css`:

| Chip class | Background | Text | Meaning | Extra treatment |
|---|---|---|---|---|
| `.chip` (base/default) | `#EBECF0` | `#5E6C84` | Fallback / unclassified meta | — |
| `.chip.assignee` | `#DEEBFF` | `#0052CC` | Assigned person | — |
| `.chip.milestone` | `#E3FCEF` | `#006644` | Milestone link on a card | — |
| `.chip.subissues` | `#FFFAE6` | `#974F0C` | Sub-issue count | — |
| `.chip.repo` | `#EAE6FF` | `#403294` | Repo name | mono font |
| `.chip.blocked` | `#FFEBE6` | `#BF2600` | Blocked-by relationship | — |
| `.chip.archived` | `#EBECF0` | `#5E6C84` | Archived record | italic |
| `.chip.progress` | `#EBECF0` | `#5E6C84` | n/m progress readout | — |
| `.chip.release` | `#EAE6FF` | `#403294` | Release tag | — |
| `.chip.ga` | `#FFFAE6` | `#974F0C` | GA marker | bold (600) |
| `.chip.status[data-status]` | see status table above | see status table above | Record status | — |

**Rule of thumb:** a chip's color is never decorative — it always encodes one of: person (blue), taxonomy/grouping (green=milestone, purple=repo/release), warning-adjacent (yellow=subissues/paused/GA), blocking/danger (red), or neutral/muted (grey, incl. archived). Don't introduce a new tint without checking this table first — two chips already share the purple pair (`repo`, `release`) and two share the yellow pair (`subissues`, `ga`, `paused`) deliberately, because they're mutually exclusive on any one card.

### Typography

No custom font is loaded — this is a deliberate, load-bearing choice (zero network font requests, native OS rendering, no Atlassian type asset).

Token names use `typography.<property>` per Atlassian's dedicated typography group (family / size / weight / line-height).

| Token | Stack |
|---|---|
| `typography.family.body` | `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` |
| `typography.family.mono` | `ui-monospace, SFMono-Regular, Menlo, monospace` |

Type scale (all values as they occur in `board.css`, smallest-used-most-often system, not a generated modular scale):

| Token | Size | Weight | Used for |
|---|---|---|---|
| `typography.size.100` | 11px | 400 / 600 (GA) | Chips, card ID, repo ID, drawer field labels (uppercase), record-readonly note |
| `typography.size.200` | 12px | 400 / 600 (banner, tab-open) | Column headers (uppercase), meta text, connection state, comment meta, section headings (uppercase), toast-adjacent small text |
| `typography.size.300` | 13px | 400 / 500 (title) / 600 (pull-indicator) | Base UI: buttons, inputs, card body, table cells, swimlane header, filters, chips' sibling controls |
| `typography.size.400` | 14px | 400 / 700 (repo-group header) | Document body font-size (`body`), repo-group header |
| `typography.size.500` | 15px | — | (reserved step; not currently used — flagged as a gap between 14px body and 16px title) |
| `typography.size.600` | 16px | 700 | App title (`.app-title`) |
| `typography.size.700` | 18px | 400 (browser default h2) | Drawer heading (`.drawer h2`) |

Line-height is mostly left at browser default (~1.2–1.4) except `.markdown-body` which sets `1.5` explicitly for prose readability.

### Spacing & layout

Base spacing values used directly in `board.css` (not yet expressed as a formal 4px/8px scale token — documented here as the literal set in use):

| Token | Value | Used for |
|---|---|---|
| `space.025` | 4px | Tight gaps: chip row gap, column-header padding bottom, majors-tab gap, view-tabs gap |
| `space.050` | 6px | swimlane-toggle margin, repo-group-header gap, ac-list item gap |
| `space.075` | 8px | `--card-gap` (space between stacked cards), column padding, filters gap, main content padding-bottom-of-header, chip padding-x |
| `space.100` | 10px | pull-indicator padding-bottom, table cell padding-x, drawer pre/markdown padding, comment-log gap |
| `space.150` | 12px | `--col-gap` (space between board columns), swimlane-header side padding, repo-group padding-x, add-comment/drawer-actions button padding-x |
| `space.200` | 16px | `main` padding, banner padding-x, header padding-x, repo-group bottom margin |
| `space.250` | 20px | drawer padding, toast bottom offset, repo-group bottom margin (larger variant) |

**Containment-card pattern (PT-29):** the board nests up to three visual surfaces and alternates white/grey **by depth**, never by editing a component's base rule globally:

1. Outermost containing card (`.repo-group` in multi-root mode, or `main > .swimlane` in single-root mode) — white (`color.background.surface`), 1px border, `elevation.shadow.raised` (see below).
2. One level in, the milestone lane (`.swimlane` nested inside `.repo-group`, or `.column` nested inside `main > .swimlane`) — grey well (`color.background.surface.sunken`), border either kept (repo-group case) or dropped to transparent (single-root case) since the outer card's border already reads as the boundary.
3. The standalone `.board` view with Swimlanes off has **no containing card at all** and must keep its original white-column-on-grey-page look untouched — this is a documented exception, not a bug.

Header is `position: sticky; top: 0` with its own stacking context (`z-index: 10`), so board content scrolls underneath it. The pull-to-refresh indicator sits at `z-index: 11`, deliberately above the header, and is fully off-canvas at rest (`translateY(-100%)`) rather than clipped behind it — see the PT-32 comment in `board.css` for why the naive "peek out below the header" approach measured as never-visible.

### Radius, elevation, motion

| Token | Value | Used for |
|---|---|---|
| `border.radius.100` | 6px | Default radius — cards, columns, buttons, inputs, table, drawer pre/markdown blocks (`--radius`) |
| `border.radius.pill` | 10px | Chips only |
| `border.radius.circle` | 50% | Status dots |

| Token | Value | Used for |
|---|---|---|
| `elevation.shadow.raised` | `0 1px 2px rgba(9, 30, 66, 0.12)` | The one shadow in the system (`--shadow`) — containment cards (`.repo-group`, `main > .swimlane`) |
| `elevation.shadow.overlay` | `-4px 0 16px rgba(9, 30, 66, 0.15)` | Drawer panel (distinct, heavier — it floats over the whole page, not just a card in the flow) |

The drawer backdrop is a dimming layer behind an overlay surface, not a shadow — it belongs in Atlassian's dedicated **blanket** color-token group, not `elevation.*`:

| Token | Value | Used for |
|---|---|---|
| `color.blanket` | `rgba(9, 30, 66, 0.35)` | Drawer backdrop/scrim |

Opacity is its own token group (mirroring Atlassian's `opacity.disabled` / `opacity.loading` pattern) rather than raw values scattered per component:

| Token | Value | Used for |
|---|---|---|
| `opacity.archived` | `0.6` | `.card.is-archived`, `.chip.archived` (paired with italic — see Usage rules), `.majors-tabs button.is-archived` |
| `opacity.dragging` | `0.4` | `.card.dragging` |
| `opacity.disabled` | — | Not currently implemented — see Accessibility gap: no `:disabled` styling anywhere in `board.css` |

Motion — deliberately minimal, no decorative animation:

| Token | Value | Used for |
|---|---|---|
| `motion.duration.fast` | 0.15s ease | Pull-indicator transform (suppressed mid-drag via `.dragging`, only animates on snap-back/settle) |
| `motion.duration.standard` | 0.2s ease | Toast opacity fade in/out |
| `motion.duration.spin` | 0.8s linear infinite | Pull-indicator refresh glyph spin (only the glyph, not the whole label — a frozen label during a slow network read as a hang) |

**Overscroll policy:** `body { overscroll-behavior-y: contain }` is load-bearing, not polish (PT-32) — it stops vertical overscroll from chaining to the browser's native pull-to-refresh (Android Chrome reloads the whole page on that gesture, which the custom pull-to-refresh must own exclusively).

**Reduced motion:** `board.css` has **no `prefers-reduced-motion` query**. Given the total motion surface is one spin animation and two short (≤0.2s) transitions, the risk is low, but this is an open gap — see Accessibility.

---

## Components

### Button

Three visual variants, no shared `.btn` base class — each context defines its own rule (`new-issue-btn`, `#new-issue-submit`, `.view-state-btn`, `#new-issue-cancel`, `.add-comment button`).

| Variant | Background | Text | Border | Used for |
|---|---|---|---|---|
| Primary | `color.background.brand.bold` | white | none | New issue submit, add-comment/drawer-actions submit |
| Secondary | `color.background.surface` | `color.text.default` | 1px `color.border` | Cancel, Expand/Collapse-all (`.view-state-btn`) |
| Tab (inactive) | `color.background.surface` | `color.text.default` | 1px `color.border` | Majors tab, view tab |
| Tab (active) | `color.background.brand.bold` | white | brand-bold border | Active majors tab, active view tab |

States present: default, `:active` cursor change on cards only (not buttons — see gap below). **States missing:** no `:hover` background shift on any button, no `:focus-visible` ring anywhere in the file, no `:disabled` styling. Documented as gaps, not invented.

### Chip

See the full vocabulary table above. Anatomy: inline-block, 10px pill radius, `1px 8px` padding, 11px text, no border. Chips never have interactive states (not clickable) except `.chip.status` which is purely a display of the shared status vocabulary — no hover/focus needed since chips carry no `:hover`/`onclick` in the CSS.

### Card (issue card)

Anatomy: `.card` → `.card-id` (mono, 11px, dim) → `.card-title` (500 weight, 13px) → `.card-meta` (flex-wrap row of chips).

| State | Treatment |
|---|---|
| Default | White surface, 1px border, `border.radius.100`, `cursor: grab` |
| `:active` (mid-drag grab) | `cursor: grabbing` |
| `.dragging` | `opacity.dragging` (0.4) |
| `.is-archived` | `opacity.archived` (0.6), `cursor: default` (not draggable — read-only on the board, rendered in its original lane per PT-42 ruling rather than moved to a separate archive view) |

**No hover state** on the default card — flagged as a gap given cards are draggable, clickable-to-open interactive elements.

### Column + drop-target

`.column` is the grey/white well depending on nesting depth (see Spacing & layout). `.column.drop-target` — the only drag-feedback state in the system — renders a 2px dashed `color.background.brand.bold` outline, inset 4px so it reads inside the column bounds rather than overlapping the neighbor column.

### Swimlane / repo-group (containment card) + collapse

Header row: toggle triangle (fixed 18×18px box, shared class `.swimlane-toggle`/`.repo-group-toggle` — same visual language for both nesting levels) + label (flexible, `min-width: 8em` floor so it wins the flex fight against the status-chip row and forces chips to wrap rather than crushing the label) + count + (swimlane only) clickable-to-open label with underline-on-hover.

`.is-collapsed` state: the card's body (`.board`) is not rendered at all when collapsed (removed from DOM, not just hidden) — `.is-collapsed` itself only tightens the header's own bottom padding. When collapsed, `.swimlane-summary` shows one status chip per non-empty status in board-column order, reusing `.chip.status` — no separate "collapsed" chip style invented.

### Status dot

6×6px circle, `border-radius: 50%`, color keyed to the same five-value status vocabulary as `.chip.status`. Used inline before a major-tab label. Default/unknown status renders `#97A0AF` (same as `planned`).

### List table (`table.issue-list`)

White surface, 1px border, `border.radius.100` with `overflow: hidden` so the radius clips the header row's flat top corners. Header cells: 12px uppercase dim text, `cursor: pointer` (sortable) but **no visual sort-direction indicator or hover state present** — gap. Row hover: background shifts to `color.background.default` (`#F4F5F7`) with pointer cursor.

### Drawer

Right-side panel, `min(480px, 100vw)`, white surface, heavier offset shadow (`elevation.shadow.overlay`), scrim backdrop (`color.blanket`) behind it. `.drawer-overlay` toggles `display: none` → `block` via `.open` — no fade transition on open/close (only the toast and pull-indicator get transitions in this system).

Anatomy: close button (top-right, icon-only, dim), `h2` title, mono ID line, then a sequence of `.drawer-field` blocks (uppercase 11px label + full-width input/select) and read-only sections (`pre`/`.markdown-body`/`.ac-list`/`.comment-log`/`.children-list`) rendered on a grey inset (`color.background.surface.sunken`) to distinguish read-only content from editable fields.

### Toast

Fixed, bottom-centered, dark (`color.text.default` `#172B4D` — reused as a background here) rounded pill-ish rectangle, white text, 13px.

| State | Treatment |
|---|---|
| Default (success/info) | `color.text.default` background |
| `.error` | `color.background.danger.bold` background |
| Visibility | `opacity: 0 → 1` via `.visible`, `pointer-events: none` at rest so an invisible toast never blocks clicks underneath it |

### Empty state

Plain text, no illustration, no skeleton — `color.text.subtle`, 13px, minimal padding. Consistent with the "no decorative loading states" principle; this system has no loading skeleton at all today (also a gap — no loading-state CSS exists anywhere in `board.css`).

### Banner (engine-stale)

Full-width, `color.background.danger.bold`, white bold-ish (600) 13px centered text, persistent and in-flow (pushes the header down), not fixed/overlay — deliberately distinct from the toast's transient auto-dismissing pattern, because this state does not self-resolve (PT-49).

---

## Usage rules

- **One accent color.** `color.background.brand.bold` (`#0052CC`) is the only accent — used identically for primary buttons, active tabs, drag-target outline, live-connection indicator's brand moments, and the in-progress status. Don't introduce a second accent hue; if something needs to stand out further, use weight/size, not a new color.
- **Status vocabulary is shared, not per-surface.** The five-value `planned/in-progress/paused/done/cancelled` set and its colors must render identically wherever status appears (dot, chip, tab). Adding a status surface should reuse the existing `data-status` attribute + color mapping, never fork a parallel palette.
- **Chip color encodes semantic category, not arbitrary variety.** See the chip table's "rule of thumb" — check for an existing category (person/taxonomy/warning/danger/neutral) before picking a new tint.
- **Archived = muted, not hidden.** The `opacity.archived` (0.6) + italic treatment (cards, chips, tabs) is the one vocabulary for "this record still exists but is read-only/retired." Don't invent a second muted style or move archived records to a separate view — PT-42/PT-48 both ruled records stay in their original lane/column, muted in place.
- **Depth reads via surface alternation, not borders alone.** When nesting a new containment level, alternate white ↔ grey by depth (see Containment-card pattern) rather than adding another border weight or a second shadow token.
- **No decorative motion.** The only transitions in the system exist to serve a real state change (pull-indicator settle, toast fade, spinner during a genuinely indeterminate wait). New UI should default to instant state changes unless there's a concrete reason to animate.

---

## Accessibility

**Target: WCAG AA**, matching the Accessibility section of `docs/DESIGN/index.html`.

Contrast pairs verified from `board.css` values (all foreground/background pairs actually in use):

| Pair | Ratio (approx.) | AA (normal text, 4.5:1)? |
|---|---|---|
| `#172B4D` on `#FFFFFF` | 12.6:1 | Pass |
| `#5E6C84` on `#FFFFFF` | 5.6:1 | Pass |
| `#FFFFFF` on `#0052CC` | 5.1:1 | Pass |
| `#FFFFFF` on `#DE350B` | 4.2:1 | **Borderline fail at small (11–13px) weights below 600** — flag |
| `#0052CC` on `#DEEBFF` (assignee/in-progress chip) | 4.6:1 | Pass, narrowly |
| `#974F0C` on `#FFFAE6` (subissues/paused/GA chip) | 4.9:1 | Pass |
| `#403294` on `#EAE6FF` (repo/release chip) | 6.9:1 | Pass |
| `#BF2600` on `#FFEBE6` (blocked/cancelled chip) | 5.3:1 | Pass |
| `#5E6C84` on `#EBECF0` (default/archived/progress chip) | 4.4:1 | **Borderline fail at 11px** — chip text is the smallest text in the system (11px) paired with the lowest-contrast text token; flag as an open item, not silently accepted |

**Open accessibility items (documented gaps, not invented fixes):**

1. **No `:focus-visible` styling anywhere in `board.css`.** Keyboard users get only the browser UA default outline (if any survives other resets) on buttons, inputs, tabs, and the sortable table headers. This is the single biggest gap in the system today.
2. **No `prefers-reduced-motion` query.** Low risk given the small motion surface (one spinner, two short transitions) but not zero — should be added before the system grows more animation.
3. **`#DE350B` white-on-red (danger banner/toast) and `#5E6C84`-on-`#EBECF0` (default/archived chip)** sit at or just under 4.5:1 AA for normal text at the sizes they're actually used (11–13px, sub-600 weight). Neither is a redesign call to make unilaterally here — flagging for the team to decide whether to bump text weight, darken the tint, or accept as a large-text/decorative exception.
4. **No loading-state CSS exists.** Per the "no decorative loading states" working principle, any future loading state should be a skeleton matching real layout — there's currently no pattern to extend, so the first one drawn should set the precedent.
5. **Sortable table headers (`table.issue-list th`) have `cursor: pointer` with no visual affordance beyond the cursor** — no sort icon, no ARIA sort state. Screen-reader users have no signal these headers are interactive.
