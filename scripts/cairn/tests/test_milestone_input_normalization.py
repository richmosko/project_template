"""PT-28 Validate-phase finding: `cairn ls --milestone` normalizes a bare
milestone value to the configured prefix (architect's ruling §3, item 2,
implemented via cmd_ls's `_normalize_milestone_filter`), but `cairn new
--milestone` and `cairn set <id> milestone=` do NOT -- confirmed by direct
manual reproduction against a disposable copy of this repo's own live
tracker data:

    cairn new "Smoke test" --milestone 0.6 --data-dir <tmp>
    -> creates the issue (exit 0, prints the new id) with milestone: "0.6"
       written VERBATIM (bare) to disk
    cairn check --data-dir <tmp>
    -> PT-35: unknown milestone '0.6'   (1 error(s))

    cairn set PT-1 milestone=0.6 --data-dir <tmp>
    -> succeeds (exit 0), same dangling-reference result

Both commands succeed (exit 0, no error to the user) while leaving the repo
in a lint-FAILING state -- worse than no bare-form leniency at all, since
the failure is silent at the point of the mistake and only surfaces later
at `cairn check` time, disconnected from the command that caused it. The
architect's ruling's stated PRINCIPLE ("the prefix is fixed per repo, so
input normalization cannot introduce ambiguity, and requiring users to
type their own repo's prefix on every local invocation is pure friction in
the one context where the prefix adds nothing") applies identically to
these two write paths; only `cmd_ls`'s read-path filter was actually wired
to `_normalize_milestone_filter`.

test_cli.py's own pre-existing test_new_with_all_flags currently locks in
the BUGGY behavior as correct (asserts `frontmatter["milestone"] == "1.0"`,
bare, with no post-write `cairn check` assertion) -- that assertion will
need updating to `"PT-1.0"` in the same commit that fixes this, or it
becomes a second copy of the same bug the fix is supposed to remove.

These two tests are RED as of this commit (c1e78ad) -- confirmed by the
manual reproduction above, not yet re-run against a fix.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def run_cairn(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(helpers.CAIRN_BIN), *args],
        capture_output=True,
        text=True,
    )


class NewCommandMilestoneNormalizationTests(unittest.TestCase):
    def test_new_with_a_bare_milestone_value_still_lints_clean(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["new", "Bare milestone smoke test", "--milestone", "1.0", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new_id = result.stdout.strip()
        fm, _ = cairn.parse_frontmatter((data_dir / "issues" / f"{new_id}.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["milestone"], "PT-1.0", "cairn new must normalize a bare --milestone value the same way cairn ls does")
        self.assertEqual(cairn.check_repo(data_dir), [], "a fresh issue cairn new just wrote must not fail cairn check's own lint")

    def test_new_with_an_already_prefixed_milestone_value_is_unaffected(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["new", "Prefixed milestone smoke test", "--milestone", "PT-1.0", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new_id = result.stdout.strip()
        fm, _ = cairn.parse_frontmatter((data_dir / "issues" / f"{new_id}.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["milestone"], "PT-1.0")
        self.assertEqual(cairn.check_repo(data_dir), [])


class SetCommandMilestoneNormalizationTests(unittest.TestCase):
    def test_set_milestone_with_a_bare_value_still_lints_clean(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["set", "PT-1", "milestone=1.0", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["milestone"], "PT-1.0", "cairn set milestone= must normalize a bare value the same way cairn ls does")
        self.assertEqual(cairn.check_repo(data_dir), [], "an issue cairn set just wrote must not fail cairn check's own lint")

    def test_set_milestone_with_an_already_prefixed_value_is_unaffected(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["set", "PT-1", "milestone=PT-1.0", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["milestone"], "PT-1.0")
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_set_milestone_cleared_to_empty_stays_null_unaffected_by_normalization(self):
        # Regression guard: normalization must not touch the existing
        # empty-string-coerces-to-null contract (test_frontmatter_rewrite.py's
        # ClearedNullableFieldTests) -- an empty value is not "bare", it's
        # "clear this field", and must still coerce to null, not "PT-".
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["set", "PT-1", "milestone=", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8"))
        self.assertIsNone(fm["milestone"])


if __name__ == "__main__":
    unittest.main()
