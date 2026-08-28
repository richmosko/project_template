"""PT-65 failing tests: the roster payload's `work` field becomes
structured (`{id, title, status, kind}`, `kind ∈ current|stale|history`),
replacing the server-composed English strings the component re-parses
with `.split(':')`. Original ask: architect's PT-56 review, split out of
PT-60 (see process/cairn/issues/PT-65.md).

Two halves in this file:

- `RosterStructuredWorkShapeTests` / `RosterStructuredWorkKindMappingTests`
  (Python, real git fixtures, same shape as test_dashboard_roster.py --
  imports its fixture helpers rather than duplicating them) pin the
  server-side payload shape and the kind classification.
- `RosterClientStructuredWorkTests` (source-text guard, this suite's
  established shape) pins the client side: no `.split(':')` string
  parsing anywhere in App.svelte, `RosterAgent['work']` is a structured
  type not `string | null`, and App.svelte accesses the new fields.

**Kind mapping -- three of five cells are unambiguous from the existing
prose** (`build_roster_payload`'s own comments, which already describe
this taxonomy in English, just not as a `kind` enum yet):
- genuinely active (in-progress/in-review, updated today) -> `current`
  (this is literally what "working" presence means)
- working-shaped but stale (updated predates today) -> `stale` (the
  ruling names this kind explicitly, and the existing code's own comment
  calls this case out on its own branch)
- done-only, "last shipped" framing -> `history` (the existing code's
  own comment: "the work line must read as HISTORY, never current work")

**The two remaining cells were open judgment calls in this file's first
revision -- team-lead's ruling (issue thread, 2026-08-28) has since
settled both, and the assertions below are tightened to match:**
- pending (backlog/todo, nothing stale/working) -> `kind: current` --
  "queued current-cycle work, not history."
- cancelled-only -> `kind: history` -- extends PT-56's own "a done
  assignment renders only as history" principle to the other terminal
  status; supersedes implementation-lead's proposed cancelled -> current
  (+ status suffix), which the ruling says would contradict PT-56's
  honesty framing.

Nothing under test exists yet: `work` is still a composed string.
Every payload-shape test is expected to fail on a `TypeError` (string
indices must be integers) or a plain assertion failure -- never an
import error. The client-side tests fail on a genuinely-still-present
`.split(':')` / genuinely-absent structured type.
"""
from __future__ import annotations

import datetime
import re
import unittest

import helpers  # noqa: F401

import cairn

from test_dashboard_roster import make_git_repo_with_agents, write_issue

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
DASHBOARD_APP_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "App.svelte"
DASHBOARD_API_TS = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "lib" / "dashboard-api.ts"

ALLOWED_KINDS = {"current", "stale", "history"}


def _read(path):
    return path.read_text(encoding="utf-8")


def _roster_agent_type_block(source: str):
    # Non-greedy up to a closing `};` that starts its own line (no
    # leading whitespace) -- distinguishes the TYPE's own closing brace
    # from the nested `work: { ... } | null;` object's closing brace
    # (which is indented, so `\n};` never matches inside it).
    match = re.search(r"export type RosterAgent = \{(.*?)\n\};", source, re.DOTALL)
    return match.group(1) if match else None


class RosterStructuredWorkShapeTests(unittest.TestCase):
    def test_work_is_a_dict_with_exactly_the_four_ruled_keys(self):
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Fix the thing", status="in-progress", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertIsInstance(qa["work"], dict, f"work is not a dict: {qa['work']!r}")
        self.assertEqual(set(qa["work"].keys()), {"id", "title", "status", "kind"}, qa["work"])

    def test_work_is_still_none_for_an_unknown_agent(self):
        # Non-regression: the "no assignment at all" case must still be
        # None, not an empty/placeholder dict -- structuring the PRESENT
        # case must not fabricate a work object for the ABSENT case.
        data_dir = make_git_repo_with_agents(self)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertIsNone(qa["work"])

    def test_kind_is_always_one_of_the_three_ruled_values(self):
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="A", status="in-progress", assignee="qa-engineer", updated=today)
        write_issue(data_dir, id="PT-2", title="B", status="done", assignee="architect", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        for agent in payload["agents"]:
            if agent["work"] is not None:
                self.assertIn(agent["work"]["kind"], ALLOWED_KINDS, agent)

    def test_work_id_and_title_match_the_underlying_issue_exactly(self):
        # Not a formatted "id: title" string anymore -- separate fields,
        # each holding the RAW value, no punctuation glued in.
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Fix the thing: carefully", status="in-progress", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["work"]["id"], "PT-1")
        self.assertEqual(qa["work"]["title"], "Fix the thing: carefully")

    def test_stale_since_top_level_field_is_unaffected_by_the_work_restructure(self):
        # Non-regression: PT-56's separately-surfaced stale_since field
        # (architect's explicit follow-up ask) must still exist and still
        # populate exactly when kind == "stale" -- this refactor touches
        # `work`'s shape, not stale_since's.
        data_dir = make_git_repo_with_agents(self)
        write_issue(data_dir, id="PT-1", title="Stalled", status="in-progress", assignee="qa-engineer", updated="2026-08-01")
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa.get("stale_since"), "2026-08-01", qa)


class RosterStructuredWorkKindMappingTests(unittest.TestCase):
    def test_actively_working_today_maps_to_kind_current(self):
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Fix the thing", status="in-progress", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["work"]["kind"], "current", qa)
        self.assertEqual(qa["work"]["status"], "in-progress", qa)

    def test_working_shaped_but_stale_maps_to_kind_stale(self):
        data_dir = make_git_repo_with_agents(self)
        write_issue(data_dir, id="PT-1", title="Stalled", status="in-progress", assignee="qa-engineer", updated="2026-08-01")
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["work"]["kind"], "stale", qa)

    def test_done_only_maps_to_kind_history(self):
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Shipped", status="done", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["work"]["kind"], "history", qa)
        self.assertEqual(qa["work"]["status"], "done", qa)

    def test_pending_backlog_or_todo_maps_to_kind_current(self):
        # Team-lead's ruling (issue thread, 2026-08-28): "queued
        # current-cycle work, not history" -- tightened from this file's
        # original weaker `!= "history"` derivation.
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Someday", status="backlog", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["work"]["kind"], "current", qa)

    def test_cancelled_only_maps_to_kind_history(self):
        # Team-lead's ruling (issue thread, 2026-08-28): extends PT-56's
        # "a done assignment renders only as history" principle to the
        # other terminal status -- supersedes implementation-lead's
        # proposed cancelled -> current (+ status suffix). Tightened from
        # this file's original structural-only assertion.
        data_dir = make_git_repo_with_agents(self)
        today = datetime.date.today().isoformat()
        write_issue(data_dir, id="PT-1", title="Scrapped", status="cancelled", assignee="qa-engineer", updated=today)
        payload = cairn.build_roster_payload(data_dir)
        qa = next(a for a in payload["agents"] if a["id"] == "qa-engineer")
        self.assertEqual(qa["work"]["kind"], "history", qa)
        self.assertEqual(qa["work"]["status"], "cancelled", qa)


class RosterClientStructuredWorkTests(unittest.TestCase):
    def test_split_colon_string_parsing_is_gone_from_app_svelte(self):
        # A bare substring check would false-fail on a comment that
        # MENTIONS the old `.split(':')` pattern by name for explanatory
        # purposes (this file's implementation does exactly that, in a
        # PT-65 doc comment) -- require a real method-call shape instead:
        # `.split(':')` immediately preceded by an identifier character
        # (`agent.work.split(':')`), which a prose comment like "...with
        # .split(':')." never has (preceded by a space, not a word char).
        source = _read(DASHBOARD_APP_SVELTE)
        match = re.search(r"\w\.split\(['\"]:['\"]\)", source)
        self.assertIsNone(
            match,
            f"App.svelte still calls .split(\':\') as real code ({match.group(0) if match else None!r}) "
            f"-- the whole point of PT-65 is that the client no longer re-parses a composed string",
        )

    def test_roster_summary_uses_the_structured_id_field(self):
        # Replaces the old `agent.work.split(':')[0]` summary-label
        # pattern -- the collapsed <summary> should read the id straight
        # off the structured object.
        source = _read(DASHBOARD_APP_SVELTE)
        self.assertRegex(
            source, r"agent\.work\.id\b",
            "expected App.svelte to access agent.work.id somewhere (the structured "
            "replacement for the old agent.work.split(':')[0] summary label)",
        )

    def test_roster_agent_type_no_longer_declares_work_as_a_bare_string(self):
        block = _roster_agent_type_block(_read(DASHBOARD_API_TS))
        self.assertIsNotNone(block, "could not find the RosterAgent type block in dashboard-api.ts")
        self.assertNotRegex(
            block, r"work\s*:\s*string\s*\|\s*null\s*;",
            "RosterAgent['work'] is still typed as `string | null` -- PT-65 makes it a "
            "structured object",
        )

    def test_roster_agent_type_declares_the_kind_enum(self):
        block = _roster_agent_type_block(_read(DASHBOARD_API_TS))
        self.assertIsNotNone(block, "could not find the RosterAgent type block in dashboard-api.ts")
        for kind in ("current", "stale", "history"):
            self.assertIn(
                f"'{kind}'", block,
                f"RosterAgent's work type doesn't mention the {kind!r} kind literal -- "
                f"the TS type should encode the same 3-value enum the server emits",
            )


if __name__ == "__main__":
    unittest.main()
