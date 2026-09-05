"""PT-85 failing acceptance tests: `/api/flow` gains a throughput view --
per-period opened/closed/WIP/cancelled, milestone-scoped -- derived from
the SAME git walk `_compute_flow_payload` (PT-61) already does.

Pinned to the architect's gating ruling, process/cairn/issues/PT-85.md
("@architect -- 2026-09-05", commit 409d310) -- read it before anything
else.

## The trap this file exists to catch (§2)

The walk keys on `Path(event["path"]).stem`, so `issues/PT-86.md` and
`archive/issues/PT-86.md` are the SAME stem. An archive move can surface
as a delete-plus-add; an implementation that scores "opened" as
"reappeared in `live`" will count every archive move as a brand-new
issue. PT-84 measured a real 7-file bulk-archive commit -- the issue
equivalent would spike "opened" by however many files move together on
a day nothing was actually opened.

Required fix (§2): a `seen_stems` set across the WHOLE walk; open counts
a stem only on its first-ever appearance. `closed` keys on a TRANSITION
(previous status != done, new status == done), so an already-done issue
that gets archived-and-re-added is not recounted. A delete (`status_letter
== "D"`) removes the stem from `live` but must NOT clear it from
`seen_stems`.

## §8's own instruction: the fixture shape IS the test

"A fixture that only ever appends new files will pass a broken
implementation." Every fixture built here includes: issues created,
issues edited in place (status flips), an issue moved to
`archive/issues/`, one issue genuinely DELETED (not moved), and --
critically -- one single commit that archives SEVERAL issues at once
(the §2 trap's natural habitat, per PT-84's measured 7-file shape).

## What this file does NOT cover yet

The period-boundary (local vs UTC day) question is open -- the ruling's
§3 claims today's day-bucketing is "local, not UTC", but reading
`_parse_flow_events` shows it converts every commit to UTC via
`.astimezone(utc)` before taking `.date()`, which is UTC bucketing, not
local. Flagged to team-lead/architect; every fixture below uses
unambiguous UTC (`+0000`) commit times so it is not exercised here
either way (same sidestep test_dashboard_flow.py's own `_commit_at`
docstring already uses). A dedicated boundary test lands once that's
resolved.

## Payload schema (agreed with implementation-lead -- update if it
changes)

`build_flow_payload`'s payload gains a `throughput` key:
    {"overall": [{"date": ..., "opened": N, "closed": N, "wip": N, "cancelled": N}, ...],
     "by_milestone": {"<milestone-id>": [ ...same shape... ], ...}}
plus `milestones` (available ids) and `default_milestone` (most recent
activity). `_call_flow_throughput` below asserts the shape exists with a
clear message before any test relies on it, so a schema mismatch fails
loudly rather than as a buried KeyError.
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from typing import Optional

import helpers  # noqa: F401

import cairn

ISSUE_TMPL = (
    "---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\nparent: null\n"
    "assignee: null\nlabels: []\npriority: null\npr: null\ncreated: 2026-08-01\nupdated: 2026-08-01\n"
    "---\n\nBody.\n"
)
MAJOR_TMPL = "---\nid: {id}\nstatus: {status}\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"


def _git(cwd: Path, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result


def _commit_at(repo_root: Path, message: str, when: str) -> None:
    """`when`: git raw date, e.g. '2026-08-10 10:00:00 +0000' -- always
    UTC (+0000), same sidestep test_dashboard_flow.py's own `_commit_at`
    already takes, since the local-vs-UTC day convention is unresolved
    (see module docstring)."""
    env = dict(os.environ)
    env["GIT_AUTHOR_DATE"] = when
    env["GIT_COMMITTER_DATE"] = when
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    _git(repo_root, "add", "-A", env=env)
    _git(repo_root, "commit", "-q", "-m", message, env=env)


def make_flow_git_repo(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "test@example.com")
    _git(tmp, "config", "user.name", "Test")
    data_dir = tmp / "process" / "cairn"
    for sub in ("issues", "archive/issues", "archive/milestones", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    (data_dir / "majors" / "PT-V1.md").write_text(MAJOR_TMPL.format(id="PT-V1", status="in-progress"), encoding="utf-8")
    (tmp / "README.md").write_text("placeholder\n", encoding="utf-8")
    _commit_at(tmp, "initial", "2026-08-09 09:00:00 +0000")
    return data_dir


def _write_issue(data_dir: Path, *, id: str, status: str, milestone: Optional[str] = None, archived: bool = False) -> Path:
    rel = "archive/issues" if archived else "issues"
    path = data_dir / rel / f"{id}.md"
    path.write_text(
        ISSUE_TMPL.format(id=id, title=f"Issue {id}", status=status, milestone=(milestone or "null")),
        encoding="utf-8",
    )
    return path


def _call_flow_throughput(data_dir: Path) -> dict:
    """Every test routes through here so a missing/mis-shaped throughput
    payload fails with one clear message instead of an opaque KeyError."""
    assert hasattr(cairn, "build_flow_payload"), (
        "cairn.build_flow_payload does not exist -- PT-61's chart data source is unimplemented"
    )
    payload = cairn.build_flow_payload(data_dir)
    assert "throughput" in payload, (
        f"PT-85's payload must carry a top-level 'throughput' key -- got top-level keys "
        f"{sorted(payload.keys())!r}"
    )
    throughput = payload["throughput"]
    assert "overall" in throughput, f"throughput must carry an 'overall' series -- got {sorted(throughput.keys())!r}"
    assert "by_milestone" in throughput, f"throughput must carry 'by_milestone' -- got {sorted(throughput.keys())!r}"
    return payload


def _points_by_date(points: list) -> dict:
    return {p["date"]: p for p in points}


# --------------------------------------------------------------------------
# §2's own named trap: the bulk-archive-move day must show opened: 0.
# --------------------------------------------------------------------------

class SeenStemsOpenedOnceTests(unittest.TestCase):
    def test_a_bulk_archive_commit_touching_several_issues_shows_zero_opened(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        # Day 1: three issues created (three real opens).
        for stem in ("PT-1", "PT-2", "PT-3"):
            _write_issue(data_dir, id=stem, status="todo")
        _commit_at(repo_root, "create PT-1/2/3", "2026-08-10 10:00:00 +0000")

        # Day 2: ALL THREE archived together, one commit -- PT-84's
        # measured 7-file bulk-archive shape, scaled down for a fixture.
        for stem in ("PT-1", "PT-2", "PT-3"):
            _git(repo_root, "mv", f"process/cairn/issues/{stem}.md", f"process/cairn/archive/issues/{stem}.md")
        _commit_at(repo_root, "bulk archive PT-1/2/3", "2026-08-11 10:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        overall = _points_by_date(payload["throughput"]["overall"])
        self.assertEqual(
            overall["2026-08-10"]["opened"], 3,
            f"day 1 (three real creations) must show opened: 3 -- got {overall.get('2026-08-10')!r}",
        )
        self.assertEqual(
            overall["2026-08-11"]["opened"], 0,
            f"a bulk-archive-move day (three files re-appearing under a new path, same stems) must "
            f"show opened: 0, not 3 -- a stem-appearance-based 'opened' would wrongly spike here, "
            f"got {overall.get('2026-08-11')!r}",
        )


class DeleteDoesNotClearSeenStemsTests(unittest.TestCase):
    def test_a_deleted_then_readded_stem_is_not_counted_as_a_new_open(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-4", status="todo")
        _commit_at(repo_root, "create PT-4", "2026-08-10 10:00:00 +0000")

        (data_dir / "issues" / "PT-4.md").unlink()
        _commit_at(repo_root, "delete PT-4", "2026-08-11 10:00:00 +0000")

        # Re-add the SAME stem later -- a naive "opened = reappeared" would
        # count this as a new open; seen_stems must prevent that, per the
        # ruling's explicit "a D event must not clear the seen set".
        _write_issue(data_dir, id="PT-4", status="todo")
        _commit_at(repo_root, "re-add PT-4", "2026-08-12 10:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        overall = _points_by_date(payload["throughput"]["overall"])
        self.assertEqual(overall["2026-08-10"]["opened"], 1, "the original creation is a real open")
        self.assertEqual(
            overall["2026-08-12"]["opened"], 0,
            f"re-adding a previously-deleted stem must NOT count as a new open -- "
            f"got {overall.get('2026-08-12')!r}",
        )


# --------------------------------------------------------------------------
# `closed` keys on a TRANSITION, never on stem-reappearance.
# --------------------------------------------------------------------------

class ClosedKeysOnTransitionTests(unittest.TestCase):
    def test_an_already_done_issue_archived_and_readded_is_not_recounted_as_closed(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-5", status="todo")
        _commit_at(repo_root, "create PT-5", "2026-08-10 10:00:00 +0000")

        _write_issue(data_dir, id="PT-5", status="done")
        _commit_at(repo_root, "PT-5 -> done", "2026-08-11 10:00:00 +0000")

        # Archived AFTER already being done -- a real, common shape (done
        # issues get archived later). Still the same stem, still "done".
        _git(repo_root, "mv", "process/cairn/issues/PT-5.md", "process/cairn/archive/issues/PT-5.md")
        _commit_at(repo_root, "archive already-done PT-5", "2026-08-12 10:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        overall = _points_by_date(payload["throughput"]["overall"])
        self.assertEqual(
            overall["2026-08-11"]["closed"], 1,
            f"the actual done-transition is the one real close -- got {overall.get('2026-08-11')!r}",
        )
        self.assertEqual(
            overall["2026-08-12"]["closed"], 0,
            f"archiving an ALREADY-done issue must not re-count it as closed -- there is no status "
            f"transition on the archive-move day -- got {overall.get('2026-08-12')!r}",
        )

    def test_a_transition_into_cancelled_counts_as_neither_opened_nor_closed(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-6", status="todo")
        _commit_at(repo_root, "create PT-6", "2026-08-10 10:00:00 +0000")

        _write_issue(data_dir, id="PT-6", status="cancelled")
        _commit_at(repo_root, "PT-6 -> cancelled", "2026-08-11 10:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        overall = _points_by_date(payload["throughput"]["overall"])
        self.assertEqual(overall["2026-08-10"]["opened"], 1)
        self.assertEqual(
            overall["2026-08-11"]["closed"], 0,
            f"a transition into cancelled must NOT count as closed -- got {overall.get('2026-08-11')!r}",
        )
        self.assertEqual(
            overall["2026-08-11"].get("opened", 0), 0,
            f"a transition into cancelled must not count as a fresh open either -- "
            f"got {overall.get('2026-08-11')!r}",
        )
        self.assertEqual(
            overall["2026-08-11"]["cancelled"], 1,
            f"the cancelled count must reflect the transition -- got {overall.get('2026-08-11')!r}",
        )


# --------------------------------------------------------------------------
# WIP is in-progress + in-review, measured at the END of each period.
# --------------------------------------------------------------------------

class WipEndOfPeriodTests(unittest.TestCase):
    def test_an_issue_passing_through_in_progress_mid_period_is_not_counted_as_wip_if_it_lands_elsewhere(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-7", status="todo")
        _commit_at(repo_root, "create PT-7", "2026-08-10 09:00:00 +0000")
        # Same day: passes THROUGH in-progress...
        _write_issue(data_dir, id="PT-7", status="in-progress")
        _commit_at(repo_root, "PT-7 -> in-progress, same day", "2026-08-10 12:00:00 +0000")
        # ...and lands in done by the END of the same period.
        _write_issue(data_dir, id="PT-7", status="done")
        _commit_at(repo_root, "PT-7 -> done, same day", "2026-08-10 18:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        overall = _points_by_date(payload["throughput"]["overall"])
        self.assertEqual(
            overall["2026-08-10"]["wip"], 0,
            f"PT-7 passed THROUGH in-progress but is 'done' by the end of the period -- WIP is "
            f"point-in-time at period END, not 'was ever in-progress during the period' -- "
            f"got {overall.get('2026-08-10')!r}",
        )
        self.assertEqual(
            overall["2026-08-10"]["closed"], 1,
            "the same-period done transition is still a real close",
        )

    def test_an_issue_still_in_progress_at_periods_end_counts_as_wip(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-8", status="todo")
        _commit_at(repo_root, "create PT-8", "2026-08-10 10:00:00 +0000")
        _write_issue(data_dir, id="PT-8", status="in-progress")
        _commit_at(repo_root, "PT-8 -> in-progress", "2026-08-11 10:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        overall = _points_by_date(payload["throughput"]["overall"])
        self.assertEqual(
            overall["2026-08-11"]["wip"], 1,
            f"PT-8 is in-progress at the end of 2026-08-11 with no later event -- must count as "
            f"WIP -- got {overall.get('2026-08-11')!r}",
        )

    def test_in_review_also_counts_as_wip_backlog_and_todo_do_not(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-9", status="in-review")
        _write_issue(data_dir, id="PT-10", status="backlog")
        _write_issue(data_dir, id="PT-11", status="todo")
        _commit_at(repo_root, "create PT-9/10/11", "2026-08-10 10:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        overall = _points_by_date(payload["throughput"]["overall"])
        self.assertEqual(
            overall["2026-08-10"]["wip"], 1,
            f"only in-review (PT-9) counts as WIP; backlog/todo (PT-10/PT-11) are queue depth, "
            f"not work in flight -- got {overall.get('2026-08-10')!r}",
        )


# --------------------------------------------------------------------------
# Milestone scope reads the milestone recorded in the blob AT THAT EVENT --
# never the issue's current/latest milestone applied retroactively.
# --------------------------------------------------------------------------

class MilestoneFromBlobAtEventTests(unittest.TestCase):
    def test_early_activity_stays_under_the_milestone_recorded_at_that_time(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-12", status="todo", milestone="PT-0.1")
        _commit_at(repo_root, "create PT-12 under PT-0.1", "2026-08-10 10:00:00 +0000")

        # Later: the SAME issue's milestone field changes.
        _write_issue(data_dir, id="PT-12", status="in-progress", milestone="PT-0.2")
        _commit_at(repo_root, "PT-12 moves to PT-0.2", "2026-08-11 10:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        by_milestone = payload["throughput"]["by_milestone"]
        self.assertIn("PT-0.1", by_milestone, f"expected a PT-0.1 bucket -- got {sorted(by_milestone.keys())!r}")
        self.assertIn("PT-0.2", by_milestone, f"expected a PT-0.2 bucket -- got {sorted(by_milestone.keys())!r}")

        pt01_points = _points_by_date(by_milestone["PT-0.1"])
        pt02_points = _points_by_date(by_milestone["PT-0.2"])
        self.assertEqual(
            pt01_points.get("2026-08-10", {}).get("opened", 0), 1,
            f"PT-12's creation must be attributed to PT-0.1, the milestone recorded AT THAT EVENT -- "
            f"got PT-0.1's 2026-08-10 point: {pt01_points.get('2026-08-10')!r}",
        )
        self.assertEqual(
            pt02_points.get("2026-08-10", {}).get("opened", 0), 0,
            f"the creation must NOT be retroactively moved to PT-0.2 (today's/latest milestone) -- "
            f"got PT-0.2's 2026-08-10 point: {pt02_points.get('2026-08-10')!r}",
        )


# --------------------------------------------------------------------------
# Payload shape sanity -- overall/by_milestone use the same point shape,
# and milestone metadata for the scope control is present.
# --------------------------------------------------------------------------

class ThroughputPayloadShapeTests(unittest.TestCase):
    def test_every_overall_point_carries_opened_closed_wip_cancelled(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-13", status="todo")
        _commit_at(repo_root, "create PT-13", "2026-08-10 10:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        expected_keys = {"date", "opened", "closed", "wip", "cancelled"}
        for point in payload["throughput"]["overall"]:
            self.assertEqual(
                set(point.keys()), expected_keys,
                f"every throughput point must carry exactly {expected_keys} -- got {point!r}",
            )

    def test_milestones_list_and_default_milestone_are_present(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-14", status="todo", milestone="PT-0.3")
        _commit_at(repo_root, "create PT-14 under PT-0.3", "2026-08-10 10:00:00 +0000")

        payload = _call_flow_throughput(data_dir)
        self.assertIn("milestones", payload, f"expected a top-level 'milestones' list for the scope control -- got {sorted(payload.keys())!r}")
        self.assertIn("PT-0.3", payload["milestones"], f"got {payload['milestones']!r}")
        self.assertIn("default_milestone", payload, f"expected a top-level 'default_milestone' -- got {sorted(payload.keys())!r}")
        self.assertEqual(
            payload["default_milestone"], "PT-0.3",
            "the only milestone with any activity must be the default",
        )
