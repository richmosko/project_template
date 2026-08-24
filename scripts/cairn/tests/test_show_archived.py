"""PASS 1 failing tests for PT-42: the "Show Archived" server surface.
Architect's ruling: temp/arch-ruling-pt42-show-archived.md.

§0/§1: `GET /api/board?archived=1` -- OFF (no param) is THE IDENTICAL code
path, unchanged (byte-identical to today, structural not asserted). ON
additionally serves archived issues (archive/), archived milestones
(archive/milestones/), archived majors (archive/majors/) -- ONE archive
read path for all three. Every record carries `archived: true`/`false`
(never absent -- PT-3 no-conditional-shape precedent). Archived issues
land in the SAME `issues` array (no parallel array -- the load-bearing
"visible must equal counted" plumbing decision). ETag folds the flag in
(two representations must never share one etag); multi-root applies the
flag per root.

§5: archived cards are read-only server-side too -- `POST /api/issue/<id>`
where the id resolves in `archive/` is refused `403 {"error": "archived"}`,
file untouched, mirroring the existing `read_only_root` 403 shape. The CLI
(`cairn set`/`cairn comment`) is DELIBERATELY still allowed -- only the
HTTP write path is restricted (find_issue_path itself stays unchanged,
same PT-3 precedent PT-39 already established for it).

Tested through the live HTTP server (test_server.py's ServerTestCase
pattern) rather than through implementation-lead's eventual internal
function names -- the query-param/etag/403 surface is inherently an HTTP-
layer concern, and this convention already served this suite's other
Pass-1 slices well (test_archive_records.py's CLI-level tests, etc.).

Nothing under test exists yet: `?archived=1` is not read by do_GET at all
(archive/ is never served over HTTP), no record carries an `archived` key,
and `_mutate_issue` never distinguishes an archived issue from a live one
(find_issue_path already resolves archive/, so today a POST to an
archived issue SUCCEEDS -- the opposite of the required 403). Every test
below is expected to fail until implementation-lead's PT-42 slice lands.
"""
from __future__ import annotations

import json
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


class ServerTestCase(unittest.TestCase):
    """Mirrors test_server.py's own ServerTestCase exactly -- duplicated
    here (rather than imported) so this file has no import-order
    dependency on that one; same fixture-copy-per-test isolation."""

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
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
                http_get(f"{self.base_url}/api/board").close()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        raise AssertionError(f"server never came up: {last_exc}")


ISSUE_TMPL = (
    "---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\nparent: null\n"
    "assignee: null\nlabels: []\npriority: null\npr: null\n"
    "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n"
)
MILESTONE_TMPL = (
    "---\nid: {id}\nname: {name}\nkind: {kind}\nmajor: {major}\nstatus: {status}\n"
    "target_tag: {target_tag}\nga: {ga}\n---\n\nDoD.\n"
)
MAJOR_TMPL = "---\nid: {id}\nstatus: {status}\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"


class DefaultOffByteIdenticalTests(ServerTestCase):
    """AC2: off-state (no param) must be THE IDENTICAL code path -- adding
    archived data must not change the default response AT ALL."""

    def test_default_board_response_is_byte_identical_with_and_without_archived_data(self):
        before = http_get(f"{self.base_url}/api/board").read()

        (self.data_dir / "archive" / "milestones").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "archive" / "majors").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "archive" / "milestones" / "PT-Z.md").write_text(
            MILESTONE_TMPL.format(id="PT-Z", name="Old", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        (self.data_dir / "archive" / "majors" / "PT-Z1.md").write_text(
            MAJOR_TMPL.format(id="PT-Z1", status="done"), encoding="utf-8"
        )

        after = http_get(f"{self.base_url}/api/board").read()
        self.assertEqual(before, after, "the DEFAULT /api/board response must never change based on archive/ contents")

    def test_default_board_excludes_existing_archived_issue(self):
        # The shared fixture already ships archive/issues/PT-9.md (PT-50;
        # test_server.py's own comment: "PT-9 is archived, excluded") --
        # regression pin.
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        ids = {i["id"] for i in payload["issues"]}
        self.assertNotIn("PT-9", ids)


class ArchivedParamServesArchiveDataTests(ServerTestCase):
    def test_archived_param_includes_the_archived_issue_in_the_same_issues_array(self):
        resp = http_get(f"{self.base_url}/api/board?archived=1")
        payload = json.loads(resp.read())
        ids = {i["id"] for i in payload["issues"]}
        self.assertIn("PT-9", ids, "PT-9 (archive/issues/PT-9.md in the shared fixture) must appear once ?archived=1")
        # Load-bearing: NOT a parallel array.
        self.assertNotIn("archivedIssues", payload)

    def test_archived_issues_are_stamped_archived_true(self):
        resp = http_get(f"{self.base_url}/api/board?archived=1")
        payload = json.loads(resp.read())
        pt9 = next(i for i in payload["issues"] if i["id"] == "PT-9")
        self.assertIs(pt9["archived"], True)

    def test_an_archived_cancelled_issue_is_served_with_both_facts_independently_true(self):
        # AC4 / ruling §4: "no new counting rule ... an archived cancelled
        # issue renders only when BOTH toggles are on" falls out of two
        # ALREADY-independent mechanisms with no special-casing needed --
        # server-side inclusion (this flag) and client-side status
        # filtering (existing showCancelled logic, unit-tested elsewhere).
        # This pins the server's half of that claim directly: archived and
        # cancelled must be two orthogonal facts on the SAME record, not
        # something the server filters/conflates based on one or the other.
        (self.data_dir / "archive" / "PT-88.md").write_text(
            ISSUE_TMPL.format(id="PT-88", title="Archived and cancelled", status="cancelled", milestone="null"),
            encoding="utf-8",
        )
        resp = http_get(f"{self.base_url}/api/board?archived=1")
        payload = json.loads(resp.read())
        pt88 = next(i for i in payload["issues"] if i["id"] == "PT-88")
        self.assertIs(pt88["archived"], True)
        self.assertEqual(pt88["status"], "cancelled")

    def test_an_archived_cancelled_issue_is_absent_by_default_for_the_archived_reason_alone(self):
        # The other half: with the toggle OFF, it must be absent because
        # it's archived -- not conflated with "absent because cancelled"
        # (a server that special-cased "cancelled implies excluded"
        # regardless of archived status would pass this test for the
        # wrong reason if it excluded PT-88 from the default payload for
        # its STATUS rather than its archive/ location -- guarded by the
        # sibling test above pinning cancelled's independent presence
        # when archived=1).
        (self.data_dir / "archive" / "PT-88.md").write_text(
            ISSUE_TMPL.format(id="PT-88", title="Archived and cancelled", status="cancelled", milestone="null"),
            encoding="utf-8",
        )
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        ids = {i["id"] for i in payload["issues"]}
        self.assertNotIn("PT-88", ids)

    def test_live_issues_are_stamped_archived_false_even_when_param_is_off(self):
        # Every record ALWAYS carries the key -- never absent (PT-3 no-
        # conditional-shape precedent) -- checked on the default (off) path.
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        pt1 = next(i for i in payload["issues"] if i["id"] == "PT-1")
        self.assertIs(pt1["archived"], False)

    def test_live_issues_are_stamped_archived_false_when_param_is_on_too(self):
        resp = http_get(f"{self.base_url}/api/board?archived=1")
        payload = json.loads(resp.read())
        pt1 = next(i for i in payload["issues"] if i["id"] == "PT-1")
        self.assertIs(pt1["archived"], False)

    def test_archived_milestones_are_served_and_stamped_when_param_is_on(self):
        (self.data_dir / "archive" / "milestones").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "archive" / "milestones" / "PT-Z.md").write_text(
            MILESTONE_TMPL.format(id="PT-Z", name="Old", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        resp = http_get(f"{self.base_url}/api/board?archived=1")
        payload = json.loads(resp.read())
        pt_z = next((m for m in payload["milestones"] if m["id"] == "PT-Z"), None)
        self.assertIsNotNone(pt_z, "archived milestone must appear in the milestones array when ?archived=1")
        self.assertIs(pt_z["archived"], True)

    def test_archived_majors_are_served_and_stamped_when_param_is_on(self):
        (self.data_dir / "archive" / "majors").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "archive" / "majors" / "PT-Z1.md").write_text(
            MAJOR_TMPL.format(id="PT-Z1", status="done"), encoding="utf-8"
        )
        resp = http_get(f"{self.base_url}/api/board?archived=1")
        payload = json.loads(resp.read())
        pt_z1 = next((m for m in payload["majors"] if m["id"] == "PT-Z1"), None)
        self.assertIsNotNone(pt_z1, "archived major must appear in the majors array when ?archived=1")
        self.assertIs(pt_z1["archived"], True)

    def test_archived_milestones_and_majors_absent_by_default(self):
        (self.data_dir / "archive" / "milestones").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "archive" / "milestones" / "PT-Z.md").write_text(
            MILESTONE_TMPL.format(id="PT-Z", name="Old", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        milestone_ids = {m["id"] for m in payload["milestones"]}
        self.assertNotIn("PT-Z", milestone_ids)


class ETagTests(ServerTestCase):
    def test_default_and_archived_etags_differ(self):
        etag_off = http_get(f"{self.base_url}/api/board").headers.get("ETag")
        etag_on = http_get(f"{self.base_url}/api/board?archived=1").headers.get("ETag")
        self.assertNotEqual(etag_off, etag_on, "two different representations must never share one etag")

    def test_an_etag_minted_off_does_not_304_a_request_for_on(self):
        etag_off = http_get(f"{self.base_url}/api/board").headers.get("ETag")
        # Sending the OFF etag against the ON endpoint must not 304 --
        # they're different representations.
        resp = http_get(f"{self.base_url}/api/board?archived=1", headers={"If-None-Match": etag_off})
        self.assertEqual(resp.status, 200)

    def test_archived_etag_supports_304_on_repeat(self):
        etag = http_get(f"{self.base_url}/api/board?archived=1").headers.get("ETag")
        self.assertTrue(etag)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            http_get(f"{self.base_url}/api/board?archived=1", headers={"If-None-Match": etag})
        self.assertEqual(ctx.exception.code, 304)

    def test_archived_etag_changes_when_an_archive_file_is_added(self):
        etag_before = http_get(f"{self.base_url}/api/board?archived=1").headers.get("ETag")
        (self.data_dir / "archive" / "PT-99.md").write_text(
            ISSUE_TMPL.format(id="PT-99", title="New archive add", status="done", milestone="null"),
            encoding="utf-8",
        )
        etag_after = http_get(f"{self.base_url}/api/board?archived=1").headers.get("ETag")
        self.assertNotEqual(etag_before, etag_after)

    def test_default_etag_is_unaffected_by_an_archive_file_being_added(self):
        etag_before = http_get(f"{self.base_url}/api/board").headers.get("ETag")
        (self.data_dir / "archive" / "PT-99.md").write_text(
            ISSUE_TMPL.format(id="PT-99", title="New archive add", status="done", milestone="null"),
            encoding="utf-8",
        )
        etag_after = http_get(f"{self.base_url}/api/board").headers.get("ETag")
        self.assertEqual(etag_before, etag_after, "the default (off) etag must not depend on archive/ contents at all")


class ArchivedIssueWriteRefusedTests(ServerTestCase):
    """§5: POST /api/issue/<id> for an archived id is refused 403 {"error":
    "archived"}, file untouched -- mirrors read_only_root's shape exactly."""

    def test_post_to_an_archived_issue_is_refused_403(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            http_post(f"{self.base_url}/api/issue/PT-9", {"seen": None, "patch": {"status": "todo"}})
        self.assertEqual(ctx.exception.code, 403)
        body = json.loads(ctx.exception.read())
        self.assertEqual(body.get("error"), "archived")

    def test_post_to_an_archived_issue_leaves_the_file_untouched(self):
        # PT-50: shared fixture's PT-9 now lives at archive/issues/, not
        # the legacy flat archive/.
        before = (self.data_dir / "archive" / "issues" / "PT-9.md").read_bytes()
        try:
            http_post(f"{self.base_url}/api/issue/PT-9", {"seen": None, "patch": {"status": "todo"}})
        except urllib.error.HTTPError:
            pass
        after = (self.data_dir / "archive" / "issues" / "PT-9.md").read_bytes()
        self.assertEqual(before, after)

    def test_post_to_a_live_issue_is_unaffected_regression_guard(self):
        # Regression guard -- the existing, unrelated behaviour for a live
        # issue must be completely unaffected by this new archived check.
        resp = http_get(f"{self.base_url}/api/issue/PT-1")
        current = json.loads(resp.read())
        result = http_post(
            f"{self.base_url}/api/issue/PT-1",
            {"seen": current["seen"], "patch": {"status": "todo"}},
        )
        self.assertEqual(result.status, 200)


class SingleIssueEndpointArchivedFlagTests(ServerTestCase):
    """GET /api/issue/<id> (the drawer's fetch): implementation-lead's plan
    -- build_issue_payload gains `archived`, and the existing single
    `read_only` flag (§5: "do not invent a second read-only flag") widens
    to `(not owning_root.primary) or payload["archived"]`, reusing the
    exact suppression path the drawer's inline editors already honor."""

    def test_archived_issue_payload_carries_archived_true(self):
        resp = http_get(f"{self.base_url}/api/issue/PT-9")
        payload = json.loads(resp.read())
        self.assertIs(payload["archived"], True)

    def test_archived_issue_payload_is_read_only(self):
        resp = http_get(f"{self.base_url}/api/issue/PT-9")
        payload = json.loads(resp.read())
        self.assertIs(payload["read_only"], True)

    def test_live_issue_payload_carries_archived_false(self):
        resp = http_get(f"{self.base_url}/api/issue/PT-1")
        payload = json.loads(resp.read())
        self.assertIs(payload["archived"], False)

    def test_live_issue_on_the_primary_root_is_not_read_only_regression_guard(self):
        resp = http_get(f"{self.base_url}/api/issue/PT-1")
        payload = json.loads(resp.read())
        self.assertIs(payload["read_only"], False)


class CliStillAllowedOnArchivedIssuesTests(unittest.TestCase):
    """§5: the CLI is DELIBERATELY still allowed to write an archived
    issue -- only the HTTP path is restricted. find_issue_path itself must
    stay completely unchanged (same PT-3/PT-39 precedent)."""

    def test_find_issue_path_still_resolves_an_archived_issue(self):
        # PT-50: shared fixture's PT-9 now lives at archive/issues/, not
        # the legacy flat archive/.
        data_dir = helpers.make_tmp_data_dir(self)
        self.assertEqual(
            cairn.find_issue_path(data_dir, "PT-9"), data_dir / "archive" / "issues" / "PT-9.md"
        )

    def test_cairn_set_cli_can_still_write_an_archived_issue(self):
        import subprocess
        data_dir = helpers.make_tmp_data_dir(self)
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "set", "PT-9", "status=cancelled", "--data-dir", str(data_dir)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "archive" / "issues" / "PT-9.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
