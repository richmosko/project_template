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

Same technique as test_column_parity.py (PT-36): read the skill AS TEXT,
extract candidate literals from its FENCED/backtick-delimited code spans
(architect's review, 2026-08-23 -- they hand-built the same extraction),
and validate each against cairn.py's OWN id-shape regexes
(`_major_id_re`/`_definition_milestone_id_re`/`_development_milestone_id_re`)
-- never a second, hand-rolled copy of PT-28's shape rules here, so a
future prefix-shape change fails HERE, in CI, not in a fresh user's first
`cairn check`.

Why code spans specifically, not "the whole file" or "only ``` fenced
blocks``": SKILL.md's write-instruction literals are a mix of ONE real
```markdown fenced block (the major frontmatter) and several single-
backtick inline paths (`majors/<PREFIX>-V1.md` in prose) -- fenced-only
would miss the inline ones; whole-file would catch prose like "founding
major (V1)", which the fix correctly left alone. Every backtick-delimited
span (`` ` `` or ```` ``` ````) covers exactly the "this is code/a
literal, not prose" signal the file's own markdown already encodes,
without a second exclusion rule.

Per PT-36's own contract (team-lead's ask, 2026-08-23, relaying the
architect's review): each extractor raises a NAMED `ExtractionError` --
never a silent empty list -- when its pattern matches nothing, so a future
restructure of this skill that accidentally drops every backtick/fence
fails loudly here instead of leaving this guard vacuously green forever.

Scope, deliberately NOT repo-wide (judgment call -- flag if you'd rather
generalize): only setup-tracker/SKILL.md. A blanket sweep of every
`.claude/skills/*/SKILL.md` hits a real false positive today --
merge-pr/SKILL.md's `` `milestones/<name>.md` `` is a DIFFERENT kind of
placeholder (documents a filename PATTERN, not a literal this skill
writes) and would wrongly fail a blanket "must start with <PREFIX>-"
check. process/WORKFLOW.md has the same problem one level worse: L595's
`` `majors/V1.md` moves to `status: done`... `` is a bare "V1" used as an
ALREADY-EXISTING example major line in a hypothetical multi-major-repo
narrative, not a scaffold instruction -- this exact extractor would
wrongly flag it. Distinguishing "documents a pattern/example" from
"writes a literal today" needs a narrower, differently-anchored guard (or
a per-file allowlist) -- a separate design question, not a PT-45 blocker.
Recommendation relayed to team-lead in the same message as this file.

PT-45 merged to main (#96) while this guard was still being written --
these tests now run green against the already-fixed tree rather than
red-then-green. Non-vacuity is instead proven by FrozenPreFixReproTests
below: a literal, frozen excerpt of the real pre-fix content (captured
before the merge), which this guard's own extraction+validation logic
still correctly flags as bad. See that class's docstring for why it's a
frozen string rather than a live `git show main:...` read.
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

# Anchored on the STRUCTURAL shape a write instruction takes, once
# restricted to code-span text (see module docstring): `(majors|milestones)/
# <id>.md` path literals, and YAML frontmatter `id:` lines.
FENCED_BLOCK_RE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
PATH_LITERAL_RE = re.compile(r"(majors|milestones)/([^/\s`]+?)\.md")
FRONTMATTER_ID_RE = re.compile(r"^id:\s*(\S+)\s*$", re.MULTILINE)


class ExtractionError(AssertionError):
    """Raised when a required literal can't be found in the skill's text.

    A plain AssertionError subclass (not a bare `return []`), mirroring
    test_column_parity.py's (PT-36) contract: a caller that forgets to
    check for an empty result still sees a loud, NAMED failure -- there is
    no code path in which "the pattern didn't match" silently becomes
    "compare zero literals to zero expectations and pass".
    """


def _code_spans(source: str) -> str:
    """Every backtick-delimited region of `source` (fenced ```blocks``` AND
    single-backtick inline spans), concatenated -- the locus every
    extractor below searches, never the raw prose. Fenced blocks are
    matched and MASKED OUT first, so the inline pattern can never
    accidentally match backtick-shaped content nested inside a multi-line
    fenced block's own body.
    """
    fenced = FENCED_BLOCK_RE.findall(source)
    masked = FENCED_BLOCK_RE.sub("", source)
    inline = INLINE_CODE_RE.findall(masked)
    return "\n".join(fenced + inline)


def extract_path_ids(source: str) -> list[tuple[str, str]]:
    """[(subdir, id), ...] for every `<subdir>/<id>.md` literal found
    inside a code span of `source`. Raises ExtractionError if none match."""
    spans = _code_spans(source)
    ids = [(m.group(1), m.group(2)) for m in PATH_LITERAL_RE.finditer(spans)]
    if not ids:
        raise ExtractionError(
            "found zero `majors/`/`milestones/`-path literals inside any backtick-delimited "
            "code span -- pattern didn't match a real write instruction. If this file's write "
            "instructions were restructured (different fencing, different phrasing), this guard "
            "needs to be updated, not silenced."
        )
    return ids


def extract_frontmatter_ids(source: str) -> list[str]:
    """Every YAML frontmatter `id:` line's value found inside a code span
    of `source`. Raises ExtractionError if none match."""
    spans = _code_spans(source)
    ids = FRONTMATTER_ID_RE.findall(spans)
    if not ids:
        raise ExtractionError(
            "found zero YAML frontmatter `id:` lines inside any backtick-delimited code span -- "
            "pattern didn't match a real frontmatter example. If this file's frontmatter example "
            "was restructured, this guard needs to be updated, not silenced."
        )
    return ids


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
    """Reds independent of the real file -- prove the extraction mechanism
    itself can match, fail to match (raising loudly), and correctly
    exclude bare prose, against synthetic source."""

    def test_path_literal_extraction_finds_a_real_example_inside_inline_code(self):
        ids = extract_path_ids("Write `process/cairn/majors/<PREFIX>-V1.md` now.")
        self.assertIn(("majors", "<PREFIX>-V1"), ids)

    def test_frontmatter_id_extraction_finds_a_real_example_inside_a_fenced_block(self):
        source = "```markdown\n---\nid: <PREFIX>-V1\nstatus: in-progress\n---\n```\n"
        ids = extract_frontmatter_ids(source)
        self.assertIn("<PREFIX>-V1", ids)

    def test_a_path_literal_in_bare_prose_with_no_backticks_is_not_extracted(self):
        # The exact class of false positive this guard must NOT produce --
        # "founding major (V1)"-shaped prose, but phrased as a bare path
        # with no code delimiter at all.
        ids = extract_path_ids_or_empty("The founding major file majors/V1.md exists conceptually.")
        self.assertEqual(ids, [], "a bare, non-backticked mention must not be extracted as a literal")

    def test_extractor_raises_extraction_error_when_no_code_spans_match_at_all(self):
        with self.assertRaises(ExtractionError):
            extract_path_ids("No backticks anywhere in this sentence at all.")

    def test_extraction_error_names_what_it_was_looking_for(self):
        with self.assertRaises(ExtractionError) as ctx:
            extract_frontmatter_ids("`some code` but no frontmatter id: line here")
        self.assertIn("frontmatter", str(ctx.exception))

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


def extract_path_ids_or_empty(source: str) -> list[tuple[str, str]]:
    """Test-only wrapper: extract_path_ids without the loud-failure
    contract, for the one test above that WANTS to observe "nothing
    extracted" as a normal (not exceptional) outcome."""
    spans = _code_spans(source)
    return [(m.group(1), m.group(2)) for m in PATH_LITERAL_RE.finditer(spans)]


class SetupTrackerSkillLiteralsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            SETUP_TRACKER_SKILL.exists(),
            f"expected setup-tracker's SKILL.md at {SETUP_TRACKER_SKILL}",
        )
        self.source = SETUP_TRACKER_SKILL.read_text(encoding="utf-8")

    def test_every_majors_milestones_path_literal_is_prefix_placeholder_shaped(self):
        bad = [
            (subdir, id_literal)
            for subdir, id_literal in extract_path_ids(self.source)  # raises loudly if extraction itself breaks
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
            for id_literal in extract_frontmatter_ids(self.source)  # raises loudly if extraction itself breaks
            # A frontmatter `id:` line could in principle belong to either
            # schema this skill seeds -- accept either the major or the
            # milestone shape, same "not bare" scope as is_validly_prefixed.
            if not (is_validly_prefixed(id_literal, "majors") or is_validly_prefixed(id_literal, "milestones"))
        ]
        self.assertEqual(bad, [], f"found bare (unprefixed) frontmatter id: literal(s): {bad}")


class FrozenPreFixReproTests(unittest.TestCase):
    """Pins the manual repro used to confirm this guard is real (not
    vacuous) as a permanent, re-runnable test.

    Deliberately a FROZEN literal snapshot (`git show
    HEAD~1:.claude/skills/setup-tracker/SKILL.md` at the moment this test
    was written -- e07... predates the PT-45 merge), NOT a live `git show
    main:...` read: main is a moving target -- PT-45 merged to main (#96)
    while this test file was still in flight, so a live read against
    `main` stopped reproducing the bug the instant that merge landed,
    silently turning this test's own sanity assertions into failures for
    a reason that has nothing to do with the guard itself. A frozen
    fixture string can't drift out from under this test the way a git ref
    can -- same reasoning as every other synthetic negative-control
    fixture in this suite (test_column_parity.py's fake_source strings,
    ExtractorSelfTests above), just sourced from real history instead of
    hand-written.
    """

    # Excerpt only (not the whole ~6KB file) -- just enough real pre-fix
    # text for both extractors to find their target literals, captured
    # verbatim from `git show` against the pre-PT-45 tree.
    PRE_FIX_EXCERPT = (
        "Write `process/cairn/majors/V1.md`:\n\n"
        "```markdown\n---\nid: V1\nstatus: in-progress\nowner: <user>\n"
        "target_ship: null\nhealth: on-track\n---\n\n"
        "Founding major line. Starts at MAJOR 0; the GA-designated milestone tags 1.0.0.\n```\n\n"
        "Write `process/cairn/milestones/A.md` and `B.md`:\n\n"
        "- Seeded: `majors/V1.md`, `milestones/A.md`, `milestones/B.md`\n"
    )

    def test_frozen_pre_fix_excerpt_would_have_failed_this_guard(self):
        bad_paths = [
            (subdir, id_literal)
            for subdir, id_literal in extract_path_ids(self.PRE_FIX_EXCERPT)
            if not is_validly_prefixed(id_literal, subdir)
        ]
        bad_fm = [
            id_literal
            for id_literal in extract_frontmatter_ids(self.PRE_FIX_EXCERPT)
            if not (is_validly_prefixed(id_literal, "majors") or is_validly_prefixed(id_literal, "milestones"))
        ]
        self.assertTrue(bad_paths, "sanity: the frozen pre-fix excerpt must have bare path literals")
        self.assertTrue(bad_fm, "sanity: the frozen pre-fix excerpt must have a bare frontmatter id")


if __name__ == "__main__":
    unittest.main()
