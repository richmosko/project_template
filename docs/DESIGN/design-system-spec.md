# Design System Spec — TBD

> The written companion to `tokens.css` + `screen.css`. The CSS files are the machine-readable source of truth; this doc explains the *why* and the usage rules. Owned by the `ux-designer` agent. Generate/refine with `/generate-designdoc`.

## Foundations

### Color

Document the palette and its semantic roles (not just hex values). For each token in `tokens.css`, note intent and contrast pairing.

| Token | Value | Role | Pairs with (AA) |
|---|---|---|---|
| `--color-primary` | _TBD_ | Primary actions | `--color-on-primary` |
| `--color-surface` | _TBD_ | Cards, sheets | `--color-text` |
| `--color-text` | _TBD_ | Body text | `--color-surface` |
| `--color-danger` | _TBD_ | Destructive / errors | `--color-on-danger` |

### Typography

Type scale, families, weights, line-heights. Reference the `--font-*` and `--text-*` tokens.

### Spacing & layout

The spacing scale (`--space-*`), grid, breakpoints, container widths.

### Radius, shadow, motion

`--radius-*`, `--shadow-*`, and motion tokens (durations/easings). Note the `prefers-reduced-motion` policy.

## Components

For each component: anatomy, variants, **all states** (default / hover / focus-visible / active / disabled / loading / error), and accessibility notes. Link to the styled-screen example.

- **Button** — _TBD_
- **Input** — _TBD_
- **Card** — _TBD_

## Usage rules

Cross-cutting rules that keep the system coherent: when to use primary vs secondary, density, empty/loading/error-state conventions, do/don't examples.

## Accessibility

The target standard (default: WCAG AA) and any deliberate exceptions, with rationale. Mirrors the Accessibility section of `index.html`.
