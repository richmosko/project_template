"""Tests for cairn.check_repo (the `cairn check` lint) and its CLI wrapper.

Each broken-tree test builds its own minimal tmp tree rather than reusing
the shared fixtures, so each case isolates exactly one defect.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn

GOOD_FRONTMATTER = (
    "id: {id}\ntitle: Thing\nstatus: {status}\nmilestone: {milestone}\nparent: {parent}\n"
    "assignee: null\nlabels: []\npriority: {priority}\npr: null\n"
    "created: 2026-08-01\nupdated: 2026-08-01\n"
)


def make_tree(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "issues").mkdir(parents=True)
    (data_dir / "archive").mkdir(parents=True)
    (data_dir / "milestones").mkdir(parents=True)
    (data_dir / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    (data_dir / "milestones" / "PT-1.0.md").write_text(
        '---\nid: "PT-1.0"\nname: MVP\nkind: product\nmajor: PT-V1\nstatus: planned\n'
        "target_tag: v1.0.0\nga: true\n---\n\nDoD.\n",
        encoding="utf-8",
    )
    # PT-12: milestones/PT-1.0.md above names major: PT-V1 -- without a
    # matching majors/PT-V1.md, the PT-12 missing/dangling-major check
    # would flag every test built on this tree the moment it lands, even
    # tests asserting `errors == []` for something unrelated (e.g.
    # CheckRepoPriorityTests). Keep the base tree internally consistent the
    # same way the real fixture under tests/fixtures/ already is.
    #
    # PT-28: ids prefixed (PT-1.0/PT-V1, was 1.0/V1) -- the id-shape lint
    # now enforces the configured prefix: on every namespace, so an
    # unprefixed base tree would fail lint on its own, tripping every
    # `errors == []` assertion built on make_tree() for a reason unrelated
    # to what each test actually exercises.
    (data_dir / "majors" / "PT-V1.md").write_text(
        "---\nid: PT-V1\nstatus: in-progress\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return data_dir


def write_milestone(data_dir: Path, filename: str, **overrides) -> None:
    fields = dict(id='"PT-1.0"', name="MVP", kind="product", major="PT-V1", status="planned",
                  target_tag="v1.0.0", ga="true")
    fields.update(overrides)
    text = (
        "---\n"
        "id: {id}\nname: {name}\nkind: {kind}\nmajor: {major}\nstatus: {status}\n"
        "target_tag: {target_tag}\nga: {ga}\n"
        "---\n\nDoD.\n"
    ).format(**fields)
    (data_dir / "milestones" / filename).write_text(text, encoding="utf-8")


def write_milestone_major_field_omitted(data_dir: Path, filename: str, milestone_id: str) -> None:
    """A milestone whose frontmatter has no `major:` key at all -- distinct
    from `major: null`, same distinction test_check_lint.py already draws
    for `priority` via write_issue_priority_field_omitted above."""
    text = (
        "---\n"
        f"id: {milestone_id}\nname: Omitted\nkind: product\nstatus: planned\n"
        "target_tag: null\nga: false\n"
        "---\n\nDoD.\n"
    )
    (data_dir / "milestones" / filename).write_text(text, encoding="utf-8")


def write_major(data_dir: Path, filename: str, major_id: str) -> None:
    text = f"---\nid: {major_id}\nstatus: in-progress\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"
    (data_dir / "majors" / filename).write_text(text, encoding="utf-8")


def write_issue_title_field_omitted(data_dir: Path, filename: str, issue_id: str) -> None:
    """A hand-crafted issue whose frontmatter has no `title:` key at all.

    PT-19: not reachable via cairn-owned write paths (allocate_and_create_issue
    always supplies title; apply_patch never strips a key) -- only a manual
    hand-edit produces this shape, per the issue's own reproduction.
    """
    text = (
        "---\n"
        f"id: {issue_id}\nstatus: todo\nmilestone: null\nparent: null\n"
        "assignee: null\nlabels: []\npriority: null\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n"
        "---\n\nBody.\n"
    )
    (data_dir / "issues" / filename).write_text(text, encoding="utf-8")


def write_milestone_with_stray_title(data_dir: Path, filename: str, **overrides) -> None:
    """A milestone whose frontmatter carries a stray `title:` key.

    PT-19: this is exactly the shape `_is_issue_shaped`'s `"title" in fields`
    discriminator (PT-13) would misclassify as issue-shaped -- reproduced here
    by hand-edit since no cairn-owned write path adds `title` to a milestone.
    """
    fields = dict(id='"1.0"', title="Stray Title", name="MVP", kind="product", major="V1",
                  status="planned", target_tag="v1.0.0", ga="true")
    fields.update(overrides)
    text = (
        "---\n"
        "id: {id}\ntitle: {title}\nname: {name}\nkind: {kind}\nmajor: {major}\nstatus: {status}\n"
        "target_tag: {target_tag}\nga: {ga}\n"
        "---\n\nDoD.\n"
    ).format(**fields)
    (data_dir / "milestones" / filename).write_text(text, encoding="utf-8")


def write_major_with_stray_title(data_dir: Path, filename: str, major_id: str) -> None:
    """Mirror of write_milestone_with_stray_title for majors/ -- same gap,
    same fix, same lint pass."""
    text = (
        f"---\nid: {major_id}\ntitle: Stray Title\nstatus: in-progress\nowner: mosko\n"
        "target_ship: null\nhealth: on-track\n---\n\nBody.\n"
    )
    (data_dir / "majors" / filename).write_text(text, encoding="utf-8")


def write_milestone_kind_field_omitted(data_dir: Path, filename: str, milestone_id: str) -> None:
    """A milestone whose frontmatter has no `kind:` key at all -- distinct
    from an invalid string value. PT-27 error 4: missing or invalid kind must
    both be flagged, mirroring the priority/major omitted-field distinction
    drawn above for issues/milestones."""
    text = (
        "---\n"
        f"id: {milestone_id}\nname: Omitted Kind\nmajor: V1\nstatus: planned\n"
        "target_tag: v1.0.0\nga: true\n"
        "---\n\nDoD.\n"
    )
    (data_dir / "milestones" / filename).write_text(text, encoding="utf-8")


def _fm_id(value: str) -> str:
    """Quote a milestone id for test frontmatter when it's dotted/numeric-shaped
    (e.g. "0.6", "10.20.30") so parse_yaml_subset keeps it a string -- matches
    how real milestone files (0.4.md etc.) are written. Letter/M-prefixed ids
    (A, M0, M0a) are unambiguous unquoted, matching the M0.md fixture."""
    return f'"{value}"' if "." in value else value


def _errors_for(errors, milestone_id):
    """Errors are formatted `f"{p.stem}: ..."` (see cairn.py's known_milestones
    loop) -- prefix-match rather than bare substring so short/ambiguous ids
    (A, M, a) can't false-positive against unrelated error text."""
    prefix = f"{milestone_id}:"
    return [e for e in errors if e.startswith(prefix)]


def write_issue(data_dir: Path, filename: str, **overrides) -> None:
    fields = dict(id="PT-1", status="todo", milestone="null", parent="null", priority="null")
    fields.update(overrides)
    text = "---\n" + GOOD_FRONTMATTER.format(**fields) + "---\n\nBody.\n"
    (data_dir / "issues" / filename).write_text(text, encoding="utf-8")


def write_issue_priority_field_omitted(data_dir: Path, filename: str, issue_id: str) -> None:
    """Write an issue whose frontmatter has no `priority:` key at all.

    Distinct from `priority: null` (an explicit null value) — this exercises
    fm.get("priority") returning None because the key is simply absent,
    matching how `milestone`/`parent`/`status` are already handled elsewhere
    in this file.
    """
    text = (
        "---\n"
        f"id: {issue_id}\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
        "assignee: null\nlabels: []\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n"
        "---\n\nBody.\n"
    )
    (data_dir / "issues" / filename).write_text(text, encoding="utf-8")


def write_issue_with_blocked_by(data_dir: Path, filename: str, issue_id: str, blocked_by: list, status: str = "todo") -> None:
    """Write an issue whose frontmatter carries an explicit `blocked_by`
    flow list -- PT-26's dependency field, `list[id]`, absent ≡ [] (not
    added to GOOD_FRONTMATTER/write_issue above, since most existing tests
    must keep exercising the absent-field case unmodified)."""
    ids = ", ".join(blocked_by)
    text = (
        "---\n"
        f"id: {issue_id}\ntitle: Thing\nstatus: {status}\nmilestone: null\nparent: null\n"
        f"blocked_by: [{ids}]\n"
        "assignee: null\nlabels: []\npriority: null\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n"
        "---\n\nBody.\n"
    )
    (data_dir / "issues" / filename).write_text(text, encoding="utf-8")


class CheckRepoTests(unittest.TestCase):
    def test_clean_fixture_tree_has_no_errors(self):
        data_dir = helpers.make_tmp_data_dir(self)
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [])

    def test_id_filename_mismatch(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-5.md", id="PT-6")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("PT-5" in e and "PT-6" in e for e in errors), errors)

    def test_dangling_parent(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", parent='"PT-999"')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("PT-1" in e and "parent" in e.lower() for e in errors), errors)

    def test_unknown_milestone(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", milestone='"9.9"')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("PT-1" in e and "milestone" in e.lower() for e in errors), errors)

    def test_bad_status(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", status="in-orbit")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("PT-1" in e and "status" in e.lower() for e in errors), errors)

    def test_unsupported_yaml_is_reported_not_raised(self):
        data_dir = make_tree(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: &anchor null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)  # must not raise
        self.assertTrue(errors)
        self.assertTrue(any("PT-1" in e for e in errors), errors)

    def test_multiple_issues_each_reported(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", status="bogus")
        write_issue(data_dir, "PT-2.md", id="PT-2", milestone='"nope"')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("PT-1" in e for e in errors))
        self.assertTrue(any("PT-2" in e for e in errors))


class CheckRepoPriorityTests(unittest.TestCase):
    """PT-5: `cairn check` must flag any issue whose priority is neither
    null nor exactly one of P0-P3, reporting the issue ID and the offending
    value, and exit non-zero on violation (CLI coverage in
    CheckCliPriorityTests below).
    """

    def test_valid_priorities_pass(self):
        for value in ("P0", "P1", "P2", "P3"):
            with self.subTest(priority=value):
                data_dir = make_tree(self)
                write_issue(data_dir, "PT-1.md", id="PT-1", priority=value)
                errors = cairn.check_repo(data_dir)
                self.assertEqual(errors, [], errors)

    def test_null_priority_passes(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", priority="null")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_missing_priority_field_passes(self):
        # No `priority:` key in frontmatter at all, as opposed to an
        # explicit `priority: null` — fm.get("priority") must return None
        # for both, not raise or be treated as a violation.
        data_dir = make_tree(self)
        write_issue_priority_field_omitted(data_dir, "PT-1.md", "PT-1")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_invalid_priority_string_is_rejected(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", priority="High")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("PT-1" in e and "priority" in e.lower() and "High" in e for e in errors),
            errors,
        )

    def test_invalid_priority_lowercase_is_rejected(self):
        # Exact-case match required — "p1" is not "P1".
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", priority="p1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("PT-1" in e and "priority" in e.lower() and "p1" in e for e in errors),
            errors,
        )

    def test_invalid_priority_numeric_is_rejected(self):
        # Bare `1` parses as an int via parse_yaml_subset, not the string
        # "P1" — must still be flagged, not silently coerced or ignored.
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", priority="1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("PT-1" in e and "priority" in e.lower() for e in errors),
            errors,
        )

    def test_invalid_priority_out_of_range_letter_is_rejected(self):
        # P4 has the right shape (P + digit) but is outside P0-P3.
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", priority="P4")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("PT-1" in e and "priority" in e.lower() and "P4" in e for e in errors),
            errors,
        )

    def test_multiple_issues_with_bad_priority_each_reported(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", priority="urgent")
        write_issue(data_dir, "PT-2.md", id="PT-2", priority="p2")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("PT-1" in e for e in errors), errors)
        self.assertTrue(any("PT-2" in e for e in errors), errors)


class CheckRepoMajorTests(unittest.TestCase):
    """PT-12: `cairn check` must flag any milestone whose `major` is
    missing/None, or names a major that doesn't exist -- known_milestones
    already gets this treatment (id/filename mismatch + dangling refs from
    issues); known_majors gets none of it today, so a milestone with
    `major: null` or `major: V9` passes silently. Mirrors the existing
    known_milestones pass, including the id/filename mismatch rule.
    """

    def test_valid_major_passes(self):
        # make_tree()'s milestones/1.0.md (major: V1) + majors/V1.md are
        # already mutually consistent -- this is the base case, unmodified.
        data_dir = make_tree(self)
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_null_major_is_flagged_as_missing(self):
        data_dir = make_tree(self)
        write_milestone(data_dir, "2.0.md", id='"2.0"', major="null")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("2.0" in e and "major" in e.lower() and "missing" in e.lower() for e in errors),
            errors,
        )

    def test_omitted_major_field_is_flagged_as_missing(self):
        # No `major:` key in frontmatter at all, as opposed to an explicit
        # `major: null` -- fm.get("major") must return None for both, and
        # both count as "missing", not just the explicit-null case.
        data_dir = make_tree(self)
        write_milestone_major_field_omitted(data_dir, "2.0.md", '"2.0"')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("2.0" in e and "major" in e.lower() and "missing" in e.lower() for e in errors),
            errors,
        )

    def test_dangling_major_is_flagged_with_the_offending_value(self):
        data_dir = make_tree(self)
        write_milestone(data_dir, "2.0.md", id='"2.0"', major="V9")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("2.0" in e and "major" in e.lower() and "V9" in e for e in errors),
            errors,
        )

    def test_major_id_filename_mismatch_is_flagged(self):
        # Same rule known_milestones already enforces on itself: a
        # majors/<stem>.md whose `id` doesn't match its filename stem is a
        # lint error, independent of whether any milestone references it.
        data_dir = make_tree(self)
        write_major(data_dir, "V9.md", major_id="V1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("V9" in e and "V1" in e for e in errors), errors)

    def test_unsupported_yaml_in_major_is_reported_not_raised(self):
        # Mirrors test_unsupported_yaml_is_reported_not_raised above, but
        # for the majors/ loop -- per-file parse errors must be caught and
        # reported per-file, not propagated, same as milestones/issues.
        data_dir = make_tree(self)
        (data_dir / "majors" / "V9.md").write_text(
            "---\nid: V9\nstatus: active\nowner: &anchor mosko\ntarget_ship: null\nhealth: on-track\n"
            "---\n\nBody.\n",
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)  # must not raise
        self.assertTrue(errors)
        self.assertTrue(any("V9" in e for e in errors), errors)

    def test_multiple_milestones_with_bad_major_each_reported(self):
        data_dir = make_tree(self)
        write_milestone(data_dir, "2.0.md", id='"2.0"', major="null")
        write_milestone(data_dir, "3.0.md", id='"3.0"', major="V9")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("2.0" in e for e in errors), errors)
        self.assertTrue(any("3.0" in e for e in errors), errors)


class CheckRepoTitleShapeTests(unittest.TestCase):
    """PT-19: `_is_issue_shaped` (PT-13) discriminates issue vs.
    milestone/major patches by `"title" in fields` -- correct for every
    well-formed file per TRACKER.md's schemas, but not schema-enforced.
    A milestone/major hand-edited to carry a stray `title:` gets
    miscategorized as issue-shaped on its next apply_patch; the mirror case
    (an issue missing `title`) silently stops getting shape-appropriate
    treatment. Neither is reachable via cairn-owned write paths -- manual
    edits only. Fix: check_repo lints title as required-on-issues,
    forbidden-on-milestones/majors, closing the gap at the lint layer.
    """

    def test_issue_missing_title_is_flagged(self):
        data_dir = make_tree(self)
        write_issue_title_field_omitted(data_dir, "PT-1.md", "PT-1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("PT-1" in e and "title" in e.lower() for e in errors), errors
        )

    def test_milestone_with_stray_title_is_flagged(self):
        data_dir = make_tree(self)
        write_milestone_with_stray_title(data_dir, "2.0.md", id='"2.0"')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("2.0" in e and "title" in e.lower() for e in errors), errors
        )

    def test_major_with_stray_title_is_flagged(self):
        data_dir = make_tree(self)
        write_major_with_stray_title(data_dir, "V9.md", major_id="V9")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("V9" in e and "title" in e.lower() for e in errors), errors
        )

    def test_well_formed_tree_passes_clean(self):
        # Issue carries title (required), milestone/major carry none
        # (forbidden) -- the shape TRACKER.md's schemas actually describe.
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_multiple_title_shape_violations_each_reported(self):
        data_dir = make_tree(self)
        write_issue_title_field_omitted(data_dir, "PT-1.md", "PT-1")
        write_milestone_with_stray_title(data_dir, "2.0.md", id='"2.0"')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("PT-1" in e for e in errors), errors)
        self.assertTrue(any("2.0" in e for e in errors), errors)


class CheckRepoIdShapeKindTests(unittest.TestCase):
    r"""PT-27: check_repo lints milestone id-shape <-> kind consistency.

    Spec (architect ruling, PT-27, ratified):
      definition  (kind: process)   ^(?!M)[A-Z][a-z]?$
      development (kind: product)   ^(?:M\d+[a-z]?|\d+\.\d+(?:\.\d+)?)$

    Four errors: (1) kind: process on a development-shaped id, (2) kind:
    product on a definition-shaped id, (3) id matching neither shape
    (regardless of kind), (4) kind missing or not product/process. `M` is
    reserved out of the definition alphabet -- `M`/`Ma` fall into error 3,
    not error 2, the case the ruling calls out as most likely to be
    implemented wrong.
    """

    def test_valid_definition_ids_pass(self):
        # PT-28: prefixed (PT-A, not A) -- the id-shape lint now requires
        # the configured prefix: on every namespace.
        for milestone_id in ("A", "B", "C", "Aa", "Ab", "Z"):
            with self.subTest(id=milestone_id):
                prefixed = f"PT-{milestone_id}"
                data_dir = make_tree(self)
                write_milestone(data_dir, f"{prefixed}.md", id=_fm_id(prefixed), kind="process", major="PT-V1")
                errors = cairn.check_repo(data_dir)
                self.assertEqual(errors, [], errors)

    def test_valid_development_ids_pass(self):
        for milestone_id in ("M0", "M1", "M12", "M0a", "M0b", "0.6", "1.0", "0.5.1", "1.0.1", "10.20.30"):
            with self.subTest(id=milestone_id):
                prefixed = f"PT-{milestone_id}"
                data_dir = make_tree(self)
                write_milestone(data_dir, f"{prefixed}.md", id=_fm_id(prefixed), kind="product", major="PT-V1")
                errors = cairn.check_repo(data_dir)
                self.assertEqual(errors, [], errors)

    def test_development_milestone_with_null_target_tag_still_passes(self):
        # Spec: the id-shape lint says nothing about target_tag/ga -- an
        # M<n> milestone with target_tag: null (pre-GA, no tag cut yet) is
        # legitimate and must not be flagged by this lint.
        data_dir = make_tree(self)
        write_milestone(data_dir, "PT-M0.md", id="PT-M0", kind="product", major="PT-V1",
                         target_tag="null", ga="false")
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_process_kind_on_development_shaped_id_is_flagged(self):
        # PT-28 QA fix (Validate-phase finding on c2c896f): the original
        # bare ids ("M0", "1.0") no longer reach error 1 at all -- a bare
        # id fails the id-shape lint FIRST (no prefix), landing in error 3
        # ("unrecognised milestone id"), whose boilerplate text happens to
        # contain the word "process" too ("...for kind: process, or...").
        # The loose `any("process" in e.lower())` check therefore passed
        # for the WRONG reason -- verified empirically: a bare "M0" milestone
        # produces ONLY the unrecognised-id message, never the kind-mismatch
        # one. Must use a PROPERLY PREFIXED, correctly-shaped id (PT-M0,
        # PT-1.0) to actually reach the id-shape<->kind mismatch branch, and
        # the assertion is tightened to the mismatch message's distinguishing
        # phrase ("but kind is") so it can't silently degrade to matching
        # error 3's boilerplate again.
        for milestone_id in ("PT-M0", "PT-1.0"):
            with self.subTest(id=milestone_id):
                data_dir = make_tree(self)
                write_milestone(data_dir, f"{milestone_id}.md", id=_fm_id(milestone_id), kind="process", major="PT-V1")
                errors = cairn.check_repo(data_dir)
                matching = _errors_for(errors, milestone_id)
                self.assertTrue(matching, errors)
                self.assertTrue(any("but kind is" in e.lower() and "process" in e.lower() for e in matching), errors)

    def test_product_kind_on_definition_shaped_id_is_flagged(self):
        # Same PT-28 QA fix as the sibling test above -- prefixed ids and a
        # tightened, mismatch-specific assertion.
        for milestone_id in ("PT-A", "PT-Aa"):
            with self.subTest(id=milestone_id):
                data_dir = make_tree(self)
                write_milestone(data_dir, f"{milestone_id}.md", id=_fm_id(milestone_id), kind="product", major="PT-V1")
                errors = cairn.check_repo(data_dir)
                matching = _errors_for(errors, milestone_id)
                self.assertTrue(matching, errors)
                self.assertTrue(any("but kind is" in e.lower() and "product" in e.lower() for e in matching), errors)

    def test_m_reservation_m_and_ma_are_unrecognised_not_definition_shaped(self):
        # `M` is reserved out of the definition alphabet -- `M` and `Ma` must
        # NOT be treated as valid (or even mismatched-kind) definition ids;
        # they match neither regex and fall to error 3 regardless of kind.
        for milestone_id in ("M", "Ma"):
            for kind in ("process", "product"):
                with self.subTest(id=milestone_id, kind=kind):
                    data_dir = make_tree(self)
                    write_milestone(data_dir, f"{milestone_id}.md", id=_fm_id(milestone_id), kind=kind, major="V1")
                    errors = cairn.check_repo(data_dir)
                    matching = _errors_for(errors, milestone_id)
                    self.assertTrue(matching, errors)
                    # Must not be reported as a process/product kind MISMATCH
                    # (errors 1/2) -- it's unrecognised (error 3), full stop.
                    self.assertTrue(
                        any("expected" in e.lower() or "unrecognised" in e.lower() or "unrecognized" in e.lower()
                            for e in matching),
                        errors,
                    )

    def test_ids_matching_neither_shape_are_flagged_regardless_of_kind(self):
        for milestone_id in ("mvp", "alpha", "1.0-rc", "V1", "AB", "a"):
            for kind in ("process", "product"):
                with self.subTest(id=milestone_id, kind=kind):
                    data_dir = make_tree(self)
                    write_milestone(data_dir, f"{milestone_id}.md", id=_fm_id(milestone_id), kind=kind, major="V1")
                    errors = cairn.check_repo(data_dir)
                    self.assertTrue(_errors_for(errors, milestone_id), errors)

    def test_missing_kind_is_flagged(self):
        data_dir = make_tree(self)
        write_milestone_kind_field_omitted(data_dir, "2.0.md", '"2.0"')
        errors = cairn.check_repo(data_dir)
        matching = _errors_for(errors, "2.0")
        self.assertTrue(matching, errors)
        self.assertTrue(any("kind" in e.lower() for e in matching), errors)

    def test_invalid_kind_value_is_flagged(self):
        data_dir = make_tree(self)
        write_milestone(data_dir, "2.0.md", id='"2.0"', kind="draft", major="V1")
        errors = cairn.check_repo(data_dir)
        matching = _errors_for(errors, "2.0")
        self.assertTrue(matching, errors)
        self.assertTrue(any("kind" in e.lower() and "draft" in e for e in matching), errors)

    def test_multiple_id_shape_violations_each_reported(self):
        data_dir = make_tree(self)
        write_milestone(data_dir, "M0.md", id="M0", kind="process", major="V1")
        write_milestone(data_dir, "A.md", id="A", kind="product", major="V1")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "M0"), errors)
        self.assertTrue(_errors_for(errors, "A"), errors)


class CheckRepoBlockedByTests(unittest.TestCase):
    """PT-26: check_repo lints blocked_by -- dangling reference, self-
    reference, and dependency cycles, all errors, same-root only (the
    lint's own tree is always exactly one root by construction -- no code
    path exists for cross-root refs at all, architect's ruling #2). A
    blocker that is done/cancelled is resolved, not an error -- the field
    is a permanent dependency record, not self-erasing on completion.
    """

    def test_absent_blocked_by_is_legal(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1")  # no blocked_by key at all
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_empty_blocked_by_is_legal(self):
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", [])
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_dangling_blocked_by_reference_is_flagged(self):
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-99"])
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any(
                "PT-1" in e and "dangling" in e.lower() and "blocked_by" in e and "PT-99" in e
                for e in errors
            ),
            errors,
        )

    def test_self_reference_is_flagged_distinctly_from_a_cycle(self):
        # Architect's ruling #2 (addendum): self-reference gets the lint's
        # own terse vocabulary, the same tier as "dangling parent" -- it
        # must NOT be swept into the cycle detector's verbose full-path
        # treatment, and must produce EXACTLY ONE error (not also a
        # 1-cycle report -- the addendum's explicit double-reporting
        # guard). A self-loop is graph-theoretically a 1-node cycle, but
        # the ruling treats it as its own category, not a degenerate cycle.
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-1"])
        errors = cairn.check_repo(data_dir)
        self.assertEqual(len(errors), 1, errors)
        message = errors[0]
        self.assertIn("PT-1", message)
        self.assertIn("self", message.lower())
        self.assertNotIn("cycle", message.lower())

    def test_two_node_cycle_is_reported_exactly_once_with_full_path(self):
        # File-iteration order (_dir_glob sorts by filename, lexicographic)
        # visits "PT-10.md" before "PT-2.md" -- so a DFS keyed to file scan
        # order would reach PT-10 first. The canonical rotation must still
        # lead with PT-2 (the _id_sort_key-SMALLEST id), not whichever
        # node the file scan happened to reach first.
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-10.md", "PT-10", ["PT-2"])
        write_issue_with_blocked_by(data_dir, "PT-2.md", "PT-2", ["PT-10"])
        errors = cairn.check_repo(data_dir)
        cycle_errors = [e for e in errors if "PT-2" in e and "PT-10" in e]
        self.assertEqual(len(cycle_errors), 1, errors)  # once per cycle, not once per node
        message = cycle_errors[0]
        self.assertIn("cycle", message.lower())
        self.assertLess(message.index("PT-2"), message.index("PT-10"))

    def test_three_node_cycle_is_reported_exactly_once_with_full_path(self):
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-10.md", "PT-10", ["PT-9"])
        write_issue_with_blocked_by(data_dir, "PT-9.md", "PT-9", ["PT-2"])
        write_issue_with_blocked_by(data_dir, "PT-2.md", "PT-2", ["PT-10"])
        errors = cairn.check_repo(data_dir)
        cycle_errors = [e for e in errors if "PT-2" in e and "PT-9" in e and "PT-10" in e]
        self.assertEqual(len(cycle_errors), 1, errors)
        message = cycle_errors[0]
        self.assertIn("cycle", message.lower())
        self.assertLess(message.index("PT-2"), message.index("PT-9"))
        self.assertLess(message.index("PT-2"), message.index("PT-10"))

    def test_done_blocker_is_legal_not_an_error(self):
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-2.md", "PT-2", [], status="done")
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-2"])
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_cancelled_blocker_is_legal_not_an_error(self):
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-2.md", "PT-2", [], status="cancelled")
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-2"])
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_blocked_by_referencing_an_archived_issue_is_not_dangling(self):
        # known_ids already spans issues/ AND archive/ -- falls out for
        # free, per the ruling.
        data_dir = make_tree(self)
        (data_dir / "archive" / "PT-9.md").write_text(
            "---\nid: PT-9\ntitle: Archived\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-9"])
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_multiple_blocked_by_violations_each_reported(self):
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-99"])
        write_issue_with_blocked_by(data_dir, "PT-2.md", "PT-2", ["PT-2"])
        errors = cairn.check_repo(data_dir)
        self.assertTrue(_errors_for(errors, "PT-1"), errors)
        self.assertTrue(_errors_for(errors, "PT-2"), errors)

    def test_two_disjoint_cycles_produce_exactly_two_errors(self):
        # Architect's addendum: separate cycles are separate errors --
        # neither merged into one report nor multiplied per member.
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-2"])
        write_issue_with_blocked_by(data_dir, "PT-2.md", "PT-2", ["PT-1"])
        write_issue_with_blocked_by(data_dir, "PT-5.md", "PT-5", ["PT-6"])
        write_issue_with_blocked_by(data_dir, "PT-6.md", "PT-6", ["PT-5"])
        errors = cairn.check_repo(data_dir)
        cycle_errors = [e for e in errors if "cycle" in e.lower()]
        self.assertEqual(len(cycle_errors), 2, errors)
        self.assertTrue(any("PT-1" in e and "PT-2" in e for e in cycle_errors), errors)
        self.assertTrue(any("PT-5" in e and "PT-6" in e for e in cycle_errors), errors)

    def test_reconvergent_dag_is_not_a_false_cycle(self):
        # THE discriminating test (architect's addendum): a plain
        # visited-set DFS reports a false cycle on any reconvergent DAG --
        # PT-1 -> PT-2, PT-1 -> PT-3, PT-2 -> PT-4, PT-3 -> PT-4 has no
        # cycle (PT-4 is reached twice, by two different paths, neither of
        # which revisits a node still on ITS OWN path), but a visited-set
        # walk that treats "already seen anywhere" as "cycle" will flag
        # PT-4 as revisited and misreport. Correct behaviour: zero errors.
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-2", "PT-3"])
        write_issue_with_blocked_by(data_dir, "PT-2.md", "PT-2", ["PT-4"])
        write_issue_with_blocked_by(data_dir, "PT-3.md", "PT-3", ["PT-4"])
        write_issue_with_blocked_by(data_dir, "PT-4.md", "PT-4", [])
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_dangling_and_cycle_on_the_same_issue_produce_exactly_two_errors(self):
        # Architect's addendum: dangling refs are excluded from the cycle
        # graph's edges entirely (you cannot walk to a node that does not
        # exist) -- one issue carrying both a dangling ref AND a real
        # cycle edge must produce exactly two errors (one dangling, one
        # cycle), not three (double-counted) and not one (the dangling ref
        # masking or fabricating the cycle).
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-99", "PT-2"])
        write_issue_with_blocked_by(data_dir, "PT-2.md", "PT-2", ["PT-1"])
        errors = cairn.check_repo(data_dir)
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(any("dangling" in e.lower() and "PT-99" in e for e in errors), errors)
        self.assertTrue(any("cycle" in e.lower() and "PT-1" in e and "PT-2" in e for e in errors), errors)

    def test_cross_root_reference_is_dangling_not_resolved(self):
        # Architect's addendum: check_repo runs per-root and has no code
        # path to resolve_roots at all -- an id that exists only in a
        # sibling root is dangling here, full stop, even when the
        # primary's own config.yml lists that root. Same-root only.
        data_dir = make_tree(self)
        sibling_dir = data_dir.parent / "sibling" / "cairn"
        (sibling_dir / "issues").mkdir(parents=True)
        (sibling_dir / "issues" / "PT-14.md").write_text(
            "---\nid: PT-14\ntitle: Lives in the sibling root\nstatus: todo\nmilestone: null\n"
            "parent: null\nassignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        (data_dir / "config.yml").write_text(
            'prefix: PT\nport: 8766\ndata_dir: process/cairn\nroots: ["../sibling/cairn"]\n',
            encoding="utf-8",
        )
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-14"])
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(
            any("PT-1" in e and "dangling" in e.lower() and "PT-14" in e for e in errors),
            errors,
        )


class CheckCliTests(unittest.TestCase):
    def test_clean_tree_exits_zero(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_broken_tree_exits_nonzero_with_pointed_message(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", status="bogus")
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("PT-1", combined)

    def test_missing_title_exits_nonzero_with_pointed_message(self):
        # PT-19 CLI coverage: an issue missing `title` must fail `cairn
        # check` with the same pointedness as the other lint violations.
        data_dir = make_tree(self)
        write_issue_title_field_omitted(data_dir, "PT-1.md", "PT-1")
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("PT-1", combined)
        self.assertIn("title", combined.lower())

    def test_bad_priority_exits_nonzero_with_id_and_value(self):
        # PT-5 criterion 2: `cairn check` exits non-zero on a priority
        # violation and its report names both the issue ID and the
        # offending value.
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", priority="urgent")
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("PT-1", combined)
        self.assertIn("urgent", combined)

    def test_process_kind_on_development_id_exits_nonzero_with_pointed_message(self):
        # PT-27 error 1: a development-shaped id (M<n> or version) with
        # kind: process must fail cairn check with the id and the
        # conflicting kind named.
        #
        # PT-28 QA fix (Validate-phase finding on c2c896f): a bare "M0" no
        # longer reaches error 1 at all -- it fails the id-shape lint FIRST
        # (no prefix) and lands in error 3 ("unrecognised milestone id"),
        # whose boilerplate text happens to also contain "process"
        # ("...for kind: process, or..."), so the old loose assertIn checks
        # passed for the wrong reason. Prefixed + tightened to "but kind is"
        # the same way the CheckRepoIdShapeKindTests sibling was.
        data_dir = make_tree(self)
        write_milestone(data_dir, "PT-M0.md", id="PT-M0", kind="process", major="PT-V1")
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("PT-M0", combined)
        self.assertIn("but kind is", combined.lower())
        self.assertIn("process", combined.lower())

    def test_unrecognised_milestone_id_shape_exits_nonzero_with_pointed_message(self):
        # PT-27 error 3: an id matching neither shape must fail regardless
        # of kind.
        data_dir = make_tree(self)
        write_milestone(data_dir, "mvp.md", id="mvp", kind="product", major="V1")
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("mvp", combined)

    def test_dangling_blocked_by_exits_nonzero_with_pointed_message(self):
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-99"])
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("PT-1", combined)
        self.assertIn("PT-99", combined)

    def test_blocked_by_cycle_exits_nonzero_with_pointed_message(self):
        data_dir = make_tree(self)
        write_issue_with_blocked_by(data_dir, "PT-1.md", "PT-1", ["PT-2"])
        write_issue_with_blocked_by(data_dir, "PT-2.md", "PT-2", ["PT-1"])
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("PT-1", combined)
        self.assertIn("PT-2", combined)
        self.assertIn("cycle", combined.lower())


if __name__ == "__main__":
    unittest.main()
