"""Tests for the `cairn` CLI surface, invoked via the bash shim as a
subprocess -- this exercises scripts/cairn/cairn (the shim) and cairn.py's
argparse wiring together, closer to real agent usage than calling
cairn.main() in-process.
"""
from __future__ import annotations

import datetime
import os
import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def run_cairn(args: list[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(helpers.CAIRN_BIN), *args],
        capture_output=True,
        text=True,
        input=input,
    )


def _write_issue_with_blocked_by(data_dir: Path, issue_id: str, blocked_by: list[str], status: str = "todo") -> None:
    """PT-26 scratch-tree helper: write (or overwrite) issues/<id>.md with
    an explicit `blocked_by` flow list, for ShowBlockersTests."""
    ids = ", ".join(blocked_by)
    (data_dir / "issues" / f"{issue_id}.md").write_text(
        "---\n"
        f"id: {issue_id}\ntitle: Issue {issue_id}\nstatus: {status}\nmilestone: null\nparent: null\n"
        f"blocked_by: [{ids}]\n"
        "assignee: null\nlabels: []\npriority: null\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n"
        "---\n\nBody.\n",
        encoding="utf-8",
    )


class NewCommandTests(unittest.TestCase):
    def test_new_with_only_a_title_uses_defaults(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["new", "A brand new issue", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        created = sorted((data_dir / "issues").glob("PT-*.md"))
        new_files = [p for p in created if p.name not in ("PT-1.md", "PT-3.md", "PT-4.md")]
        self.assertEqual(len(new_files), 1)
        path = new_files[0]

        frontmatter, _ = cairn.parse_frontmatter(path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["title"], "A brand new issue")
        self.assertEqual(frontmatter["status"], cairn.DEFAULT_STATUS)
        self.assertIsNone(frontmatter["milestone"])
        self.assertIsNone(frontmatter["parent"])
        self.assertIsNone(frontmatter["assignee"])
        self.assertEqual(frontmatter["labels"], [])
        today = datetime.date.today().isoformat()
        self.assertEqual(frontmatter["created"], today)
        self.assertEqual(frontmatter["updated"], today)

    def test_new_with_all_flags(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(
            [
                "new",
                "Sub-issue of PT-1",
                "--milestone", "1.0",
                "--assignee", "backend-lead",
                "--status", "todo",
                "--parent", "PT-1",
                "--data-dir", str(data_dir),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new_files = [
            p for p in sorted((data_dir / "issues").glob("PT-*.md"))
            if p.name not in ("PT-1.md", "PT-3.md", "PT-4.md")
        ]
        self.assertEqual(len(new_files), 1)
        frontmatter, _ = cairn.parse_frontmatter(new_files[0].read_text(encoding="utf-8"))
        # PT-28 (Validate-phase fix): --milestone accepts the bare form and
        # normalizes to the configured prefix (same as `cairn ls
        # --milestone`) -- a bare "1.0" written straight to disk left the
        # repo lint-failing with a dangling ref, which this test locked in
        # as correct before the fix landed.
        self.assertEqual(frontmatter["milestone"], "PT-1.0")
        self.assertEqual(frontmatter["assignee"], "backend-lead")
        self.assertEqual(frontmatter["status"], "todo")
        self.assertEqual(frontmatter["parent"], "PT-1")
        self.assertEqual(cairn.check_repo(data_dir), [], "cairn new must never write an issue that fails its own lint")
        # A prefixed milestone id isn't numeric-looking, so it round-trips
        # unquoted (PT-28's finalized ruling § 9.2, verified against
        # dump_frontmatter's actual output).
        raw = new_files[0].read_text(encoding="utf-8")
        self.assertIn("milestone: PT-1.0", raw)

    def test_new_prints_the_new_id(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["new", "Prints its id", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0)
        self.assertIn("PT-10", result.stdout)

    def test_new_with_blocked_by_writes_the_field_as_a_list(self):
        # PT-26: --blocked-by (kebab flag) -> args.blocked_by -> blocked_by:
        # (snake key), comma-separated, same shape as --labels.
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(
            ["new", "Blocked issue", "--blocked-by", "PT-1,PT-3", "--data-dir", str(data_dir)]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new_files = [
            p for p in sorted((data_dir / "issues").glob("PT-*.md"))
            if p.name not in ("PT-1.md", "PT-3.md", "PT-4.md")
        ]
        self.assertEqual(len(new_files), 1)
        frontmatter, _ = cairn.parse_frontmatter(new_files[0].read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["blocked_by"], ["PT-1", "PT-3"])

    def test_new_without_blocked_by_defaults_to_empty_list(self):
        # Absent flag ≡ [] -- not null, not omitted from the written file.
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["new", "No blockers", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new_files = [
            p for p in sorted((data_dir / "issues").glob("PT-*.md"))
            if p.name not in ("PT-1.md", "PT-3.md", "PT-4.md")
        ]
        frontmatter, _ = cairn.parse_frontmatter(new_files[0].read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["blocked_by"], [])


class LsCommandTests(unittest.TestCase):
    def test_ls_lists_active_issues_one_line_each(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["ls", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)  # PT-1, PT-3, PT-4 -- PT-9 is archived
        joined = "\n".join(lines)
        self.assertIn("PT-1", joined)
        self.assertIn("PT-3", joined)
        self.assertIn("PT-4", joined)
        self.assertNotIn("PT-9", joined)

    def test_ls_filters_by_status(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["ls", "--status", "todo", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("PT-3", lines[0])

    def test_ls_filters_by_milestone(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["ls", "--milestone", "1.0", "--data-dir", str(data_dir)])
        joined = result.stdout
        self.assertIn("PT-1", joined)
        self.assertIn("PT-3", joined)
        self.assertNotIn("PT-4", joined)  # PT-4's milestone is null

    def test_ls_filters_by_assignee(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["ls", "--assignee", "backend-lead", "--data-dir", str(data_dir)])
        joined = result.stdout
        self.assertIn("PT-1", joined)
        self.assertIn("PT-3", joined)
        self.assertNotIn("PT-4", joined)

    def test_ls_orders_numerically_by_id_not_lexicographically_by_filename(self):
        # PT-21: _dir_glob's filename order is lexicographic ("PT-10"
        # sorts before "PT-2", since '1' < '2') -- cmd_ls must not just
        # print that order verbatim. Add PT-2 and PT-10 (the fixture
        # ships PT-1/3/4/9 only, no double-digit id) so this is a real
        # regression case, not a fixture accident.
        data_dir = helpers.make_tmp_data_dir(self)
        for issue_id in ("PT-2", "PT-10"):
            (data_dir / "issues" / f"{issue_id}.md").write_text(
                "---\n"
                f"id: {issue_id}\ntitle: Numeric sort case\nstatus: backlog\n"
                "milestone: null\nparent: null\nassignee: null\nlabels: []\n"
                "priority: null\npr: null\ncreated: 2026-08-01\nupdated: 2026-08-01\n"
                "---\n\nBody.\n",
                encoding="utf-8",
            )
        result = run_cairn(["ls", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        ids_in_order = [line.split("\t", 1)[0] for line in lines]
        self.assertIn("PT-2", ids_in_order)
        self.assertIn("PT-10", ids_in_order)
        self.assertLess(
            ids_in_order.index("PT-2"), ids_in_order.index("PT-10"),
            f"expected PT-2 before PT-10, got order: {ids_in_order}",
        )


class SetCommandTests(unittest.TestCase):
    def test_set_updates_fields_and_bumps_updated(self):
        data_dir = helpers.make_tmp_data_dir(self)
        path = data_dir / "issues" / "PT-1.md"
        before_raw = path.read_bytes()

        result = run_cairn(
            ["set", "PT-1", "status=in-review", "pr=https://example.com/pr/1", "--data-dir", str(data_dir)]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        after_raw = path.read_bytes()
        frontmatter, _ = cairn.parse_frontmatter(after_raw.decode("utf-8"))
        self.assertEqual(frontmatter["status"], "in-review")
        self.assertEqual(frontmatter["pr"], "https://example.com/pr/1")
        self.assertEqual(frontmatter["updated"], datetime.date.today().isoformat())

        # Tail = everything after the closing frontmatter fence. Not a
        # second `.split(b"---\n", 1)[1]` on top of that: PT-1's fixture
        # body contains no further literal "---\n" (only ``` fences and
        # ### headings), so that extra split raised IndexError on [1] for
        # every run of this test regardless of implementation correctness.
        before_tail = before_raw.split(b"---\n", 2)[2]
        after_tail = after_raw.split(b"---\n", 2)[2]
        self.assertEqual(before_tail, after_tail)

    def test_set_on_unknown_id_fails_loudly(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["set", "PT-999", "status=done", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PT-999", result.stdout + result.stderr)


class SetBlockedByTests(unittest.TestCase):
    """PT-26: `cairn set <id> blocked_by=...` writes/clears the field --
    comma-separated, empty clears to [] (never null, since blocked_by is
    NOT a NULLABLE_FIELDS member -- it's list-valued like labels)."""

    def test_set_writes_blocked_by_as_a_list(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["set", "PT-1", "blocked_by=PT-3,PT-4", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        frontmatter, _ = cairn.parse_frontmatter(
            (data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8")
        )
        self.assertEqual(frontmatter["blocked_by"], ["PT-3", "PT-4"])

    def test_set_blocked_by_empty_clears_to_empty_list_never_null(self):
        data_dir = helpers.make_tmp_data_dir(self)
        run_cairn(["set", "PT-1", "blocked_by=PT-3", "--data-dir", str(data_dir)])  # give it something to clear
        result = run_cairn(["set", "PT-1", "blocked_by=", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        frontmatter, _ = cairn.parse_frontmatter(
            (data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8")
        )
        self.assertEqual(frontmatter["blocked_by"], [])
        self.assertIsNotNone(frontmatter["blocked_by"])

    def test_labels_and_blocked_by_split_identically_on_messy_input(self):
        # Architect's ruling #3: one shared _split_csv helper and a
        # LIST_FIELDS membership test -- no second `if key == "blocked_by"`
        # branch. Can't assert the internal structure directly (that's
        # implementation-lead's call), but if labels and blocked_by really
        # share one helper, they MUST agree, byte-for-byte, on every edge
        # case: trailing commas, embedded whitespace, empty segments.
        data_dir = helpers.make_tmp_data_dir(self)
        messy = "  PT-1 , ,PT-3,  "
        run_cairn(["set", "PT-1", f"labels={messy}", "--data-dir", str(data_dir)])
        run_cairn(["set", "PT-1", f"blocked_by={messy}", "--data-dir", str(data_dir)])
        frontmatter, _ = cairn.parse_frontmatter(
            (data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8")
        )
        self.assertEqual(frontmatter["labels"], frontmatter["blocked_by"])
        self.assertEqual(frontmatter["blocked_by"], ["PT-1", "PT-3"])


class InformationalOnlyBlockedByTests(unittest.TestCase):
    """PT-26 architect's addendum: blocked_by is informational only in
    v1 -- no exit-code effect, no stderr, no refusal, on any write path."""

    def test_set_status_in_progress_on_a_blocked_issue_is_silent_and_succeeds(self):
        data_dir = helpers.make_tmp_data_dir(self)
        setup = run_cairn(["set", "PT-1", "blocked_by=PT-3", "--data-dir", str(data_dir)])
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)  # precondition: PT-1 is actually blocked
        result = run_cairn(["set", "PT-1", "status=in-progress", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.strip(), "PT-1")


class CommentCommandTests(unittest.TestCase):
    def test_comment_appends_from_stdin_with_correct_delimiter(self):
        data_dir = helpers.make_tmp_data_dir(self)
        path = data_dir / "issues" / "PT-1.md"

        result = run_cairn(
            ["comment", "PT-1", "--author", "qa-engineer", "--body", "-", "--data-dir", str(data_dir)],
            input="Looks good, ship it.\n",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        text = path.read_text(encoding="utf-8")
        _, body = cairn.parse_frontmatter(text)
        _, comments = cairn.split_comments(body)
        # PT-1 fixture now has 3 real comments post finding-4's
        # fence-tracking removal (see test_server.py's
        # test_get_issue_includes_full_comments_and_seen) + 1 appended here.
        self.assertEqual(len(comments), 4)
        self.assertEqual(comments[-1]["author"], "qa-engineer")
        self.assertEqual(comments[-1]["date"], datetime.date.today().isoformat())
        self.assertIn("Looks good, ship it.", comments[-1]["body"])


class ShowCommandTests(unittest.TestCase):
    def test_show_renders_issue_contents(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["show", "PT-1", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PT-1", result.stdout)
        self.assertIn("Google OAuth login", result.stdout)
        self.assertIn("qa-engineer", result.stdout)

    def test_show_renders_full_frontmatter_not_just_title(self):
        # `show` is meant to be a complete single-issue rendering an agent
        # can read without opening the file -- not just id/title/comments.
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["show", "PT-1", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("in-progress", result.stdout)  # status
        self.assertIn("1.0", result.stdout)  # milestone
        self.assertIn("backend-lead", result.stdout)  # assignee
        self.assertIn("auth", result.stdout)  # labels
        self.assertIn("P1", result.stdout)  # priority


class ShowChildrenTests(unittest.TestCase):
    """PT-25: `cairn show <id>` structural addition -- a parent lists its
    children (id, status, title); a child already names its parent
    (architect's finding, verified against real CLI output before writing
    these -- cmd_show already prints `parent:` via the ISSUE_FIELD_ORDER[2:]
    loop, so that half needs no code change. Recorded here as a regression
    lock, not built to a criterion already met.
    """

    def test_show_on_child_already_names_its_parent(self):
        # NOT a red test -- confirmed passing against current cairn.py
        # (qa-engineer, 2026-08-22) before this file was written. PT-3's
        # fixture parent is PT-1.
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["show", "PT-3", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PT-1", result.stdout)

    def test_show_on_parent_lists_its_children(self):
        # PT-1's fixture already has PT-3 as a child (parent: PT-1).
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["show", "PT-1", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("child", result.stdout.lower())
        self.assertIn("PT-3", result.stdout)
        self.assertIn("Link existing email-password user to Google identity", result.stdout)
        self.assertIn("todo", result.stdout)

    def test_show_on_issue_with_no_children_has_no_children_section(self):
        # PT-4 has no children in the fixture -- must not print a
        # children heading with nothing under it.
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["show", "PT-4", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("child", result.stdout.lower())

    def test_show_children_are_sorted_numerically_not_lexicographically(self):
        # Same PT-2 < PT-9 < PT-10 case list as the drift pair
        # (test_id_sort.py / tests/js/id-sort.test.js) -- cmd_show's
        # children listing reuses _id_sort_key, not a lexicographic sort.
        data_dir = helpers.make_tmp_data_dir(self)
        for child_id in ("PT-10", "PT-2", "PT-9"):
            (data_dir / "issues" / f"{child_id}.md").write_text(
                "---\n"
                f"id: {child_id}\ntitle: Child {child_id}\nstatus: todo\n"
                'milestone: null\nparent: "PT-1"\nassignee: null\nlabels: []\n'
                "priority: null\npr: null\ncreated: 2026-08-01\nupdated: 2026-08-01\n"
                "---\n\nBody.\n",
                encoding="utf-8",
            )
        result = run_cairn(["show", "PT-1", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # PT-3 is PT-1's existing fixture child too -- four children total.
        positions = {}
        for child_id in ("PT-2", "PT-3", "PT-9", "PT-10"):
            idx = result.stdout.find(child_id)
            self.assertNotEqual(idx, -1, f"{child_id} missing from output:\n{result.stdout}")
            positions[child_id] = idx
        self.assertLess(positions["PT-2"], positions["PT-9"])
        self.assertLess(positions["PT-9"], positions["PT-10"])


class ShowBlockersTests(unittest.TestCase):
    """PT-26: `cairn show <id>` displays blocked_by (blockers) and the
    reverse "blocks" links, both directions sorted by _id_sort_key
    (architect's ruling)."""

    def test_show_displays_its_blockers(self):
        data_dir = helpers.make_tmp_data_dir(self)
        _write_issue_with_blocked_by(data_dir, "PT-1", ["PT-3"])
        result = run_cairn(["show", "PT-1", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("block", result.stdout.lower())
        self.assertIn("PT-3", result.stdout)

    def test_show_displays_reverse_blocks_links(self):
        data_dir = helpers.make_tmp_data_dir(self)
        _write_issue_with_blocked_by(data_dir, "PT-1", ["PT-3"])
        result = run_cairn(["show", "PT-3", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("block", result.stdout.lower())
        self.assertIn("PT-1", result.stdout)

    def test_show_on_issue_with_no_dependencies_has_no_dependency_sections(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["show", "PT-4", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("block", result.stdout.lower())

    def test_show_blockers_are_sorted_numerically_not_lexicographically(self):
        data_dir = helpers.make_tmp_data_dir(self)
        for blocker_id in ("PT-10", "PT-2", "PT-9"):
            _write_issue_with_blocked_by(data_dir, blocker_id, [])
        _write_issue_with_blocked_by(data_dir, "PT-1", ["PT-10", "PT-2", "PT-9"])
        result = run_cairn(["show", "PT-1", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        positions = {}
        for blocker_id in ("PT-2", "PT-9", "PT-10"):
            idx = result.stdout.find(blocker_id)
            self.assertNotEqual(idx, -1, f"{blocker_id} missing from output:\n{result.stdout}")
            positions[blocker_id] = idx
        self.assertLess(positions["PT-2"], positions["PT-9"])
        self.assertLess(positions["PT-9"], positions["PT-10"])

    def test_show_reverse_blocks_are_sorted_numerically_not_lexicographically(self):
        data_dir = helpers.make_tmp_data_dir(self)
        for blocked_id in ("PT-10", "PT-2", "PT-9"):
            _write_issue_with_blocked_by(data_dir, blocked_id, ["PT-1"])
        result = run_cairn(["show", "PT-1", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        positions = {}
        for blocked_id in ("PT-2", "PT-9", "PT-10"):
            idx = result.stdout.find(blocked_id)
            self.assertNotEqual(idx, -1, f"{blocked_id} missing from output:\n{result.stdout}")
            positions[blocked_id] = idx
        self.assertLess(positions["PT-2"], positions["PT-9"])
        self.assertLess(positions["PT-9"], positions["PT-10"])


class NonDefaultPrefixTests(unittest.TestCase):
    """The fixture tree hard-codes prefix: PT everywhere else in this file --
    exercise a distinct prefix end-to-end through the CLI to confirm it's
    actually config-driven and not accidentally hard-coded to "PT"."""

    def _tree(self, tmp_root: Path) -> Path:
        data_dir = tmp_root / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: ZZ\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        return data_dir

    def test_new_ls_set_honor_a_non_default_prefix(self):
        tmp_root = helpers.make_empty_tmp_dir(self)
        data_dir = self._tree(tmp_root)

        result = run_cairn(["new", "Prefix-honoring issue", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ZZ-1", result.stdout)
        self.assertTrue((data_dir / "issues" / "ZZ-1.md").exists())
        self.assertFalse((data_dir / "issues" / "PT-1.md").exists())

        ls_result = run_cairn(["ls", "--data-dir", str(data_dir)])
        self.assertIn("ZZ-1", ls_result.stdout)

        set_result = run_cairn(["set", "ZZ-1", "status=todo", "--data-dir", str(data_dir)])
        self.assertEqual(set_result.returncode, 0, set_result.stdout + set_result.stderr)
        frontmatter, _ = cairn.parse_frontmatter((data_dir / "issues" / "ZZ-1.md").read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["status"], "todo")


class ArchiveCommandTests(unittest.TestCase):
    def _tree(self):
        data_dir = helpers.make_tmp_data_dir(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Old and done\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nDone a while ago.\n",
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-3.md").write_text(
            "---\nid: PT-3\ntitle: Recently done\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-10\n---\n\nDone recently.\n",
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-4.md").write_text(
            "---\nid: PT-4\ntitle: Still open\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-01\n---\n\nNot done.\n",
            encoding="utf-8",
        )
        return data_dir

    def test_archive_moves_only_done_issues_before_cutoff(self):
        data_dir = self._tree()
        result = run_cairn(["archive", "--done-before", "2026-02-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertFalse((data_dir / "issues" / "PT-1.md").exists())
        self.assertTrue((data_dir / "archive" / "issues" / "PT-1.md").exists())

        self.assertTrue((data_dir / "issues" / "PT-3.md").exists(), "done but updated after cutoff should stay")
        self.assertTrue((data_dir / "issues" / "PT-4.md").exists(), "not done should never be archived")


class PT8DoneBeforeValidationTests(unittest.TestCase):
    """PT-8: `cairn archive --done-before` must validate its value as a
    real-calendar YYYY-MM-DD date before touching any file. Today it's
    string-compared against each issue's `updated` with no validation at
    all, so malformed input either silently skips issues it should have
    archived, or -- worse -- archives issues it shouldn't have, depending
    on how the garbage string happens to sort lexicographically against
    real dates. Both are the opposite of "clear error, nothing touched"."""

    def _data_dir_with_a_done_issue(self):
        data_dir = helpers.make_tmp_data_dir(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Old and done\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nDone a while ago.\n",
            encoding="utf-8",
        )
        return data_dir

    def test_wrong_format_is_rejected_and_no_file_is_touched(self):
        data_dir = self._data_dir_with_a_done_issue()
        result = run_cairn(["archive", "--done-before", "02/01/2026", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "issues" / "PT-1.md").exists(), "file must not move when validation fails")
        self.assertFalse((data_dir / "archive" / "issues" / "PT-1.md").exists())

    def test_out_of_range_calendar_date_is_rejected(self):
        # Right shape (YYYY-MM-DD), not a real calendar date -- Feb 30
        # doesn't exist. A naive regex-only check would let this through;
        # this pins that the validation is a real calendar parse.
        data_dir = self._data_dir_with_a_done_issue()
        result = run_cairn(["archive", "--done-before", "2026-02-30", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "issues" / "PT-1.md").exists())
        self.assertFalse((data_dir / "archive" / "issues" / "PT-1.md").exists())

    def test_garbage_string_is_rejected(self):
        data_dir = self._data_dir_with_a_done_issue()
        result = run_cairn(["archive", "--done-before", "not-a-date", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "issues" / "PT-1.md").exists())
        self.assertFalse((data_dir / "archive" / "issues" / "PT-1.md").exists())

    def test_valid_date_is_unaffected(self):
        # Regression guard -- a real date must keep behaving exactly as it
        # does today (test_archive_moves_only_done_issues_before_cutoff
        # pins the same shape against a different fixture tree).
        data_dir = self._data_dir_with_a_done_issue()
        result = run_cairn(["archive", "--done-before", "2026-02-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "archive" / "issues" / "PT-1.md").exists())


class PT9DataDirTopLevelOptionTests(unittest.TestCase):
    """PT-9: --data-dir must be accepted as a top-level option (before the
    subcommand), in addition to its current per-subcommand position. The
    both-given precedence is the implementation's documented choice
    (subcommand wins vs. an unambiguous error) -- pinned below in
    test_both_positions_given_the_subcommand_position_wins."""

    def test_data_dir_before_subcommand_is_accepted(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["--data-dir", str(data_dir), "ls"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PT-1", result.stdout)

    def test_data_dir_after_subcommand_still_works(self):
        # Regression guard -- the position that already works today.
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["ls", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PT-1", result.stdout)

    def test_data_dir_before_subcommand_works_for_a_mutating_command_too(self):
        # Not just `ls` (read-only) -- confirm it plumbs through to a
        # command that writes, e.g. `set`.
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["--data-dir", str(data_dir), "set", "PT-1", "status=todo"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        frontmatter, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["status"], "todo")

    def test_help_text_documents_data_dir(self):
        # AC: "implementation picks one and documents it in the --help
        # text." Doesn't pin which choice -- just that top-level --help
        # mentions --data-dir once it's a top-level option.
        result = run_cairn(["--help"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--data-dir", result.stdout)

    def test_both_positions_given_the_subcommand_position_wins(self):
        # PT-9: implementation's documented choice (see --help: "if given
        # in both places, the value after the subcommand takes
        # precedence") -- the more specific position overrides the less
        # specific one. Two data dirs with distinguishable content: the
        # top-level dir keeps the checked-in fixture's PT-1 title, the
        # subcommand-position dir's PT-1 is overwritten with a marker
        # title only it carries.
        top_dir = helpers.make_tmp_data_dir(self)
        sub_dir = helpers.make_tmp_data_dir(self)
        (sub_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: From the subcommand-position dir\nstatus: todo\n"
            "milestone: null\nparent: null\nassignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )

        result = run_cairn(["--data-dir", str(top_dir), "ls", "--data-dir", str(sub_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("From the subcommand-position dir", result.stdout)
        self.assertNotIn("Google OAuth login", result.stdout, "top-level dir's fixture data leaked through")


class ArchiveGitMoveTests(unittest.TestCase):
    """The spec's CLI table is explicit: `cairn archive` is a "Bulk git mv",
    and later: "Archived issues remain in git, remain greppable". A plain
    filesystem move inside a git worktree does NOT preserve that on its
    own -- git only sees a delete + an untracked add until something stages
    it as a rename. This is the gap the (unrecoverable) test_cairn.py draft
    may have covered and mine didn't: verify the move is actually staged as
    a git rename, not just a filesystem move that happens to sit in a repo."""

    def test_archive_stages_a_git_rename_inside_a_repo(self):
        tmp_root = helpers.make_empty_tmp_dir(self)
        subprocess.run(["git", "init", "-q"], cwd=tmp_root, check=True)
        subprocess.run(["git", "config", "user.email", "qa@example.com"], cwd=tmp_root, check=True)
        subprocess.run(["git", "config", "user.name", "qa"], cwd=tmp_root, check=True)

        data_dir = helpers.copy_fixture_data_dir(tmp_root)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Old and done\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nDone a while ago.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=tmp_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=tmp_root, check=True)

        result = run_cairn(["archive", "--done-before", "2026-02-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((data_dir / "issues" / "PT-1.md").exists())
        self.assertTrue((data_dir / "archive" / "issues" / "PT-1.md").exists())

        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=tmp_root, capture_output=True, text=True, check=True
        ).stdout
        # A staged rename shows as "R  <old> -> <new>". A plain filesystem
        # move that git hasn't been told about shows as a deleted line and
        # a separate untracked ("??") line instead -- that's the failure
        # mode this test exists to catch.
        self.assertIn("R  ", status, f"archive did not stage a git rename; git status was:\n{status}")
        self.assertNotIn("??", status, f"archived file is untracked, not staged as a rename:\n{status}")

    def test_archive_falls_back_to_plain_move_outside_a_repo(self):
        # Not every data_dir lives inside a git worktree in every test setup
        # -- confirm archive still works (doesn't crash on a missing git)
        # when there's no repo to stage a rename into.
        data_dir = helpers.make_tmp_data_dir(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Old and done\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nDone a while ago.\n",
            encoding="utf-8",
        )
        result = run_cairn(["archive", "--done-before", "2026-02-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "archive" / "issues" / "PT-1.md").exists())


class DiscoveryErrorTests(unittest.TestCase):
    """MUST-FIX finding 3 (architect conformance review): when no
    `--data-dir` is given, `find_data_dir` walks up from cwd looking for
    `process/cairn/config.yml`; if it never finds one it falls back to
    `cwd / "process" / "cairn"` regardless, and every command downstream
    (`_dir_glob` etc.) treats a nonexistent/empty directory exactly like a
    real, empty tracker -- silent 0-exit, no output, no hint that discovery
    failed. Ruled: `data_dir` in config.yml stays inert (spec being
    amended), discovery stays hardcoded to `process/cairn/`, but a
    resolution with no `config.yml` at the end of it must be a LOUD error
    (nonzero exit, pointed message), never an empty list. Both tests here
    deliberately omit `--data-dir` to exercise the real discovery path, and
    are RED against current cairn.py (which exits 0 with empty stdout in
    both cases)."""

    def _env_without_override(self) -> dict:
        env = os.environ.copy()
        env.pop("CAIRN_DATA_DIR", None)
        return env

    def test_ls_with_no_process_cairn_anywhere_up_the_tree_errors_loudly(self):
        # A bare tmp dir under the system temp root -- walking up from here
        # never reaches this repo's real process/cairn/config.yml.
        tmp_root = helpers.make_empty_tmp_dir(self)
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "ls"],
            cwd=str(tmp_root), capture_output=True, text=True, env=self._env_without_override(),
        )
        self.assertNotEqual(
            result.returncode, 0,
            "an undiscoverable data dir must be a loud error, not a silent empty result "
            f"(stdout={result.stdout!r} stderr={result.stderr!r})",
        )
        self.assertEqual(result.stdout.strip(), "", "no issue lines should print on a discovery failure")

    def test_ls_with_data_dir_present_but_config_yml_missing_errors_loudly(self):
        tmp_root = helpers.make_empty_tmp_dir(self)
        cairn_dir = tmp_root / "process" / "cairn"
        (cairn_dir / "issues").mkdir(parents=True)
        (cairn_dir / "archive").mkdir(parents=True)
        (cairn_dir / "milestones").mkdir(parents=True)
        (cairn_dir / "majors").mkdir(parents=True)
        # Deliberately no config.yml -- the directory shape is right but the
        # thing that would confirm "this is really a tracker" is absent.
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "ls"],
            cwd=str(tmp_root), capture_output=True, text=True, env=self._env_without_override(),
        )
        self.assertNotEqual(
            result.returncode, 0,
            "a data dir with no config.yml must error, not silently proceed as if it were empty "
            f"(stdout={result.stdout!r} stderr={result.stderr!r})",
        )

    # PT-80 (AC2/AC4): `check` and `serve` extend the same coverage `ls`
    # already had -- both already route through resolve_data_dir before
    # touching load_config, so these are regression tests confirming that
    # stays true, not reproductions of PT-80's actual bug (which lives in
    # load_config itself, pinned in test_load_config_raises.py -- any
    # DIRECT caller of load_config, bypassing resolve_data_dir, is where
    # the silent default actually happens). Also the first tests in this
    # class to assert the resolved PATH actually appears in stderr, per
    # PT-80 AC4's literal wording ("asserts exit 1 and the path in
    # stderr") -- the existing `ls` tests above only assert a nonzero
    # exit.

    def test_cairn_data_dir_env_var_pointing_at_a_dir_with_no_config_yml_errors_loudly(self):
        # Distinct code path from the two `ls` tests above: CAIRN_DATA_DIR
        # explicitly SET (not cwd walk-up discovery). resolve_data_dir
        # applies the same config.yml-existence check regardless of where
        # data_dir came from, so -- like the check/serve tests below --
        # this is regression coverage for a path already correct today,
        # not a red-first reproduction.
        tmp_root = helpers.make_empty_tmp_dir(self)
        bogus_data_dir = helpers.make_empty_tmp_dir(self)  # exists, no config.yml
        env = self._env_without_override()
        env["CAIRN_DATA_DIR"] = str(bogus_data_dir)
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "ls"],
            cwd=str(tmp_root), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 1, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn(str(bogus_data_dir), result.stderr, f"error must name the CAIRN_DATA_DIR path -- got: {result.stderr!r}")

    def test_check_with_no_process_cairn_anywhere_up_the_tree_errors_loudly(self):
        tmp_root = helpers.make_empty_tmp_dir(self)
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check"],
            cwd=str(tmp_root), capture_output=True, text=True, env=self._env_without_override(),
        )
        self.assertEqual(result.returncode, 1, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        expected_data_dir = tmp_root / "process" / "cairn"
        self.assertIn(str(expected_data_dir), result.stderr, f"error must name the resolved path -- got: {result.stderr!r}")

    def test_check_with_data_dir_present_but_config_yml_missing_errors_loudly(self):
        tmp_root = helpers.make_empty_tmp_dir(self)
        cairn_dir = tmp_root / "process" / "cairn"
        (cairn_dir / "issues").mkdir(parents=True)
        (cairn_dir / "archive").mkdir(parents=True)
        (cairn_dir / "milestones").mkdir(parents=True)
        (cairn_dir / "majors").mkdir(parents=True)
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check"],
            cwd=str(tmp_root), capture_output=True, text=True, env=self._env_without_override(),
        )
        self.assertEqual(result.returncode, 1, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn(str(cairn_dir), result.stderr, f"error must name the resolved path -- got: {result.stderr!r}")

    def test_serve_with_no_process_cairn_anywhere_up_the_tree_errors_loudly_and_exits_promptly(self):
        # Must fail BEFORE server.serve_forever() is ever reached -- a
        # generous timeout is a safety net against a regression that
        # moves the check too late and hangs the process instead of
        # exiting, not an expected-duration budget.
        tmp_root = helpers.make_empty_tmp_dir(self)
        try:
            result = subprocess.run(
                [str(helpers.CAIRN_BIN), "serve"],
                cwd=str(tmp_root), capture_output=True, text=True, env=self._env_without_override(),
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            self.fail("cairn serve must exit immediately on an undiscoverable data dir, not hang in serve_forever()")
        self.assertEqual(result.returncode, 1, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        expected_data_dir = tmp_root / "process" / "cairn"
        self.assertIn(str(expected_data_dir), result.stderr, f"error must name the resolved path -- got: {result.stderr!r}")

    def test_serve_with_data_dir_present_but_config_yml_missing_errors_loudly_and_exits_promptly(self):
        tmp_root = helpers.make_empty_tmp_dir(self)
        cairn_dir = tmp_root / "process" / "cairn"
        (cairn_dir / "issues").mkdir(parents=True)
        (cairn_dir / "archive").mkdir(parents=True)
        (cairn_dir / "milestones").mkdir(parents=True)
        (cairn_dir / "majors").mkdir(parents=True)
        try:
            result = subprocess.run(
                [str(helpers.CAIRN_BIN), "serve"],
                cwd=str(tmp_root), capture_output=True, text=True, env=self._env_without_override(),
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            self.fail("cairn serve must exit immediately on a config-less data dir, not hang in serve_forever()")
        self.assertEqual(result.returncode, 1, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn(str(cairn_dir), result.stderr, f"error must name the resolved path -- got: {result.stderr!r}")


class ErrorHandlingTests(unittest.TestCase):
    def test_unknown_subcommand_fails_loudly(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["bogus-command", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
