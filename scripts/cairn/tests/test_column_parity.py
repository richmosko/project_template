"""PT-36 (architect's ruling @ 49174b7): a cross-language drift GUARD, not a
red-then-green feature test in the usual sense. `DEFAULT_COLUMNS` (cairn.py)
and `BOARD_COLUMNS` (board-logic.js) are the same list maintained in two
languages, with no shared-code seam across them (a build step is explicitly
rejected -- see the ruling's § 1) -- this file is the thing that fails loudly
if they ever drift, by reading board-logic.js AS TEXT and comparing the
extracted literals against cairn's own values.

Lives in the Python suite specifically (JC1): Python is the hard test gate
(`finish-feature/SKILL.md` runs it unconditionally; the JS suite only runs
`if command -v node` -- TEMPLATE_DECISIONS.md, 2026-08-20), so a guard here
catches drift regardless of which language's file changed, and regardless of
whether the editor has Node installed. Reading the JS as text rather than
shelling out to `node` is the load-bearing half of that call -- executing it
would make Node a hard prerequisite of the Python suite, silently reversing
that recorded decision. Cost, stated in the ruling: this guard compares
SOURCE LITERALS, not evaluated values, so it can't see through a future
dynamic construction of the list -- which is exactly what the extractor's
own fail-loudly contract (§ 3.3, tested directly below) exists to catch: if
the regex ever stops matching a real declaration, the guard must error, not
silently pass.

Mixed red/green is expected and correct here, not a bug in how these tests
were written: tests 1, 3, and 4 below assert either an already-true fact
(BOARD_COLUMNS already equals DEFAULT_COLUMNS today, unchanged by PT-36) or
the extractor's own self-contained correctness against synthetic source
strings -- both pass immediately. Tests 2, 5, and 6 need `cairn.STATUS_ORDER`
(implementation-lead's PT-36 Part A addition to cairn.py, collapsing the
Python-side triplicate append rule) and are expected to fail with
AttributeError until that lands.

NOT edited here: tests/test_snapshot.py. Its local `STATUS_ORDER = list(
cairn.DEFAULT_COLUMNS) + ["cancelled"]` (line 33) is meant to become
`STATUS_ORDER = cairn.STATUS_ORDER` once Part A lands (the ruling's JC5-style
gate: single-sourcing only, no expected value may change) -- but that edit
has a hard dependency `test_snapshot.py`'s threading edit in PT-35 didn't:
`cairn.STATUS_ORDER` doesn't exist yet, and a module-level `cairn.STATUS_ORDER`
reference in an ALREADY-GREEN file would raise AttributeError at IMPORT time,
erroring every test in that file, not just new coverage -- unlike PT-35's JS
threading, where an extra function argument was silently ignored by the old
single-arg implementation and every existing test stayed green through the
edit. Deferred to Validate, once implementation-lead's Part A lands, so that
edit can be reviewed as the true single-sourcing-only diff the gate requires
rather than committed pre-emptively as a guaranteed collection failure.
"""
from __future__ import annotations

import json
import re
import unittest

import helpers  # noqa: F401

import cairn

BOARD_LOGIC_PATH = helpers.CAIRN_DIR / "board" / "board-logic.js"


class ExtractionError(AssertionError):
    """Raised when a required declaration can't be found in JS source text.

    A plain AssertionError subclass (not a bare `return None`/`[]`) so a
    caller that forgets to check for it still sees a loud, named failure --
    the ruling's § 3.3 requirement made structural: there is no code path in
    which "the pattern didn't match" silently becomes "compare empty to
    empty and pass".
    """


def _extract_json_array(source, pattern, description):
    match = re.search(pattern, source)
    if not match:
        raise ExtractionError(
            f"could not find {description} in the given source -- "
            f"pattern {pattern!r} did not match. If this declaration was "
            f"renamed or restructured, this guard needs to be updated, not "
            f"silenced."
        )
    return json.loads(match.group(1))


def extract_board_columns(source):
    """The array literal from `var BOARD_COLUMNS = [...]`.

    Anchored on the declaration itself (ruling § 3: "not a bare bracket
    search that could match any array in the file") -- `board-logic.js` has
    several other array literals (BOARD_COLUMNS's own six-column companion
    inside boardColumns, laneSummary's byStatus construction, etc.); a
    generic `\\[[^\\]]*\\]` search could silently latch onto any of them.
    """
    return _extract_json_array(
        source,
        r"var\s+BOARD_COLUMNS\s*=\s*(\[[^\]]*\])",
        "the `var BOARD_COLUMNS = [...]` declaration",
    )


def extract_cancelled_append(source):
    """The array literal appended inside `boardColumns`'s `.concat([...])`.

    Anchored on `BOARD_COLUMNS.concat(...)` specifically -- the append RULE
    PT-35 introduced and PT-36 exists to guard, not just the base list (a
    guard on the base list alone would leave the actual duplicated rule free
    to drift, per the ruling's § 3 item 2).
    """
    return _extract_json_array(
        source,
        r"BOARD_COLUMNS\.concat\((\[[^\]]*\])\)",
        "the `BOARD_COLUMNS.concat([...])` append literal inside boardColumns",
    )


class ColumnParityTests(unittest.TestCase):
    """Reds 1, 2: the real guard, against the actual board-logic.js file."""

    def setUp(self):
        self.source = BOARD_LOGIC_PATH.read_text(encoding="utf-8")

    def test_1_js_board_columns_matches_python_default_columns(self):
        js_columns = extract_board_columns(self.source)
        self.assertEqual(
            js_columns,
            list(cairn.DEFAULT_COLUMNS),
            "board-logic.js's BOARD_COLUMNS and cairn.py's DEFAULT_COLUMNS "
            "must be the same five columns in the same order",
        )

    def test_2_js_cancelled_append_composes_to_python_status_order(self):
        js_columns = extract_board_columns(self.source)
        appended = extract_cancelled_append(self.source)
        composed = js_columns + appended
        self.assertEqual(
            composed,
            list(cairn.STATUS_ORDER),
            "BOARD_COLUMNS.concat([...]) composed must equal cairn.STATUS_ORDER "
            "-- the APPEND RULE is what PT-35 actually duplicated, not just "
            "the base list",
        )


class ExtractorSelfTests(unittest.TestCase):
    """Reds 3, 4: the extractor's own correctness, against synthetic source
    strings -- independent of the real board-logic.js file or cairn.py, so
    these prove the guard mechanism CAN fail, not just that it currently
    doesn't (ruling § 3.3's explicit requirement)."""

    def test_3_negative_control_extractor_reports_a_real_mismatch(self):
        # Without this, a parity check that always reports "equal" would
        # look identical to one that actually compares anything.
        fake_source = 'var BOARD_COLUMNS = ["backlog", "todo", "done"];'
        js_columns = extract_board_columns(fake_source)
        self.assertNotEqual(
            js_columns,
            list(cairn.DEFAULT_COLUMNS),
            "sanity: this fixture is deliberately wrong and must be caught as such",
        )

    def test_4_missing_declaration_raises_loudly_naming_the_symbol(self):
        # No `BOARD_COLUMNS` anywhere in this source -- the extractor must
        # raise, not return None/[] and let a caller quietly compare empty
        # to empty and report success. This is the case a renamed or
        # restructured declaration produces for real.
        fake_source = "var SOME_OTHER_CONSTANT = [1, 2, 3];\nfunction noop() {}\n"
        with self.assertRaises(ExtractionError) as ctx:
            extract_board_columns(fake_source)
        self.assertIn(
            "BOARD_COLUMNS",
            str(ctx.exception),
            "the raised error must NAME the symbol it was looking for, per the ruling's own wording",
        )

    def test_4b_missing_append_literal_also_raises_loudly(self):
        fake_source = 'var BOARD_COLUMNS = ["a", "b"];\nfunction boardColumns() { return BOARD_COLUMNS; }\n'
        with self.assertRaises(ExtractionError) as ctx:
            extract_cancelled_append(fake_source)
        self.assertIn("concat", str(ctx.exception))


class StatusOrderTests(unittest.TestCase):
    """Reds 5, 6: cairn.STATUS_ORDER's own contract (Part A of the ruling --
    implementation-lead's collapse of the THREE Python-side copies of the
    append rule into one). Expected to fail with AttributeError until that
    lands."""

    def test_5_status_order_exact_value_cancelled_last(self):
        self.assertEqual(
            list(cairn.STATUS_ORDER),
            ["backlog", "todo", "in-progress", "in-review", "done", "cancelled"],
            "a rename or reorder of STATUS_ORDER must break this test",
        )

    def test_6_status_order_is_not_an_alias_of_default_columns(self):
        # DEFAULT_COLUMNS + [...] builds a NEW list (ruling § 2's own
        # reasoning) -- mutating STATUS_ORDER must not touch DEFAULT_COLUMNS.
        # addCleanup restores STATUS_ORDER's contents in place regardless of
        # outcome, so this test can't leak a mutated shared module list into
        # any other test in the suite (order-independence, per this suite's
        # existing fixture-isolation convention in helpers.py).
        original_default = list(cairn.DEFAULT_COLUMNS)
        original_status_order = list(cairn.STATUS_ORDER)

        def _restore():
            cairn.STATUS_ORDER[:] = original_status_order

        self.addCleanup(_restore)

        cairn.STATUS_ORDER.append("MUTATED-FOR-TEST-DO-NOT-LEAK")

        self.assertEqual(
            list(cairn.DEFAULT_COLUMNS),
            original_default,
            "mutating cairn.STATUS_ORDER must not affect cairn.DEFAULT_COLUMNS -- "
            "STATUS_ORDER must be a fresh list, never an alias",
        )


if __name__ == "__main__":
    unittest.main()
