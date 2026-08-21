"""Tests for PT-3's multi-root read-only board -- cross-project
aggregation in `cairn serve`. Built directly against architect's design
note (temp/2026-08-21-architect-pt3-design.md), which is the authoritative
interface here (Root NamedTuple shape, function names/signatures, the
warn-and-skip reason-code table, the payload shape) more so than QA's own
invention in earlier features.

Deliberately NOT covered here, per the design note's open rulings (§7) --
do not add these until team-lead rules:
  - Swimlane/major-tab grouping when milestone ids collide across roots
    (§7-A, blocking `renderKanban` too).
  - `cairn check` validation of `roots:` shape (§7-C -- the ruling is
    about whether reachability is even checkable, which changes what
    "valid" means here).
  - `--repos` CLI semantics (§7-B -- replace vs. union changes the
    assertions entirely).
Also out of scope structurally, per the design: `cairn ls/show/set/
comment/new/check/snapshot/archive` stay strictly single-root in v1 --
nothing here exercises `--repos` or multi-root through those commands.

Interface assumed (architect's §1.2, §1.1):
    Root = NamedTuple("Root", [("id", str), ("label", str), ("path", Path), ("primary", bool)])
    resolve_roots(data_dir, config, cli_repos=None) -> (List[Root], List[dict])
    build_multi_board_payload(roots, warnings) -> dict
    compute_multi_etag(roots) -> str
    find_issue_in_roots(roots, issue_id) -> Optional[Root]
    make_server(data_dir, config=None, port=None, roots=None)  -- roots is new,
        optional; omitted/None synthesises the single primary root (back-compat).
    DataDirWatcher(roots, broadcaster, interval=1.0)  -- takes roots, not data_dir

Back-compat note (§1.3, §7 framing): the load-bearing back-compat claim is
that every existing test_server.py test keeps passing UNMODIFIED. That is
not re-tested here -- it IS the test, by construction, as long as nobody
edits test_server.py for this feature.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import helpers  # noqa: F401

import cairn


def http_get(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=5)


def http_post(url: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    return urllib.request.urlopen(req, timeout=5)


# --------------------------------------------------------------------------
# Fixture helpers -- each test builds its own sibling-repos tree rather
# than sharing one, so a bad fixture in one test can't bleed into another
# (matches test_check_lint.py's / test_snapshot.py's existing convention).
# --------------------------------------------------------------------------

def make_repo(tmp_base: Path, dirname: str, prefix: str, port: int = 8766) -> Path:
    """A standalone tracker repo at tmp_base/<dirname>/process/cairn.
    Returns the data_dir. `tmp_base.parent.parent` is what resolve_roots
    treats as "the repo root" for a root built from this data_dir as
    primary -- i.e. this mirrors the real process/cairn layout exactly,
    not a flattened test shortcut.
    """
    data_dir = tmp_base / dirname / "process" / "cairn"
    (data_dir / "issues").mkdir(parents=True)
    (data_dir / "archive").mkdir(parents=True)
    (data_dir / "milestones").mkdir(parents=True)
    (data_dir / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text(
        f"prefix: {prefix}\nport: {port}\ndata_dir: process/cairn\n", encoding="utf-8"
    )
    return data_dir


def write_major(data_dir: Path, filename: str, major_id: str) -> None:
    text = f"---\nid: {major_id}\nstatus: active\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"
    (data_dir / "majors" / filename).write_text(text, encoding="utf-8")


def write_milestone(data_dir: Path, filename: str, milestone_id: str, name: str, major: str) -> None:
    text = (
        f"---\nid: {milestone_id}\nname: {name}\nkind: product\nmajor: {major}\nstatus: planned\n"
        "target_tag: null\nga: false\n---\n\nDoD.\n"
    )
    (data_dir / "milestones" / filename).write_text(text, encoding="utf-8")


def write_issue(data_dir: Path, filename: str, issue_id: str, title: str, status: str, milestone: str = "null") -> None:
    text = (
        "---\n"
        f"id: {issue_id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\nparent: null\n"
        "assignee: null\nlabels: []\npriority: null\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n"
        "---\n\nBody.\n"
    )
    (data_dir / "issues" / filename).write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# resolve_roots
# --------------------------------------------------------------------------

class ResolveRootsBaseTests(unittest.TestCase):
    def test_no_roots_key_yields_single_primary_root_no_warnings(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        roots, warnings = cairn.resolve_roots(primary, {"prefix": "AA", "port": 8766})
        self.assertEqual(warnings, [])
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].id, "AA")
        self.assertEqual(roots[0].label, "repo_a")
        self.assertEqual(roots[0].path, primary)
        self.assertTrue(roots[0].primary)

    def test_empty_roots_list_yields_single_primary_root(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        roots, warnings = cairn.resolve_roots(primary, {"prefix": "AA", "port": 8766, "roots": []})
        self.assertEqual(warnings, [])
        self.assertEqual(len(roots), 1)
        self.assertTrue(roots[0].primary)

    def test_primary_is_always_element_zero(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        secondary = make_repo(tmp, "repo_b", "BB")
        assert secondary  # exists on disk; entry below references it by relative name
        roots, _warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../repo_b"]}
        )
        self.assertTrue(roots[0].primary)
        self.assertEqual(roots[0].id, "AA")


class ResolveRootsPathShapeTests(unittest.TestCase):
    """§2.1: a root entry may point directly at a data dir (p/config.yml
    exists), or at a repo root (p/process/cairn/config.yml exists)."""

    def test_entry_pointing_directly_at_a_data_dir(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        make_repo(tmp, "repo_b", "BB")
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../repo_b/process/cairn"]}
        )
        self.assertEqual(warnings, [])
        self.assertEqual(len(roots), 2)
        secondary = roots[1]
        self.assertEqual(secondary.id, "BB")
        self.assertEqual(secondary.label, "repo_b")
        self.assertFalse(secondary.primary)

    def test_entry_pointing_at_a_repo_root(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        make_repo(tmp, "repo_b", "BB")
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../repo_b"]}
        )
        self.assertEqual(warnings, [])
        self.assertEqual(len(roots), 2)
        secondary = roots[1]
        self.assertEqual(secondary.id, "BB")
        self.assertEqual(secondary.label, "repo_b")
        self.assertFalse(secondary.primary)


class ResolveRootsWarnAndSkipTests(unittest.TestCase):
    """§2.2's exhaustive reason-code table, secondaries only (primary is
    exempt -- see ResolveRootsPrimaryExemptTests)."""

    def test_missing_directory_is_not_found(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../does-not-exist"]}
        )
        self.assertEqual(len(roots), 1)  # primary only
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["reason"], "not_found")
        self.assertEqual(warnings[0]["root"], "../does-not-exist")

    def test_directory_with_no_config_yml_at_either_shape_is_not_found(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        (tmp / "repo_b" / "process" / "cairn").mkdir(parents=True)  # no config.yml anywhere
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../repo_b"]}
        )
        self.assertEqual(len(roots), 1)
        self.assertEqual(warnings[0]["reason"], "not_found")

    def test_malformed_secondary_config_is_bad_config(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        secondary = make_repo(tmp, "repo_b", "BB")
        # An anchor is outside parse_yaml_subset's documented subset --
        # YamlError, same construct test_yaml_parser.py's LoudErrorTests
        # already pins as rejected.
        (secondary / "config.yml").write_text("prefix: &anchor BB\nport: 8766\n", encoding="utf-8")
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../repo_b"]}
        )
        self.assertEqual(len(roots), 1)
        self.assertEqual(warnings[0]["reason"], "bad_config")

    def test_duplicate_secondary_prefix_keeps_first_drops_second(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        make_repo(tmp, "repo_b", "DUP")
        make_repo(tmp, "repo_c", "DUP")
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../repo_b", "../repo_c"]}
        )
        dup_roots = [r for r in roots if r.id == "DUP"]
        self.assertEqual(len(dup_roots), 1)
        self.assertEqual(dup_roots[0].label, "repo_b")  # first wins
        self.assertTrue(any(w["reason"] == "duplicate" for w in warnings), warnings)

    def test_absolute_path_entry_is_bad_entry(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        secondary = make_repo(tmp, "repo_b", "BB")
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": [str(secondary)]}
        )
        self.assertEqual(len(roots), 1)
        self.assertEqual(warnings[0]["reason"], "bad_entry")

    def test_non_string_entry_is_bad_entry(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": [123]}
        )
        self.assertEqual(len(roots), 1)
        self.assertEqual(warnings[0]["reason"], "bad_entry")

    def test_zero_reachable_secondaries_is_not_an_error(self):
        # Every entry unreachable -- board still resolves to just the
        # primary root, no exception.
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../nope-1", "../nope-2"]}
        )
        self.assertEqual(len(roots), 1)
        self.assertEqual(len(warnings), 2)


class ResolveRootsPrimaryExemptTests(unittest.TestCase):
    """§2.2: "The primary root is exempt from all of this." A broken
    primary is a hard CairnError via resolve_data_dir upstream, never a
    warn-and-skip entry -- resolve_roots itself always trusts the
    already-resolved primary data_dir it's given, unconditionally.
    """

    def test_primary_root_entry_is_never_a_warning_even_if_it_were_reachable_via_roots_too(self):
        # Degenerate but telling case: if the primary's own path somehow
        # also appeared in the roots: list (e.g. a copy-paste config
        # mistake), it must not produce a duplicate/self-referential
        # warning that could ever suppress the primary itself.
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        roots, warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["."]}
        )
        primaries = [r for r in roots if r.primary]
        self.assertEqual(len(primaries), 1)
        self.assertEqual(primaries[0].path, primary)


class ResolveRootsCliReposTests(unittest.TestCase):
    """Team-lead's ruling B (2026-08-21): `--repos` REPLACES config.yml's
    `roots:` list, not unions with it; the primary root is always included
    regardless. Tested at `resolve_roots`'s `cli_repos` parameter directly
    -- `cmd_serve --repos` is a thin argparse-to-comma-split wrapper over
    the same call, not re-tested at the CLI/subprocess level here (`serve`
    is long-running; there's nothing left to prove once this layer is
    pinned).
    """

    def test_cli_repos_replaces_config_roots_entirely(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        make_repo(tmp, "repo_b", "BB")  # named in config.yml's roots:
        make_repo(tmp, "repo_c", "CC")  # named only via cli_repos
        roots, warnings = cairn.resolve_roots(
            primary,
            {"prefix": "AA", "port": 8766, "roots": ["../repo_b"]},
            cli_repos=["../repo_c"],
        )
        self.assertEqual(warnings, [])
        ids = {r.id for r in roots}
        self.assertEqual(ids, {"AA", "CC"})  # BB replaced away, not unioned in

    def test_cli_repos_none_falls_back_to_config_roots(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        make_repo(tmp, "repo_b", "BB")
        roots, _warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../repo_b"]}, cli_repos=None
        )
        self.assertEqual({r.id for r in roots}, {"AA", "BB"})

    def test_cli_repos_empty_list_means_primary_only_even_with_config_roots_set(self):
        # Explicit "no secondaries" override -- distinct from cli_repos=None
        # (which defers to config). An empty --repos must not be silently
        # reinterpreted as "no override given."
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        make_repo(tmp, "repo_b", "BB")
        roots, _warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766, "roots": ["../repo_b"]}, cli_repos=[]
        )
        self.assertEqual({r.id for r in roots}, {"AA"})

    def test_primary_always_included_regardless_of_cli_repos(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        make_repo(tmp, "repo_c", "CC")
        roots, _warnings = cairn.resolve_roots(
            primary, {"prefix": "AA", "port": 8766}, cli_repos=["../repo_c"]
        )
        self.assertTrue(any(r.primary and r.id == "AA" for r in roots), roots)


# --------------------------------------------------------------------------
# check_repo: `roots:` shape validation (team-lead's ruling C, 2026-08-21 --
# shape only, never reachability; a sibling repo absent on this clone/CI
# machine must not fail lint).
# --------------------------------------------------------------------------

class CheckRepoRootsShapeTests(unittest.TestCase):
    def _data_dir_with_config(self, config_text: str) -> Path:
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text(config_text, encoding="utf-8")
        return data_dir

    def test_no_roots_key_is_clean(self):
        data_dir = self._data_dir_with_config("prefix: AA\nport: 8766\n")
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_roots_as_a_flat_list_of_relative_paths_is_clean(self):
        data_dir = self._data_dir_with_config(
            "prefix: AA\nport: 8766\nroots:\n  - ../repo-b\n  - ../repo-c\n"
        )
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_roots_not_a_list_is_an_error(self):
        # A bare scalar under `roots:` -- parse_yaml_subset gives a plain
        # string here, not a list.
        data_dir = self._data_dir_with_config("prefix: AA\nport: 8766\nroots: nope\n")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("roots" in e and "list" in e.lower() for e in errors), errors)

    def test_non_string_entry_is_an_error(self):
        data_dir = self._data_dir_with_config("prefix: AA\nport: 8766\nroots:\n  - 123\n")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("roots" in e for e in errors), errors)

    def test_absolute_path_entry_is_an_error(self):
        data_dir = self._data_dir_with_config(
            "prefix: AA\nport: 8766\nroots:\n  - /etc/nope\n"
        )
        errors = cairn.check_repo(data_dir)
        self.assertTrue(
            any("roots" in e and "relative" in e.lower() for e in errors), errors
        )

    def test_empty_string_entry_is_an_error(self):
        data_dir = self._data_dir_with_config("prefix: AA\nport: 8766\nroots:\n  - \"\"\n")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("roots" in e for e in errors), errors)

    def test_a_root_path_that_does_not_exist_on_disk_is_not_flagged(self):
        # The load-bearing negative case: reachability is a runtime/warn-
        # and-skip concern (resolve_roots), never a lint error -- `cairn
        # check` must stay green in CI and on any clone lacking the
        # sibling repo.
        data_dir = self._data_dir_with_config(
            "prefix: AA\nport: 8766\nroots:\n  - ../this-repo-does-not-exist-anywhere\n"
        )
        self.assertEqual(cairn.check_repo(data_dir), [])


# --------------------------------------------------------------------------
# build_multi_board_payload
# --------------------------------------------------------------------------

class MultiRootPayloadTests(unittest.TestCase):
    def test_repo_stamped_on_every_record_type(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        secondary = make_repo(tmp, "repo_b", "BB")
        write_major(primary, "V1.md", "V1")
        write_major(secondary, "V9.md", "V9")
        write_milestone(primary, "1.0.md", '"1.0"', "MVP", major="V1")
        write_milestone(secondary, "2.0.md", '"2.0"', "Next", major="V9")
        write_issue(primary, "AA-1.md", "AA-1", "A", status="todo")
        write_issue(secondary, "BB-1.md", "BB-1", "B", status="todo")
        roots = [
            cairn.Root(id="AA", label="repo_a", path=primary, primary=True),
            cairn.Root(id="BB", label="repo_b", path=secondary, primary=False),
        ]
        payload = cairn.build_multi_board_payload(roots, [])
        for major in payload["majors"]:
            self.assertIn("repo", major)
        for ms in payload["milestones"]:
            self.assertIn("repo", ms)
        for issue in payload["issues"]:
            self.assertIn("repo", issue)
        self.assertEqual({i["repo"] for i in payload["issues"]}, {"AA", "BB"})
        self.assertEqual({m["repo"] for m in payload["majors"]}, {"AA", "BB"})
        self.assertEqual({m["repo"] for m in payload["milestones"]}, {"AA", "BB"})

    def test_payload_carries_roots_and_warnings_top_level(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        roots = [cairn.Root(id="AA", label="repo_a", path=primary, primary=True)]
        given_warnings = [{"root": "../gone", "reason": "not_found", "detail": "x"}]
        payload = cairn.build_multi_board_payload(roots, given_warnings)
        self.assertEqual(payload["warnings"], given_warnings)
        self.assertEqual(len(payload["roots"]), 1)
        self.assertEqual(payload["roots"][0]["id"], "AA")
        self.assertTrue(payload["roots"][0]["primary"])

    def test_single_root_back_compat_shape(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        write_issue(primary, "AA-1.md", "AA-1", "A", status="todo")
        roots = [cairn.Root(id="AA", label="repo_a", path=primary, primary=True)]
        payload = cairn.build_multi_board_payload(roots, [])
        self.assertEqual(len(payload["roots"]), 1)
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["issues"][0]["repo"], "AA")

    def test_secondary_root_with_unparseable_file_contributes_nothing_and_warns(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        secondary = make_repo(tmp, "repo_b", "BB")
        write_issue(primary, "AA-1.md", "AA-1", "A", status="todo")
        write_issue(secondary, "BB-1.md", "BB-1", "B", status="todo")
        (secondary / "issues" / "BB-2.md").write_text(
            "---\nid: BB-2\ntitle: Bad\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: &anchor null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        roots = [
            cairn.Root(id="AA", label="repo_a", path=primary, primary=True),
            cairn.Root(id="BB", label="repo_b", path=secondary, primary=False),
        ]
        payload = cairn.build_multi_board_payload(roots, [])
        self.assertEqual([i["id"] for i in payload["issues"] if i["repo"] == "AA"], ["AA-1"])
        self.assertEqual([i["id"] for i in payload["issues"] if i["repo"] == "BB"], [])
        self.assertTrue(
            any(w.get("reason") == "parse_error" for w in payload["warnings"]), payload["warnings"]
        )


# --------------------------------------------------------------------------
# compute_multi_etag
# --------------------------------------------------------------------------

class MultiRootEtagTests(unittest.TestCase):
    def test_touching_a_secondary_root_file_changes_the_etag(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        secondary = make_repo(tmp, "repo_b", "BB")
        write_issue(primary, "AA-1.md", "AA-1", "A", status="todo")
        write_issue(secondary, "BB-1.md", "BB-1", "B", status="todo")
        roots = [
            cairn.Root(id="AA", label="repo_a", path=primary, primary=True),
            cairn.Root(id="BB", label="repo_b", path=secondary, primary=False),
        ]
        before = cairn.compute_multi_etag(roots)
        cairn.apply_patch(secondary / "issues" / "BB-1.md", {"status": "in-progress"})
        after = cairn.compute_multi_etag(roots)
        self.assertNotEqual(before, after)

    def test_etag_is_stable_when_nothing_changes(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        secondary = make_repo(tmp, "repo_b", "BB")
        write_issue(primary, "AA-1.md", "AA-1", "A", status="todo")
        roots = [
            cairn.Root(id="AA", label="repo_a", path=primary, primary=True),
            cairn.Root(id="BB", label="repo_b", path=secondary, primary=False),
        ]
        first = cairn.compute_multi_etag(roots)
        second = cairn.compute_multi_etag(roots)
        self.assertEqual(first, second)


# --------------------------------------------------------------------------
# find_issue_in_roots
# --------------------------------------------------------------------------

class FindIssueInRootsTests(unittest.TestCase):
    def test_finds_the_root_an_issue_lives_in(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        secondary = make_repo(tmp, "repo_b", "BB")
        write_issue(primary, "AA-1.md", "AA-1", "A", status="todo")
        write_issue(secondary, "BB-1.md", "BB-1", "B", status="todo")
        roots = [
            cairn.Root(id="AA", label="repo_a", path=primary, primary=True),
            cairn.Root(id="BB", label="repo_b", path=secondary, primary=False),
        ]
        found = cairn.find_issue_in_roots(roots, "BB-1")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, "BB")

    def test_returns_none_for_an_unknown_id(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        roots = [cairn.Root(id="AA", label="repo_a", path=primary, primary=True)]
        self.assertIsNone(cairn.find_issue_in_roots(roots, "ZZ-999"))

    def test_is_a_distinct_function_from_find_issue_path(self):
        # Structural guard for §5.1's design point: find_issue_path must
        # never itself have grown roots-awareness (that would blur the
        # exact boundary that makes cross-root writes unreachable). A
        # secondary-only id must NOT resolve via find_issue_path against
        # the primary data_dir.
        tmp = helpers.make_empty_tmp_dir(self)
        primary = make_repo(tmp, "repo_a", "AA")
        secondary = make_repo(tmp, "repo_b", "BB")
        write_issue(secondary, "BB-1.md", "BB-1", "B", status="todo")
        self.assertIsNone(cairn.find_issue_path(primary, "BB-1"))


# --------------------------------------------------------------------------
# Server-level: the critical read-only guarantee (§5), plus SSE/watcher
# cross-root namespacing (§1.4).
# --------------------------------------------------------------------------

class MultiRootServerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_base = helpers.make_empty_tmp_dir(self)
        self.primary_dir = make_repo(self.tmp_base, "repo_a", "AA")
        self.secondary_dir = make_repo(self.tmp_base, "repo_b", "BB")
        write_issue(self.primary_dir, "AA-1.md", "AA-1", "Primary issue", status="todo")
        write_issue(self.secondary_dir, "BB-1.md", "BB-1", "Secondary issue", status="todo")
        write_milestone(self.secondary_dir, "0.5.md", '"0.5"', "Their polish", major="V1")
        self.roots = [
            cairn.Root(id="AA", label="repo_a", path=self.primary_dir, primary=True),
            cairn.Root(id="BB", label="repo_b", path=self.secondary_dir, primary=False),
        ]
        self.server = cairn.make_server(self.primary_dir, port=0, roots=self.roots)
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
                http_get(f"{self.base_url}/api/board").close()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        raise AssertionError(f"server never came up: {last_exc}")


class MultiRootReadOnlyTests(MultiRootServerTestCase):
    """§5: the assertion that matters most. A mutation aimed at a
    secondary-root issue must be refused with a truthful error, and the
    file itself must be provably untouched -- not just "the response
    looked like an error"."""

    def test_mutating_a_secondary_root_issue_is_rejected_with_403(self):
        secondary_path = self.secondary_dir / "issues" / "BB-1.md"
        before = secondary_path.read_bytes()
        req = urllib.request.Request(
            f"{self.base_url}/api/issue/BB-1",
            data=json.dumps({"seen": None, "patch": {"status": "done"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("expected an HTTPError (403) but the request succeeded")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 403)
            body = json.loads(exc.read())
            self.assertEqual(body.get("error"), "read_only_root")
        after = secondary_path.read_bytes()
        self.assertEqual(before, after, "a rejected cross-root write must not touch the file at all")

    def test_primary_root_writes_still_work_with_multiple_roots_configured(self):
        # Discriminates a broken read-only check that blocks ALL writes
        # (not just foreign ones) from the correct, narrowly-scoped one.
        result = http_post(
            f"{self.base_url}/api/issue/AA-1", {"seen": None, "patch": {"status": "in-progress"}}
        )
        self.assertEqual(result.status, 200)
        fm, _ = cairn.parse_frontmatter(
            (self.primary_dir / "issues" / "AA-1.md").read_text(encoding="utf-8")
        )
        self.assertEqual(fm["status"], "in-progress")

    def test_get_issue_from_secondary_root_is_readable_and_marked_read_only(self):
        resp = http_get(f"{self.base_url}/api/issue/BB-1")
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertEqual(payload.get("repo"), "BB")
        self.assertTrue(payload.get("read_only"))

    def test_get_issue_from_primary_root_is_not_read_only(self):
        resp = http_get(f"{self.base_url}/api/issue/AA-1")
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertEqual(payload.get("repo"), "AA")
        self.assertFalse(payload.get("read_only"))


class MultiRootSSETests(MultiRootServerTestCase):
    """§1.4: watcher scan keys must be namespaced per root ("<root.id>:<sub>/
    <file>.md") -- both roots have a milestones/0.5.md, so an unnamespaced
    key would let a change in one root be masked by an identical-looking
    key in the other."""

    def test_change_in_secondary_root_fires_an_sse_event(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.addCleanup(sock.close)
        sock.settimeout(5)
        sock.sendall(
            b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        _head, _, leftover = buf.partition(b"\r\n\r\n")

        cairn.apply_patch(self.secondary_dir / "milestones" / "0.5.md", {"name": "Renamed"})

        deadline = time.time() + 5.0
        got_frame = False
        buf = leftover
        while time.time() < deadline:
            if b"\n\n" in buf:
                got_frame = True
                break
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
        self.assertTrue(got_frame, "no SSE frame arrived within 5s of a secondary-root mutation")


if __name__ == "__main__":
    unittest.main()
