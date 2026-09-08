"""PT-92 gate-1 ruling (architect, process/cairn/issues/PT-92.md @
15fe9b6, item (c)): red tests 2-4. Test 1 (the existing distinctness
guard, `test_flow_series_distinctness.py`, re-run against ux-designer's
FINAL token values) is DONE, no code change needed -- 4/4 green against
the values ux-designer landed at 069b8db.

**Ratified spec** (ux-designer, PT-92.md @ 069b8db, "Line treatment
(binding on implementation-lead)"; precision from architect's addendum 1
@ f1b76c6): NOT an assumed shape any more -- these are the landed,
binding numbers.
- **Stroke, bottom-to-top z-order:** `opened` solid 2px (no dasharray),
  `closed` dashed 2px `stroke-dasharray="6,4"`, `wip` dotted 2.5px
  `stroke-dasharray="2,4"` -- each drawn ON TOP of the previous, so
  document/paint order must be opened, then closed, then wip.
- **Markers, same relative z-order:** a filled circle at every vertex,
  per series, graduated radius -- `opened` r=5, `closed` r=3.5, `wip`
  r=2 with a 1px `--card`-colored outline ring.
- **Addendum 1, the precision that matters for the config-level test:**
  at the actual measured coincidence (2026-09-07, a single shared
  vertex, opened=closed=3, not a run) the paths CROSS rather than run
  together, so a dash gap is not guaranteed to fall there -- "the
  markers carry that case, not the dashes". This file's coincidence
  test therefore requires MARKERS specifically on opened/closed, not
  "a dash pattern or a marker, either one" (the looser check an earlier
  draft of this file used before the spec landed).
- **Legend:** FIXED order Opened, Closed, WIP (token declaration order
  = semantic reading order) -- not just "all three present", the order
  itself is binding.
- **Caption/tooltip:** name all three series, same fixed order.

Nothing under test exists in its final form yet: IssueFlowChart.svelte
still renders opened/closed as grouped `<Bars>` (test's own subject,
L229) -- every red test below is expected to fail loudly on that shape,
not silently skip."""
from __future__ import annotations

import re
import unittest
from typing import Optional

import helpers  # noqa: F401
from test_flow_series_distinctness import FLOW_CHART_SVELTE, _series_color_tokens  # noqa: F401

FLOW_CHART_LOGIC_TS = helpers.CAIRN_DIR / "dashboard" / "src" / "lib" / "flow-chart-logic.ts"

MARKS_START_RE = re.compile(r"\{#snippet marks\(\{\s*context\s*\}\)\}")
MARKS_END_MARKER = "{#snippet tooltip()}"
LEGEND_ITEMS_START_RE = re.compile(r"legendItems\s*=\s*\[")
SPLINE_ELEMENT_RE = re.compile(r"<Spline\b.*?/>", re.DOTALL)
POINTS_ELEMENT_RE = re.compile(r"<Points\b.*?/>", re.DOTALL)

SERIES_KEYS = ("opened", "closed", "wip")
SERIES_ORDER = ("opened", "closed", "wip")  # bottom-to-top z-order AND legend order (same sequence)

# ux-designer's ratified spec (PT-92.md @ 069b8db, "Line treatment"):
# dasharray per series -- `None` for opened means "no dasharray at all"
# (solid), not "dasharray declared as empty".
SERIES_DASHARRAY = {"opened": None, "closed": "6,4", "wip": "2,4"}
SERIES_MARKER_RADIUS = {"opened": "5", "closed": "3.5", "wip": "2"}
# Loose match: "6,4", "6, 4", "6 4" are all the same dasharray to an SVG
# renderer -- this file does not pin one whitespace/separator style.
_DASH_VALUE_RE_TMPL = r"{a}\s*[, ]\s*{b}"


class ExtractionError(AssertionError):
    """Raised when a required anchor (the marks snippet, the legend
    array, the caption function) can't be found -- never a silent
    empty/None result, mirroring this suite's standing contract
    (test_ratified_text_scanners.py, test_agent_worktree_protocol_
    block.py) for a guard that must fail loudly, not go vacuously
    green, the moment its anchor text stops matching."""


def _strip_svelte_comments(source: str) -> str:
    return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)


def _load_component_source() -> str:
    assert FLOW_CHART_SVELTE.is_file(), f"{FLOW_CHART_SVELTE} does not exist"
    return FLOW_CHART_SVELTE.read_text(encoding="utf-8")


def extract_marks_region(source: str) -> str:
    """The `{#snippet marks({ context })}` ... `{#snippet tooltip()}`
    span -- bounded by the NEXT sibling snippet rather than a full
    `{#snippet}`/`{/snippet}` depth-match, since `marks` currently nests
    no snippet of its own (only `{#each}`/`{/each}`); this is simpler
    and just as precise for this file's shape."""
    stripped = _strip_svelte_comments(source)
    start_match = MARKS_START_RE.search(stripped)
    if not start_match:
        raise ExtractionError(
            "found no `{#snippet marks({ context })}` in IssueFlowChart.svelte -- the marks "
            "snippet is the seam PT-92's ruling names (item (a)); if the real snippet signature "
            "diverges, update this assumption, don't silence the guard."
        )
    end_idx = stripped.find(MARKS_END_MARKER, start_match.end())
    if end_idx == -1:
        raise ExtractionError(
            f"found `{{#snippet marks({{ context }})}}` but no following `{MARKS_END_MARKER}` -- "
            f"cannot bound the marks region. If the tooltip snippet was renamed/reordered, update "
            f"this assumption, don't silence the guard."
        )
    return stripped[start_match.end():end_idx]


def extract_legend_items_region(source: str) -> str:
    stripped = _strip_svelte_comments(source)
    m = LEGEND_ITEMS_START_RE.search(stripped)
    if not m:
        raise ExtractionError("found no `legendItems = [` array literal in IssueFlowChart.svelte")
    depth, i, n = 1, m.end(), len(stripped)
    while i < n and depth > 0:
        if stripped[i] == "[":
            depth += 1
        elif stripped[i] == "]":
            depth -= 1
        i += 1
    return stripped[m.end():i - 1]


def extract_format_flow_caption_body(source: str) -> str:
    m = re.search(r"export function formatFlowCaption\([^)]*\)[^{]*\{", source)
    if not m:
        raise ExtractionError("found no `export function formatFlowCaption(...) {` in flow-chart-logic.ts")
    depth, i, n = 1, m.end(), len(source)
    while i < n and depth > 0:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    return source[m.end():i - 1]


def _elements_by_series_key(elements):
    """{key: [element_text, ...]} -- every mark element (Spline or
    Points) whose text references that series' SERIES_COLOR entry OR
    whose `seriesKey` prop names it literally. An element can belong to
    at most... actually may match more than one key only in a
    pathological case; that's fine, over-matching here only makes the
    guard MORE conservative, never less."""
    by_key: dict = {k: [] for k in SERIES_KEYS}
    for el in elements:
        for key in SERIES_KEYS:
            color_hit = (
                re.search(rf"SERIES_COLOR\.{key}\b", el)
                or re.search(rf"SERIES_COLOR\[['\"]{key}['\"]\]", el)
            )
            key_hit = re.search(rf"seriesKey\s*=\s*[\"'{{]*{key}\b", el)
            if color_hit or key_hit:
                by_key[key].append(el)
    return by_key


def _has_distinguishing_treatment(elements) -> bool:
    has_points_mark = any(el.strip().startswith("<Points") for el in elements)
    has_dash = any(re.search(r"stroke-dasharray|strokeDasharray|\bdash\b", el, re.IGNORECASE) for el in elements)
    return has_points_mark or has_dash


def _points_elements(elements):
    return [el for el in elements if el.strip().startswith("<Points")]


def _spline_elements(elements):
    return [el for el in elements if el.strip().startswith("<Spline")]


def _dasharray_matches(el: str, value: Optional[str]) -> bool:
    """`value` is a "a,b" pair (or None for "no dasharray at all")."""
    if value is None:
        return not re.search(r"stroke-dasharray|strokeDasharray", el)
    a, b = value.split(",")
    pattern = _DASH_VALUE_RE_TMPL.format(a=re.escape(a.strip()), b=re.escape(b.strip()))
    return bool(re.search(rf"(?:stroke-dasharray|strokeDasharray)\s*[=:]\s*[\"'{{]*{pattern}", el))


def _radius_matches(el: str, radius: str) -> bool:
    return bool(re.search(rf"\br\s*=\s*[\"'{{]*{re.escape(radius)}\b", el))


def _first_index_referencing_key(region: str, elements, key: str) -> Optional[int]:
    """The region's own start-index of the FIRST element (by document
    order) among `elements` that references `key` -- used to check
    relative z-order (document/paint order == the ratified bottom-to-top
    order) without needing exact element boundaries region-wide."""
    for el in elements:
        if re.search(rf"SERIES_COLOR\.{key}\b", el) or re.search(rf"SERIES_COLOR\[['\"]{key}['\"]\]", el) or re.search(rf"seriesKey\s*=\s*[\"'{{]*{key}\b", el):
            idx = region.find(el)
            if idx != -1:
                return idx
    return None


class NoFlowSeriesRendersAsBarsTests(unittest.TestCase):
    """Ruling item (c)(2), first half. Mutation: revert one series to
    `<Bars`."""

    def test_no_bars_tag_anywhere_in_the_component(self):
        source = _load_component_source()
        self.assertNotIn(
            "<Bars", source,
            "IssueFlowChart.svelte must render opened/closed/wip as line marks, not bars -- "
            "found a `<Bars` tag (ruling item (a): replace the grouped Bars at L229 with a line "
            "mark per series)",
        )


class EachSeriesDeclaresALineMarkWithADistinguishingTreatmentTests(unittest.TestCase):
    """Ruling item (c)(2), second half, tightened to ux-designer's landed
    spec (PT-92.md @ 069b8db): each series' STROKE carries its own exact
    dasharray (opened solid/none, closed "6,4", wip "2,4"), each series
    has its own MARKER at the exact graduated radius (5 / 3.5 / 2), and
    document order (paint/z-order) is opened, then closed, then wip for
    both strokes and markers."""

    def test_each_series_has_its_own_line_mark(self):
        source = _load_component_source()
        region = extract_marks_region(source)
        splines = SPLINE_ELEMENT_RE.findall(region)
        points = POINTS_ELEMENT_RE.findall(region)
        by_key = _elements_by_series_key(splines + points)
        missing_mark = [k for k in SERIES_KEYS if not by_key[k]]
        self.assertEqual(
            missing_mark, [],
            f"every flow series must have its own line mark referencing SERIES_COLOR -- missing "
            f"a mark for: {missing_mark} (marks region: {region!r})",
        )

    def test_each_series_strokes_the_exact_ratified_dasharray(self):
        source = _load_component_source()
        region = extract_marks_region(source)
        splines = SPLINE_ELEMENT_RE.findall(region)
        by_key = _elements_by_series_key(splines)
        wrong = []
        for key in SERIES_KEYS:
            strokes = _spline_elements(by_key[key])
            if not strokes or not any(_dasharray_matches(el, SERIES_DASHARRAY[key]) for el in strokes):
                wrong.append((key, SERIES_DASHARRAY[key]))
        self.assertEqual(
            wrong, [],
            f"each series must stroke the exact ratified dasharray (opened=solid/none, "
            f"closed='6,4', wip='2,4') -- wrong or missing for: {wrong!r} (region: {region!r})",
        )

    def test_each_series_markers_the_exact_ratified_radius(self):
        source = _load_component_source()
        region = extract_marks_region(source)
        points = POINTS_ELEMENT_RE.findall(region)
        by_key = _elements_by_series_key(points)
        wrong = []
        for key in SERIES_KEYS:
            markers = _points_elements(by_key[key])
            if not markers or not any(_radius_matches(el, SERIES_MARKER_RADIUS[key]) for el in markers):
                wrong.append((key, SERIES_MARKER_RADIUS[key]))
        self.assertEqual(
            wrong, [],
            f"each series must have its own marker at the exact ratified graduated radius "
            f"(opened=5, closed=3.5, wip=2) -- wrong or missing for: {wrong!r} (region: {region!r})",
        )

    def test_wip_marker_carries_a_card_colored_outline_ring(self):
        source = _load_component_source()
        region = extract_marks_region(source)
        points = POINTS_ELEMENT_RE.findall(region)
        by_key = _elements_by_series_key(points)
        wip_markers = _points_elements(by_key["wip"])
        self.assertTrue(wip_markers, f"'wip' must have its own marker (region: {region!r})")
        has_ring = any(re.search(r"stroke\s*=\s*[\"'{]*(?:var\()?--card\b", el) for el in wip_markers)
        self.assertTrue(
            has_ring,
            f"wip's marker must carry a 1px --card-colored outline ring (ux-designer's spec, "
            f"069b8db) so the smaller top marker stays visible nested inside a larger one at a "
            f"coincidence -- got {wip_markers!r}",
        )

    def test_strokes_and_markers_paint_bottom_to_top_opened_closed_wip(self):
        source = _load_component_source()
        region = extract_marks_region(source)
        splines = SPLINE_ELEMENT_RE.findall(region)
        points = POINTS_ELEMENT_RE.findall(region)

        stroke_indices = [_first_index_referencing_key(region, splines, k) for k in SERIES_ORDER]
        marker_indices = [_first_index_referencing_key(region, points, k) for k in SERIES_ORDER]

        self.assertNotIn(None, stroke_indices, f"could not locate every series' stroke element in document order -- {stroke_indices!r} (region: {region!r})")
        self.assertNotIn(None, marker_indices, f"could not locate every series' marker element in document order -- {marker_indices!r} (region: {region!r})")

        self.assertEqual(
            stroke_indices, sorted(stroke_indices),
            f"strokes must paint bottom-to-top in the ratified order opened, closed, wip -- got "
            f"document positions {dict(zip(SERIES_ORDER, stroke_indices))}",
        )
        self.assertEqual(
            marker_indices, sorted(marker_indices),
            f"markers must paint in the SAME relative z-order as the strokes (opened, closed, "
            f"wip) -- got document positions {dict(zip(SERIES_ORDER, marker_indices))}",
        )


class LegendAndCaptionNameAllThreeSeriesTests(unittest.TestCase):
    """Ruling item (c)(3), tightened to ux-designer's landed spec
    (069b8db): "fixed order Opened, Closed, WIP (token declaration
    order = semantic reading order)" -- the ORDER itself is binding, not
    just presence. Mutation: drop one from the legend list, or reorder
    it."""

    def test_legend_items_list_all_three_series_keys(self):
        source = _load_component_source()
        region = extract_legend_items_region(source)
        missing = [k for k in SERIES_KEYS if not re.search(rf"key\s*:\s*['\"]{k}['\"]", region)]
        self.assertEqual(
            missing, [],
            f"legendItems must list all three series -- missing: {missing} (region: {region!r})",
        )

    def test_legend_items_are_in_the_ratified_fixed_order(self):
        source = _load_component_source()
        region = extract_legend_items_region(source)
        key_positions = []
        for key in SERIES_ORDER:
            m = re.search(rf"key\s*:\s*['\"]{key}['\"]", region)
            self.assertIsNotNone(m, f"legendItems has no '{key}' entry (region: {region!r})")
            key_positions.append(m.start())
        self.assertEqual(
            key_positions, sorted(key_positions),
            f"legendItems must list Opened, Closed, WIP in that FIXED order (ux-designer's spec, "
            f"069b8db: 'token declaration order = semantic reading order') -- got document "
            f"positions {dict(zip(SERIES_ORDER, key_positions))}",
        )

    def test_caption_text_names_opened_closed_and_wip(self):
        assert FLOW_CHART_LOGIC_TS.is_file(), f"{FLOW_CHART_LOGIC_TS} does not exist"
        source = FLOW_CHART_LOGIC_TS.read_text(encoding="utf-8")
        body = extract_format_flow_caption_body(source)
        missing = []
        if not re.search(r"\bopened\b", body, re.IGNORECASE):
            missing.append("opened")
        if not re.search(r"\bclosed\b", body, re.IGNORECASE):
            missing.append("closed")
        if not re.search(r"\bWIP\b", body):
            missing.append("wip")
        self.assertEqual(
            missing, [],
            f"formatFlowCaption's returned text must name all three series -- missing: {missing} "
            f"(body: {body!r})",
        )


class CoincidentValuesStillResolveToIndependentMarksTests(unittest.TestCase):
    """Ruling item (c)(4), the one this feature exists for (architect,
    measured: live /api/flow, 2026-09-07 has opened=closed=3 -- not
    hypothetical, 18% of points share a value across at least two
    series). Testable at the CONFIG level only -- both series present in
    the mark set with distinct treatment, unconditioned on comparing
    their values; the RENDERED proof (that they remain visually distinct
    AT that exact coincident point) is the lead's browser leg, not this
    test -- the ruling says so rather than pretending a source scan
    settles it."""

    def test_no_mark_is_conditioned_on_comparing_two_series_values(self):
        # A conditional wrapping a mark and comparing two series' data
        # values (e.g. `{#if d.opened !== d.closed}`) is exactly the
        # anti-pattern this feature exists to prevent -- it would make
        # the coincident point silently drop one series' mark instead of
        # rendering both with independent, distinguishing treatment.
        source = _load_component_source()
        region = extract_marks_region(source)
        offending = re.findall(
            r"\{#if[^}]*\b(?:opened|closed|wip)\b[^}]*(?:===|!==|==|!=)[^}]*\b(?:opened|closed|wip)\b[^}]*\}",
            region,
        )
        self.assertEqual(
            offending, [],
            f"no mark in the marks snippet may be conditioned on comparing two series' values -- "
            f"at a coincident point (measured live: 2026-09-07 has opened=closed=3) this would "
            f"silently drop one series' mark -- found: {offending!r}",
        )

    def test_opened_and_closed_each_have_their_own_marker_not_just_any_treatment(self):
        # Addendum 1 (architect, PT-92.md @ f1b76c6): 2026-09-07 is a
        # SINGLE shared vertex, not a run -- the paths cross rather than
        # overlap, so a dash gap is not guaranteed to fall exactly there.
        # "The markers carry that case, not the dashes." A series with a
        # dash pattern but no marker would pass the looser check this
        # file used before the spec landed, but NOT this one -- markers
        # specifically are required for the two series the measured
        # coincidence involves.
        source = _load_component_source()
        region = extract_marks_region(source)
        points = POINTS_ELEMENT_RE.findall(region)
        by_key = _elements_by_series_key(points)
        missing = [k for k in ("opened", "closed") if not _points_elements(by_key[k])]
        self.assertEqual(
            missing, [],
            f"'opened' and 'closed' must each have their own MARKER (not merely a dash pattern) "
            f"-- at a single-vertex coincidence a dash gap is not guaranteed to land there, so "
            f"the marker is what keeps them identifiable (addendum 1, f1b76c6) -- missing marker "
            f"for: {missing} (region: {region!r})",
        )


if __name__ == "__main__":
    unittest.main()
