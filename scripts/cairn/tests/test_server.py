"""Tests for the cairn board server: cairn.make_server + the /api/* routes.

The server is run in-process on an ephemeral port (port=0) in a daemon
thread, rather than shelled out to as a subprocess -- this avoids a whole
class of "did the child process finish binding yet" flakiness and lets
each test read `server.server_address[1]` directly for the real port.
"""
from __future__ import annotations

import datetime
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


def _sse_connect(port: int, path: str = "/api/events", timeout: float = 5.0) -> socket.socket:
    """Open a raw GET to `path` and return the connected socket, read
    timeout already set.

    SSE keeps the connection open indefinitely -- urllib's high-level API
    isn't built for incrementally reading an open-ended stream with a hard
    per-read timeout, so these tests talk HTTP/1.0 directly over a socket
    instead. `Connection: close` in the request is just our preference;
    the server holding the response open past that is exactly the
    behavior under test.
    """
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    sock.settimeout(timeout)
    request = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    sock.sendall(request.encode("ascii"))
    return sock


def _sse_read_headers(sock: socket.socket) -> tuple:
    """Read off `sock` up through the blank line ending the HTTP headers.
    Returns (status_line, headers dict, leftover body bytes already read).
    """
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("utf-8", errors="replace").split("\r\n")
    status_line = lines[0] if lines else ""
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return status_line, headers, rest


def _sse_read_one_frame(sock: socket.socket, leftover: bytes, timeout: float):
    """Read until one SSE frame (terminated by a blank line) has arrived,
    or `timeout` elapses -- returns the frame text, or None on timeout.
    Never blocks past `timeout` regardless of what the server does, so a
    broken/hanging implementation can't hang the suite."""
    sock.settimeout(timeout)
    buf = leftover
    deadline = time.time() + timeout
    while b"\n\n" not in buf:
        remaining = deadline - time.time()
        if remaining <= 0:
            return None
        sock.settimeout(remaining)
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            return None
        if not chunk:
            return None
        buf += chunk
    frame, _, _ = buf.partition(b"\n\n")
    return frame.decode("utf-8", errors="replace")


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

    def test_milestone_payload_carries_name_for_id_dot_name_rendering(self):
        # PT-16: swimlane headers and both milestone <select> dropdowns
        # render "id · name" (already true of the progress strip). board.js
        # is purely a lens over this payload -- pin the field it depends on
        # so a future frontmatter/payload refactor can't silently drop
        # `name` out from under the UI without a server-side test noticing.
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        milestone_10 = next(m for m in payload["milestones"] if m["id"] == "1.0")
        self.assertEqual(milestone_10["name"], "MVP")

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


class PT10IssuePathFieldTests(ServerTestCase):
    """PT-10: GET /api/issue/<id> must carry the file's real repo-relative
    path -- board.js:495 currently hardcodes "process/cairn/issues/" +
    id + ".md" in the drawer, which is wrong for any archived issue. Pinned
    at the subdirectory+filename suffix level, not the exact root prefix:
    the real repo runs with --data-dir process/cairn, but this suite's
    fixture copies live under a temp dir with no "process/" segment
    (helpers.copy_fixture_data_dir names the copy just "cairn") -- any
    implementation that's correct in production will still produce a
    string ending in ".../issues/PT-1.md" or ".../archive/PT-9.md" here.
    PT-9 is the fixture's pre-archived issue (tests/fixtures/process/cairn/
    archive/PT-9.md).
    """

    def test_active_issue_path_names_the_issues_subdir(self):
        resp = http_get(f"{self.base_url}/api/issue/PT-1")
        payload = json.loads(resp.read())
        self.assertIn("path", payload)
        self.assertTrue(
            payload["path"].replace("\\", "/").endswith("issues/PT-1.md"),
            payload["path"],
        )

    def test_archived_issue_path_names_the_archive_subdir(self):
        resp = http_get(f"{self.base_url}/api/issue/PT-9")
        payload = json.loads(resp.read())
        self.assertIn("path", payload)
        self.assertTrue(
            payload["path"].replace("\\", "/").endswith("archive/PT-9.md"),
            payload["path"],
        )

    def test_path_resolves_to_the_actual_file_on_disk(self):
        # The strongest, implementation-agnostic invariant: however the
        # server chooses to root the string (repo-relative, data-dir-
        # relative, or absolute), it must point at the real file, not just
        # be a plausible-looking tag.
        resp = http_get(f"{self.base_url}/api/issue/PT-1")
        payload = json.loads(resp.read())
        self.assertIn("path", payload)
        served = Path(payload["path"])
        candidate = served
        if not candidate.is_absolute():
            for root in (Path.cwd(), self.data_dir.parent, self.data_dir):
                if (root / candidate).exists():
                    candidate = root / candidate
                    break
        self.assertTrue(Path(candidate).exists(), f"served path {payload['path']!r} does not resolve to a real file")
        self.assertEqual(Path(candidate).resolve(), (self.data_dir / "issues" / "PT-1.md").resolve())

    def test_board_payload_path_is_correct_when_present(self):
        # AC's "(if cheap)" clause on the board payload is optional scope
        # -- build_board_payload already holds the Path object for each
        # issue in hand, so it's cheap, but not required. If the field
        # shows up there too, it must be correct; if it's absent, that's
        # a legitimate implementation choice this test doesn't force.
        #
        # implementation-lead (PT-10): the skip guard that used to live
        # here ("if 'path' not in pt1: self.skipTest(...)") is removed --
        # build_board_payload now carries "path" (see cairn.py), so this
        # assertion runs live. Sanctioned edit, confined to removing the
        # guard only, per team-lead's instruction; flagged for QA audit.
        resp = http_get(f"{self.base_url}/api/board")
        payload = json.loads(resp.read())
        pt1 = next(i for i in payload["issues"] if i["id"] == "PT-1")
        self.assertTrue(pt1["path"].replace("\\", "/").endswith("issues/PT-1.md"), pt1["path"])


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

    def test_patch_response_round_trips_the_new_title(self):
        # PT-11 prerequisite (regression guard, already true today): the
        # drawer's h2 fix reads the new title straight off the POST
        # response (result.data), never re-fetching -- confirm the server
        # side of that contract is already correct before treating h2
        # staleness as a client-only bug. Green today; would need to move
        # here first if it weren't.
        seen = self._seen("PT-1")
        resp = http_post(
            f"{self.base_url}/api/issue/PT-1",
            {"seen": seen, "patch": {"title": "Renamed via drawer"}},
        )
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertEqual(payload["title"], "Renamed via drawer")

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


class MarkdownVendorAssetTests(ServerTestCase):
    """PT-4: marked + DOMPurify are vendored (not CDN-fetched) under
    scripts/cairn/board/vendor/ and must be servable at runtime with zero
    server-side change -- _send_static already serves any file under
    BOARD_DIR generically, with .js already mapped to
    "application/javascript" in its content-type table. If these fail, the
    files either aren't vendored yet or the path/filename implementation
    picked doesn't match what got documented back to QA.
    """

    def test_marked_vendor_asset_served(self):
        resp = http_get(f"{self.base_url}/board/vendor/marked.js")
        self.assertEqual(resp.status, 200)
        self.assertIn("javascript", resp.headers.get("Content-Type", ""))

    def test_dompurify_vendor_asset_served(self):
        resp = http_get(f"{self.base_url}/board/vendor/purify.min.js")
        self.assertEqual(resp.status, 200)
        self.assertIn("javascript", resp.headers.get("Content-Type", ""))


class MarkdownVendorAssetHygieneTests(unittest.TestCase):
    """PT-4: "no CDN, no network fetch" must hold at runtime, not just at
    vendor-time -- even a devtools-only sourcemap fetch attempt (Chrome
    auto-requests a `//# sourceMappingURL` target when devtools is open)
    would violate that. Reads the checked-in files directly off disk, not
    through the HTTP server -- this is a repo-hygiene guard, independent of
    the static route working at all.
    """

    def test_vendored_assets_carry_no_sourcemap_reference(self):
        vendor_dir = helpers.CAIRN_DIR / "board" / "vendor"
        for name in ("marked.js", "purify.min.js"):
            path = vendor_dir / name
            self.assertTrue(path.is_file(), f"missing vendored asset: {path}")
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn(
                "sourceMappingURL", text, f"{name} still carries a sourcemap reference"
            )


class SSEEventsTests(ServerTestCase):
    """PT-1: GET /api/events is an SSE stream (text/event-stream) that
    emits a frame after any data-dir mutation, driven by the periodic
    fs-scan watcher (AC's documented cadence: <=2s). HTTP-level, using
    ServerTestCase's existing make_server(...) + serve_forever-in-a-thread
    setup exactly like every other test in this file -- QA is assuming the
    watcher is live as soon as the server object exists (same lifecycle as
    the HTTP serving loop itself), not gated behind a second explicit
    start call `cmd_serve` alone would make. If implementation instead
    ties watcher-start to `cmd_serve` only, these tests will time out
    rather than erroring cleanly -- flagged in the hand-off report as a
    design fork QA guessed at, not a contract handed down.

    Every read here has a hard timeout (via _sse_read_one_frame's
    deadline), and every socket is closed via addCleanup -- a broken or
    hanging implementation fails/times out this test, it cannot hang the
    suite.
    """

    def test_content_type_is_event_stream(self):
        sock = _sse_connect(self.port, timeout=5)
        self.addCleanup(sock.close)
        status_line, headers, _ = _sse_read_headers(sock)
        self.assertIn("200", status_line)
        self.assertIn("text/event-stream", headers.get("content-type", ""))

    def test_event_arrives_after_a_mutation(self):
        sock = _sse_connect(self.port, timeout=5)
        self.addCleanup(sock.close)
        _status_line, headers, leftover = _sse_read_headers(sock)
        self.assertIn("text/event-stream", headers.get("content-type", ""))

        # Mutate a tracked file after connecting -- the watcher's next
        # scan should notice and push a frame within the documented <=2s
        # cadence. Generous 5s budget to absorb scheduling jitter without
        # ever hanging the suite.
        cairn.apply_patch(self.data_dir / "issues" / "PT-1.md", {"status": "in-review"})

        frame = _sse_read_one_frame(sock, leftover, timeout=5.0)
        self.assertIsNotNone(frame, "no SSE frame arrived within 5s of a mutation")
        self.assertTrue(frame.startswith("data:"), frame)

    def test_no_event_when_nothing_changes(self):
        # Quiet case, HTTP-level companion to test_watcher.py's pure-diff
        # unit tests. Also catches a specific real bug shape: a watcher
        # that diffs its first scan against an empty baseline would treat
        # every pre-existing fixture file as newly "created" and fire
        # immediately on connect with zero mutations -- this test fails
        # loudly if that happens instead of timing out clean.
        sock = _sse_connect(self.port, timeout=3)
        self.addCleanup(sock.close)
        _status_line, headers, leftover = _sse_read_headers(sock)
        self.assertIn("text/event-stream", headers.get("content-type", ""))

        frame = _sse_read_one_frame(sock, leftover, timeout=2.5)
        self.assertIsNone(frame, f"got an unexpected frame with no mutation: {frame!r}")

    def test_two_concurrent_clients_both_receive_the_event(self):
        # AC #2: "concurrent SSE clients ... must not block each other."
        sock_a = _sse_connect(self.port, timeout=5)
        self.addCleanup(sock_a.close)
        sock_b = _sse_connect(self.port, timeout=5)
        self.addCleanup(sock_b.close)
        _sl_a, headers_a, leftover_a = _sse_read_headers(sock_a)
        _sl_b, headers_b, leftover_b = _sse_read_headers(sock_b)
        self.assertIn("text/event-stream", headers_a.get("content-type", ""))
        self.assertIn("text/event-stream", headers_b.get("content-type", ""))

        cairn.apply_patch(self.data_dir / "issues" / "PT-1.md", {"status": "in-review"})

        frame_a = _sse_read_one_frame(sock_a, leftover_a, timeout=5.0)
        frame_b = _sse_read_one_frame(sock_b, leftover_b, timeout=5.0)
        self.assertIsNotNone(frame_a, "client A never received the event")
        self.assertIsNotNone(frame_b, "client B never received the event")

    def test_normal_api_requests_are_not_blocked_while_sse_is_open(self):
        # AC #2's other half: "normal API requests must not block" while
        # an SSE connection sits open. The current `Server` class is a
        # plain http.server.HTTPServer (no ThreadingMixIn) -- serving a
        # long-lived SSE GET on a single-threaded accept loop would starve
        # every other connection until the SSE client disconnects. This
        # test is the direct proof; if it hangs/fails, the fix likely
        # needs Server to inherit socketserver.ThreadingMixIn (or become
        # an http.server.ThreadingHTTPServer), not just a watcher thread.
        sse_sock = _sse_connect(self.port, timeout=5)
        self.addCleanup(sse_sock.close)
        _sse_read_headers(sse_sock)  # connected, held open, deliberately not closed

        start = time.time()
        resp = http_get(f"{self.base_url}/api/board")
        elapsed = time.time() - start
        self.assertEqual(resp.status, 200)
        self.assertLess(elapsed, 2.0, "a normal API request was blocked by an open SSE connection")


if __name__ == "__main__":
    unittest.main()
