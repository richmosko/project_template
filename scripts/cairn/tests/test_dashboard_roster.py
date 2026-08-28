"""PT-56 failing acceptance tests: `GET /api/roster`, per the architect's
presence-source ruling (PT-56 comment, 2026-08-27 -- full ruling in
process/cairn/issues/PT-56.md):

- Identity: `.claude/agents/*.md` (name + description frontmatter; role =
  the description's first sentence) plus `.claude/roles/team-lead.md`.
  Every clone ships these -- a roster with zero live team running still
  shows every identity, all `unknown`.
- Work attribution: the tracker's `assignee` field, LIVE issues only
  (archived excluded, matching every other "live by default" convention
  in this codebase -- PT-42's own precedent).
- Presence, exactly three values, never anything else: `working` / `idle`
  / `unknown`.
  - `working`: assignee of >=1 live issue with status `in-progress` or
    `in-review`, AND that issue's `updated:` is today (not stale).
  - `idle`: exists, with no current `working`-qualifying assignment --
    either no assignment at all beyond backlog/todo, or a `working`-
    shaped assignment that's gone stale (see below).
  - `unknown`: no presence-bearing data at all for this identity.
- Staleness: a `working`-qualifying issue whose `updated:` predates today
  degrades that row to `idle`, annotated with the date -- never silently
  stays `working`. Degradation is one-directional (working -> idle ->
  unknown, never upward) -- this file does not test the "never upward"
  direction beyond staleness, since nothing in the ruled contract lets a
  single payload build re-promote a row (each build recomputes from
  scratch; there is no persisted state to ratchet).
- Code location: a separate composed reader module + `GET /api/roster`,
  NOT a new key on `/api/dashboard` -- protects PT-54's payload contract
  (already pinned by test_dashboard_agent_roster.py's payload-boundary
  guard, not duplicated here). Repo root via `git -C <data_dir> rev-parse
  --show-toplevel`, falling back to `data_dir.parent.parent` -- same
  never-raises contract as `read_git_tags`.

Nothing under test exists yet: no `cairn.build_roster_payload`, no
`/api/roster` route. Every payload test below is expected to fail with
AttributeError or an unexpected 404 -- never an import error.
"""
from __future__ import annotations

import datetime
import json
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import helpers  # noqa: F401

import cairn


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


AGENT_TMPL = "---\nname: {name}\ndescription: {description}\ntools: Read, Write\nmodel: sonnet\n---\n\n# {name}\n\nBody.\n"
TEAM_LEAD_ROLE_TMPL = "---\nname: team-lead\ndescription: {description}\n---\n\n# Team lead\n\nBody.\n"

ISSUE_TMPL = (
    "---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: null\nparent: null\n"
    "assignee: {assignee}\nlabels: []\npriority: null\npr: null\ncreated: 2026-08-20\nupdated: {updated}\n"
    "---\n\nBody.\n"
)


def make_git_repo_with_agents(testcase, *, agents=None, team_lead_description="The main session."):
    """A fresh git repo with a `process/cairn` data dir AND a `.claude/`
    tree at the repo root -- the ruling's identity source. `agents` is a
    dict of {name: description}; defaults to a small fixed roster (NOT
    the real template's actual .claude/agents/, which would make this
    suite's expectations drift every time a real agent file is added).
    Returns data_dir (repo_root/process/cairn).
    """
    if agents is None:
        agents = {
            "qa-engineer": "Owns testing and validation. Drives the Validate side of every loop.",
            "architect": "Owns system design and technical rulings. Investigates before deciding.",
        }
    tmp = helpers.make_empty_tmp_dir(testcase)
    _run_git(tmp, "init", "-q")
    _run_git(tmp, "config", "user.email", "test@example.com")
    _run_git(tmp, "config", "user.name", "Test")

    data_dir = tmp / "process" / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text(
        "prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8"
    )

    claude_agents = tmp / ".claude" / "agents"
    claude_agents.mkdir(parents=True)
    for name, description in agents.items():
        (claude_agents / f"{name}.md").write_text(
            AGENT_TMPL.format(name=name, description=description), encoding="utf-8"
        )
    claude_roles = tmp / ".claude" / "roles"
    claude_roles.mkdir(parents=True)
    (claude_roles / "team-lead.md").write_text(
        TEAM_LEAD_ROLE_TMPL.format(description=team_lead_description), encoding="utf-8"
    )

    (tmp / "README.md").write_text("placeholder\n", encoding="utf-8")
    _run_git(tmp, "add", ".")
    _run_git(tmp, "commit", "-q", "-m", "initial")
    return data_dir


def write_issue(data_dir: Path, *, id: str, title: str, status: str, assignee, updated: str) -> None:
    assignee_yaml = "null" if assignee is None else assignee
    (data_dir / "issues" / f"{id}.md").write_text(
        ISSUE_TMPL.format(id=id, title=title, status=status, assignee=assignee_yaml, updated=updated),
        encoding="utf-8",
    )


class RosterPayloadIdentityTests(unittest.TestCase):
    def test_payload_includes_every_agent_file_plus_team_lead(self):
        data_dir = make_git_repo_with_agents(self)
        payload = cairn.build_roster_payload(data_dir)
        ids = {a["id"] for a in payload["agents"]}
        self.assertEqual(ids, {"qa-engineer", "architect", "team-lead"})

    def test_role_is_the_first_sentence_of_the_description(self):
        data_dir = make_git_repo_with_agents(self)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["role"], "Owns testing and validation.")

    def test_every_agent_carries_a_name(self):
        data_dir = make_git_repo_with_agents(self)
        payload = cairn.build_roster_payload(data_dir)
        for agent in payload["agents"]:
            self.assertTrue(agent.get("name"), agent)

    def test_empty_repo_with_no_tracker_data_yields_every_identity_as_unknown(self):
        # The ruling's own "empty state is not empty" case: a fresh clone
        # with no live team running still shows every identity, all
        # `unknown` -- a genuinely useful first run, not a placeholder.
        data_dir = make_git_repo_with_agents(self)
        payload = cairn.build_roster_payload(data_dir)
        self.assertEqual(len(payload["agents"]), 3)
        for agent in payload["agents"]:
            self.assertEqual(agent["presence"], "unknown", agent)

    def test_never_raises_when_claude_agents_dir_is_missing(self):
        # Never-raises contract, same posture as read_git_tags -- a repo
        # (or a spun-off copy of cairn alone) with no .claude/ tree at all
        # must degrade to an empty roster, not crash the endpoint.
        tmp = helpers.make_empty_tmp_dir(self)
        _run_git(tmp, "init", "-q")
        _run_git(tmp, "config", "user.email", "test@example.com")
        _run_git(tmp, "config", "user.name", "Test")
        data_dir = tmp / "process" / "cairn"
        for sub in ("issues", "archive", "milestones", "majors"):
            (data_dir / sub).mkdir(parents=True)
        (data_dir / "config.yml").write_text(
            "prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8"
        )
        (tmp / "README.md").write_text("x\n", encoding="utf-8")
        _run_git(tmp, "add", ".")
        _run_git(tmp, "commit", "-q", "-m", "initial")
        try:
            payload = cairn.build_roster_payload(data_dir)
        except Exception as e:  # noqa: BLE001
            self.fail(f"build_roster_payload must never raise when .claude/ is missing, got {e!r}")
        self.assertEqual(payload["agents"], [])


class RosterPayloadPresenceTests(unittest.TestCase):
    def test_working_when_assignee_has_an_in_progress_issue_updated_today(self):
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Fix the thing", status="in-progress", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["presence"], "working")
        self.assertIsNone(qa.get("stale_since"), "a genuinely working row must not carry a staleness date")

    def test_working_also_holds_for_in_review_status(self):
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Under review", status="in-review", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["presence"], "working")

    def test_idle_when_the_only_assignment_is_backlog(self):
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Someday", status="backlog", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["presence"], "idle")

    def test_unknown_when_no_issue_references_this_agent_at_all(self):
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Someone else's", status="in-progress", assignee="architect", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["presence"], "unknown")

    def test_a_stale_in_progress_assignment_degrades_to_idle_not_working(self):
        # Staleness: updated: predates today -> idle, annotated with the
        # date, never working -- this is the ruling's central honesty
        # requirement, so it gets its own dedicated test. The date must be
        # SURFACED (architect's explicit follow-up), not just implied by
        # the presence value -- a UI showing "idle" alone can't render
        # "last tracker update 2026-08-01" without this field.
        data_dir = make_git_repo_with_agents(self)
        write_issue(data_dir, id="PT-1", title="Stalled", status="in-progress", assignee="qa-engineer", updated="2026-08-01")
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["presence"], "idle")
        self.assertEqual(qa.get("stale_since"), "2026-08-01", qa)

    def test_done_only_assignment_is_idle_not_unknown(self):
        # Architect's addendum (the "done-but-live cell"): team-lead's
        # preserve-assignee-on-done decision means a `done` issue stays in
        # the LIVE issues/ dir until archived at release close -- the
        # common case, not an edge one. Explicitly ruled `idle`, not
        # `unknown`: a completed assignment is real data (the agent
        # exists in the record, nothing in flight), and collapsing it to
        # `unknown` would discard the provenance preserve-on-done exists
        # to keep.
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Shipped", status="done", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["presence"], "idle")

    def test_done_assignment_never_reads_as_current_work_in_the_work_line(self):
        # Architect's addendum, second half: a done assignment may appear
        # as HISTORY, never presented as current work. Pinned by
        # contrasting the done work string against the plain in-progress
        # one for the identical issue shape -- they must not be
        # indistinguishable, or a roster reader could mistake completed
        # work for active work.
        data_dir_done = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir_done, id="PT-1", title="Shipped", status="done", assignee="qa-engineer", updated=today)
        done_payload = cairn.build_roster_payload(data_dir_done)
        done_work = next(a for a in done_payload["agents"] if a["id"] == "qa-engineer")["work"]

        data_dir_working = make_git_repo_with_agents(self)
        write_issue(data_dir_working, id="PT-1", title="Shipped", status="in-progress", assignee="qa-engineer", updated=today)
        working_payload = cairn.build_roster_payload(data_dir_working)
        working_work = next(a for a in working_payload["agents"] if a["id"] == "qa-engineer")["work"]

        self.assertIsNotNone(done_work)
        self.assertNotEqual(
            done_work, working_work,
            "a done assignment's work-line text must be distinguishable from an in-progress "
            "one for the same issue -- otherwise completed work reads as current work",
        )

    def test_live_pending_work_outranks_done_history_in_the_work_line(self):
        # Architect's diff-review finding: an agent with BOTH a done issue
        # AND a live backlog/todo assignment must surface the PENDING
        # item, not "last shipped" -- the done-as-history framing is the
        # fallback for when nothing is pending, not the preferred read.
        # Presence is idle either way; this pins the work-line CONTENT,
        # not the presence value (already covered above).
        #
        # PT-65: updated for the structured `work` shape ({id, title,
        # status, kind}) -- `work` is no longer a composed string, so
        # this no longer does substring checks. See
        # test_dashboard_roster_structured_work.py for the full shape
        # contract; this test keeps its original business-rule scope
        # (pending outranks done) expressed against the new fields.
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Ship it", status="done", assignee="qa-engineer", updated=today)
        write_issue(data_dir, id="PT-2", title="Next thing", status="todo", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["presence"], "idle")
        self.assertEqual(qa["work"]["id"], "PT-2", qa)
        self.assertNotEqual(qa["work"]["kind"], "history", qa)

    def test_archived_issues_do_not_count_toward_presence(self):
        # "Live issues only" -- an archived issue assigned to this agent
        # must not manufacture a working/idle presence from dead data.
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        (data_dir / "archive" / "issues").mkdir(parents=True, exist_ok=True)
        (data_dir / "archive" / "issues" / "PT-9.md").write_text(
            ISSUE_TMPL.format(id="PT-9", title="Old", status="in-progress", assignee="qa-engineer", updated=today),
            encoding="utf-8",
        )
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["presence"], "unknown")

    def test_presence_is_never_a_value_outside_the_three_ruled_states(self):
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="A", status="in-progress", assignee="qa-engineer", updated=today)
        write_issue(data_dir, id="PT-2", title="B", status="backlog", assignee="architect", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        for agent in payload["agents"]:
            self.assertIn(agent["presence"], {"working", "idle", "unknown"}, agent)

    def test_vocabulary_guard_no_fabricated_liveness_words_anywhere_in_presence_values(self):
        # Architect's explicit ask: assert the served payload's EXTRACTED
        # status values never include "active"/"online"/"live" -- the
        # exact fabrication the AC forbids. Targets the actual `presence`
        # values (a real payload field), not a whole-file text scan --
        # same "extracted value, not file prose" discipline as PT-55's
        # sandbox-attribute correction.
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="A", status="in-progress", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        forbidden = {"active", "online", "live"}
        presence_values = {agent["presence"] for agent in payload["agents"]}
        self.assertEqual(
            presence_values & forbidden, set(),
            f"presence values must never include {forbidden} -- got {presence_values}, "
            f"the ruling's vocabulary is strictly working/idle/unknown",
        )

    def test_one_directional_invariant_nothing_stale_or_absent_ever_reads_as_working(self):
        # The AC's honesty clause, expressed as a property rather than an
        # example (architect's explicit ask): sweep every kind of
        # stale/absent/weak input this contract defines and confirm NONE
        # of them ever produce "working". A single example test (like the
        # staleness test above) can't catch a future implementation that
        # special-cases one shape of staleness but not another.
        today = datetime.date.today().isoformat()

        def _no_assignment(d):
            pass

        def _archived_in_progress_updated_today(d):
            (d / "archive" / "issues").mkdir(parents=True, exist_ok=True)
            (d / "archive" / "issues" / "PT-9.md").write_text(
                ISSUE_TMPL.format(id="PT-9", title="x", status="in-progress", assignee="qa-engineer", updated=today),
                encoding="utf-8",
            )

        scenarios = [
            ("no assignment at all", _no_assignment),
            ("backlog assignment", lambda d: write_issue(d, id="PT-1", title="x", status="backlog", assignee="qa-engineer", updated=today)),
            ("todo assignment", lambda d: write_issue(d, id="PT-1", title="x", status="todo", assignee="qa-engineer", updated=today)),
            ("done assignment", lambda d: write_issue(d, id="PT-1", title="x", status="done", assignee="qa-engineer", updated=today)),
            ("stale in-progress (1 day old)", lambda d: write_issue(d, id="PT-1", title="x", status="in-progress", assignee="qa-engineer", updated="2026-08-26")),
            ("stale in-progress (long ago)", lambda d: write_issue(d, id="PT-1", title="x", status="in-progress", assignee="qa-engineer", updated="2020-01-01")),
            ("stale in-review", lambda d: write_issue(d, id="PT-1", title="x", status="in-review", assignee="qa-engineer", updated="2026-08-01")),
            ("archived in-progress (updated today)", _archived_in_progress_updated_today),
        ]
        for label, setup in scenarios:
            with self.subTest(label):
                data_dir = make_git_repo_with_agents(self)
                setup(data_dir)
                payload = cairn.build_roster_payload(data_dir)
                qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
                self.assertNotEqual(qa["presence"], "working", f"{label} must never read as working, got {qa}")

    def test_real_claude_agents_with_a_fresh_empty_tracker_yields_eleven_all_unknown(self):
        # Architect's explicit "cloner state" ask, made STABLE: a real
        # assertion about the SHIPPED template's identity files (ten real
        # `.claude/agents/*.md` + team-lead's role = 11), against a
        # genuinely fresh/empty tracker -- not this repo's own live
        # process/cairn, whose issue statuses/assignees change constantly
        # as the team works (this exact test broke twice already: once
        # when claim-sets-assignee landed, once when implementation-lead
        # picked up PT-57 mid-session -- see git blame). Copying the REAL
        # .claude/ tree into a synthetic empty-tracker repo tests the
        # thing architect actually asked for (a genuine fresh clone's
        # first-run roster) without coupling to this repo's own churn.
        import shutil

        real_claude_dir = helpers.CAIRN_DIR.parent.parent / ".claude"
        self.assertTrue(real_claude_dir.is_dir(), f"{real_claude_dir} missing -- can't run this smoke test")

        tmp = helpers.make_empty_tmp_dir(self)
        _run_git(tmp, "init", "-q")
        _run_git(tmp, "config", "user.email", "test@example.com")
        _run_git(tmp, "config", "user.name", "Test")
        data_dir = tmp / "process" / "cairn"
        for sub in ("issues", "archive", "milestones", "majors"):
            (data_dir / sub).mkdir(parents=True)
        (data_dir / "config.yml").write_text(
            "prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8"
        )
        shutil.copytree(real_claude_dir / "agents", tmp / ".claude" / "agents")
        shutil.copytree(real_claude_dir / "roles", tmp / ".claude" / "roles")
        (tmp / "README.md").write_text("x\n", encoding="utf-8")
        _run_git(tmp, "add", ".")
        _run_git(tmp, "commit", "-q", "-m", "initial")

        payload = cairn.build_roster_payload(data_dir)
        self.assertEqual(len(payload["agents"]), 11, [a["id"] for a in payload["agents"]])
        for agent in payload["agents"]:
            self.assertEqual(agent["presence"], "unknown", agent)

    def test_live_repo_roster_is_internally_consistent(self):
        # A lighter, non-fragile companion against THIS repo's actual
        # live tracker: doesn't hardcode which agent is in which state
        # (that changes as the team works), only that the payload is
        # well-formed -- eleven identities, every presence value legal,
        # no crash. Real integration coverage (wrong id resolution, a
        # crash reading the live issues/ tree) without being a slave to
        # today's assignment snapshot.
        repo_root = helpers.CAIRN_DIR.parent.parent
        data_dir = repo_root / "process" / "cairn"
        payload = cairn.build_roster_payload(data_dir)
        self.assertEqual(len(payload["agents"]), 11, [a["id"] for a in payload["agents"]])
        for agent in payload["agents"]:
            self.assertIn(agent["presence"], {"working", "idle", "unknown"}, agent)


class RosterEndpointHTTPTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = make_git_repo_with_agents(self)
        self.server = cairn.make_server(self.data_dir, port=0)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)
        self._wait_until_up()

    def _shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _wait_until_up(self):
        last_exc = None
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{self.base_url}/api/board", timeout=5).close()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        raise AssertionError(f"server never came up: {last_exc}")

    def test_get_api_roster_returns_200_json_with_agents_key(self):
        resp = urllib.request.urlopen(f"{self.base_url}/api/roster", timeout=5)
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertIn("agents", payload)
        ids = {a["id"] for a in payload["agents"]}
        self.assertEqual(ids, {"qa-engineer", "architect", "team-lead"})

    def test_get_api_dashboard_is_unaffected_by_the_roster_endpoint_existing(self):
        # The ruling's own stated point: a SEPARATE endpoint, not a key on
        # /api/dashboard. Cheap regression pin at the HTTP level,
        # complementing test_dashboard_agent_roster.py's payload-level
        # guard.
        resp = urllib.request.urlopen(f"{self.base_url}/api/dashboard", timeout=5)
        payload = json.loads(resp.read())
        self.assertNotIn("agents", payload)
        self.assertNotIn("roster", payload)


class RosterEndpointMissingClaudeDirDegradationTests(unittest.TestCase):
    """Architect's explicit follow-up: missing `.claude/agents/` must
    degrade `/api/roster` (empty roster, never a 500) AND leave
    `/api/dashboard` fully intact on the SAME server -- that isolation is
    the whole reason the ruling insists on a separate endpoint rather than
    a key on the existing payload, so it gets its own dedicated HTTP-level
    test rather than resting on the Python-level `build_roster_payload`
    never-raises test alone.
    """

    def setUp(self):
        tmp = helpers.make_empty_tmp_dir(self)
        _run_git(tmp, "init", "-q")
        _run_git(tmp, "config", "user.email", "test@example.com")
        _run_git(tmp, "config", "user.name", "Test")
        self.data_dir = tmp / "process" / "cairn"
        for sub in ("issues", "archive", "milestones", "majors"):
            (self.data_dir / sub).mkdir(parents=True)
        (self.data_dir / "config.yml").write_text(
            "prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8"
        )
        # Deliberately NO .claude/ tree anywhere under tmp.
        (tmp / "README.md").write_text("x\n", encoding="utf-8")
        _run_git(tmp, "add", ".")
        _run_git(tmp, "commit", "-q", "-m", "initial")

        self.server = cairn.make_server(self.data_dir, port=0)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)
        self._wait_until_up()

    def _shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _wait_until_up(self):
        last_exc = None
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{self.base_url}/api/board", timeout=5).close()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        raise AssertionError(f"server never came up: {last_exc}")

    def test_api_roster_degrades_to_200_empty_list_never_500(self):
        resp = urllib.request.urlopen(f"{self.base_url}/api/roster", timeout=5)
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertEqual(payload["agents"], [])

    def test_api_dashboard_is_fully_intact_when_claude_dir_is_missing(self):
        resp = urllib.request.urlopen(f"{self.base_url}/api/dashboard", timeout=5)
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertEqual(
            set(payload.keys()),
            {"git", "tracker", "check", "release", "generated_at"},
            "the roster source being entirely absent must not touch /api/dashboard's own contract at all",
        )


if __name__ == "__main__":
    unittest.main()
