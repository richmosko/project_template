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

    def test_milestone_and_major_carry_the_fields_the_board_header_needs(self):
        # The header renders "1.0 · GA · v1.0.0 · 7/12 done" and a major
        # selector -- the API has to expose kind/ga/target_tag/status and
        # major status/health for that, not just ids. Nothing previously
        # pinned these fields were actually in the payload (vs. just id).
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())

        milestone_10 = next(m for m in payload["milestones"] if m["id"] == "1.0")
        self.assertEqual(milestone_10["kind"], "product")
        self.assertTrue(milestone_10["ga"])
        self.assertEqual(milestone_10["target_tag"], "v1.0.0")

        milestone_m0 = next(m for m in payload["milestones"] if m["id"] == "M0")
        self.assertEqual(milestone_m0["kind"], "process")
        self.assertFalse(milestone_m0["ga"])

        major_v1 = next(m for m in payload["majors"] if m["id"] == "V1")
        self.assertEqual(major_v1["status"], "active")
        self.assertEqual(major_v1["health"], "on-track")

    def test_sub_issue_count_supports_the_2_of_3_badge(self):
        # PT-1 has one sub-issue (PT-3, parent: PT-1) in the fixture. The
        # board's parent-card badge needs this count from somewhere; if the
        # API doesn't expose it, board.js would have to compute it itself
        # from the full issues list, which is a design point worth pinning
        # down with a test either way.
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        pt1 = next(i for i in payload["issues"] if i["id"] == "PT-1")
        pt3 = next(i for i in payload["issues"] if i["id"] == "PT-3")
        pt4 = next(i for i in payload["issues"] if i["id"] == "PT-4")
        self.assertEqual(pt1.get("sub_issue_count", 0), 1)
        self.assertEqual(pt3.get("sub_issue_count", 0), 0)
        self.assertEqual(pt4.get("sub_issue_count", 0), 0)

    def test_etag_changes_after_a_mutation(self):
        # test_etag_supports_304 only proves the SAME etag round-trips to a
        # 304. It doesn't prove a STALE etag is correctly rejected -- a
        # server that hard-coded one fixed ETag forever would also pass
        # that test. Mutate a file on disk, then replay the old etag.
        resp = http_get(f"{self.base_url}/api/board")
        old_etag = resp.headers.get("ETag")
        resp.close()

        cairn.apply_patch(self.data_dir / "issues" / "PT-1.md", {"status": "in-review"})

        resp2 = http_get(f"{self.base_url}/api/board", headers={"If-None-Match": old_etag})
        self.assertEqual(resp2.status, 200, "stale ETag must not be honored as a 304 after a mutation")
        new_etag = resp2.headers.get("ETag")
        self.assertNotEqual(old_etag, new_etag)


class IssueEndpointTests(ServerTestCase):
    def test_get_issue_includes_full_comments_and_seen(self):
        # Comment count bumped 2 -> 3 (2026-08-19): PT-1.md's fenced fake
        # delimiter now correctly splits as its own comment per architect
        # conformance review finding 4 (fence-tracking removed from
        # split_comments -- see test_issue_parsing.py and INTERFACE.md).
        # RED against current cairn.py, which still fence-tracks and so
        # still returns 2 here.
        resp = http_get(f"{self.base_url}/api/issue/PT-1")
        payload = json.loads(resp.read())
        self.assertEqual(payload["id"], "PT-1")
        self.assertEqual(len(payload["comments"]), 3)
        self.assertEqual(payload["comments"][0]["author"], "qa-engineer")
        self.assertEqual(payload["comments"][1]["author"], "not-a-real-author")
        self.assertEqual(payload["comments"][2]["author"], "architect")
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

    def test_post_creates_issue_with_title_and_milestone(self):
        # Board — phase 1 scope is explicit: "issue creation from the board
        # beyond title + milestone" is out of scope, which implies title +
        # milestone together IS the in-scope case. Not previously exercised
        # -- the existing test only ever sent title alone.
        resp = http_post(f"{self.base_url}/api/issue", {"title": "Scoped to 1.0", "milestone": "1.0"})
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertEqual(payload["milestone"], "1.0")

        new_path = self.data_dir / "issues" / f"{payload['id']}.md"
        frontmatter, _ = cairn.parse_frontmatter(new_path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["milestone"], "1.0")
        # Must round-trip as a string on disk, same numeric-looking-value
        # guarantee as everywhere else.
        raw = new_path.read_text(encoding="utf-8")
        self.assertIn('milestone: "1.0"', raw)


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
        # 3 pre-existing (post finding-4 fix -- see
        # test_get_issue_includes_full_comments_and_seen) + 1 appended here.
        self.assertEqual(len(payload["comments"]), 4)
        self.assertEqual(payload["comments"][-1]["author"], "mosko")
        self.assertEqual(payload["comments"][-1]["body"].strip(), "Ship it behind a flag.")

    def test_comment_only_mutation_with_stale_seen_also_returns_409(self):
        # Spec: "Handles the drag-to-column case ..., inline field edits,
        # and comment append through one code path." test_patch_with_stale_
        # seen only proves the conflict check fires for a `patch` body --
        # it says nothing about a `comment`-only body, which is the other
        # mutation kind sharing that one path. Pin both, not just one.
        seen = self._seen("PT-1")
        path = self.data_dir / "issues" / "PT-1.md"
        cairn.apply_patch(path, {"status": "done"})
        mutated_raw = path.read_bytes()

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            http_post(
                f"{self.base_url}/api/issue/PT-1",
                {"seen": seen, "comment": {"author": "mosko", "body": "Should be rejected."}},
            )
        self.assertEqual(ctx.exception.code, 409)
        error_payload = json.loads(ctx.exception.read())
        self.assertEqual(error_payload["error"], "stale")

        # The comment must not have been appended.
        self.assertEqual(path.read_bytes(), mutated_raw)


class RequireSeenTests(ServerTestCase):
    """PT-6: `seen` becomes a required key on the POST /api/issue/<id>
    path, not just a required *value*. Before this, an absent key and an
    explicit `null` were indistinguishable server-side -- both read back as
    None via `payload.get("seen")` -- so a client that simply forgot to
    send the token silently bypassed the staleness check (the lost-update
    window). An explicit `null` remains a deliberate override.

    These tests build the raw payload dict by hand and assert on Python
    `in` / `is None` against the *dict*, not the JSON string, so the
    absent-key vs. present-with-null distinction is pinned before it ever
    reaches the wire.
    """

    def _seen(self, issue_id: str) -> str:
        resp = http_get(f"{self.base_url}/api/issue/{issue_id}")
        return json.loads(resp.read())["seen"]

    def test_missing_seen_key_is_400_and_names_the_missing_key(self):
        path = self.data_dir / "issues" / "PT-1.md"
        raw_before = path.read_bytes()

        payload = {"patch": {"status": "in-review"}}  # no "seen" key at all
        self.assertNotIn("seen", payload)

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            http_post(f"{self.base_url}/api/issue/PT-1", payload)
        self.assertEqual(ctx.exception.code, 400)
        error_payload = json.loads(ctx.exception.read())
        self.assertEqual(error_payload.get("error"), "bad_request")
        self.assertIn("seen", error_payload.get("message", ""))

        self.assertEqual(path.read_bytes(), raw_before, "write must not be applied when seen is absent")

    def test_missing_seen_key_rejects_comment_only_mutation_too(self):
        # Same "seen required" check has to fire on the comment-only body,
        # not just the patch body -- mirrors test_comment_only_mutation_
        # with_stale_seen_also_returns_409 above, which pins the same
        # split for the stale case.
        path = self.data_dir / "issues" / "PT-1.md"
        raw_before = path.read_bytes()

        payload = {"comment": {"author": "mosko", "body": "Should be rejected."}}
        self.assertNotIn("seen", payload)

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            http_post(f"{self.base_url}/api/issue/PT-1", payload)
        self.assertEqual(ctx.exception.code, 400)

        self.assertEqual(path.read_bytes(), raw_before, "comment must not be appended when seen is absent")

    def test_explicit_null_seen_bypasses_staleness_check(self):
        # Simulate a concurrent write landing after this browser tab loaded
        # PT-1, then override with an explicit null -- the deliberate "I
        # know it's stale, write anyway" escape hatch. Must NOT 409.
        self._seen("PT-1")  # loads the (soon-to-be-stale) token; unused on purpose
        path = self.data_dir / "issues" / "PT-1.md"
        cairn.apply_patch(path, {"status": "done"})

        payload = {"seen": None, "patch": {"status": "in-review"}}
        self.assertIn("seen", payload)
        self.assertIsNone(payload["seen"])

        resp = http_post(f"{self.base_url}/api/issue/PT-1", payload)
        self.assertEqual(resp.status, 200)
        result = json.loads(resp.read())
        self.assertEqual(result["status"], "in-review")

    def test_seen_present_and_matching_proceeds(self):
        # Regression guard -- unchanged behavior, restated under the PT-6
        # suite so the four-way absent/null/match/stale matrix lives
        # together in one place.
        seen = self._seen("PT-1")
        resp = http_post(f"{self.base_url}/api/issue/PT-1", {"seen": seen, "patch": {"status": "in-review"}})
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(resp.read())["status"], "in-review")

    def test_seen_present_and_stale_returns_409_and_no_write(self):
        # Regression guard -- unchanged behavior, restated under the PT-6
        # suite for the same reason as test_seen_present_and_matching_
        # proceeds above.
        seen = self._seen("PT-1")
        path = self.data_dir / "issues" / "PT-1.md"
        cairn.apply_patch(path, {"status": "done"})
        mutated_raw = path.read_bytes()

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            http_post(f"{self.base_url}/api/issue/PT-1", {"seen": seen, "patch": {"status": "in-review"}})
        self.assertEqual(ctx.exception.code, 409)
        error_payload = json.loads(ctx.exception.read())
        self.assertEqual(error_payload["error"], "stale")

        self.assertEqual(path.read_bytes(), mutated_raw)


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
