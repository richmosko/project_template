"""PT-68 failing tests: the dashboard sidebar's header hardcodes "Cairn"
on every clone -- Mosko's scope (issue thread, 2026-08-28): show the REPO
NAME instead, derived server-side and surfaced through the payload,
never hardcoded client-side. Implementation note: "the engine already
reads git state; repo root basename is the obvious candidate -- team
decides the exact source."

**This file's own placement/naming judgment calls, not spelled out by
the ruling, flagged rather than silently assumed:**
- `repo_name` lands inside `/api/dashboard`'s existing `git` group
  (alongside `branch`/`dirty`/`head`/`latest_tag`/`warning`) rather than
  a new top-level payload key or a new endpoint -- it's git-adjacent
  data, the dashboard already fetches this payload on load, and the
  sidebar header is populated from it either way.
- `repo_name` is derived from the repo ROOT's directory basename (the
  ruling's own "obvious candidate"), via the SAME repo-root resolution
  `_repo_root_for` already uses for the roster panel (`git rev-parse
  --show-toplevel`, falling back to `data_dir.parent.parent` -- never
  raises) -- one definition point for "where is the repo root", not a
  second one growing here.
- Unlike every OTHER field in the `git` group, `repo_name` does NOT
  degrade to `null` when git itself is unavailable: resolving a
  directory's basename needs no subprocess at all (the fallback path in
  `_repo_root_for` is pure filesystem math), so a repo with no git
  history still gets an honest, non-empty header instead of the sidebar
  going blank. This is the one asymmetry in the group worth calling out
  explicitly, in case the team disagrees and wants it to degrade too.

Two halves: `DashboardPayloadRepoNameTests` (Python, real git + non-git
fixtures, imports test_dashboard.py's fixture helpers) pins the server
side; `SidebarHeaderRepoNameTests` (source-text guard) pins the client
side -- the hardcoded "Cairn" span is gone, the header renders from the
payload's `git.repo_name` field, and the `GitState` TS type gains the
field.

Nothing under test exists yet: `payload["git"]` has no `repo_name` key,
and App.svelte's sidebar header still reads the literal string "Cairn".
Every test below is expected to fail on a genuinely-missing dict key or a
genuinely-still-hardcoded string, never an import error.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

import cairn

from test_dashboard import make_git_repo, make_non_git_data_dir

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
DASHBOARD_APP_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "App.svelte"
DASHBOARD_API_TS = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "lib" / "dashboard-api.ts"


def _read(path):
    return path.read_text(encoding="utf-8")


class DashboardPayloadRepoNameTests(unittest.TestCase):
    def test_git_group_carries_a_repo_name_key(self):
        data_dir = make_git_repo(self)
        payload = cairn.build_dashboard_payload(data_dir)
        self.assertIn("repo_name", payload["git"], payload["git"])

    def test_repo_name_matches_the_repo_roots_own_directory_basename(self):
        # repo_root is data_dir.parent.parent (process/cairn -> repo
        # root) -- not data_dir's own leaf ("cairn") and not the
        # intermediate "process" -- the OUTER checkout directory's name.
        data_dir = make_git_repo(self)
        repo_root = data_dir.parent.parent
        payload = cairn.build_dashboard_payload(data_dir)
        self.assertEqual(payload["git"]["repo_name"], repo_root.name)

    def test_repo_name_is_non_empty_even_when_git_itself_is_unavailable(self):
        # Every OTHER git field degrades to None + a warning here
        # (read_git_state's whole-group-degrades posture) -- repo_name is
        # the deliberate asymmetry: a directory basename needs no
        # subprocess, so the header still has something honest to show.
        data_dir = make_non_git_data_dir(self)
        payload = cairn.build_dashboard_payload(data_dir)
        self.assertIsNone(payload["git"]["branch"], "sanity: this fixture should still degrade the other git fields")
        self.assertTrue(payload["git"].get("repo_name"), payload["git"])


class SidebarHeaderRepoNameTests(unittest.TestCase):
    def test_hardcoded_cairn_span_is_gone_from_the_sidebar_header(self):
        source = _read(DASHBOARD_APP_SVELTE)
        header_match = re.search(r"<Sidebar\.Header>(.*?)</Sidebar\.Header>", source, re.DOTALL)
        self.assertIsNotNone(header_match, "could not find the <Sidebar.Header> block in App.svelte")
        header_block = header_match.group(1)
        self.assertNotRegex(
            header_block, r">\s*Cairn\s*<",
            "the sidebar header still hardcodes the literal text 'Cairn' -- PT-68 wants it "
            "reading the repo name from the payload instead",
        )

    def test_sidebar_header_reads_the_repo_name_field(self):
        source = _read(DASHBOARD_APP_SVELTE)
        header_match = re.search(r"<Sidebar\.Header>(.*?)</Sidebar\.Header>", source, re.DOTALL)
        self.assertIsNotNone(header_match)
        header_block = header_match.group(1)
        self.assertRegex(
            header_block, r"\.git\.repo_name\b",
            "expected the <Sidebar.Header> block to reference <something>.git.repo_name "
            "somewhere -- the structured replacement for the hardcoded 'Cairn' text",
        )

    def test_git_state_type_declares_repo_name(self):
        source = _read(DASHBOARD_API_TS)
        match = re.search(r"export type GitState = \{(.*?)\n\};", source, re.DOTALL)
        self.assertIsNotNone(match, "could not find the GitState type block in dashboard-api.ts")
        block = match.group(1)
        self.assertRegex(
            block, r"repo_name\s*:\s*string",
            "GitState's TS type doesn't declare repo_name: string -- the client type should "
            "match the new payload field",
        )


if __name__ == "__main__":
    unittest.main()
