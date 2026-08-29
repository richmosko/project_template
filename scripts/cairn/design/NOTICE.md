# Vendored theme-variant data (PT-69)

`variants.json` in this directory is hand-vendored data, extracted from shadcn-svelte's
own live theme generator — never fetched at runtime, per the architect's ruling
("registry-fetch-at-build is rejected outright: the board is zero-build and 'clone and
it works' is the template's strongest property"). This follows the same precedent as
`scripts/cairn/board/vendor/NOTICE.md`'s font vendoring: checked into git, sourced once
by an agent, re-vendor by hand when the upstream preset changes.

`gen_variants.py` (same directory) is the authoring tool that turns `variants.json` into
the three checked-in `variants.css` copies (`scripts/cairn/board/variants.css`,
`scripts/cairn/dashboard/src/variants.css`, `docs/DESIGN/variants.css`). It is
stdlib-only, zero network — regenerate with `python3 scripts/cairn/design/gen_variants.py`
after any edit to `variants.json`.

## Source and method

Every value in `variants.json` was extracted from the same generator the app's own
`b6XadDxmQS` preset (`docs/DESIGN/design-system-spec.md`'s canonical source) comes from:
shadcn-svelte's CLI preset system (`packages/cli/src/preset/preset.ts` in
`huntabyte/shadcn-svelte`), decoded/re-encoded with each dimension's target value swapped
(base color, theme, or chart color), then materialized via the CLI's own live data
endpoint — `https://www.shadcn-svelte.com/init?preset=<encoded-preset-code>` — which
returns the exact `cssVars` a real `shadcn-svelte init --preset <code>` run would write.
This endpoint was verified byte-exact against this app's own checked-in `app.css` for the
known `b6XadDxmQS` code before being trusted for any new variant. Extracted 2026-08-29.

Each generated preset kept every OTHER field fixed at this app's own values (style
`mira`, font `merriweather`, heading font `space-grotesk`, radius `medium`, icon library
`lucide`, menu color `default`, menu accent `subtle`) — only the one dimension under
extraction (base color / theme / chart color) varied, so the output isolates exactly that
dimension's delta.

## Per-dimension notes

- **Base Color.** The classic shadcn/ui 5-name vocabulary (Stone/Neutral/Zinc/Gray/Slate)
  does **not** exist in this preset system — the real, complete `PRESET_BASE_COLOR_KEYS`
  set is **Stone (default), Neutral, Zinc, Mauve, Olive, Mist, Taupe** (7). "Gray"/"Slate"
  only exist in a separate, legacy, pre-OKLCH (HSL) shadcn generator that also redefines
  Theme/Chart-owned tokens per base color — a partition violation, not usable here. See
  `process/cairn/issues/PT-69.md` (implementation-lead's live-generator finding,
  ux-designer's "ship all 7" ruling) for the full trail.
- **`--destructive`/`--destructive-foreground`.** The live generator no longer emits
  `--destructive-foreground` for any variant, and `--destructive` is identical across
  every fetched Base Color option (verified: same value for all 6 non-default bases) —
  i.e. this pair is genuinely base-invariant in the live system, not something the
  generator forgot to vary. `variants.json` reuses this app's own already-vendored
  default value (`docs/DESIGN/design-system-spec.md`'s Foundations → Color table,
  extracted 2026-08-26) for `--destructive-foreground` in every Base Color variant rather
  than inventing one.
- **Theme.** Expanded 2026-08-29 (Mosko's live-test finding #5) from a curated 7 to the
  **full 24-name `PRESET_THEME_KEYS` reference set** (Sky default + 23 alternates —
  Amber/Blue/Cyan/Emerald/Fuchsia/Green/Indigo/Lime/Mauve/Mist/Neutral/Olive/Orange/Pink/
  Purple/Red/Rose/Stone/Taupe/Teal/Violet/Yellow/Zinc). One live-generator quirk found and
  filtered out: the `rose` theme's dark-mode output also shifts the plain `--sidebar`
  token (Base-Color-owned, not Theme-owned) — `gen_variants.py`/this vendoring step keeps
  only the four tokens architect's ownership table actually assigns to Theme
  (`--primary`/`--primary-foreground`/`--sidebar-primary`/`--sidebar-primary-foreground`),
  discarding anything else the upstream generator happened to return, so the partition
  invariant holds regardless of upstream behavior. **`lime` dropped** after the expansion —
  its dark-mode `--primary-foreground`/`--primary` fails WCAG AA on its own (4.4612:1,
  every other Theme variant clears the same pair fine), the drop-don't-rederive fence's
  textbook case. **`--primary-foreground` is now derived, not vendored verbatim**, same
  "darken the ink" treatment as Base's `--muted-foreground` (`gen_variants.py`'s
  `derive_primary_foreground()`) — found because `yellow` (now real, previously excluded
  from the curated 7) sat inside the two-model derivation-headroom margin on its own
  dark-mode pair even though it clears the bare 4.5:1 floor.
- **Chart Color.** Expanded 2026-08-29 (same live-test finding, ≤5 cap lifted) from a
  curated 3 to the **full 24-name `PRESET_CHART_COLORS` reference set** (Yellow default +
  23 alternates, same names as Theme's set). Yellow's `--chart-flow-*` is the existing
  PT-61 ramp, untouched. Every other variant's `--chart-1..5` is the live generator's own
  value; its 6-step `--chart-flow-*` ordinal ramp is newly derived (this project's own
  token, same as Yellow's, never vendored) per PT-61's method — single hue held constant
  (the source ramp's own `--chart-3` hue), chroma capped and glided from the light end's
  own `chart-1` chroma to the dark end's own `chart-5` chroma, extremal `L` bounds found by
  binary search per hue — validated with the dataviz skill's `validate_ordinal` against
  both the light surface (`#ffffff`, the light `--card` in every Base Color option) and
  the extremal dark surface (`#171717` — Neutral's dark `--card`, the darkest across every
  fetched Base Color option, per architect's §4 extrema method) with a 0.03 contrast-ratio
  margin over the 2:1 floor to absorb hex-quantization rounding noise. All 23 alternates
  passed on the first derivation attempt — no per-hue exceptions.

## Re-vendoring / updating

If the upstream preset generator changes, or a new dimension option is added:

1. Decode this app's current preset (`b6XadDxmQS`) using the same base62 field-packing
   algorithm as `packages/cli/src/preset/preset.ts`, to get the fixed non-varying fields.
2. Re-encode with the target dimension swapped to the new option's key.
3. `curl -s "https://www.shadcn-svelte.com/init?preset=<code>"` and read `.cssVars`.
4. Filter to the dimension's owned-key set (architect's ownership table /
   `test_theme_variants_generator.py`'s `EXPECTED_VARS_BY_DIM`) and update `variants.json`.
5. Re-run the dataviz skill's ordinal validator for any Chart Color change (new ramp
   needed every time — PT-61's finding recurs per hue, not just for some).
6. `python3 scripts/cairn/design/gen_variants.py` to regenerate the three checked-in
   `variants.css` copies.
