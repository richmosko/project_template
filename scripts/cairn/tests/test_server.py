"""Tests for the cairn board server: cairn.make_server + the /api/* routes.

The server is run in-process on an ephemeral port (port=0) in a daemon
thread, rather than shelled out to as a subprocess -- this avoids a whole
class of "did the child process finish binding yet" flakiness and lets
each test read `server.server_address[1]` directly for the real port.
"""
from __future__ import annotations

import datetime
import json
import threading
import time
import unittest
import urllib.error
import urllib.request

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
    """Shared setUp/tearDown: fresh fixture copy, server bound to an
    ephemeral port, served in a background thread."""

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


class BoardEndpointTests(ServerTestCase):
    def test_board_shape(self):
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        self.assertIn("majors", payload)
        self.assertIn("milestones", payload)
        self.assertIn("issues", payload)

        ids = {issue["id"] for issue in payload["issues"]}
        self.assertEqual(ids, {"PT-1", "PT-3", "PT-4"})  # PT-9 is archived, excluded

    def test_board_issues_have_no_comment_bodies(self):
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        for issue in payload["issues"]:
            self.assertNotIn("comments", issue, "board payload must omit comment bodies")

    def test_board_issue_has_core_fields(self):
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        pt1 = next(i for i in payload["issues"] if i["id"] == "PT-1")
        for field in ("title", "status", "milestone", "assignee", "labels", "priority", "parent", "updated"):
            self.assertIn(field, pt1)
        self.assertEqual(pt1["title"], "Google OAuth login")

    def test_etag_supports_304(self):
        resp = http_get(f"{self.base_url}/api/board")
        etag = resp.headers.get("ETag")
        self.assertTrue(etag)
        resp.close()

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            http_get(f"{self.base_url}/api/board", headers={"If-None-Match": etag})
        self.assertEqual(ctx.exception.code, 304)

    def test_majors_and_milestones_present(self):
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        major_ids = {m["id"] for m in payload["majors"]}
        self.assertIn("V1", major_ids)
        milestone_ids = {m["id"] for m in payload["milestones"]}
        self.assertIn("1.0", milestone_ids)
        self.assertIn("M0", milestone_ids)


class IssueEndpointTests(ServerTestCase):
    def test_get_issue_includes_full_comments_and_seen(self):
        resp = http_get(f"{self.base_url}/api/issue/PT-1")
        payload = json.loads(resp.read())
        self.assertEqual(payload["id"], "PT-1")
        self.assertEqual(len(payload["comments"]), 2)
        self.assertEqual(payload["comments"][0]["author"], "qa-engineer")
        self.assertIn("seen", payload)
        self.assertTrue(str(payload["seen"]).isdigit(), payload["seen"])

    def test_get_unknown_issue_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            http_get(f"{self.base_url}/api/issue/PT-999")
        self.assertEqual(ctx.exception.code, 404)


class CreateIssueTests(ServerTestCase):
    def test_post_creates_issue_with_allocated_id(self):
        resp = http_post(f"{self.base_url}/api/issue", {"title": "Created from the board"})
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertTrue(payload["id"].startswith("PT-"))
        new_path = self.data_dir / "issues" / f"{payload['id']}.md"
        self.assertTrue(new_path.exists())
        frontmatter, _ = cairn.parse_frontmatter(new_path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["title"], "Created from the board")
        self.assertEqual(frontmatter["status"], cairn.DEFAULT_STATUS)


class PatchIssueTests(ServerTestCase):
    def _seen(self, issue_id: str) -> str:
        resp = http_get(f"{self.base_url}/api/issue/{issue_id}")
        return json.loads(resp.read())["seen"]

    def test_patch_happy_path(self):
        seen = self._seen("PT-1")
        resp = http_post(f"{self.base_url}/api/issue/PT-1", {"seen": seen, "patch": {"status": "in-review"}})
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertEqual(payload["status"], "in-review")
        self.assertEqual(payload["updated"], datetime.date.today().isoformat())

        # Persisted, not just echoed.
        resp2 = http_get(f"{self.base_url}/api/issue/PT-1")
        self.assertEqual(json.loads(resp2.read())["status"], "in-review")

    def test_patch_with_stale_seen_returns_409(self):
        seen = self._seen("PT-1")

        # Simulate a concurrent write landing after this browser tab loaded PT-1.
        path = self.data_dir / "issues" / "PT-1.md"
        cairn.apply_patch(path, {"status": "done"})
        mutated_raw = path.read_bytes()

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            http_post(f"{self.base_url}/api/issue/PT-1", {"seen": seen, "patch": {"status": "in-review"}})
        self.assertEqual(ctx.exception.code, 409)
        error_payload = json.loads(ctx.exception.read())
        self.assertEqual(error_payload["error"], "stale")
        self.assertEqual(error_payload["current"]["status"], "done")

        # The conflicting write must not have been applied.
        self.assertEqual(path.read_bytes(), mutated_raw)

    def test_patch_via_comment(self):
        seen = self._seen("PT-1")
        resp = http_post(
            f"{self.base_url}/api/issue/PT-1",
            {"seen": seen, "comment": {"author": "mosko", "body": "Ship it behind a flag."}},
        )
        self.assertEqual(resp.status, 200)

        resp2 = http_get(f"{self.base_url}/api/issue/PT-1")
        payload = json.loads(resp2.read())
        self.assertEqual(len(payload["comments"]), 3)
        self.assertEqual(payload["comments"][-1]["author"], "mosko")
        self.assertEqual(payload["comments"][-1]["body"].strip(), "Ship it behind a flag.")


class StaticRouteTests(ServerTestCase):
    """Smoke tests for the board's static asset routes. These assume
    scripts/cairn/board/{board.html,board.js,board.css} exist per the
    spec's file layout -- also part of this stage's deliverable."""

    def test_kanban_root_serves_html(self):
        resp = http_get(f"{self.base_url}/")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))

    def test_list_view_serves_html(self):
        resp = http_get(f"{self.base_url}/list")
        self.assertEqual(resp.status, 200)

    def test_board_js_asset_served(self):
        resp = http_get(f"{self.base_url}/board/board.js")
        self.assertEqual(resp.status, 200)


if __name__ == "__main__":
    unittest.main()
