"""PT-85 failing acceptance tests: `/api/flow` gains a throughput view --
per-period opened/closed/WIP/cancelled, milestone-scoped -- derived from
the SAME git walk `_compute_flow_payload` (PT-61) already does.

Pinned to the architect's gating ruling, process/cairn/issues/PT-85.md
("@architect -- 2026-09-05", commit 409d310, §3 corrected at e974a0e/
123aa54, payload shape pinned at 2f8eba0) -- read it before anything
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

## §3 (corrected): day buckets are UTC

The architect's original ruling claimed today's day-bucketing is
"local, not UTC"; both implementation-lead and I independently read
`_parse_flow_events` and found it does `.astimezone(utc).date()` --
UTC bucketing. Corrected at e974a0e, verified by execution at 123aa54.
`UtcDayBoundaryTests` below is the discriminating fixture (a late-
evening local-offset commit that lands on the next UTC day) -- a
fixture built only from mid-day commits cannot tell the two
conventions apart.

## Payload schema (pinned by the architect at 2f8eba0 -- the third,
authoritative revision; my two earlier guesses in this file's history
used a wrong `throughput: {overall, by_milestone}` wrapper and then a
bare `milestone` key/plain-string milestones list)

    {"period": "day",
     "series": [{"date": "YYYY-MM-DD",
                 "opened": n, "closed": n, "cancelled": n, "wip": n,
                 "by_milestone": {"<id>": {"opened": n, "closed": n,
                                           "cancelled": n, "wip": n}, ...}}],
     "milestones": [{"id": "...", "name": "..."|null, "status": "..."|null}],
     "default_milestone": "<id>"|null,
     "as_of": "<head sha>", "scope": "...", "warning": "..."|absent}

Top-level `opened`/`closed`/`cancelled`/`wip` are OVERALL (every stem,
including any with no milestone recorded). `by_milestone` is DENSE once
a milestone has first appeared -- every already-seen milestone appears
on EVERY later point, zeros for the deltas and the CARRIED value for
`wip` (never absent, since a missing day would ambiguously mean either
"zero delta" or "unchanged WIP" -- the ruling's own point: mixing two
gap semantics in one sparse structure is PT-85's defect reproduced in
the schema). `default_milestone`'s "activity" is a TRANSITION (nonzero
opened/closed/cancelled), never standing WIP alone, else an abandoned
milestone with stale in-progress issues would stay the default forever.
`period` names the granularity the SERVER emits (always "day" -- the
client aggregates for the week toggle: sum opened/closed/cancelled,
take the LAST wip of the week, never a sum/mean of WIP).
`_call_flow_payload` below asserts the top-level keys exist with a
clear message before any test relies on them, so a schema mismatch
fails loudly rather than as a buried KeyError.
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
MILESTONE_TMPL = "---\nid: {id}\nname: {name}\nkind: product\nmajor: PT-V1\nstatus: {status}\ntarget_tag: null\nga: false\n---\n\nBody.\n"


def _git(cwd: Path, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result


def _commit_at(repo_root: Path, message: str, when: str) -> None:
    """`when`: git raw date, e.g. '2026-08-10 10:00:00 +0000' (UTC) or
    '2026-03-10 23:30:00 -0700' (a local offset, for UtcDayBoundaryTests
    specifically -- every other fixture uses +0000 so the day-convention
    question is never accidentally exercised by tests that aren't about
    it)."""
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


def _write_milestone(data_dir: Path, *, id: str, name: str, status: str = "in-progress") -> Path:
    """A CURRENT milestone record -- `name`/`status` in the payload's
    `milestones` list come from these files as they stand at HEAD, per
    the ruling ("name/status come from the current milestone records"),
    never from history."""
    path = data_dir / "milestones" / f"{id}.md"
    path.write_text(MILESTONE_TMPL.format(id=id, name=name, status=status), encoding="utf-8")
    return path


def _call_flow_payload(data_dir: Path) -> dict:
    """Every test routes through here so a missing/mis-shaped payload
    fails with one clear message instead of an opaque KeyError."""
    assert hasattr(cairn, "build_flow_payload"), (
        "cairn.build_flow_payload does not exist -- PT-61's chart data source is unimplemented"
    )
    payload = cairn.build_flow_payload(data_dir)
    for key in ("series", "milestones", "default_milestone", "period"):
        assert key in payload, (
            f"PT-85's payload must carry '{key}' -- got top-level keys {sorted(payload.keys())!r}"
        )
    return payload


def _points_by_date(points: list) -> dict:
    return {p["date"]: p for p in points}


def _milestone_ids(payload: dict) -> set:
    return {m["id"] for m in payload["milestones"]}


def _by_milestone(point: dict, milestone_id: str) -> dict:
    """A milestone sub-point. Once a milestone has appeared, the ruling
    (2f8eba0, change 1) requires it DENSE on every later point -- a
    missing key past that point is itself a bug. Before a milestone's
    first appearance, absence is correct; tests that need to
    distinguish the two check for KEY PRESENCE explicitly rather than
    relying on this default."""
    return point.get("by_milestone", {}).get(milestone_id, {"opened": 0, "closed": 0, "cancelled": 0, "wip": 0})


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

        payload = _call_flow_payload(data_dir)
        points = _points_by_date(payload["series"])
        self.assertEqual(
            points["2026-08-10"]["opened"], 3,
            f"day 1 (three real creations) must show opened: 3 -- got {points.get('2026-08-10')!r}",
        )
        self.assertEqual(
            points["2026-08-11"]["opened"], 0,
            f"a bulk-archive-move day (three files re-appearing under a new path, same stems) must "
            f"show opened: 0, not 3 -- a stem-appearance-based 'opened' would wrongly spike here, "
            f"got {points.get('2026-08-11')!r}",
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

        payload = _call_flow_payload(data_dir)
        points = _points_by_date(payload["series"])
        self.assertEqual(points["2026-08-10"]["opened"], 1, "the original creation is a real open")
        self.assertEqual(
            points["2026-08-12"]["opened"], 0,
            f"re-adding a previously-deleted stem must NOT count as a new open -- "
            f"got {points.get('2026-08-12')!r}",
        )


# --------------------------------------------------------------------------
# §3 (corrected, e974a0e): day buckets are UTC, not local-offset --
# demonstrated by the architect at 123aa54 (a 23:30 PDT commit buckets to
# the NEXT UTC day). A fixture built entirely from mid-day commits passes
# under either convention and so cannot detect a silent flip -- this one
# deliberately can't.
# --------------------------------------------------------------------------

class UtcDayBoundaryTests(unittest.TestCase):
    def test_a_late_evening_local_commit_buckets_to_the_next_utc_day(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-15", status="todo")
        # 23:30 PDT (-0700) on 2026-03-10 is 06:30 UTC on 2026-03-11 --
        # the exact case the architect measured directly against
        # _parse_flow_events (123aa54).
        _commit_at(repo_root, "create PT-15 late evening PDT", "2026-03-10 23:30:00 -0700")

        payload = _call_flow_payload(data_dir)
        points = _points_by_date(payload["series"])
        self.assertNotIn(
            "2026-03-10", points,
            f"a commit at 23:30 PDT on 2026-03-10 must NOT bucket to the LOCAL calendar day -- "
            f"got points {sorted(points.keys())!r}",
        )
        self.assertIn(
            "2026-03-11", points,
            f"a commit at 23:30 PDT on 2026-03-10 (06:30 UTC on 2026-03-11) must bucket to the "
            f"UTC day 2026-03-11 -- got points {sorted(points.keys())!r}",
        )
        self.assertEqual(
            points["2026-03-11"]["opened"], 1,
            f"the late-evening-PDT creation must be the sole open on the UTC day -- "
            f"got {points['2026-03-11']!r}",
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

        payload = _call_flow_payload(data_dir)
        points = _points_by_date(payload["series"])
        self.assertEqual(
            points["2026-08-11"]["closed"], 1,
            f"the actual done-transition is the one real close -- got {points.get('2026-08-11')!r}",
        )
        self.assertEqual(
            points["2026-08-12"]["closed"], 0,
            f"archiving an ALREADY-done issue must not re-count it as closed -- there is no status "
            f"transition on the archive-move day -- got {points.get('2026-08-12')!r}",
        )

    def test_a_transition_into_cancelled_counts_as_neither_opened_nor_closed(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-6", status="todo")
        _commit_at(repo_root, "create PT-6", "2026-08-10 10:00:00 +0000")

        _write_issue(data_dir, id="PT-6", status="cancelled")
        _commit_at(repo_root, "PT-6 -> cancelled", "2026-08-11 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        points = _points_by_date(payload["series"])
        self.assertEqual(points["2026-08-10"]["opened"], 1)
        self.assertEqual(
            points["2026-08-11"]["closed"], 0,
            f"a transition into cancelled must NOT count as closed -- got {points.get('2026-08-11')!r}",
        )
        self.assertEqual(
            points["2026-08-11"].get("opened", 0), 0,
            f"a transition into cancelled must not count as a fresh open either -- "
            f"got {points.get('2026-08-11')!r}",
        )
        self.assertEqual(
            points["2026-08-11"]["cancelled"], 1,
            f"the cancelled count must reflect the transition -- got {points.get('2026-08-11')!r}",
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

        payload = _call_flow_payload(data_dir)
        points = _points_by_date(payload["series"])
        self.assertEqual(
            points["2026-08-10"]["wip"], 0,
            f"PT-7 passed THROUGH in-progress but is 'done' by the end of the period -- WIP is "
            f"point-in-time at period END, not 'was ever in-progress during the period' -- "
            f"got {points.get('2026-08-10')!r}",
        )
        self.assertEqual(
            points["2026-08-10"]["closed"], 1,
            "the same-period done transition is still a real close",
        )

    def test_an_issue_still_in_progress_at_periods_end_counts_as_wip(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-8", status="todo")
        _commit_at(repo_root, "create PT-8", "2026-08-10 10:00:00 +0000")
        _write_issue(data_dir, id="PT-8", status="in-progress")
        _commit_at(repo_root, "PT-8 -> in-progress", "2026-08-11 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        points = _points_by_date(payload["series"])
        self.assertEqual(
            points["2026-08-11"]["wip"], 1,
            f"PT-8 is in-progress at the end of 2026-08-11 with no later event -- must count as "
            f"WIP -- got {points.get('2026-08-11')!r}",
        )

    def test_in_review_also_counts_as_wip_backlog_and_todo_do_not(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-9", status="in-review")
        _write_issue(data_dir, id="PT-10", status="backlog")
        _write_issue(data_dir, id="PT-11", status="todo")
        _commit_at(repo_root, "create PT-9/10/11", "2026-08-10 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        points = _points_by_date(payload["series"])
        self.assertEqual(
            points["2026-08-10"]["wip"], 1,
            f"only in-review (PT-9) counts as WIP; backlog/todo (PT-10/PT-11) are queue depth, "
            f"not work in flight -- got {points.get('2026-08-10')!r}",
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

        payload = _call_flow_payload(data_dir)
        ids = _milestone_ids(payload)
        self.assertIn("PT-0.1", ids, f"expected PT-0.1 in the scope list -- got {ids!r}")
        self.assertIn("PT-0.2", ids, f"expected PT-0.2 in the scope list -- got {ids!r}")

        points = _points_by_date(payload["series"])
        day1 = points.get("2026-08-10", {})
        self.assertEqual(
            _by_milestone(day1, "PT-0.1")["opened"], 1,
            f"PT-12's creation must be attributed to PT-0.1, the milestone recorded AT THAT EVENT -- "
            f"got day1's PT-0.1 sub-point: {_by_milestone(day1, 'PT-0.1')!r}",
        )
        self.assertEqual(
            _by_milestone(day1, "PT-0.2")["opened"], 0,
            f"the creation must NOT be retroactively moved to PT-0.2 (today's/latest milestone) -- "
            f"got day1's PT-0.2 sub-point: {_by_milestone(day1, 'PT-0.2')!r}",
        )


# --------------------------------------------------------------------------
# 2f8eba0 change 1: by_milestone is DENSE once a milestone has first
# appeared -- a gap day still carries a zeroed delta and the CARRIED wip,
# never absence (absence would mix two incompatible gap semantics: delta
# fields treat a missing day as zero, wip treats it as unchanged).
# --------------------------------------------------------------------------

class ByMilestoneDensityTests(unittest.TestCase):
    def test_a_milestone_stays_present_with_zero_deltas_and_carried_wip_on_a_day_with_no_events_for_it(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        _write_issue(data_dir, id="PT-16", status="in-progress", milestone="PT-0.4")
        _commit_at(repo_root, "create PT-16 under PT-0.4, in-progress", "2026-08-10 10:00:00 +0000")

        # A day with an event for a DIFFERENT (unrelated) stem/milestone --
        # PT-0.4 itself has no event on this day, but has already appeared.
        _write_issue(data_dir, id="PT-17", status="todo", milestone="PT-0.5")
        _commit_at(repo_root, "create PT-17 under PT-0.5", "2026-08-11 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        points = _points_by_date(payload["series"])
        day2 = points["2026-08-11"]
        self.assertIn(
            "PT-0.4", day2.get("by_milestone", {}),
            f"PT-0.4 already appeared on 2026-08-10 -- it must stay present (dense), not vanish "
            f"on a day it had no events -- got by_milestone keys {list(day2.get('by_milestone', {}).keys())!r}",
        )
        self.assertEqual(
            _by_milestone(day2, "PT-0.4"),
            {"opened": 0, "closed": 0, "cancelled": 0, "wip": 1},
            f"PT-0.4's deltas must be zeroed (no event that day) but wip must be CARRIED (still 1, "
            f"PT-16 is still in-progress) -- got {_by_milestone(day2, 'PT-0.4')!r}",
        )


# --------------------------------------------------------------------------
# 2f8eba0 change 3: default_milestone's "activity" is a TRANSITION, never
# standing WIP alone -- else an abandoned milestone with stale in-progress
# issues stays the default forever.
# --------------------------------------------------------------------------

class DefaultMilestoneRequiresTransitionTests(unittest.TestCase):
    def test_a_milestone_with_only_standing_wip_and_no_transitions_is_never_the_default(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        # Milestone A: a real transition (open) on day 1.
        _write_issue(data_dir, id="PT-18", status="todo", milestone="PT-0.6")
        _commit_at(repo_root, "create PT-18 under PT-0.6", "2026-08-10 10:00:00 +0000")
        _write_issue(data_dir, id="PT-18", status="in-progress", milestone="PT-0.6")
        _commit_at(repo_root, "PT-18 -> in-progress under PT-0.6", "2026-08-11 10:00:00 +0000")

        # Day 3: PT-18's milestone field alone changes to PT-0.7 (status
        # stays in-progress -- no transition). PT-18 was already
        # seen_stems'd under PT-0.6, so this produces NO opened/closed/
        # cancelled anywhere; PT-0.7 only ever gets standing WIP.
        _write_issue(data_dir, id="PT-18", status="in-progress", milestone="PT-0.7")
        _commit_at(repo_root, "PT-18 moves to PT-0.7, still in-progress", "2026-08-12 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        ids = _milestone_ids(payload)
        self.assertIn("PT-0.7", ids, f"PT-0.7 must still appear in the scope list -- got {ids!r}")
        self.assertEqual(
            payload["default_milestone"], "PT-0.6",
            f"PT-0.7 has standing WIP but ZERO transitions ever -- it must never become the "
            f"default despite being the most recently touched milestone; PT-0.6 (the milestone "
            f"with the actual open/close activity) must remain the default -- got "
            f"default_milestone={payload['default_milestone']!r}",
        )


class DefaultMilestoneTieBreakTests(unittest.TestCase):
    """ea185fc: the tie-break (two milestones sharing the latest transition
    day) is CREATION order via cairn.milestone_windows, never numeric/
    lexicographic id order. WORKFLOW's versioning scheme allows a patch
    milestone (e.g. PT-0.11.1) to be created AFTER a later-numbered one
    (PT-0.12) already exists -- the documented hotfix-against-an-already-
    released-line path, not an invented edge case. A fixture using only
    milestones whose numeric and creation orders agree (the real corpus's
    own shape, per the ruling's own measurement) can never expose a
    lexicographic-order bug -- this one deliberately reverses them."""

    def test_a_later_created_lower_numbered_milestone_wins_the_tie_over_creation_order_not_numeric_order(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent

        # Creation order: PT-0.12's milestone FILE committed FIRST...
        _write_milestone(data_dir, id="PT-0.12", name="Telemetry attribution")
        _commit_at(repo_root, "open milestone PT-0.12", "2026-08-10 09:00:00 +0000")
        # ...PT-0.11.1's milestone FILE committed SECOND (later in real
        # time) despite its LOWER numeric id -- the hotfix-against-an-
        # already-released-line shape WORKFLOW documents.
        _write_milestone(data_dir, id="PT-0.11.1", name="Hotfix patch")
        _commit_at(repo_root, "open patch milestone PT-0.11.1 after PT-0.12", "2026-08-11 09:00:00 +0000")

        # Both milestones get their ONLY (and therefore latest) real
        # transition on the SAME day -- a genuine tie on "latest
        # transition day" that only creation order, not numeric/string
        # id order, can break correctly.
        _write_issue(data_dir, id="PT-30", status="todo", milestone="PT-0.12")
        _write_issue(data_dir, id="PT-31", status="todo", milestone="PT-0.11.1")
        _commit_at(repo_root, "open one issue under each milestone, same day", "2026-08-12 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        ids = _milestone_ids(payload)
        self.assertIn("PT-0.12", ids, f"got {ids!r}")
        self.assertIn("PT-0.11.1", ids, f"got {ids!r}")
        self.assertEqual(
            payload["default_milestone"], "PT-0.11.1",
            f"PT-0.12 and PT-0.11.1 tie on latest-transition-day -- creation order (PT-0.11.1's "
            f"milestone file committed SECOND, i.e. later) must win the tie, not numeric/"
            f"lexicographic id order (which would wrongly pick PT-0.12, since 'PT-0.11.1' < "
            f"'PT-0.12' as a string) -- got default_milestone={payload['default_milestone']!r}",
        )


# --------------------------------------------------------------------------
# Payload shape sanity -- per-point overall fields, milestone metadata for
# the scope control, and the server-emitted granularity marker.
# --------------------------------------------------------------------------

class ThroughputPayloadShapeTests(unittest.TestCase):
    def test_every_point_carries_opened_closed_wip_cancelled_and_a_by_milestone_breakdown(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-13", status="todo")
        _commit_at(repo_root, "create PT-13", "2026-08-10 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        expected_keys = {"date", "opened", "closed", "wip", "cancelled", "by_milestone"}
        for point in payload["series"]:
            self.assertEqual(
                set(point.keys()), expected_keys,
                f"every series point must carry exactly {expected_keys} -- got {point!r}",
            )
            self.assertIsInstance(point["by_milestone"], dict, f"'by_milestone' must be a dict -- got {point['by_milestone']!r}")

    def test_period_is_day(self):
        data_dir = make_flow_git_repo(self)
        payload = _call_flow_payload(data_dir)
        self.assertEqual(
            payload["period"], "day",
            f"the server emits day granularity only -- the client aggregates weeks itself -- "
            f"got period={payload['period']!r}",
        )

    def test_milestones_list_carries_id_name_status_dicts_and_default_milestone_is_present(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_milestone(data_dir, id="PT-0.3", name="Throughput chart", status="in-progress")
        _write_issue(data_dir, id="PT-14", status="todo", milestone="PT-0.3")
        _commit_at(repo_root, "create PT-14 under PT-0.3", "2026-08-10 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        matches = [m for m in payload["milestones"] if m.get("id") == "PT-0.3"]
        self.assertEqual(len(matches), 1, f"expected exactly one PT-0.3 entry -- got {payload['milestones']!r}")
        self.assertEqual(
            matches[0].get("name"), "Throughput chart",
            f"name must come from the CURRENT milestone record -- got {matches[0]!r}",
        )
        self.assertEqual(
            payload["default_milestone"], "PT-0.3",
            "the only milestone with any activity must be the default",
        )

    def test_a_milestone_id_seen_only_in_history_with_no_current_file_still_appears_with_null_name(self):
        # The ruling's own instruction: dropping a historical id with no
        # CURRENT milestone file would erase history from the scope
        # control, which is the one thing this list exists to expose.
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-19", status="todo", milestone="PT-0.8")
        _commit_at(repo_root, "create PT-19 under long-gone PT-0.8", "2026-08-10 10:00:00 +0000")
        # Deliberately no milestones/PT-0.8.md file at all.

        payload = _call_flow_payload(data_dir)
        matches = [m for m in payload["milestones"] if m.get("id") == "PT-0.8"]
        self.assertEqual(
            len(matches), 1,
            f"a milestone id seen in the WALK must appear even with no current file -- "
            f"got {payload['milestones']!r}",
        )
        self.assertIsNone(
            matches[0].get("name"),
            f"with no current milestone file, name must be null, not fabricated -- got {matches[0]!r}",
        )


# --------------------------------------------------------------------------
# AC 5: TRACKER.md documents the day-bucketing convention explicitly --
# the architect's own §3 mistake (inferring "local" from %cI without
# reading the line that computes `day`) is exactly what an unstated
# convention invites the next reader to repeat.
# --------------------------------------------------------------------------

class TrackerDocumentsUtcDayConventionTests(unittest.TestCase):
    def test_tracker_states_api_flow_day_bucketing_is_utc(self):
        tracker_path = helpers.TESTS_DIR.parent.parent.parent / "process" / "TRACKER.md"
        text = tracker_path.read_text(encoding="utf-8")
        # Scoped, not whole-file (this suite's own convention: no real
        # parser over prose docs) -- find the /api/flow section and look
        # for "UTC" in a reasonably-sized nearby window, not anywhere in
        # the whole file (which would pass on an unrelated UTC mention).
        idx = text.find("/api/flow")
        self.assertNotEqual(idx, -1, "TRACKER.md has no /api/flow section yet")
        window = text[idx: idx + 1500]
        self.assertIn(
            "UTC", window,
            f"the /api/flow section must explicitly state its day-bucketing is UTC, not "
            f"local-offset -- the architect's own corrected §3 (inferring 'local' from %cI "
            f"without reading the line that computes `day`) is exactly the mistake an unstated "
            f"convention invites the next reader to repeat -- got window: {window!r}",
        )


# --------------------------------------------------------------------------
# ce521a5: legacy (pre-PT-28) milestone ids in issue blobs are unprefixed --
# "0.4" instead of "PT-0.4" -- and split into a phantom ghost entry unless
# folded. Assignment (which milestone, at that event) stays historical;
# identity (how it's named) is canonical. Canonicalise: strip quotes,
# prefix with the tracker's configured prefix if absent, accept ONLY if
# the result matches a known milestone record, else keep the raw value as
# its own `name: null` ghost.
#
# Verified before writing these (not assumed): parse_frontmatter's own
# scalar parser already strips quotes generically (`raw[1:-1]` for both
# quote styles) BEFORE any milestone-specific code sees the value, so a
# bare and a quoted-bare legacy id parse to the IDENTICAL python string.
# A "prefix-only, quote-unaware" implementation is therefore not a
# distinguishable bug shape in THIS reader -- both forms are included
# below anyway (cheap, and the underlying corpus really does have both),
# but neither is framed as its own discriminating mutation target.
# --------------------------------------------------------------------------

class LegacyMilestoneIdCanonicalizationTests(unittest.TestCase):
    def test_an_unprefixed_legacy_milestone_id_folds_into_its_canonical_prefixed_record(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_milestone(data_dir, id="PT-0.4", name="Legacy migration fixture")
        _commit_at(repo_root, "add milestone record PT-0.4", "2026-08-09 12:00:00 +0000")

        # Early history: bare, unprefixed id -- the real pre-PT-28 shape.
        _write_issue(data_dir, id="PT-20", status="todo", milestone="0.4")
        _commit_at(repo_root, "create PT-20 under bare 0.4", "2026-08-10 10:00:00 +0000")
        # Later: same issue, same milestone, now prefixed (post-migration).
        _write_issue(data_dir, id="PT-20", status="in-progress", milestone="PT-0.4")
        _commit_at(repo_root, "PT-20 -> in-progress under PT-0.4", "2026-08-11 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        ids = _milestone_ids(payload)
        self.assertIn("PT-0.4", ids, f"got {ids!r}")
        self.assertNotIn(
            "0.4", ids,
            f"the bare id must fold into its canonical record, not survive as a separate "
            f"ghost -- got {ids!r}",
        )

        points = _points_by_date(payload["series"])
        day1 = points.get("2026-08-10", {})
        self.assertEqual(
            _by_milestone(day1, "PT-0.4")["opened"], 1,
            f"the EARLY, bare-id activity must land under the CANONICAL id, not be lost or split "
            f"-- got {_by_milestone(day1, 'PT-0.4')!r}",
        )

    def test_a_quoted_legacy_milestone_id_also_folds_into_its_canonical_record(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_milestone(data_dir, id="PT-0.5", name="Legacy migration fixture 2")
        _commit_at(repo_root, "add milestone record PT-0.5", "2026-08-09 12:00:00 +0000")

        # Quoted bare id -- the same YAML-quoting artifact PT-87 found in
        # milestone frontmatter (id: "0.3").
        _write_issue(data_dir, id="PT-21", status="todo", milestone='"0.5"')
        _commit_at(repo_root, "create PT-21 under quoted bare 0.5", "2026-08-10 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        ids = _milestone_ids(payload)
        self.assertIn("PT-0.5", ids, f"got {ids!r}")
        self.assertNotIn("0.5", ids, f"got {ids!r}")
        self.assertNotIn('"0.5"', ids, f"the surrounding quote characters must never leak into an id -- got {ids!r}")

        points = _points_by_date(payload["series"])
        day1 = points.get("2026-08-10", {})
        self.assertEqual(
            _by_milestone(day1, "PT-0.5")["opened"], 1,
            f"got {_by_milestone(day1, 'PT-0.5')!r}",
        )

    def test_an_unresolvable_bare_milestone_id_survives_as_its_own_ghost_entry(self):
        # PT-89's own lesson, reapplied (architect's own framing): the
        # canonicalization fold makes every REAL legacy id resolve, which
        # means nothing in normal fixtures exercises the "doesn't match
        # any known record" fallback any more. Without a fixture built
        # specifically to hit it, that branch could be deleted or broken
        # and every other test would stay green.
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        # Deliberately NO milestones/PT-0.99.md record exists anywhere.
        _write_issue(data_dir, id="PT-22", status="todo", milestone="0.99")
        _commit_at(repo_root, "create PT-22 under unresolvable bare 0.99", "2026-08-10 10:00:00 +0000")

        payload = _call_flow_payload(data_dir)
        matches = [m for m in payload["milestones"] if m.get("id") == "0.99"]
        self.assertEqual(
            len(matches), 1,
            f"an unresolvable bare id (no matching PT-0.99 record anywhere) must survive as its "
            f"own entry, raw, rather than being silently dropped or force-matched -- "
            f"got {payload['milestones']!r}",
        )
        self.assertIsNone(
            matches[0].get("name"),
            f"an unresolvable id's entry must have name: null (a genuine ghost), same shape as "
            f"a historical id with no current file -- got {matches[0]!r}",
        )
