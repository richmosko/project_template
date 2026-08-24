"""PT-41 failing tests: the two riders shipped alongside "Option A -- keep
PT-V1, define its meaning explicitly" (temp/arch-ruling-pt41-major-naming.md).
`V<n>` is DEFINED as "the line that culminates in v<n>.0.0" -- the riders
bind that definition to the DATA, via check_repo, instead of leaving it as
prose nobody enforces:

1. At most ONE `ga: true` milestone per major -- more than one is a lint
   error (two milestones both claiming to be the GA line of the same
   major is incoherent).
2. A `ga: true` milestone's `target_tag` must be `v<N>.0.0`, where `N` is
   its major's own version number (extracted from the major's id shape,
   `<PREFIX>-V<N>`) -- a GA milestone tagging anything else contradicts
   the very definition this rider exists to enforce.

Explicitly NOT an error: ZERO `ga: true` milestones for a major. A young
major legitimately hasn't designated its GA milestone yet (this repo's
own PT-V1 is exactly that case, per the ruling's own "Findings" section --
fixed by this same PT-41 slice creating PT-1.0.md, but the lint must not
REQUIRE a GA designation to exist).

Nothing under test exists yet: check_repo has no ga:true-related check at
all. Every red test below is expected to fail until implementation-lead's
PT-41 slice lands.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


MAJOR_TMPL = "---\nid: {id}\nstatus: {status}\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"
MILESTONE_TMPL = (
    "---\nid: {id}\nname: {name}\nkind: {kind}\nmajor: {major}\nstatus: {status}\n"
    "target_tag: {target_tag}\nga: {ga}\n---\n\nDoD.\n"
)


def make_repo(testcase, major_id: str = "PT-V1") -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    (data_dir / "majors" / f"{major_id}.md").write_text(
        MAJOR_TMPL.format(id=major_id, status="in-progress"), encoding="utf-8"
    )
    return data_dir


def write_milestone(data_dir: Path, filename: str, **overrides) -> None:
    fields = dict(id=filename[:-3], name="Thing", kind="product", major="PT-V1",
                  status="in-progress", target_tag="null", ga="false")
    fields.update(overrides)
    (data_dir / "milestones" / filename).write_text(MILESTONE_TMPL.format(**fields), encoding="utf-8")


def ga_errors_for(errors: list[str], major_id: str) -> list[str]:
    return [e for e in errors if "ga" in e.lower() and major_id in e]


class AtMostOneGaMilestonePerMajorTests(unittest.TestCase):
    def test_zero_ga_true_milestones_is_legal(self):
        data_dir = make_repo(self)
        write_milestone(data_dir, "PT-1.0.md", target_tag="v1.0.0", ga="false")
        write_milestone(data_dir, "PT-1.1.md", target_tag="v1.1.0", ga="false")
        errors = cairn.check_repo(data_dir)
        self.assertEqual([e for e in errors if "ga" in e.lower()], [], errors)

    def test_exactly_one_ga_true_milestone_is_legal(self):
        data_dir = make_repo(self)
        write_milestone(data_dir, "PT-1.0.md", target_tag="v1.0.0", ga="true")
        write_milestone(data_dir, "PT-1.1.md", target_tag="v1.1.0", ga="false")
        errors = cairn.check_repo(data_dir)
        self.assertEqual([e for e in errors if "ga" in e.lower()], [], errors)

    def test_two_ga_true_milestones_under_the_same_major_is_a_lint_error(self):
        data_dir = make_repo(self)
        write_milestone(data_dir, "PT-1.0.md", target_tag="v1.0.0", ga="true")
        write_milestone(data_dir, "PT-1.1.md", target_tag="v1.1.0", ga="true")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(ga_errors_for(errors, "PT-V1"), f"expected a GA-conflict error, got: {errors}")

    def test_two_ga_true_milestones_under_different_majors_is_not_an_error(self):
        # The "at most one" rule is scoped PER MAJOR -- two different
        # major lines each designating their own GA milestone is normal,
        # concurrent-majors shape (WORKFLOW.md's parallel-maintenance
        # model), not a conflict.
        data_dir = make_repo(self)
        (data_dir / "majors" / "PT-V2.md").write_text(
            MAJOR_TMPL.format(id="PT-V2", status="in-progress"), encoding="utf-8"
        )
        write_milestone(data_dir, "PT-1.0.md", major="PT-V1", target_tag="v1.0.0", ga="true")
        write_milestone(data_dir, "PT-2.0.md", major="PT-V2", target_tag="v2.0.0", ga="true")
        errors = cairn.check_repo(data_dir)
        self.assertEqual([e for e in errors if "ga" in e.lower()], [], errors)


class GaCapErrorMarksArchivedSiblingTests(unittest.TestCase):
    """PT-47: when the "at most one ga: true per major" cap trips because
    one sibling is a shipped-then-archived GA milestone and the other is
    live, the error's sibling list must say which is which -- otherwise it
    reads as two live milestones fighting over the same major, which is
    the wrong incident to chase."""

    def test_ga_cap_error_marks_the_archived_sibling_and_not_the_live_one(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "milestones").mkdir(parents=True)
        (data_dir / "archive" / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="Shipped", kind="product", major="PT-V1",
                                   status="done", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        write_milestone(data_dir, "PT-2.0.md", target_tag="v1.0.0", ga="true")
        errors = cairn.check_repo(data_dir)
        cap_errors = [e for e in ga_errors_for(errors, "PT-V1") if "more than one ga" in e]
        self.assertTrue(cap_errors, f"expected a GA-conflict error, got: {errors}")
        self.assertTrue(
            all("PT-1.0 (archived)" in e and "PT-2.0" in e and "PT-2.0 (archived)" not in e
                for e in cap_errors),
            f"expected the archived sibling marked and the live one unmarked, got: {cap_errors}",
        )


class GaTargetTagMatchesMajorNTests(unittest.TestCase):
    def test_ga_milestone_target_tag_matching_its_majors_n_is_legal(self):
        data_dir = make_repo(self, major_id="PT-V1")
        write_milestone(data_dir, "PT-1.0.md", major="PT-V1", target_tag="v1.0.0", ga="true")
        errors = cairn.check_repo(data_dir)
        self.assertEqual([e for e in errors if "ga" in e.lower()], [], errors)

    def test_ga_milestone_target_tag_with_the_wrong_major_number_is_a_lint_error(self):
        data_dir = make_repo(self, major_id="PT-V1")
        write_milestone(data_dir, "PT-2.0.md", major="PT-V1", target_tag="v2.0.0", ga="true")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(
            ga_errors_for(errors, "PT-V1"),
            f"a v2.0.0 GA tag under major PT-V1 (N=1) must be flagged, got: {errors}",
        )

    def test_ga_milestone_target_tag_with_a_minor_or_patch_suffix_is_a_lint_error(self):
        # v<N>.0.0 EXACTLY -- v1.1.0/v1.0.1 are not GA tags for major N=1,
        # regardless of how close they look.
        data_dir = make_repo(self, major_id="PT-V1")
        write_milestone(data_dir, "PT-1.1.md", major="PT-V1", target_tag="v1.1.0", ga="true")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(ga_errors_for(errors, "PT-V1"), errors)

    def test_ga_milestone_with_a_null_target_tag_is_a_lint_error(self):
        # A definition milestone (target_tag: null) claiming ga: true
        # makes no sense -- ga is a development-milestone-only claim.
        data_dir = make_repo(self, major_id="PT-V1")
        write_milestone(data_dir, "PT-1.0.md", major="PT-V1", target_tag="null", ga="true")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(ga_errors_for(errors, "PT-V1"), errors)

    def test_a_non_ga_milestones_target_tag_is_unconstrained_by_this_rule(self):
        # This rule only ever applies to ga:true milestones -- an ordinary
        # 1.1/1.2 development milestone's target_tag is untouched.
        data_dir = make_repo(self, major_id="PT-V1")
        write_milestone(data_dir, "PT-1.1.md", major="PT-V1", target_tag="v1.1.0", ga="false")
        errors = cairn.check_repo(data_dir)
        self.assertEqual([e for e in errors if "ga" in e.lower()], [], errors)

    def test_major_v2_expects_v2_0_0_not_v1_0_0(self):
        data_dir = make_repo(self, major_id="PT-V2")
        write_milestone(data_dir, "PT-2.0.md", major="PT-V2", target_tag="v2.0.0", ga="true")
        errors = cairn.check_repo(data_dir)
        self.assertEqual([e for e in errors if "ga" in e.lower()], [], errors)


if __name__ == "__main__":
    unittest.main()
