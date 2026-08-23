"""PT-45 drift guard: `.claude/skills/setup-tracker/SKILL.md` must never
scaffold a BARE (unprefixed) major/milestone id literal again.

Architect's finding (temp/2026-08-23-architect-skill-write-path-drift.md
§A, §C): PT-28 (v0.6.1) made prefixed ids mandatory with no grandfather
clause, but SKILL.md kept writing bare `majors/V1.md`, `milestones/A.md`,
`milestones/B.md` -- every repo instantiated from the template since
v0.6.1 started `cairn check`-red on day one. Fixed (this branch) by
switching every write-instruction literal to the `<PREFIX>-` placeholder
form (`<PREFIX>-V1`, `<PREFIX>-A`, `<PREFIX>-B`). §C's class note: "after
any change to check_repo's accepted values, grep the skills for literals
that write those fields."

Same technique as test_column_parity.py (PT-36) and the PT-37 source-text
extractors: read the skill AS TEXT, extract the specific literals with an
ANCHORED regex (the structural shape -- a `majors/`/`milestones/` path, or
a YAML frontmatter `id:` line -- not "is this inside a fenced code block",
which both over- and under-matches here: SKILL.md's id/path literals are a
mix of inline-backtick prose and one real YAML fence, while the "founding
major (V1)" prose the fix correctly left alone is neither), then reuse
cairn.py's OWN id-shape regexes (`_major_id_re`/`_definition_milestone_id_re`/
`_development_milestone_id_re`) as the single source of truth for "is this
shape actually valid" -- never a second, hand-rolled copy of PT-28's shape
rules here.

Scope, deliberately NOT repo-wide (judgment call -- flag if you'd rather
generalize): only setup-tracker/SKILL.md, the actual PT-45 fix target. A
repo-wide sweep of every `.claude/skills/*/SKILL.md` hits a real false
positive today -- merge-pr/SKILL.md's `milestones/<name>.md` is a
DIFFERENT kind of placeholder (a generic filename-pattern explanation, not
a literal bootstrap id) and would wrongly fail a blanket "must start with
<PREFIX>-" check. Generalizing this guard needs a way to distinguish
"placeholder documenting a pattern" from "placeholder for a literal this
skill actually writes" -- a separate design question, not a PT-45 blocker.

Expected RED until PT-45's fix lands: pre-fix SKILL.md's path/id literals
were bare (`V1`, `A`, `B`), so `<PREFIX>-` substitution never applies and
the shape-regex match fails.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn

SETUP_TRACKER_SKILL = helpers.CAIRN_DIR.parent.parent / ".claude" / "skills" / "setup-tracker" / "SKILL.md"
PLACEHOLDER = "<PREFIX>"
SYNTHETIC_PREFIX = "ZZ"  # arbitrary, real-shaped -- proves the regex substitution actually runs

# Anchored on the STRUCTURAL shape a write instruction takes in this file,
# not on markdown fencing (see module docstring) -- `(majors|milestones)/
# <id>.md` path literals, and YAML frontmatter `id:` lines.
PATH_LITERAL_RE = re.compile(r"(majors|milestones)/([^/\s`]+?)\.md")
FRONTMATTER_ID_RE = re.compile(r"^id:\s*(\S+)\s*$", re.MULTILINE)


def extract_path_ids(source: str) -> list[tuple[str, str]]:
    """[(subdir, id), ...] for every `<subdir>/<id>.md` literal in `source`."""
    return [(m.group(1), m.group(2)) for m in PATH_LITERAL_RE.finditer(source)]


def extract_frontmatter_ids(source: str) -> list[str]:
    return FRONTMATTER_ID_RE.findall(source)


def is_validly_prefixed(id_literal: str, subdir: str) -> bool:
    """True if `id_literal` (still containing the literal `<PREFIX>` token,
    as it appears in the unrendered skill file) becomes a real, correctly-
    shaped id once `<PREFIX>` is substituted with a real prefix -- checked
    against cairn.py's OWN id-shape regexes, not a re-derived copy of them.
    A literal that never carried the placeholder at all (a genuinely bare
    id, the PT-45 bug) fails this immediately: substitution is a no-op, and
    the bare shape doesn't match any real prefix's id regex.
    """
    if PLACEHOLDER not in id_literal:
        return False
    rendered = id_literal.replace(PLACEHOLDER, SYNTHETIC_PREFIX)
    if subdir == "majors":
        return bool(cairn._major_id_re(SYNTHETIC_PREFIX).match(rendered))
    # milestones/: setup-tracker only ever seeds definition-kind (letter)
    # milestones (A, B) -- accept EITHER shape regex here rather than
    # hardcoding "must be definition-shaped", since this guard's job is
    # "not bare", not re-asserting which specific milestone kind this
    # skill happens to seed today.
    return bool(
        cairn._definition_milestone_id_re(SYNTHETIC_PREFIX).match(rendered)
        or cairn._development_milestone_id_re(SYNTHETIC_PREFIX).match(rendered)
    )


class ExtractorSelfTests(unittest.TestCase):
    """Reds independent of the real file -- prove the extractor mechanism
    itself can both match and fail to match, against synthetic source."""

    def test_path_literal_extraction_finds_a_real_example(self):
        ids = extract_path_ids("Write `process/cairn/majors/<PREFIX>-V1.md` now.")
        self.assertIn(("majors", "<PREFIX>-V1"), ids)

    def test_frontmatter_id_extraction_finds_a_real_example(self):
        ids = extract_frontmatter_ids("---\nid: <PREFIX>-V1\nstatus: in-progress\n---\n")
        self.assertIn("<PREFIX>-V1", ids)

    def test_negative_control_a_bare_unprefixed_path_literal_is_flagged(self):
        # This is the PT-45 bug shape, reproduced synthetically -- proves
        # is_validly_prefixed can FAIL, not just always return True.
        self.assertFalse(is_validly_prefixed("V1", "majors"))
        self.assertFalse(is_validly_prefixed("A", "milestones"))

    def test_positive_control_a_correctly_prefixed_literal_passes(self):
        self.assertTrue(is_validly_prefixed("<PREFIX>-V1", "majors"))
        self.assertTrue(is_validly_prefixed("<PREFIX>-A", "milestones"))
        self.assertTrue(is_validly_prefixed("<PREFIX>-B", "milestones"))

    def test_a_wrong_shape_placeholder_is_still_flagged_not_just_presence_of_the_token(self):
        # Carries the <PREFIX> token but renders to an invalid shape once
        # substituted (lowercase, missing the V/letter convention) -- pins
        # that this checks REAL shape validity via cairn.py's regexes, not
        # just "does the string contain <PREFIX>".
        self.assertFalse(is_validly_prefixed("<PREFIX>-v1", "majors"))
        self.assertFalse(is_validly_prefixed("<PREFIX>-1", "milestones"))


class SetupTrackerSkillLiteralsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            SETUP_TRACKER_SKILL.exists(),
            f"expected setup-tracker's SKILL.md at {SETUP_TRACKER_SKILL}",
        )
        self.source = SETUP_TRACKER_SKILL.read_text(encoding="utf-8")

    def test_extraction_finds_at_least_one_path_literal_and_one_frontmatter_id(self):
        # Sanity floor -- if a future rewrite of this skill restructures it
        # so NEITHER extractor matches anything, every assertion below
        # would vacuously pass (0 items, all "flagged" checks trivially
        # true). This is what test_column_parity.py's ExtractionError
        # does for board-logic.js; a plain count-floor serves the same
        # role here without needing a raise-on-miss extractor of its own.
        self.assertGreater(len(extract_path_ids(self.source)), 0, "extractor found no majors/milestones path literals")
        self.assertGreater(len(extract_frontmatter_ids(self.source)), 0, "extractor found no frontmatter id: lines")

    def test_every_majors_milestones_path_literal_is_prefix_placeholder_shaped(self):
        bad = [
            (subdir, id_literal)
            for subdir, id_literal in extract_path_ids(self.source)
            if not is_validly_prefixed(id_literal, subdir)
        ]
        self.assertEqual(
            bad, [],
            f"found bare (unprefixed) id literal(s) in a majors/milestones path -- "
            f"PT-28 (v0.6.1) made prefixed ids mandatory with no grandfather; a bare "
            f"id here means every repo scaffolded from this skill starts `cairn check`-red: {bad}",
        )

    def test_every_frontmatter_id_line_is_prefix_placeholder_shaped(self):
        bad = [
            id_literal
            for id_literal in extract_frontmatter_ids(self.source)
            # A frontmatter `id:` line could in principle belong to either
            # schema this skill seeds -- accept either the major or the
            # milestone shape, same "not bare" scope as is_validly_prefixed.
            if not (is_validly_prefixed(id_literal, "majors") or is_validly_prefixed(id_literal, "milestones"))
        ]
        self.assertEqual(bad, [], f"found bare (unprefixed) frontmatter id: literal(s): {bad}")


if __name__ == "__main__":
    unittest.main()
