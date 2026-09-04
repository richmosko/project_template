"""PT-84 failing acceptance tests: main-branch token usage attributed to
the milestone active at the record's timestamp, never to a single issue.

Pinned to the architect's gating ruling, process/cairn/issues/PT-84.md
("@architect -- 2026-09-04", commit 81a9d96) -- read §1 before anything
else; every section below follows from the measured fact that NO
milestone file carries a date field, and that issue-derived/archive-move
timestamps both fail (coverage: PT-0.3 has zero issues; collision: three
milestones share `created: 2026-08-20`; archive-move is retroactive
bookkeeping, not a close time -- five milestones archived in one bulk
commit).

Written strictly AFTER the ruling landed in the tracked issue file --
same discipline as PT-86/PT-87.

## Seam under test (architect §4)

`backfill_tokens.py`, beside PT-87's `resolve_role_from_header`:
    milestone_windows(repo_root) -> List[Tuple[str, str]]
        [(start_iso, milestone_id), ...] sorted ascending by start.
        Git-derived: one `--diff-filter=A` walk over BOTH
        `milestones/` and `archive/milestones/`, earliest add per file,
        id read from the file's own frontmatter (NOT the filename --
        §3.1's trap: the first six milestone files were committed
        unprefixed, `0.3.md`..`0.6.1.md`, and renamed later).
    milestone_for_timestamp(ts, windows) -> Optional[str]
        PURE, no git. Half-open windows: `[this milestone's start, next
        milestone's start)`. A timestamp exactly on a boundary resolves
        to the LATER window, by construction (§2). A timestamp before
        the first window's start returns None (stays `main`). The
        newest window has no upper bound.

`_bucket_for_branch`/its caller in both collectors: when a record's
branch resolves to `main`, consult `milestone_for_timestamp` using the
record's own timestamp; a hit becomes `issue: "milestone:<id>"`
verbatim from frontmatter (§6, no `-<digits>` normalisation -- it's not
an agentName-shaped value at all); a miss (or a genuinely pre-cairn
timestamp) stays plain `"main"`.

## §8's five test shapes, each traced to a real tracker anomaly

1. A milestone with ZERO issues (the real `PT-0.3` shape) -- must still
   get a window; windows are never issue-derived.
2. A record exactly ON a boundary -- asserted into the LATER window.
3. Adjacent boundaries with NO gap (the real `PT-0.7.0`/`PT-0.7.1`
   same-commit shape) -- a zero-width window is not an error.
4. A record before the first milestone -- stays `main` (the ONLY
   "outside any window" case AC 1 needs).
5. Filename != id (the real first-six-milestones shape) -- a
   filename-keyed implementation must not silently pass.

No git in `MilestoneForTimestampPureTests` (architect's explicit
instruction) -- windows are hand-built tuples. `MilestoneWindowsGitTests`
is where a REAL throwaway git repo proves the two traps §3 names
directly (filename != id; a milestone can be archived under a
different path than it was created at, and `--diff-filter=A` must still
find its ORIGINAL creation, not its archive-move).

## What this file does not cover yet

AC 4 (chart bars) and AC 5 (`/api/tokens` `kind` field) are a separate,
dashboard-layer pass -- sequenced after the window-derivation and
collector tests below, per team-lead's own ordering. Flagged, not
silently dropped.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Optional

import helpers  # noqa: F401

import backfill_tokens
import cairn

BACKFILL_SCRIPT = helpers.CAIRN_DIR / "backfill_tokens.py"
OTEL_SCRIPT = helpers.CAIRN_DIR / "otel_receiver.py"
OTLP_FIXTURES = helpers.FIXTURES_DIR / "otlp"

MILESTONE_TMPL = "---\nid: {id}\nname: {name}\nkind: product\nmajor: PT-V1\nstatus: {status}\ntarget_tag: null\nga: false\n---\n\nBody.\n"
ISSUE_TMPL = (
    "---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\nparent: null\n"
    "blocked_by: []\nassignee: null\nlabels: []\npriority: null\npr: null\ncreated: {created}\nupdated: {created}\n"
    "---\n\nBody.\n"
)


def read_jsonl(path: Path) -> list[dict]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            out.append(json.loads(raw))
    return out


# --------------------------------------------------------------------------
# §8: milestone_for_timestamp -- pure, no git, hand-built windows.
# --------------------------------------------------------------------------

class MilestoneForTimestampPureTests(unittest.TestCase):
    """Windows are hand-built (start_iso, id) tuples -- this class never
    touches git or the filesystem, matching the architect's explicit
    'no git in the unit tests' instruction."""

    def _resolve(self, ts: str, windows: list[tuple[str, str]]) -> Optional[str]:
        self.assertTrue(
            hasattr(backfill_tokens, "milestone_for_timestamp"),
            "cairn.milestone_for_timestamp does not exist yet -- PT-84's window-resolution seam is unimplemented",
        )
        return cairn.milestone_for_timestamp(ts, windows)

    def test_a_timestamp_strictly_inside_one_window_resolves_to_that_milestone(self):
        windows = [
            ("2026-08-20T08:19:49Z", "PT-0.3"),
            ("2026-08-20T09:03:41Z", "PT-0.4"),
            ("2026-08-20T14:39:56Z", "PT-0.5"),
        ]
        self.assertEqual(self._resolve("2026-08-20T10:00:00Z", windows), "PT-0.4")

    def test_a_timestamp_exactly_on_a_boundary_resolves_to_the_later_window(self):
        # §2: half-open windows, boundary belongs to the LATER one by
        # construction -- the real shape this must never get backwards.
        windows = [
            ("2026-08-20T09:03:41Z", "PT-0.4"),
            ("2026-08-20T14:39:56Z", "PT-0.5"),
        ]
        self.assertEqual(
            self._resolve("2026-08-20T14:39:56Z", windows), "PT-0.5",
            "a timestamp exactly equal to PT-0.5's start must resolve to PT-0.5 (the later window), not PT-0.4",
        )

    def test_adjacent_boundaries_with_no_gap_zero_width_window_is_not_an_error(self):
        # The real PT-0.7.0/PT-0.7.1 shape: archived in the same commit
        # that created the next milestone -- both windows share a
        # boundary with nothing between them. No timestamp can ever
        # land in PT-0.7.0's now-zero-width window; that's expected, not
        # a bug -- confirmed by resolving a timestamp exactly at the
        # shared boundary into PT-0.7.1, and one a second earlier into
        # the milestone before PT-0.7.0.
        windows = [
            ("2026-08-23T10:00:00Z", "PT-0.6.1"),
            ("2026-08-23T15:00:00Z", "PT-0.7.0"),
            ("2026-08-23T15:00:00Z", "PT-0.7.1"),
        ]
        self.assertEqual(self._resolve("2026-08-23T15:00:00Z", windows), "PT-0.7.1", "the shared boundary instant belongs to the LATER of the two same-second milestones")
        self.assertEqual(self._resolve("2026-08-23T14:59:59Z", windows), "PT-0.6.1", "one second before the zero-width pair must still resolve to whatever milestone was active before it")

    def test_a_milestone_with_zero_issues_still_resolves_normally(self):
        # The real PT-0.3 shape: milestone_for_timestamp doesn't know or
        # care about issue counts at all -- it only ever sees windows.
        # This pins that a window for a zero-issue milestone works
        # exactly like any other, so a caller that (incorrectly) built
        # windows from issue data rather than milestone-file creation
        # would be the thing that breaks, not this function.
        windows = [
            ("2026-08-20T08:19:49Z", "PT-0.3"),
            ("2026-08-20T09:03:41Z", "PT-0.4"),
        ]
        self.assertEqual(self._resolve("2026-08-20T08:30:00Z", windows), "PT-0.3")

    def test_a_timestamp_before_the_first_milestone_stays_unresolved(self):
        # The ONLY "outside any window" case AC 1 needs -- pre-cairn
        # work, must return None so the caller keeps "main".
        windows = [("2026-08-20T08:19:49Z", "PT-0.3")]
        self.assertIsNone(self._resolve("2026-08-19T23:00:00Z", windows), "a timestamp before the earliest milestone's creation must resolve to None, not the earliest milestone")

    def test_the_newest_window_has_no_upper_bound(self):
        windows = [
            ("2026-08-20T08:19:49Z", "PT-0.3"),
            ("2026-09-04T00:00:00Z", "PT-0.12"),
        ]
        self.assertEqual(self._resolve("2099-01-01T00:00:00Z", windows), "PT-0.12", "the newest milestone's window must extend to infinity, not stop at some implicit end")

    def test_an_empty_windows_list_never_resolves(self):
        self.assertIsNone(self._resolve("2026-08-20T10:00:00Z", []))

    def test_a_fractional_second_timestamp_in_the_same_second_as_a_boundary_lands_in_the_later_window(self):
        # Architect's addendum (e0c116f): the backfill's real transcript
        # timestamps carry milliseconds ("...52.326Z"); the receiver's
        # and milestone_windows' own timestamps do not ("...52Z"). Under
        # a NAIVE string compare, "...52.326Z" < "...52Z" is True ('.' =
        # 0x2E sorts before 'Z' = 0x5A) -- a record 326ms INTO a window
        # would wrongly compare as BEFORE its own boundary and land in
        # the PREVIOUS milestone. milestone_for_timestamp must
        # canonicalise (truncate fractional seconds) before comparing.
        windows = [
            ("2026-08-22T06:38:00Z", "PT-0.11"),
            ("2026-08-22T06:38:52Z", "PT-0.12"),
        ]
        self.assertEqual(
            self._resolve("2026-08-22T06:38:52.326Z", windows), "PT-0.12",
            "a record 326ms into PT-0.12's window must resolve to PT-0.12, not fall back to PT-0.11 "
            "because of an uncanonicalised string compare",
        )


# --------------------------------------------------------------------------
# §3's two real traps -- only testable against a real git history.
# --------------------------------------------------------------------------

def _git(cwd: Path, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result


def _commit_at(repo_root: Path, message: str, when: str) -> None:
    """`when`: git raw date, e.g. '2026-08-20 08:19:49 +0000' -- always
    UTC so the boundary instant is unambiguous."""
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    })
    _git(repo_root, "add", "-A", env=env)
    _git(repo_root, "commit", "-q", "-m", message, env=env)


def make_milestone_git_repo(testcase, with_engine_copy: bool = False) -> Path:
    """Fresh git repo with a process/cairn data dir, matching the real
    project layout (milestones/, archive/milestones/, issues/) so
    milestone_windows(repo_root) can walk it exactly like production.

    `with_engine_copy=True` ALSO copies backfill_tokens.py + cairn.py
    into <repo_root>/scripts/cairn/ -- needed only by tests that invoke
    the CLI as a subprocess: backfill_tokens.py has no --repo-root
    override (unlike otel_receiver.py), it always resolves repo_root
    from its OWN on-disk location (`_repo_root()`, __file__-anchored,
    same PT-77/PT-80 discipline) -- so the only way to point it at a
    throwaway tracker is to give it a throwaway COPY of itself to run,
    same technique test_otel_receiver_hardening.py's
    make_fake_engine_root already established."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    _git(tmp, "init", "-q", "-b", "main")
    _git(tmp, "config", "user.email", "test@example.com")
    _git(tmp, "config", "user.name", "Test")
    data_dir = tmp / "process" / "cairn"
    for sub in ("milestones", "archive/milestones", "issues", "archive/issues"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    if with_engine_copy:
        engine_dir = tmp / "scripts" / "cairn"
        engine_dir.mkdir(parents=True)
        for name in ("backfill_tokens.py", "cairn.py"):
            (engine_dir / name).write_bytes((helpers.CAIRN_DIR / name).read_bytes())
        (tmp / ".claude" / "agents").mkdir(parents=True)
    _commit_at(tmp, "initial", "2026-08-09 09:00:00 +0000")
    return tmp


class MilestoneWindowsGitTests(unittest.TestCase):
    """§3's two real traps, against a real throwaway git repo -- never
    the shared checkout."""

    def test_filename_not_matching_frontmatter_id_still_resolves_by_id(self):
        # The real first-six-milestones shape: files committed
        # unprefixed (0.3.md) with id: PT-0.3 in frontmatter, renamed
        # later. milestone_windows must read the id from frontmatter,
        # never derive it from the filename.
        repo_root = make_milestone_git_repo(self)
        milestones_dir = repo_root / "process" / "cairn" / "milestones"
        (milestones_dir / "0.3.md").write_text(MILESTONE_TMPL.format(id="PT-0.3", name="zero issues", status="archived"), encoding="utf-8")
        _commit_at(repo_root, "add 0.3.md (unprefixed filename)", "2026-08-20 08:19:49 +0000")

        self.assertTrue(hasattr(cairn, "milestone_windows"), "cairn.milestone_windows does not exist yet")
        windows = cairn.milestone_windows(repo_root)
        ids = [mid for _start, mid in windows]
        self.assertIn("PT-0.3", ids, f"must resolve the frontmatter id even though the filename is 0.3.md, not PT-0.3.md -- got {windows!r}")
        self.assertNotIn("0.3", ids, f"must never derive the id from the filename stem -- got {windows!r}")

    def test_a_milestone_with_zero_issue_files_still_gets_a_window(self):
        # The real PT-0.3 shape -- no issue file references it at all.
        # Proves windows come from milestone-file creation, never from
        # issue existence/dates.
        repo_root = make_milestone_git_repo(self)
        milestones_dir = repo_root / "process" / "cairn" / "milestones"
        (milestones_dir / "PT-0.3.md").write_text(MILESTONE_TMPL.format(id="PT-0.3", name="zero issues", status="archived"), encoding="utf-8")
        _commit_at(repo_root, "add PT-0.3.md, no issues ever reference it", "2026-08-20 08:19:49 +0000")

        windows = cairn.milestone_windows(repo_root)
        ids = [mid for _start, mid in windows]
        self.assertIn("PT-0.3", ids, f"a milestone with zero issue files must still produce a window -- got {windows!r}")

    def test_an_archived_milestones_creation_is_found_under_its_original_path(self):
        # Architect's addendum (c0affa5 supersedes the original §3.2 "one
        # combined diff-filter=A walk" -- withdrawn in favour of a
        # PER-FILE `git log --follow --diff-filter=A` on the CURRENT
        # path): --follow walks the current, live path's history
        # BACKWARD through its own renames to the true origin commit --
        # an archived milestone's creation is only visible under its
        # original (pre-move) path, and --follow is what survives that.
        repo_root = make_milestone_git_repo(self)
        milestones_dir = repo_root / "process" / "cairn" / "milestones"
        archive_dir = repo_root / "process" / "cairn" / "archive" / "milestones"
        (milestones_dir / "PT-0.4.md").write_text(MILESTONE_TMPL.format(id="PT-0.4", name="early work", status="planned"), encoding="utf-8")
        _commit_at(repo_root, "create PT-0.4.md", "2026-08-20 09:03:41 +0000")

        # Archive it later -- a real git mv, so the file's history shows
        # a rename/move, not a fresh add under the archive path.
        _git(repo_root, "mv", str(milestones_dir / "PT-0.4.md"), str(archive_dir / "PT-0.4.md"))
        _commit_at(repo_root, "archive PT-0.4.md (retroactive bookkeeping)", "2026-09-01 12:00:00 +0000")

        windows = cairn.milestone_windows(repo_root)
        entry = next((w for w in windows if w[1] == "PT-0.4"), None)
        self.assertIsNotNone(entry, f"an archived milestone must still appear in the windows -- got {windows!r}")
        self.assertEqual(
            entry[0], "2026-08-20T09:03:41Z",
            f"the window start must be the ORIGINAL creation time (2026-08-20T09:03:41Z, UTC-normalised), not the later archive-move commit (2026-09-01) -- got {entry!r}",
        )

    def test_id_comes_from_current_content_not_the_creation_commits_content(self):
        # Architect's deepened §3.1 (c0affa5): the trap runs one level
        # below the filename -- the real PT-0.3.md's OWN FRONTMATTER at
        # its creation commit said the bare, quoted `id: "0.3"`, not
        # `PT-0.3`; it was corrected (and the file renamed) in a LATER
        # commit. A implementation that reads the id from the historical
        # creation-commit's blob (`git show <add-commit>:<path>`)
        # reproduces the exact same stale id one level down from the
        # filename bug. The id must come from the file's CURRENT (HEAD)
        # content; the timestamp must still come from --follow finding
        # the TRUE origin commit, even though that commit's own content
        # disagrees with HEAD.
        repo_root = make_milestone_git_repo(self)
        milestones_dir = repo_root / "process" / "cairn" / "milestones"
        archive_dir = repo_root / "process" / "cairn" / "archive" / "milestones"

        # 1: created unprefixed, filename AND frontmatter both stale.
        (milestones_dir / "0.3.md").write_text('---\nid: "0.3"\nname: zero issues\nkind: product\nmajor: PT-V1\nstatus: planned\ntarget_tag: null\nga: false\n---\n\nBody.\n', encoding="utf-8")
        _commit_at(repo_root, "create 0.3.md, id: \"0.3\" (the real historical shape)", "2026-08-20 08:19:49 +0000")

        # 2: pure rename, no content change -- keeps git's rename
        # detection unambiguous.
        _git(repo_root, "mv", str(milestones_dir / "0.3.md"), str(milestones_dir / "PT-0.3.md"))
        _commit_at(repo_root, "rename 0.3.md -> PT-0.3.md", "2026-08-25 10:00:00 +0000")

        # 3: much later, a pure content fix on the ALREADY-renamed path
        # (and separately archived) -- HEAD's frontmatter is correct.
        _git(repo_root, "mv", str(milestones_dir / "PT-0.3.md"), str(archive_dir / "PT-0.3.md"))
        (archive_dir / "PT-0.3.md").write_text(MILESTONE_TMPL.format(id="PT-0.3", name="zero issues", status="archived"), encoding="utf-8")
        _commit_at(repo_root, "archive + correct frontmatter id to PT-0.3", "2026-08-26 09:47:07 +0000")

        windows = cairn.milestone_windows(repo_root)
        entry = next((w for w in windows if w[1] == "PT-0.3"), None)
        self.assertIsNotNone(
            entry, f"must resolve to the CURRENT, correct id PT-0.3 -- a history-content-reading implementation "
            f"would instead produce the stale '0.3' and never match this lookup -- got {windows!r}",
        )
        self.assertNotIn(
            "0.3", [mid for _start, mid in windows if mid != "PT-0.3"],
            f"the stale unprefixed id must never appear as its own separate window -- got {windows!r}",
        )
        self.assertEqual(
            entry[0], "2026-08-20T08:19:49Z",
            f"the timestamp must be the TRUE ORIGIN commit (found via --follow through both renames), "
            f"not the much-later archive+content-fix commit -- got {entry!r}",
        )

    def test_windows_are_sorted_by_creation_time_not_by_id_string(self):
        # §6's trap: "PT-0.10" sorts before "PT-0.5" lexicographically.
        # milestone_windows' own ordering (ascending by start) must not
        # be fooled by this even though this test doesn't touch the
        # chart's own sort -- the windows list itself must be
        # chronological or milestone_for_timestamp's boundary logic
        # breaks silently.
        repo_root = make_milestone_git_repo(self)
        milestones_dir = repo_root / "process" / "cairn" / "milestones"
        (milestones_dir / "PT-0.5.md").write_text(MILESTONE_TMPL.format(id="PT-0.5", name="fifth", status="archived"), encoding="utf-8")
        _commit_at(repo_root, "create PT-0.5.md", "2026-08-20 14:39:56 +0000")
        (milestones_dir / "PT-0.10.md").write_text(MILESTONE_TMPL.format(id="PT-0.10", name="tenth", status="archived"), encoding="utf-8")
        _commit_at(repo_root, "create PT-0.10.md", "2026-08-30 10:00:00 +0000")

        windows = cairn.milestone_windows(repo_root)
        ids_in_order = [mid for _start, mid in windows]
        self.assertLess(
            ids_in_order.index("PT-0.5"), ids_in_order.index("PT-0.10"),
            f"PT-0.5 was created BEFORE PT-0.10 -- windows must be chronological, not alphabetical -- got {ids_in_order!r}",
        )


# --------------------------------------------------------------------------
# ACs 2/3: both collectors attribute a main-branch record to the right
# milestone bucket, and leave out-of-window records in `main`.
# --------------------------------------------------------------------------

class BackfillMilestoneAttributionTests(unittest.TestCase):
    """A main-branch assistant record, timestamped inside a milestone's
    window, must bucket to issue: "milestone:<id>" -- never plain
    "main", never the milestone's own issues' bucket."""

    def _repo_with_two_milestones(self, testcase) -> Path:
        repo_root = make_milestone_git_repo(testcase, with_engine_copy=True)
        milestones_dir = repo_root / "process" / "cairn" / "milestones"
        (milestones_dir / "PT-0.3.md").write_text(MILESTONE_TMPL.format(id="PT-0.3", name="early", status="archived"), encoding="utf-8")
        _commit_at(repo_root, "create PT-0.3.md", "2026-08-20 08:19:49 +0000")
        (milestones_dir / "PT-0.4.md").write_text(MILESTONE_TMPL.format(id="PT-0.4", name="later", status="archived"), encoding="utf-8")
        _commit_at(repo_root, "create PT-0.4.md", "2026-08-20 09:03:41 +0000")
        return repo_root

    def _transcript_dir_for(self, testcase, records: list[dict]) -> Path:
        tmp = helpers.make_empty_tmp_dir(testcase)
        path = tmp / "session.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return tmp

    def _run_backfill(self, repo_root: Path, transcripts_dir: Path, out_path: Path) -> subprocess.CompletedProcess:
        # backfill_tokens.py has no --repo-root override -- it always
        # resolves repo_root from its OWN on-disk location, so the copy
        # living inside repo_root (make_milestone_git_repo's
        # with_engine_copy=True) is what makes it see THIS throwaway
        # tracker rather than the real one.
        script = repo_root / "scripts" / "cairn" / "backfill_tokens.py"
        return subprocess.run(
            [sys.executable, str(script),
             "--transcripts-dir", str(transcripts_dir), "--out-file", str(out_path)],
            capture_output=True, text=True,
        )

    def test_a_main_branch_record_inside_a_milestone_window_buckets_to_that_milestone(self):
        repo_root = self._repo_with_two_milestones(self)
        record = {
            "type": "assistant", "timestamp": "2026-08-20T10:00:00Z", "gitBranch": "main",
            "requestId": "req-milestone-1", "uuid": "uuid-milestone-1",
            "message": {"model": "claude-sonnet-5", "usage": {
                "input_tokens": 10, "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 10, "output_tokens": 10,
            }},
        }
        transcripts_dir = self._transcript_dir_for(self, [record])
        out_path = helpers.make_empty_tmp_dir(self) / "token-usage.jsonl"
        result = self._run_backfill(repo_root, transcripts_dir, out_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        issues = {l["issue"] for l in lines}
        self.assertIn("milestone:PT-0.4", issues, f"a 2026-08-20T10:00 record falls inside PT-0.4's window -- got {issues!r}")
        self.assertNotIn("main", issues, "a record inside a milestone's window must NOT also appear as plain main")

    def test_a_main_branch_record_before_the_first_milestone_stays_plain_main(self):
        repo_root = self._repo_with_two_milestones(self)
        record = {
            "type": "assistant", "timestamp": "2026-08-15T10:00:00Z", "gitBranch": "main",
            "requestId": "req-premilestone-1", "uuid": "uuid-premilestone-1",
            "message": {"model": "claude-sonnet-5", "usage": {
                "input_tokens": 7, "cache_creation_input_tokens": 7,
                "cache_read_input_tokens": 7, "output_tokens": 7,
            }},
        }
        transcripts_dir = self._transcript_dir_for(self, [record])
        out_path = helpers.make_empty_tmp_dir(self) / "token-usage.jsonl"
        result = self._run_backfill(repo_root, transcripts_dir, out_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        issues = {l["issue"] for l in lines}
        self.assertEqual(issues, {"main"}, f"a record before the first milestone's creation must stay plain main -- got {issues!r}")


class ReceiverMilestoneAttributionTests(unittest.TestCase):
    """Same rule, the receiver's own flush path (§3/§5: same function,
    table built once per flush from --repo-root, never per datapoint)."""

    def test_a_main_branch_datapoint_inside_a_milestone_window_buckets_to_that_milestone(self):
        repo_root = make_milestone_git_repo(self)
        milestones_dir = repo_root / "process" / "cairn" / "milestones"
        (milestones_dir / "PT-0.4.md").write_text(MILESTONE_TMPL.format(id="PT-0.4", name="later", status="archived"), encoding="utf-8")
        _commit_at(repo_root, "create PT-0.4.md", "2026-08-20 09:03:41 +0000")

        payload = {
            "resourceMetrics": [{
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "claude-code"}}]},
                "scopeMetrics": [{
                    "scope": {"name": "com.anthropic.claude_code", "version": "1.0.0"},
                    "metrics": [{
                        "name": "claude_code.token.usage",
                        "sum": {
                            "dataPoints": [{
                                "attributes": [
                                    {"key": "type", "value": {"stringValue": "input"}},
                                    {"key": "model", "value": {"stringValue": "claude-sonnet-5"}},
                                ],
                                "startTimeUnixNano": "1755680400000000000",  # 2026-08-20T10:00:00Z
                                "timeUnixNano": "1755680400000000000",
                                "asInt": "42",
                            }],
                            "aggregationTemporality": 1, "isMonotonic": True,
                        },
                    }],
                }],
            }],
        }
        payload_path = helpers.make_empty_tmp_dir(self) / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        out_path = helpers.make_empty_tmp_dir(self) / "token-usage.jsonl"

        # main branch: this throwaway repo's default branch IS "main"
        # (make_milestone_git_repo inits with -b main), and --repo-root
        # here steers `_current_branch`'s read per otel_receiver.py's own
        # documented contract.
        result = subprocess.run(
            [sys.executable, str(OTEL_SCRIPT), "--ingest", str(payload_path),
             "--out-file", str(out_path), "--repo-root", str(repo_root)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        issues = {l["issue"] for l in lines}
        self.assertIn("milestone:PT-0.4", issues, f"got {issues!r}")


if __name__ == "__main__":
    unittest.main()
