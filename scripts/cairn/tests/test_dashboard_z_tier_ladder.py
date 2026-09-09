"""PT-114 gate-1 ruling (architect, process/cairn/issues/PT-114.md @
f7869cd): the dashboard's z-tier ladder -- content `z-auto` (inside an
`isolate` page-root child, PT-117) < sidebar container `z-10` < sidebar
rail `z-20` < header `z-40` (PT-110) < portal'd floating overlays `z-50`
(the `[data-bits-floating-content-wrapper]` floor, PT-110 verdict delta
2) -- recorded in docs/DESIGN/design-system-spec.md, plus four
structural guards so the doc and the code cannot drift silently.

The subtlety the spec (and this file's own comments) must carry: two
different things wear `z-50`. PORTAL'D overlays (popover/dropdown/
select/tooltip/sheet) escape every `isolate` because bits-ui re-parents
them to `<body>` -- they need the app.css floor. IN-CONTENT library
overlays (LayerChart's chart tooltips) do NOT escape; a `z-50` inside an
`isolate` block is a LOCAL 50, not a global one, and is safe only
because PT-117 isolated its ancestor. Guard 2 below does not (and
cannot) tell these apart from source alone -- both are `<= 50` and pass
without needing a ladder comment; only a value ABOVE 50 requires one.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import helpers  # noqa: F401

DASHBOARD_SRC = helpers.CAIRN_DIR / "dashboard" / "src"
DASHBOARD_APP_SVELTE = DASHBOARD_SRC / "App.svelte"
APP_CSS = DASHBOARD_SRC / "app.css"
SIDEBAR_SVELTE = DASHBOARD_SRC / "lib" / "components" / "ui" / "sidebar" / "sidebar.svelte"
SIDEBAR_RAIL_SVELTE = DASHBOARD_SRC / "lib" / "components" / "ui" / "sidebar" / "sidebar-rail.svelte"
REPO_ROOT = helpers.CAIRN_DIR.parent.parent  # scripts/cairn -> scripts -> repo root
DESIGN_SPEC = REPO_ROOT / "docs" / "DESIGN" / "design-system-spec.md"


def _strip_html_comments(source: str) -> str:
    return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)


def _strip_css_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


# ------------------------------------------------------------- guard 1

_TAG_RE = re.compile(r"<(/?)([A-Za-z][\w.:-]*)((?:\"[^\"]*\"|'[^']*'|[^>])*?)(/?)>")
_PAGE_ROOT_OPEN_RE = re.compile(r'<div class="flex min-h-screen flex-col gap-6 bg-muted px-7 py-7">')


def page_root_direct_children(source: str):
    """Structural scan, not text position: from the page-root div's own
    opening tag, walk the tag stream tracking nesting DEPTH, so a Svelte
    `{#if}/{:else}/{/if}` (no tag of its own -- transparent to depth)
    never hides a child, and an element nested INSIDE a child is never
    mistaken for a second direct one. Returns [(tag_name,
    opening_tag_text), ...] for every element opened at depth 1, in
    document order, stopping at the root's own matching close. Comments
    are stripped first so a `<div>` mentioned in one can never appear as
    a phantom child."""
    source = _strip_html_comments(source)
    root_match = _PAGE_ROOT_OPEN_RE.search(source)
    if root_match is None:
        return []
    i = root_match.end()
    depth = 1
    stack: list[str] = []
    children = []
    while i < len(source):
        m = _TAG_RE.search(source, i)
        if not m:
            break
        closing, name, _attrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
                depth -= 1
                if depth == 0:
                    break
            elif stack:
                stack.pop()
                depth -= 1
            i = m.end()
            continue
        if selfclose:
            if depth == 1:
                children.append((name, m.group(0)))
            i = m.end()
            continue
        if depth == 1:
            children.append((name, m.group(0)))
        stack.append(name)
        depth += 1
        i = m.end()
    return children


def _classes_in_tag(tag_text: str) -> set[str]:
    m = re.search(r'class="([^"]*)"', tag_text)
    return set(m.group(1).split()) if m else set()


class PageRootChildrenAreAllIsolatedTests(unittest.TestCase):
    """Guard 1: every non-`<header>` direct child of the page root
    carries `isolate` -- derived structurally, never a hard-coded count
    of three. A scan that silently finds zero children must fail, not
    pass (a stale/changed page-root anchor is a broken test, not a
    green one)."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = DASHBOARD_APP_SVELTE.read_text(encoding="utf-8")
        self.children = page_root_direct_children(self.source)

    def test_the_scan_finds_at_least_one_child(self):
        self.assertGreaterEqual(
            len(self.children), 1,
            f"{DASHBOARD_APP_SVELTE}: found zero page-root children -- the page-root anchor "
            f"or the tag walker is broken, this is not a pass",
        )

    def test_every_non_header_child_is_isolated(self):
        non_header = [(name, tag) for name, tag in self.children if name != "header"]
        self.assertGreaterEqual(
            len(non_header), 1,
            f"found children {self.children!r} but none is a non-header sibling -- suspicious",
        )
        for name, tag in non_header:
            with self.subTest(tag=tag):
                self.assertIn(
                    "isolate", _classes_in_tag(tag),
                    f"page-root child <{name}> must carry `isolate` (PT-117) -- got tag={tag!r}",
                )

    def test_exactly_one_header_child(self):
        headers = [name for name, _tag in self.children if name == "header"]
        self.assertEqual(len(headers), 1, f"expected exactly one <header> direct child -- got {self.children!r}")


# ------------------------------------------------------------- guard 2

_Z_CLASS_RE = re.compile(r"\bz-(\d+)\b")
_Z_ARBITRARY_RE = re.compile(r"\bz-\[(\d+)\]")
_Z_INDEX_RAW_RE = re.compile(r"\bz-index\s*:\s*(\d+)")


def lines_with_z_above_50(text: str):
    """Yields (line_no, value) for every z-token (Tailwind `z-<n>`,
    arbitrary `z-[<n>]`, or raw CSS `z-index: <n>`) whose value exceeds
    50, scanning line by line so the "line above" rule in
    `has_ladder_comment` is well defined."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for rx in (_Z_CLASS_RE, _Z_ARBITRARY_RE, _Z_INDEX_RAW_RE):
            for m in rx.finditer(line):
                value = int(m.group(1))
                if value > 50:
                    yield i, value


def has_ladder_comment(lines: list[str], line_no: int) -> bool:
    candidates = [lines[line_no]]
    if line_no > 0:
        candidates.append(lines[line_no - 1])
    return any("ladder" in c.lower() for c in candidates)


class NoRungAboveFiftyWithoutALadderCommentTests(unittest.TestCase):
    """Guard 2: nothing in `src/` declares a z-index (Tailwind class,
    arbitrary value, or raw CSS) above 50 without a comment naming the
    ladder on that line or the one above. Measured (gate-1 ruling):
    nothing in `src/` is above 50 today, so this is a floor against
    future drift, not a fix. Includes a control proving the scan
    function itself can actually fail."""

    def test_no_z_above_50_in_dashboard_src_without_a_ladder_comment(self):
        offenders = []
        for path in sorted(DASHBOARD_SRC.rglob("*")):
            if not path.is_file() or path.suffix not in (".svelte", ".css"):
                continue
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            for line_no, value in lines_with_z_above_50(text):
                if not has_ladder_comment(lines, line_no):
                    offenders.append((str(path), line_no + 1, value, lines[line_no].strip()))
        self.assertEqual(
            offenders, [],
            f"z-index above 50 with no comment naming the ladder (PT-114.md @f7869cd): {offenders!r}",
        )

    def test_the_scan_can_actually_fail_on_a_synthetic_violation(self):
        synthetic = 'class="something z-[60] more"\n'
        offenders = list(lines_with_z_above_50(synthetic))
        self.assertTrue(offenders, "the scan must detect a synthetic z-[60]")
        line_no, value = offenders[0]
        self.assertEqual(value, 60)
        self.assertFalse(
            has_ladder_comment(synthetic.splitlines(), line_no),
            "no ladder-naming comment is present -- this synthetic case must NOT be excused",
        )

    def test_a_ladder_naming_comment_on_the_line_above_excuses_it(self):
        synthetic = "<!-- ladder: local escape hatch, see spec -->\nclass=\"something z-[60] more\"\n"
        lines = synthetic.splitlines()
        offenders = list(lines_with_z_above_50(synthetic))
        self.assertTrue(offenders)
        line_no, _value = offenders[0]
        self.assertTrue(has_ladder_comment(lines, line_no), "a ladder-naming comment on the line above must excuse it")


# ------------------------------------------------------------- guard 3

class RungsArePinnedToSourceTests(unittest.TestCase):
    """Guard 3: the ladder's five rungs, pinned directly to their
    measured source locations (PT-114.md @f7869cd's own table) -- drift
    in either direction trips this, so the spec's table stops being a
    claim about the past."""

    def test_header_is_z_40(self):
        source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))
        match = re.search(r'<header\b[^>]*\bclass="([^"]*)"', source)
        self.assertIsNotNone(match, f"{DASHBOARD_APP_SVELTE}: no <header class=\"...\"> found")
        classes = set(match.group(1).split())
        self.assertIn("z-40", classes, f"header must carry z-40 -- got {sorted(classes)}")

    def test_the_floating_wrapper_floor_is_50(self):
        stripped = _strip_css_comments(APP_CSS.read_text(encoding="utf-8"))
        match = re.search(r"\[data-bits-floating-content-wrapper\]\s*\{", stripped)
        self.assertIsNotNone(match, f"{APP_CSS}: no [data-bits-floating-content-wrapper] rule found")
        depth, i, n = 1, match.end(), len(stripped)
        while i < n and depth > 0:
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            i += 1
        body = stripped[match.end() : i - 1]
        self.assertRegex(body, r"z-index\s*:\s*50\s*;", f"{APP_CSS}: floor rule body must set z-index: 50 -- got {body!r}")

    def test_sidebar_container_is_z_10(self):
        self.assertTrue(SIDEBAR_SVELTE.is_file(), f"{SIDEBAR_SVELTE} does not exist")
        source = SIDEBAR_SVELTE.read_text(encoding="utf-8")
        self.assertRegex(source, r"\bz-10\b", f"{SIDEBAR_SVELTE}: sidebar container must carry z-10")

    def test_sidebar_rail_is_z_20(self):
        self.assertTrue(SIDEBAR_RAIL_SVELTE.is_file(), f"{SIDEBAR_RAIL_SVELTE} does not exist")
        source = SIDEBAR_RAIL_SVELTE.read_text(encoding="utf-8")
        self.assertRegex(source, r"\bz-20\b", f"{SIDEBAR_RAIL_SVELTE}: sidebar rail must carry z-20 (measured -- NOT z-10)")


# ------------------------------------------------------------- guard 4

class StackingOrderSpecPresenceTests(unittest.TestCase):
    """Guard 4: `### Stacking order (z-tier ladder)` exists under
    `## Unified shell (PT-72)` in the design spec and names all five
    rungs -- red until ux-designer's spec commit lands. Writer:
    ux-designer."""

    def setUp(self):
        self.assertTrue(DESIGN_SPEC.is_file(), f"{DESIGN_SPEC} does not exist")
        self.text = DESIGN_SPEC.read_text(encoding="utf-8")

    def _unified_shell_section(self) -> str:
        m = re.search(r"^## Unified shell \(PT-72\)\s*$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, f"{DESIGN_SPEC}: no '## Unified shell (PT-72)' section found")
        rest = self.text[m.end():]
        next_h2 = re.search(r"^## ", rest, re.MULTILINE)
        return rest[: next_h2.start()] if next_h2 else rest

    def test_stacking_order_subsection_exists_under_unified_shell(self):
        section = self._unified_shell_section()
        self.assertTrue(
            re.search(r"^### Stacking order \(z-tier ladder\)\s*$", section, re.MULTILINE),
            f"{DESIGN_SPEC}: no '### Stacking order (z-tier ladder)' subsection found under Unified shell",
        )

    def test_all_five_rungs_are_named(self):
        section = self._unified_shell_section()
        m = re.search(r"^### Stacking order \(z-tier ladder\)\s*$", section, re.MULTILINE)
        self.assertIsNotNone(m, f"{DESIGN_SPEC}: no Stacking order subsection to check rungs in")
        rest = section[m.end():]
        next_h3 = re.search(r"^### ", rest, re.MULTILINE)
        subsection = rest[: next_h3.start()] if next_h3 else rest
        for rung in ("z-auto", "z-10", "z-20", "z-40", "z-50"):
            with self.subTest(rung=rung):
                self.assertIn(rung, subsection, f"Stacking order subsection must name rung {rung!r}")


if __name__ == "__main__":
    unittest.main()
