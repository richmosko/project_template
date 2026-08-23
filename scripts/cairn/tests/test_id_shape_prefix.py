"""Tests for PT-28's prefixed id-shape lint: majors/milestones/issues must
all carry the configured `prefix:` (built into `check_repo`'s regexes, never
a literal "PT"), the `V` reservation joining `M` in the definition-letter
sequence, the `prefix:` format lint itself (`^[A-Z]{2,5}$`), and the
missing/prefix-less config.yml hard-error.

Architect's finalized ruling: process/cairn/issues/PT-28.md (dbdbb7e).
Regex block (confirmations #1-4 + finalized §§1-3):

    definition   (kind: process)   ^<P>-(?!M|V)[A-Z][a-z]?$
    development  (kind: product)   ^<P>-(?:M\\d+[a-z]?|\\d+\\.\\d+(?:\\.\\d+)?)$
    major                           ^<P>-V\\d+$
    issue                           ^<P>-\\d+$

Each test builds its own minimal, ISOLATED tmp tree (test_check_lint.py's
own convention, stated at the top of that file) rather than reusing the
shared fixtures/checked-in tree -- deliberately so, since that shared tree
(and test_check_lint.py's own make_tree()/write_major()/write_milestone()
helpers) currently write BARE ids ("V1", "1.0") and will need a coordinated
migration of their own once this lint lands for their ~90 existing "clean
lint" assertions to keep passing. That migration is implementation-lead's
job (see the hand-off report), not something these new tests depend on.

None of this lint exists in check_repo as of this commit -- every test
below is expected to fail (a clean tree wrongly reports errors, or a
malformed tree wrongly passes) until implementation-lead's PT-28 slice
lands.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def make_empty_repo(testcase, prefix: str = "PT", config_text: str | None = None) -> Path:
    """A bare data_dir: empty issues/majors/milestones/archive, a config.yml
    with the given prefix (or a caller-supplied config_text override, e.g.
    to omit `prefix:` entirely or omit config.yml's normal shape)."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "issues").mkdir(parents=True)
    (data_dir / "archive").mkdir(parents=True)
    (data_dir / "milestones").mkdir(parents=True)
    (data_dir / "majors").mkdir(parents=True)
    if config_text is None:
        config_text = f"prefix: {prefix}\nport: 8766\ndata_dir: process/cairn\n"
    (data_dir / "config.yml").write_text(config_text, encoding="utf-8")
    return data_dir


def write_major(data_dir: Path, filename: str, major_id: str) -> None:
    text = f"---\nid: {major_id}\nstatus: in-progress\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"
    (data_dir / "majors" / filename).write_text(text, encoding="utf-8")


def _fm_id(value: str) -> str:
    # Quote a dotted/numeric-shaped id so parse_yaml_subset keeps it a
    # string, matching how real version-named milestone files are written.
    return f'"{value}"' if "." in value else value


def write_milestone(data_dir: Path, filename: str, milestone_id: str, kind: str, major: str = "PT-V1", **overrides) -> None:
    fields = dict(
        id=_fm_id(milestone_id), name="Thing", kind=kind, major=major, status="planned",
        target_tag="null", ga="false",
    )
    fields.update(overrides)
    text = (
        "---\n"
        "id: {id}\nname: {name}\nkind: {kind}\nmajor: {major}\nstatus: {status}\n"
        "target_tag: {target_tag}\nga: {ga}\n"
        "---\n\nDoD.\n"
    ).format(**fields)
    (data_dir / "milestones" / filename).write_text(text, encoding="utf-8")


def write_issue(data_dir: Path, filename: str, issue_id: str, milestone: str = "null") -> None:
    text = (
        "---\n"
        f"id: {issue_id}\ntitle: Thing\nstatus: todo\nmilestone: {milestone}\nparent: null\n"
        "assignee: null\nlabels: []\npriority: null\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n"
        "---\n\nBody.\n"
    )
    (data_dir / "issues" / filename).write_text(text, encoding="utf-8")


def _errors_for(errors, stem):
    prefix = f"{stem}:"
    return [e for e in errors if e.startswith(prefix)]


class PrefixFormatLintTests(unittest.TestCase):
    """Architect's ruling §7: `cairn check` enforces `^[A-Z]{2,5}$` on
    `prefix:` -- the SAME regex /setup-tracker already uses. A malformed
    prefix must hard-fail since every id-shape regex is derived from it."""

    def test_a_well_formed_two_letter_prefix_is_clean(self):
        data_dir = make_empty_repo(self, prefix="PT")
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_a_well_formed_five_letter_prefix_is_clean(self):
        data_dir = make_empty_repo(self, prefix="WXYZA")
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_missing_config_yml_entirely_is_a_hard_error(self):
        # Confirmation #2: a missing config.yml stops being safe to
        # tolerate once id shapes are derived from prefix: -- must now be
        # a hard lint error, not the pre-PT-28 silent "out of scope" pass.
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        # Deliberately no config.yml written at all.
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors, "a missing config.yml must be a hard lint error, not a silent pass")
        self.assertTrue(any("config" in e.lower() for e in errors), errors)

    def test_config_yml_present_but_missing_prefix_key_is_a_hard_error(self):
        data_dir = make_empty_repo(self, config_text="port: 8766\ndata_dir: process/cairn\n")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors, "config.yml with no prefix: key must be a hard lint error")
        self.assertTrue(any("prefix" in e.lower() for e in errors), errors)

    def test_lowercase_prefix_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="pt")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("prefix" in e.lower() for e in errors), errors)

    def test_single_letter_prefix_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="P")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("prefix" in e.lower() for e in errors), errors)

    def test_six_letter_prefix_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="ABCDEF")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("prefix" in e.lower() for e in errors), errors)

    def test_prefix_containing_a_digit_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="PT1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("prefix" in e.lower() for e in errors), errors)

    def test_prefix_containing_a_hyphen_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="P-T")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("prefix" in e.lower() for e in errors), errors)

    def test_empty_string_prefix_is_rejected(self):
        data_dir = make_empty_repo(self, config_text='prefix: ""\nport: 8766\n')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("prefix" in e.lower() for e in errors), errors)

    def test_a_malformed_prefix_does_not_silently_skip_the_rest_of_the_lint(self):
        # The ruling's own worry: "a lint that quietly stops linting is
        # worse than no lint" -- a malformed prefix must still surface an
        # error (rather than e.g. returning [] because the regexes
        # couldn't be built), even when there's real content to lint.
        data_dir = make_empty_repo(self, prefix="pt")
        write_major(data_dir, "V1.md", "V1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("prefix" in e.lower() for e in errors), errors)


class MajorIdShapeTests(unittest.TestCase):
    """Major ids must match ^<P>-V\\d+$ -- this is NEW enforcement (pre-
    PT-28, check_repo never validated a major's id shape at all, only
    id==filename + no stray title)."""

    def test_bare_major_id_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "V1.md", "V1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "V1"), errors)

    def test_prefixed_major_id_is_clean(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(_errors_for(errors, "PT-V1"), [], errors)

    def test_prefixed_but_wrong_shape_major_id_is_rejected(self):
        # Looks like an issue id, not a major -- must not slip through
        # just because it carries the right prefix.
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-1.md", "PT-1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "PT-1"), errors)

    def test_major_id_with_a_different_repos_prefix_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "ZZ-V1.md", "ZZ-V1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "ZZ-V1"), errors)


class DefinitionMilestoneShapeTests(unittest.TestCase):
    """Definition milestones: ^<P>-(?!M|V)[A-Z][a-z]?$ -- V joins M as a
    reserved letter (confirmation #1)."""

    def test_bare_definition_milestone_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "A.md", "A", kind="process")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "A"), errors)

    def test_prefixed_definition_milestone_is_clean(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-A.md", "PT-A", kind="process")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(_errors_for(errors, "PT-A"), [], errors)

    def test_prefixed_definition_milestone_subdivision_is_clean(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-Aa.md", "PT-Aa", kind="process")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(_errors_for(errors, "PT-Aa"), [], errors)

    def test_v_reserved_as_a_definition_letter_is_rejected(self):
        # The whole point of confirmation #1: PT-V (a would-be definition
        # milestone) sits one character from PT-V1 (the major) -- V must
        # be reserved out of the definition-letter sequence exactly as M
        # already is.
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-V.md", "PT-V", kind="process")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "PT-V"), errors)

    def test_m_still_reserved_as_a_definition_letter_alongside_v(self):
        # Pre-existing PT-27 behaviour must survive V joining the
        # reservation -- this is a regression guard, not new ground.
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-M.md", "PT-M", kind="process")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "PT-M"), errors)


class DevelopmentMilestoneShapeTests(unittest.TestCase):
    """Development milestones: ^<P>-(?:M\\d+[a-z]?|\\d+\\.\\d+(?:\\.\\d+)?)$"""

    def test_bare_version_milestone_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "0.6.md", "0.6", kind="product")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "0.6"), errors)

    def test_prefixed_version_milestone_is_clean(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-0.6.md", "PT-0.6", kind="product")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(_errors_for(errors, "PT-0.6"), [], errors)

    def test_prefixed_ordinal_milestone_m0_is_clean(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-M0.md", "PT-M0", kind="product")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(_errors_for(errors, "PT-M0"), [], errors)

    def test_prefixed_ordinal_milestone_subdivision_is_clean(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-M0a.md", "PT-M0a", kind="product")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(_errors_for(errors, "PT-M0a"), [], errors)

    def test_prefixed_patch_version_milestone_is_clean(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-0.5.1.md", "PT-0.5.1", kind="product")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(_errors_for(errors, "PT-0.5.1"), [], errors)


class IssueIdShapeTests(unittest.TestCase):
    """Issue ids: ^<P>-\\d+$ -- NEW enforcement. Pre-PT-28, check_repo only
    ever checked id == filename for issues; it never validated the id's
    shape against the prefix at all."""

    def test_well_formed_prefixed_issue_id_is_clean(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_issue(data_dir, "PT-29.md", "PT-29")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(_errors_for(errors, "PT-29"), [], errors)

    def test_non_numeric_issue_id_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_issue(data_dir, "PT-abc.md", "PT-abc")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "PT-abc"), errors)

    def test_issue_id_missing_the_prefix_entirely_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_issue(data_dir, "29.md", "29")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "29"), errors)

    def test_issue_id_with_a_different_repos_prefix_is_rejected(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_issue(data_dir, "ZZ-29.md", "ZZ-29")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "ZZ-29"), errors)


class ConfusablePairCoexistenceTests(unittest.TestCase):
    """The one genuinely confusable pair per the ruling: PT-1 (issue) vs
    PT-1.0 (development milestone) -- the dot resolves it. Also covers the
    issue's own scope note: 'must keep the name->target_tag derivation
    unambiguous' -- CONFIRMED by the architect's addendum § A.1: there is
    no derivation FUNCTION and none is being added (target_tag stays an
    explicit, never-inferred field; the phrase only ever meant the id must
    stay LEGIBLE to a human as implying its release, a constraint on id
    SHAPE discharged by §1, not a constraint on code). No derivation-
    function tests exist here, deliberately, per that ruling -- the
    observable property this class actually tests is narrower: both ids
    validate independently and neither's lint outcome depends on the
    other existing."""

    def test_issue_pt_1_and_milestone_pt_1_0_coexist_without_a_false_collision(self):
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-1.0.md", "PT-1.0", kind="product", target_tag="v1.0.0", ga="true")
        write_issue(data_dir, "PT-1.md", "PT-1", milestone=_fm_id("PT-1.0"))
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_issue_pt_1_milestone_field_resolves_to_the_version_milestone_not_the_issue(self):
        # A stricter version of the above: an issue referencing milestone
        # "1.0" must resolve against known_milestones (id "PT-1.0"), never
        # be silently matched against the unrelated issue id "PT-1" that
        # happens to share a numeric prefix.
        data_dir = make_empty_repo(self, prefix="PT")
        write_major(data_dir, "PT-V1.md", "PT-V1")
        write_milestone(data_dir, "PT-1.0.md", "PT-1.0", kind="product", target_tag="v1.0.0", ga="true")
        write_issue(data_dir, "PT-1.md", "PT-1", milestone=_fm_id("PT-1.0"))
        write_issue(data_dir, "PT-2.md", "PT-2", milestone='"nonexistent"')
        errors = cairn.check_repo(data_dir)
        # PT-1's milestone ref must NOT be flagged (it correctly resolves
        # to PT-1.0); PT-2's must (it references nothing real).
        self.assertEqual(_errors_for(errors, "PT-1"), [], errors)
        self.assertTrue(_errors_for(errors, "PT-2"), errors)


if __name__ == "__main__":
    unittest.main()
