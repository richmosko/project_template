"""Ratified-text scanners -- two independent predicates over the SAME
kind of source (backtick code spans in agent-facing docs), sharing one
extraction mechanism. Merged by PT-98's consolidation ruling (architect,
process/cairn/issues/PT-98.md @ 04270d0, item (c)): "the two ratified-
text scanners -- test_gate_leg_naming.py and test_js_runner_canonical_
form.py -- are one subject and the clean case." Hygiene only (~0.03s of
interpreter start saved, not a speed lever) -- merging also de-
duplicates the two files' byte-identical `extract_code_spans`/
`ExtractionError`/`FENCED_BLOCK_RE`/`INLINE_CODE_RE` into one copy and
drops one redundant "raises on a spanless file" test the two files each
carried separately.

--------------------------------------------------------------------
PT-99 predicate (was test_gate_leg_naming.py) -- gate 2 (qa-engineer),
pinned to the architect's gate-1 ruling (process/cairn/issues/PT-99.md
@ eab939a -- "Measured", AC1): the bare `unittest discover` leg is
retired from every gate/verdict instruction -- no backtick code span in
ratified text may still hand a teammate that command.

Ratified-text set (33 files, ruling's own count): `process/WORKFLOW.md`,
`process/TRACKER.md`, `.claude/roles/*.md`, `.claude/agents/*.md`,
`.claude/skills/*/SKILL.md`. The ruling measured exactly 2 offending
spans at 1ae3a94 -- `process/WORKFLOW.md:100` and
`.claude/skills/finish-feature/SKILL.md:21`, both `` `unittest discover` ``
-- both fixed since; this guard now proves the fix holds.

--------------------------------------------------------------------
PT-83 predicate (was test_js_runner_canonical_form.py) -- gate 2
(qa-engineer), pinned to the architect's gate-1 ruling
(process/cairn/issues/PT-83.md @ 0c79168 -- item (d)/(f)(5)): the JS
test runner's canonical command is
`node --test "scripts/cairn/tests/js/**/*.test.js"` (quoted, so node --
not the shell -- expands the glob, measured rc 0/458 pass at node
26.7.0). No ratified text may still name `node --test` on a bare,
glob-less argument -- a directory positional or any other un-globbed
path: node 26.7.0 resolves that as a MODULE ENTRY POINT, never a
discovery root (measured: `Cannot find module '.../tests/js'`,
`MODULE_NOT_FOUND`, rc 1). Naming that form anywhere a teammate might
copy-paste it is a live footgun, not a style nit -- renaming
`scripts/cairn/tests/js/helpers.js` fixes nothing and is explicitly out
of scope (ruling item (d)); this file never reads that file.

Scope: the three files the ruling (addendum 1) names as recording this
command -- `.claude/skills/finish-feature/SKILL.md` (the finish-feature
gate), `scripts/cairn/tests/js/INTERFACE.md` (`## Running the suite`),
and `process/WORKFLOW.md` (the tiered-gating bullet's JS-suite sentence)
-- deliberately NOT the full PT-99 33-file ratified-text set above,
since this predicate (a bare-directory `node --test` argument) is
JS-runner-specific, not general agent-facing prose. WORKFLOW.md sits in
BOTH scopes for two unrelated predicates; that's incidental overlap,
not a reason to collapse the two file lists into one.

--------------------------------------------------------------------
Shared extraction, in `test_skill_id_literals.py`'s (PT-45) style: read
each file as text, pull every backtick-delimited code span (fenced
```blocks``` and inline `spans`), and raise a NAMED `ExtractionError` --
never a silent empty list -- if a file yields zero spans, so a future
restructure that accidentally drops every backtick in a ratified file
fails loudly here instead of leaving either guard vacuously green.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent  # scripts/cairn -> scripts -> repo root

# Shared structural extraction (test_skill_id_literals.py, PT-45): fenced
# ```blocks``` matched first, then masked out, so a single-backtick scan
# of the remainder can never re-match content nested inside a fenced
# block's own body. Used by BOTH predicates below.
FENCED_BLOCK_RE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


class ExtractionError(AssertionError):
    """Raised when a source yields zero backtick-delimited code spans.

    A plain AssertionError subclass (not a bare `return []`), mirroring
    test_skill_id_literals.py's contract: a caller that forgets to guard
    against an empty result still sees a loud, named failure instead of a
    silently vacuous pass.
    """


def extract_code_spans(source: str, label: str = "<source>") -> list[str]:
    """Every backtick-delimited span (fenced or inline) in `source`, as a
    list of individual span strings -- kept separate (not joined into one
    blob) so a failing match can be reported alongside the exact span it
    came from. Raises ExtractionError if `source` has no code spans at
    all. Shared by both predicates below."""
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


class ExtractionRaisesOnSpanlessFileTests(unittest.TestCase):
    """A file with zero backtick-delimited code spans raises ExtractionError
    rather than silently returning an empty span list -- proves the
    shared extractor can't go vacuously green for either predicate below
    if a ratified file loses every backtick."""

    def test_extraction_raises_when_a_file_has_no_code_spans(self):
        with self.assertRaises(ExtractionError):
            extract_code_spans("No backticks anywhere in this sentence at all.", label="<spanless>")


# --------------------------------------------------------------------------
# PT-99: no ratified code span may name `unittest` (the retired bare-
# discover gate/verdict leg).
# --------------------------------------------------------------------------

# The ruling's exact 33-file ratified-text set.
UNITTEST_RATIFIED_FILES = (
    [REPO_ROOT / "process" / "WORKFLOW.md", REPO_ROOT / "process" / "TRACKER.md"]
    + sorted((REPO_ROOT / ".claude" / "roles").glob("*.md"))
    + sorted((REPO_ROOT / ".claude" / "agents").glob("*.md"))
    + sorted((REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md"))
)

UNITTEST_TOKEN_RE = re.compile(r"\bunittest\b")


class NoRatifiedCodeSpanNamesUnittestTests(unittest.TestCase):
    """AC1 (PT-99.md @ eab939a): no code span across the 33-file ratified
    set names the token `unittest` -- the bare-discover leg is retired."""

    def test_no_ratified_code_span_names_unittest(self):
        offenders = []
        for path in UNITTEST_RATIFIED_FILES:
            self.assertTrue(path.exists(), f"expected ratified file at {path}")
            source = path.read_text(encoding="utf-8")
            for span in extract_code_spans(source, label=str(path)):
                if UNITTEST_TOKEN_RE.search(span):
                    offenders.append((str(path), span))
        self.assertEqual(
            offenders, [],
            "found a code span naming `unittest` in ratified text -- the bare `unittest "
            "discover` gate/verdict leg was retired (PT-99): a teammate can never issue it "
            f"under the guard, so no instruction may still hand it out: {offenders}",
        )


# --------------------------------------------------------------------------
# PT-83: no ratified code span may name `node --test` on a bare,
# glob-less argument (the JS runner's retired footgun form).
# --------------------------------------------------------------------------

# The ruling's own three-file scope for the JS-runner command (addendum 1
# added process/WORKFLOW.md as a third recording site).
JS_RUNNER_RATIFIED_FILES = [
    REPO_ROOT / ".claude" / "skills" / "finish-feature" / "SKILL.md",
    REPO_ROOT / "scripts" / "cairn" / "tests" / "js" / "INTERFACE.md",
    REPO_ROOT / "process" / "WORKFLOW.md",
]

# `node --test <arg>`, arg optionally double-quoted -- captures the raw
# argument text (quotes stripped) so the caller can check it for a glob
# character, regardless of whether the ratified text quoted it or not.
NODE_TEST_INVOCATION_RE = re.compile(r"node\s+--test\s+\"?([^\"\s]+)\"?")


def bare_directory_invocations(span: str) -> list[str]:
    """Every `node --test <arg>` invocation inside `span` whose argument
    carries no glob character (`*`) -- the bare-directory/no-discovery
    form node 26.7.0 cannot resolve (a quoted OR unquoted argument counts
    equally; quoting alone doesn't fix a glob-less path). Returns the raw
    argument strings, for reporting."""
    return [arg for arg in NODE_TEST_INVOCATION_RE.findall(span) if "*" not in arg]


class NoRatifiedTextNamesTheBareDirectoryFormTests(unittest.TestCase):
    """AC4 (PT-83.md @ 0c79168): no code span across the three ratified
    files names `node --test` on a bare, glob-less argument."""

    def test_no_ratified_code_span_names_a_bare_directory_node_test_form(self):
        offenders = []
        for path in JS_RUNNER_RATIFIED_FILES:
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


if __name__ == "__main__":
    unittest.main()
