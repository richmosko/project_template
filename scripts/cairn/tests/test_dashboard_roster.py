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
        # requirement, so it gets its own dedicated test.
        data_dir = make_git_repo_with_agents(self)
        write_issue(data_dir, id="PT-1", title="Stalled", status="in-progress", assignee="qa-engineer", updated="2026-08-01")
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["presence"], "idle")

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


if __name__ == "__main__":
    unittest.main()
