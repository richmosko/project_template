"""PT-83 gate 2 (qa-engineer), pinned to the architect's gate-1 ruling
(process/cairn/issues/PT-83.md @ 0c79168 -- item (d)/(f)(5)): the JS test
runner's canonical command is
`node --test "scripts/cairn/tests/js/**/*.test.js"` (quoted, so node --
not the shell -- expands the glob, measured rc 0/458 pass at node
26.7.0). No ratified text may still name `node --test` on a bare,
glob-less argument -- a directory positional or any other un-globbed
path: node 26.7.0 resolves that as a MODULE ENTRY POINT, never a
discovery root (measured: `Cannot find module '.../tests/js'`,
`MODULE_NOT_FOUND`, rc 1). Naming that form anywhere a teammate might
copy-paste it is a live footgun, not a style nit -- renaming
`scripts/cairn/tests/js/helpers.js` fixes nothing and is explicitly
out of scope (ruling item (d)); this test never reads that file.

Scope: the three files the ruling (addendum 1) names as recording this
command -- `.claude/skills/finish-feature/SKILL.md` (the finish-feature
gate), `scripts/cairn/tests/js/INTERFACE.md` (`## Running the suite`),
and `process/WORKFLOW.md` (the tiered-gating bullet's new JS-suite
sentence) -- not the full PT-99 33-file ratified-text set
(`test_gate_leg_naming.py`'s own scope) as a whole, since this predicate
(a bare-directory `node --test` argument) is JS-runner-specific, not
general agent-facing prose. WORKFLOW.md happens to already sit inside
that 33-file set for PT-99's own (unrelated) `unittest`-token predicate;
that's incidental overlap, not a reason to skip listing it here too --
this file's predicate is different and needs its own explicit scope.

Red at HEAD (measured): `scripts/cairn/tests/js/INTERFACE.md:197` carries
`` `node --test scripts/cairn/tests/js` `` -- a bare directory path with
no glob -- inside a code span explaining why that form fails. A code
span naming the broken form (even to warn about it) is still ratified
text handing a teammate that exact string to copy, so this test is red
at HEAD regardless of anything in SKILL.md (which currently uses the
unquoted single-star glob form, not the bare-directory one, and so does
not itself trip this guard).

Extraction, in `test_gate_leg_naming.py`'s (PT-99) style: read each file
as text, pull every backtick-delimited code span (fenced ```blocks``` and
inline `spans`), and raise a named `ExtractionError` -- never a silent
empty list -- if a file yields zero spans.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent

# The ruling's own three-file scope for the JS-runner command (addendum 1
# added process/WORKFLOW.md as a third recording site).
RATIFIED_FILES = [
    REPO_ROOT / ".claude" / "skills" / "finish-feature" / "SKILL.md",
    REPO_ROOT / "scripts" / "cairn" / "tests" / "js" / "INTERFACE.md",
    REPO_ROOT / "process" / "WORKFLOW.md",
]

FENCED_BLOCK_RE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
# `node --test <arg>`, arg optionally double-quoted -- captures the raw
# argument text (quotes stripped) so the caller can check it for a glob
# character, regardless of whether the ratified text quoted it or not.
NODE_TEST_INVOCATION_RE = re.compile(r"node\s+--test\s+\"?([^\"\s]+)\"?")


class ExtractionError(AssertionError):
    """Raised when a source yields zero backtick-delimited code spans.

    A plain AssertionError subclass (not a bare `return []`), mirroring
    test_gate_leg_naming.py's (PT-99) and test_skill_id_literals.py's
    (PT-45) contract: a caller that forgets to guard against an empty
    result still sees a loud, named failure instead of a silently
    vacuous pass.
    """


def extract_code_spans(source: str, label: str = "<source>") -> list[str]:
    """Every backtick-delimited span (fenced or inline) in `source`, as a
    list of individual span strings. Raises ExtractionError if `source`
    has no code spans at all."""
    fenced = FENCED_BLOCK_RE.findall(source)
    masked = FENCED_BLOCK_RE.sub("", source)
    inline = INLINE_CODE_RE.findall(masked)
    spans = fenced + inline
    if not spans:
        raise ExtractionError(
            f"found zero backtick-delimited code spans in {label} -- pattern didn't match any "
            "code/command literal. If this file's formatting changed (no more backticks at "
            "all), this guard needs to be updated, not silenced."
        )
    return spans


def bare_directory_invocations(span: str) -> list[str]:
    """Every `node --test <arg>` invocation inside `span` whose argument
    carries no glob character (`*`) -- the bare-directory/no-discovery
    form node 26.7.0 cannot resolve (a quoted OR unquoted argument counts
    equally; quoting alone doesn't fix a glob-less path). Returns the raw
    argument strings, for reporting."""
    return [arg for arg in NODE_TEST_INVOCATION_RE.findall(span) if "*" not in arg]


class NoRatifiedTextNamesTheBareDirectoryFormTests(unittest.TestCase):
    """AC4 (PT-83.md @ 0c79168): no code span across the two ratified
    files names `node --test` on a bare, glob-less argument."""

    def test_no_ratified_code_span_names_a_bare_directory_node_test_form(self):
        offenders = []
        for path in RATIFIED_FILES:
            self.assertTrue(path.exists(), f"expected ratified file at {path}")
            source = path.read_text(encoding="utf-8")
            for span in extract_code_spans(source, label=str(path)):
                for arg in bare_directory_invocations(span):
                    offenders.append((str(path), arg))
        self.assertEqual(
            offenders, [],
            "found a `node --test <bare path, no glob>` invocation in ratified text -- node "
            "26.7.0 resolves a bare directory positional as a module ENTRY POINT, never a "
            "discovery root (MODULE_NOT_FOUND per the ruling's own measurement), so this form "
            f"must never be named as something to run (PT-83): {offenders}",
        )


class BareDirectoryDetectionSelfTests(unittest.TestCase):
    """Reds independent of the real files -- prove the detector
    distinguishes a bare path from a globbed one and from the quoted
    canonical recursive form, in both quoting styles."""

    def test_a_bare_unquoted_directory_argument_is_flagged(self):
        self.assertEqual(
            bare_directory_invocations("node --test scripts/cairn/tests/js"),
            ["scripts/cairn/tests/js"],
        )

    def test_a_bare_quoted_directory_argument_is_flagged(self):
        self.assertEqual(
            bare_directory_invocations('node --test "scripts/cairn/tests/js"'),
            ["scripts/cairn/tests/js"],
        )

    def test_a_single_star_globbed_argument_is_not_flagged(self):
        self.assertEqual(bare_directory_invocations("node --test scripts/cairn/tests/js/*.test.js"), [])

    def test_the_canonical_quoted_recursive_glob_is_not_flagged(self):
        self.assertEqual(
            bare_directory_invocations('node --test "scripts/cairn/tests/js/**/*.test.js"'), []
        )

    def test_extraction_raises_when_a_file_has_no_code_spans(self):
        with self.assertRaises(ExtractionError):
            extract_code_spans("No backticks anywhere in this sentence at all.", label="<spanless>")


if __name__ == "__main__":
    unittest.main()
