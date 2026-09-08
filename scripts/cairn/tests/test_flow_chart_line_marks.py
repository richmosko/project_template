"""PT-92 gate-1 ruling (architect, process/cairn/issues/PT-92.md @
15fe9b6, item (c)): red tests 2-4. Test 1 (the existing distinctness
guard, `test_flow_series_distinctness.py`, re-run against ux-designer's
FINAL token values) is deferred -- it waits on ux-designer's decision
commit landing on this branch (architect, verbatim: "Test 1 waits on
ux-designer's values landing on the branch"). That file needs no code
changes for this ticket; its own hue-floor math already fails a
same-value mutation (distance 0 < the 60-degree floor), so re-running it
once the final values land is the whole job.

**Assumed seam** (the ruling fixes the OUTCOME -- no Bars, each series
individually identifiable via a marker or dash pattern -- not the exact
Svelte shape; flag to the architect/implementation-lead/ux-designer if
the real shape diverges): three `<Spline>` (or `<Points>`-companioned)
marks inside the `marks` snippet, one per opened/closed/wip -- ruling
item (a), verbatim: "three Splines on the same scale is the existing
arrangement generalised, not a new rendering path" (the WIP Spline
already there is the precedent). Each carries `stroke={SERIES_COLOR.
<key>}` (or a bracket-form equivalent) plus ONE of: a dash-pattern prop
(`stroke-dasharray`/`strokeDasharray`, or a `class` naming "dash") or a
companion per-series `<Points seriesKey="...">` marker mark. ux-designer
picks which per the ruling's own framing ("the mechanism is ux-
designer's call") -- this file accepts EITHER, checked independently
per series, so it does not prescribe one treatment over the other.

Nothing under test exists in its final form yet: IssueFlowChart.svelte
still renders opened/closed as grouped `<Bars>` (test 2's own subject,
L229) -- every red test below is expected to fail loudly on that shape,
not silently skip."""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401
from test_flow_series_distinctness import FLOW_CHART_SVELTE, _series_color_tokens  # noqa: F401

FLOW_CHART_LOGIC_TS = helpers.CAIRN_DIR / "dashboard" / "src" / "lib" / "flow-chart-logic.ts"

MARKS_START_RE = re.compile(r"\{#snippet marks\(\{\s*context\s*\}\)\}")
MARKS_END_MARKER = "{#snippet tooltip()}"
LEGEND_ITEMS_START_RE = re.compile(r"legendItems\s*=\s*\[")
SPLINE_ELEMENT_RE = re.compile(r"<Spline\b.*?/>", re.DOTALL)
POINTS_ELEMENT_RE = re.compile(r"<Points\b.*?/>", re.DOTALL)

SERIES_KEYS = ("opened", "closed", "wip")


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
    """Ruling item (c)(2), second half: each series declares the chosen
    distinguishability property (marker or dash) -- the mechanism is
    ux-designer's call (PT-92.md @ 15fe9b6: per-series point markers or
    per-series dash patterns; NOT draw-order/opacity, NOT a vertical
    offset). Checked per series independently -- a series with neither
    fails, regardless of whether its SIBLINGS have one."""

    def test_each_series_has_its_own_line_mark_and_a_distinguishing_treatment(self):
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

        missing_treatment = [k for k in SERIES_KEYS if not _has_distinguishing_treatment(by_key[k])]
        self.assertEqual(
            missing_treatment, [],
            f"every flow series must declare a distinguishing treatment beyond color -- a dash "
            f"pattern or a companion Points marker (this test accepts either; ux-designer picks "
            f"which) -- missing for: {missing_treatment} (marks region: {region!r})",
        )


class LegendAndCaptionNameAllThreeSeriesTests(unittest.TestCase):
    """Ruling item (c)(3). Mutation: drop one from the legend list."""

    def test_legend_items_list_all_three_series_keys(self):
        source = _load_component_source()
        region = extract_legend_items_region(source)
        missing = [k for k in SERIES_KEYS if not re.search(rf"key\s*:\s*['\"]{k}['\"]", region)]
        self.assertEqual(
            missing, [],
            f"legendItems must list all three series -- missing: {missing} (region: {region!r})",
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

    def test_opened_and_closed_each_have_an_independent_mark_with_a_distinguishing_treatment(self):
        # Same structural claim as the general per-series test above,
        # scoped explicitly to the two series the measured coincidence
        # involves -- grounding this feature's own motivating defect in
        # the mark-set check directly, not just inheriting it implicitly.
        source = _load_component_source()
        region = extract_marks_region(source)
        splines = SPLINE_ELEMENT_RE.findall(region)
        points = POINTS_ELEMENT_RE.findall(region)
        by_key = _elements_by_series_key(splines + points)
        for key in ("opened", "closed"):
            with self.subTest(series=key):
                elements = by_key[key]
                self.assertTrue(elements, f"'{key}' must have its own mark in the mark set (region: {region!r})")
                self.assertTrue(
                    _has_distinguishing_treatment(elements),
                    f"'{key}' must declare a distinguishing treatment (marker or dash), so it "
                    f"remains identifiable even when its value coincides with another series' -- "
                    f"got {elements!r}",
                )


if __name__ == "__main__":
    unittest.main()
