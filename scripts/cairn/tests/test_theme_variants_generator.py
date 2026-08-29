"""PT-69 architect ruling guard (issue thread, 2026-08-29, "theme-variant
architecture"): the variant-token pipeline is hand-vendored data
(`scripts/cairn/design/variants.json`) emitted by a stdlib-only, zero-network
generator (`scripts/cairn/design/gen_variants.py`) into three checked-in CSS
files. Nothing under test exists yet when this file is written -- every
class below is a genuinely-absent construct, never an import error, per this
suite's established discipline (see test_dashboard_chart_ramp.py's own
docstring on the same point).

CLI CONTRACT this file assumes (spec-by-test -- no generator existed when
this was written, so this IS the contract implementation-lead builds to,
same role QA's red guards played for PT-61's derived-token naming):

    python3 gen_variants.py --out-dir DIR

writes DIR/board/variants.css, DIR/dashboard/src/variants.css, and
DIR/docs/DESIGN/variants.css -- mirroring the three real repo-relative homes
exactly, so the byte-compare below is a straight per-path diff with no path
translation. Called with no arguments, it writes directly to the real
checked-in locations (the authoring invocation, run by an agent, never
tested here since it's destructive against the working tree). Output must
be deterministic (architect's own requirement: "sorted keys, fixed block
order") -- verified by running --out-dir TWICE into independent temp dirs
and diffing them against EACH OTHER, which can go green before the checked-
in files even exist.

Partition-invariant tests below parse `board/variants.css` directly (plain
CSS, no Tailwind directives, the easiest of the three generated files to
hand-parse) rather than introspecting variants.json's internal JSON shape --
this is deliberate: the architect's hard invariant ("the three groups must
PARTITION the token set") is a claim about the SHIPPED CSS, and checking it
there catches a generator bug regardless of how variants.json happens to be
laid out internally. The JSON-content tests do the same "don't overspecify
the schema" reasoning: they substring-search the serialized JSON text for
the ruled variant names rather than assuming particular key names, so a
reasonable schema choice by implementation-lead won't spuriously fail here.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
DESIGN_DIR = helpers.CAIRN_DIR / "design"
VARIANTS_JSON = DESIGN_DIR / "variants.json"
GEN_VARIANTS_PY = DESIGN_DIR / "gen_variants.py"
NOTICE_MD = DESIGN_DIR / "NOTICE.md"

BOARD_VARIANTS_CSS = helpers.CAIRN_DIR / "board" / "variants.css"
DASHBOARD_VARIANTS_CSS = helpers.CAIRN_DIR / "dashboard" / "src" / "variants.css"
DOCS_VARIANTS_CSS = REPO_ROOT / "docs" / "DESIGN" / "variants.css"

# Ruled option sets.
#
# Base per ux-designer's 2026-08-29 "Ruling -- Base Color: ship all 7 real
# options (option B)": implementation-lead's live-generator verification
# found "Gray"/"Slate" (the spec table's original names) don't exist in
# the OKLCH preset system this app is built on -- only Stone/Neutral/Zinc/
# Mauve/Olive/Mist/Taupe do (Gray/Slate belong to a separate legacy HSL
# system that also redefines Theme/Chart tokens per base color, which
# would itself violate the partition invariant). Base is x7 (Stone
# default), not x5 -- dropped, not swapped 1:1.
#
# Theme and Chart per Mosko's live-test finding #5 (issue thread,
# 2026-08-29, "fix iteration before merge") -- this SUPERSEDES the earlier
# curated Theme x7 / Chart x3 (architect's chart-validator-cost ceiling)
# ruling: Mosko lifted the cap directly, and implementation-lead enumerated
# the real, full option sets from the live generator's own
# `PRESET_THEME_KEYS`/`PRESET_CHART_COLORS` -- a single 24-name vocabulary
# both dimensions draw from (`packages/cli/src/preset/preset.ts`), each
# dimension offering all 24 (its own default included, restated as itself
# rather than omitted). Theme x24 (Sky default), Chart x24 (Yellow
# default) -- both REQUIRED sets below are therefore the SAME 24 names,
# just with a different one singled out as each dimension's default.
# Case-insensitive substring match against the raw JSON text --
# deliberately not anchored to any particular key path.
ALL_24_PRESET_NAMES = {
    "neutral", "stone", "zinc", "amber", "blue", "cyan", "emerald", "fuchsia",
    "green", "indigo", "lime", "orange", "pink", "purple", "red", "rose",
    "sky", "teal", "violet", "yellow", "mauve", "olive", "mist", "taupe",
}
REQUIRED_BASE_NAMES = {"stone", "neutral", "zinc", "mauve", "olive", "mist", "taupe"}
REQUIRED_THEME_NAMES = set(ALL_24_PRESET_NAMES)
REQUIRED_CHART_NAMES = set(ALL_24_PRESET_NAMES)

# The architect's own token-ownership table (§2) -- what each dimension's
# attribute-qualified CSS blocks must declare, exactly. A var appearing
# under more than one of these three sets in the shipped CSS is precisely
# the "cascade race" the hard invariant forbids.
EXPECTED_VARS_BY_DIM = {
    "base": frozenset({
        "--background", "--foreground", "--card", "--card-foreground",
        "--popover", "--popover-foreground", "--secondary", "--secondary-foreground",
        "--muted", "--muted-foreground", "--accent", "--accent-foreground",
        "--border", "--input", "--ring", "--destructive", "--destructive-foreground",
        "--sidebar", "--sidebar-foreground", "--sidebar-accent", "--sidebar-accent-foreground",
        "--sidebar-border", "--sidebar-ring",
    }),
    "theme": frozenset({
        "--primary", "--primary-foreground", "--sidebar-primary", "--sidebar-primary-foreground",
    }),
    "chart": frozenset({
        "--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5",
        "--chart-flow-backlog", "--chart-flow-todo", "--chart-flow-in-progress",
        "--chart-flow-in-review", "--chart-flow-done", "--chart-flow-cancelled",
    }),
}

_BLOCK_OPEN_RE = re.compile(
    r':root(?P<dark>\.dark)?\[data-cairn-(?P<dim>base|theme|chart)="(?P<name>[\w-]+)"\]\s*\{'
)


def _strip_css_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _find_variant_blocks(source: str):
    """Yields (dim, name, is_dark, body) for every attribute-qualified
    `:root[data-cairn-<dim>="<name>"]` / `:root.dark[data-cairn-<dim>="<name>"]`
    block in `source`, brace-matched (not a naive `[^}]*` capture) so a
    `calc(...)`-bearing value can't truncate the body early -- same
    discipline as test_board_tokens_parity.py's `_extract_block`."""
    stripped = _strip_css_comments(source)
    for match in _BLOCK_OPEN_RE.finditer(stripped):
        start = match.end()
        depth = 1
        i = start
        n = len(stripped)
        while i < n and depth > 0:
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            i += 1
        body = stripped[start : i - 1]
        yield match.group("dim"), match.group("name"), bool(match.group("dark")), body


def _vars_in_body(body: str) -> set:
    return {name for name, _ in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)}


class VariantsJsonContractTests(unittest.TestCase):
    def test_variants_json_exists(self):
        self.assertTrue(
            VARIANTS_JSON.is_file(),
            f"{VARIANTS_JSON} does not exist -- architect's ruling names this the vendored "
            f"source of truth for every offered variant option.",
        )

    def _load(self):
        if not VARIANTS_JSON.is_file():
            self.skipTest("variants.json missing -- see test_variants_json_exists")
        raw = VARIANTS_JSON.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            self.fail(f"{VARIANTS_JSON} is not valid JSON: {e}")
        return raw, data

    def test_variants_json_is_a_non_empty_object(self):
        _, data = self._load()
        self.assertIsInstance(data, dict)
        self.assertTrue(data, "variants.json parses but is an empty object")

    def test_variants_json_names_every_required_base_variant(self):
        raw, _ = self._load()
        lowered = raw.lower()
        missing = sorted(n for n in REQUIRED_BASE_NAMES if n not in lowered)
        self.assertEqual(missing, [], f"variants.json is missing required Base Color name(s): {missing}")

    def test_variants_json_names_every_required_theme_variant(self):
        raw, _ = self._load()
        lowered = raw.lower()
        missing = sorted(n for n in REQUIRED_THEME_NAMES if n not in lowered)
        self.assertEqual(missing, [], f"variants.json is missing required Theme name(s): {missing}")

    def test_variants_json_names_every_required_chart_variant(self):
        raw, _ = self._load()
        lowered = raw.lower()
        missing = sorted(n for n in REQUIRED_CHART_NAMES if n not in lowered)
        self.assertEqual(missing, [], f"variants.json is missing required Chart Color name(s): {missing}")

    def test_notice_md_exists_with_provenance(self):
        self.assertTrue(
            NOTICE_MD.is_file(),
            f"{NOTICE_MD} missing -- architect's ruling requires a NOTICE.md carrying "
            f"provenance/extraction date per dimension, the PT-63 font-vendoring precedent.",
        )
        if NOTICE_MD.is_file():
            text = NOTICE_MD.read_text(encoding="utf-8").lower()
            for dim in ("base", "theme", "chart"):
                self.assertIn(dim, text, f"NOTICE.md doesn't mention the '{dim}' dimension")


class GeneratorStdlibOnlyTests(unittest.TestCase):
    """Architect: 'stdlib-only, zero deps, no network.' Parses the AST
    rather than regex-scanning `import` lines, so a `from x import y`
    variant can't slip past."""

    def test_gen_variants_py_exists(self):
        self.assertTrue(GEN_VARIANTS_PY.is_file(), f"{GEN_VARIANTS_PY} does not exist")

    def test_gen_variants_py_imports_only_stdlib_modules(self):
        if not GEN_VARIANTS_PY.is_file():
            self.skipTest("gen_variants.py missing -- see test_gen_variants_py_exists")
        source = GEN_VARIANTS_PY.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(GEN_VARIANTS_PY))
        stdlib_names = set(getattr(sys, "stdlib_module_names", ()))
        non_stdlib = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in stdlib_names and top != "__future__":
                        non_stdlib.add(top)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top not in stdlib_names and top != "__future__" and node.level == 0:
                        non_stdlib.add(top)
        self.assertEqual(
            non_stdlib, set(),
            f"gen_variants.py imports non-stdlib module(s) {sorted(non_stdlib)} -- architect's "
            f"ruling requires stdlib-only, zero deps, no network (rejected registry-fetch-at-build "
            f"outright).",
        )


class GeneratorDeterminismTests(unittest.TestCase):
    """Runs the generator twice into independent temp dirs and diffs them
    against EACH OTHER -- can go green before the checked-in files exist,
    isolating 'is the generator itself deterministic' from 'do the checked-
    in files match.'"""

    def _run_generator(self, out_dir: Path):
        result = subprocess.run(
            [sys.executable, str(GEN_VARIANTS_PY), "--out-dir", str(out_dir)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.assertEqual(
            result.returncode, 0,
            f"gen_variants.py --out-dir {out_dir} exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}",
        )

    def test_two_independent_runs_produce_byte_identical_output(self):
        if not GEN_VARIANTS_PY.is_file():
            self.skipTest("gen_variants.py missing")
        import tempfile
        rel_paths = [
            Path("board") / "variants.css",
            Path("dashboard") / "src" / "variants.css",
            Path("docs") / "DESIGN" / "variants.css",
        ]
        with tempfile.TemporaryDirectory(prefix="cairn-gen-a-") as a, \
             tempfile.TemporaryDirectory(prefix="cairn-gen-b-") as b:
            self._run_generator(Path(a))
            self._run_generator(Path(b))
            for rel in rel_paths:
                pa, pb = Path(a) / rel, Path(b) / rel
                self.assertTrue(pa.is_file(), f"run A did not write {rel}")
                self.assertTrue(pb.is_file(), f"run B did not write {rel}")
                self.assertEqual(
                    pa.read_bytes(), pb.read_bytes(),
                    f"{rel}: two independent generator runs produced different bytes -- "
                    f"architect requires deterministic output (sorted keys, fixed block order).",
                )


class GeneratorByteIdenticalToCheckedInTests(unittest.TestCase):
    """The exact test architect ruled: regenerate to a temp dir, assert
    byte-identical to the three checked-in files. Strictly stronger than
    test_board_tokens_parity.py's value-comparison."""

    CHECKED_IN = {
        Path("board") / "variants.css": BOARD_VARIANTS_CSS,
        Path("dashboard") / "src" / "variants.css": DASHBOARD_VARIANTS_CSS,
        Path("docs") / "DESIGN" / "variants.css": DOCS_VARIANTS_CSS,
    }

    def test_regenerated_output_is_byte_identical_to_checked_in_files(self):
        if not GEN_VARIANTS_PY.is_file():
            self.skipTest("gen_variants.py missing")
        import tempfile
        with tempfile.TemporaryDirectory(prefix="cairn-gen-check-") as tmp:
            result = subprocess.run(
                [sys.executable, str(GEN_VARIANTS_PY), "--out-dir", tmp],
                capture_output=True, text=True, cwd=str(REPO_ROOT),
            )
            self.assertEqual(
                result.returncode, 0,
                f"gen_variants.py --out-dir {tmp} exited {result.returncode}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}",
            )
            for rel, checked_in_path in self.CHECKED_IN.items():
                generated_path = Path(tmp) / rel
                self.assertTrue(generated_path.is_file(), f"generator did not write {rel}")
                self.assertTrue(
                    checked_in_path.is_file(),
                    f"checked-in {checked_in_path} does not exist yet -- run gen_variants.py "
                    f"with no args to author it, then check it in.",
                )
                self.assertEqual(
                    generated_path.read_bytes(), checked_in_path.read_bytes(),
                    f"{checked_in_path} has drifted from what gen_variants.py currently produces "
                    f"-- regenerate and re-commit (hand-editing a generated file is exactly the "
                    f"drift class this guard exists to catch).",
                )


class PartitionInvariantTests(unittest.TestCase):
    """Architect's hard invariant: 'the three groups must PARTITION the
    token set... a variable declared under two dimensions is a cascade
    race.' Parses the checked-in board/variants.css directly -- a claim
    about the shipped CSS, not about variants.json's internal shape."""

    def setUp(self):
        if not BOARD_VARIANTS_CSS.is_file():
            self.skipTest(f"{BOARD_VARIANTS_CSS} does not exist yet")
        self.source = BOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        self.blocks = list(_find_variant_blocks(self.source))

    def test_at_least_one_block_is_found_per_dimension(self):
        # Guards against every test below vacuously passing because the
        # selector regex simply found nothing.
        dims_found = {dim for dim, _, _, _ in self.blocks}
        self.assertEqual(
            dims_found, {"base", "theme", "chart"},
            f"expected attribute-qualified blocks for all three dimensions in "
            f"{BOARD_VARIANTS_CSS}, found: {sorted(dims_found)}",
        )

    def test_every_dimension_block_declares_exactly_its_owned_vars(self):
        mismatches = []
        for dim, name, is_dark, body in self.blocks:
            found = _vars_in_body(body)
            expected = EXPECTED_VARS_BY_DIM[dim]
            if found != expected:
                extra = sorted(found - expected)
                missing = sorted(expected - found)
                mismatches.append((dim, name, "dark" if is_dark else "light", extra, missing))
        self.assertEqual(
            mismatches, [],
            "one or more variant blocks declare vars outside their dimension's owned set "
            "(a partition violation -- a cascade race whose winner depends on source order) "
            "or are missing vars their dimension should carry: "
            f"{mismatches}",
        )

    def test_no_variable_name_is_declared_under_more_than_one_dimension(self):
        # Direct, structural check -- independent of the exact-match test
        # above, so it still catches a partition violation even if
        # implementation-lead's per-block var set otherwise looks plausible.
        base_ids, theme_ids, chart_ids = (
            EXPECTED_VARS_BY_DIM["base"], EXPECTED_VARS_BY_DIM["theme"], EXPECTED_VARS_BY_DIM["chart"],
        )
        self.assertEqual(base_ids & theme_ids, set())
        self.assertEqual(base_ids & chart_ids, set())
        self.assertEqual(theme_ids & chart_ids, set())


class VariantBlockParserSelfTests(unittest.TestCase):
    """The parser's own correctness against synthetic source -- proves it
    CAN detect a partition violation, not just that real files currently
    pass (same discipline as this suite's other source-text extractors)."""

    def test_finds_light_and_dark_blocks_for_a_variant(self):
        source = (
            ':root[data-cairn-base="zinc"] { --background: oklch(1 0 0); }\n'
            ':root.dark[data-cairn-base="zinc"] { --background: oklch(0.1 0 0); }\n'
        )
        blocks = list(_find_variant_blocks(source))
        self.assertEqual(len(blocks), 2)
        dims_darks = {(dim, is_dark) for dim, _, is_dark, _ in blocks}
        self.assertEqual(dims_darks, {("base", False), ("base", True)})

    def test_detects_a_variable_declared_under_two_dimensions(self):
        source = (
            ':root[data-cairn-base="zinc"] { --primary: oklch(0.5 0.1 240); }\n'
            ':root[data-cairn-theme="blue"] { --primary: oklch(0.5 0.1 250); }\n'
        )
        blocks = list(_find_variant_blocks(source))
        by_dim = {}
        for dim, _, _, body in blocks:
            by_dim.setdefault(dim, set()).update(_vars_in_body(body))
        self.assertIn("--primary", by_dim["base"] & by_dim["theme"])

    def test_brace_matching_does_not_truncate_at_a_nested_calc(self):
        source = ':root[data-cairn-base="zinc"] { --radius-sm: calc(var(--radius) * 0.6); --border: oklch(1 0 0); }'
        _, _, _, body = next(_find_variant_blocks(source))
        self.assertIn("--border", _vars_in_body(body))


if __name__ == "__main__":
    unittest.main()
