"""PT-99 gate 2 (qa-engineer), pinned to the architect's gate-1 ruling
(process/cairn/issues/PT-99.md @ eab939a -- "Measured", AC1): the bare
`unittest discover` leg is retired from every gate/verdict instruction --
no backtick code span in ratified text may still hand a teammate that
command.

Ratified-text set (33 files, ruling's own count): `process/WORKFLOW.md`,
`process/TRACKER.md`, `.claude/roles/*.md`, `.claude/agents/*.md`,
`.claude/skills/*/SKILL.md`. The ruling measured exactly 2 offending
spans at 1ae3a94 -- `process/WORKFLOW.md:100` and
`.claude/skills/finish-feature/SKILL.md:21`, both `` `unittest discover` ``
-- so this test is red at HEAD before the implementation lead's fix and
must go green once those two lines are replaced (per the ruling's exact
replacement text) without a third occurrence appearing anywhere else.

Extraction, in `test_skill_id_literals.py`'s (PT-45) style: read each
file as text, pull every backtick-delimited code span (fenced ```blocks```
and inline `spans`), and raise a NAMED `ExtractionError` -- never a
silent empty list -- if a file yields zero spans, so a future restructure
that accidentally drops every backtick in a ratified file fails loudly
here instead of leaving this guard vacuously green. Every file in the
33-file set is asserted (in the ruling's own measurement) to yield >= 1
span, so a real `ExtractionError` here means the file changed shape, not
that the pattern is wrong.

Scope note: this scans CODE SPANS ONLY, not prose -- the ruling is
explicit that a retired-form mention in prose (no backticks) is not in
scope for AC1, and deliberately leaves such a sentence out of the
replacement text. `test_test_run_hooks.py` is untouched by this feature
(the guard and its refusal message do not change) and is not read here.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent  # scripts/cairn -> scripts -> repo root

# The ruling's exact 33-file ratified-text set.
RATIFIED_FILES = (
    [REPO_ROOT / "process" / "WORKFLOW.md", REPO_ROOT / "process" / "TRACKER.md"]
    + sorted((REPO_ROOT / ".claude" / "roles").glob("*.md"))
    + sorted((REPO_ROOT / ".claude" / "agents").glob("*.md"))
    + sorted((REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md"))
)

# Same structural extraction as test_skill_id_literals.py (PT-45): fenced
# ```blocks``` matched first, then masked out, so a single-backtick scan
# of the remainder can never re-match content nested inside a fenced
# block's own body.
FENCED_BLOCK_RE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
UNITTEST_TOKEN_RE = re.compile(r"\bunittest\b")


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
    all."""
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


class NoRatifiedCodeSpanNamesUnittestTests(unittest.TestCase):
    """AC1 (PT-99.md @ eab939a): no code span across the 33-file ratified
    set names the token `unittest` -- the bare-discover leg is retired.
    Red at HEAD (ruling's own measurement): exactly 2 hits, WORKFLOW.md:100
    and finish-feature/SKILL.md:21, both `` `unittest discover` ``."""

    def test_no_ratified_code_span_names_unittest(self):
        offenders = []
        for path in RATIFIED_FILES:
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


class ExtractionRaisesOnSpanlessFileTests(unittest.TestCase):
    """A file with zero backtick-delimited code spans raises ExtractionError
    rather than silently returning an empty span list -- proves the
    extractor can't go vacuously green if a ratified file loses every
    backtick."""

    def test_extraction_raises_when_a_file_has_no_code_spans(self):
        with self.assertRaises(ExtractionError):
            extract_code_spans("No backticks anywhere in this sentence at all.", label="<spanless>")


if __name__ == "__main__":
    unittest.main()
