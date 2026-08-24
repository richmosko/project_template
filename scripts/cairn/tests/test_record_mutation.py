"""PT-51 failing tests: milestone/major cards editable + comments -- lifts
the 0.7.0 read-only ruling. Built directly against architect's ruling
comment in process/cairn/issues/PT-51.md, §1-§7, which is authoritative
here (endpoint name/shape, the six-step check order, field policy,
comment schema).

Nothing under test exists yet: there is no `POST /api/record/<id>` route
at all, `build_board_payload`'s milestone/major records carry neither
`seen` nor `comments`, and `cmd_comment` only resolves issues. Every red
test below is expected to fail until implementation-lead's PT-51 slice
lands.
"""
from __future__ import annotations

import json
import subprocess
import sys
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


def http_post_raw(url: str, body_text: str):
    req = urllib.request.Request(
        url, data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"
    )
    return urllib.request.urlopen(req, timeout=5)


def http_post(url: str, payload: dict):
    return http_post_raw(url, json.dumps(payload))


# --------------------------------------------------------------------------
# Server (§1, §7)
# --------------------------------------------------------------------------

class RecordServerTestCase(unittest.TestCase):
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

    def _seen_for(self, kind: str, record_id: str) -> str:
        resp = http_get(f"{self.base_url}/api/board")
        board = json.loads(resp.read())
        collection = board["milestones"] if kind == "milestone" else board["majors"]
        return next(r for r in collection if r["id"] == record_id)["seen"]

    def _expect_http_error(self, req: urllib.request.Request) -> urllib.error.HTTPError:
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            return exc
        self.fail("expected an HTTPError but the request succeeded")


class RecordMutation200Tests(RecordServerTestCase):
    def test_200_patch_updates_a_milestone_field_and_returns_a_fresh_seen(self):
        seen = self._seen_for("milestone", "PT-1.0")
        resp = http_post(f"{self.base_url}/api/record/PT-1.0", {"seen": seen, "patch": {"target_tag": "v1.2.0"}})
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read())
        self.assertEqual(data["target_tag"], "v1.2.0")
        self.assertNotEqual(data["seen"], seen)

    def test_200_patch_updates_a_major_field(self):
        seen = self._seen_for("major", "PT-V1")
        resp = http_post(f"{self.base_url}/api/record/PT-V1", {"seen": seen, "patch": {"health": "at-risk"}})
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read())
        self.assertEqual(data["health"], "at-risk")

    def test_200_response_shape_matches_the_boards_own_record_shape(self):
        # §2's own promise: the POST response is "the fresh record
        # payload, same shape as the 409's `current`" -- pin the fields a
        # drawer re-render actually needs (§1's own wording).
        seen = self._seen_for("milestone", "PT-1.0")
        resp = http_post(f"{self.base_url}/api/record/PT-1.0", {"seen": seen, "patch": {"status": "paused"}})
        data = json.loads(resp.read())
        for field in ("id", "name", "status", "major", "target_tag", "ga", "body", "comments", "seen", "path", "archived"):
            self.assertIn(field, data, f"missing {field!r} in the record payload")


class RecordMutation409Tests(RecordServerTestCase):
    def test_409_on_stale_seen_carries_a_record_payload_as_current(self):
        cairn.apply_patch(self.data_dir / "milestones" / "PT-1.0.md", {"status": "done"})
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-1.0",
            data=json.dumps({"seen": "definitely-not-the-real-token", "patch": {"status": "paused"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 409)
        body = json.loads(exc.read())
        self.assertEqual(body["error"], "stale")
        self.assertEqual(body["current"]["id"], "PT-1.0")
        self.assertEqual(body["current"]["status"], "done")


class RecordMutationArchived403Tests(unittest.TestCase):
    """§1 step 3: archived is checked BEFORE the seen comparison -- must
    hold regardless of the request body."""

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        (self.data_dir / "archive" / "milestones").mkdir(parents=True)
        self.archived_path = self.data_dir / "archive" / "milestones" / "PT-Z.md"
        self.archived_path.write_text(
            "---\nid: PT-Z\nname: Archived one\nkind: product\nmajor: PT-V1\nstatus: done\n"
            "target_tag: v9.0.0\nga: false\n---\n\nDoD.\n",
            encoding="utf-8",
        )
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

    def test_archived_is_403_even_with_a_garbage_body_that_would_otherwise_400(self):
        before = self.archived_path.read_bytes()
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-Z",
            data=json.dumps({"this_is": "not seen/patch/comment shaped at all"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("expected HTTPError 403")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 403)
            body = json.loads(exc.read())
            self.assertEqual(body["error"], "archived")
        after = self.archived_path.read_bytes()
        self.assertEqual(before, after, "an archived record must be provably untouched")


class RecordMutation400Tests(RecordServerTestCase):
    def test_an_issue_id_is_refused_with_wrong_endpoint(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-1",
            data=json.dumps({"seen": None, "patch": {"status": "done"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 400)
        body = json.loads(exc.read())
        self.assertEqual(body["error"], "wrong_endpoint")
        self.assertIn("/api/issue/PT-1", body["message"])

    def test_id_field_in_patch_is_rejected(self):
        seen = self._seen_for("milestone", "PT-1.0")
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-1.0",
            data=json.dumps({"seen": seen, "patch": {"id": "PT-9.9"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 400)

    def test_kind_field_in_patch_is_rejected(self):
        seen = self._seen_for("milestone", "PT-1.0")
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-1.0",
            data=json.dumps({"seen": seen, "patch": {"kind": "process"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 400)

    def test_a_bad_status_value_is_rejected(self):
        seen = self._seen_for("milestone", "PT-1.0")
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-1.0",
            data=json.dumps({"seen": seen, "patch": {"status": "not-a-real-status"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 400)

    def test_a_bad_health_value_is_rejected(self):
        seen = self._seen_for("major", "PT-V1")
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-V1",
            data=json.dumps({"seen": seen, "patch": {"health": "on-fire"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 400)

    def test_a_non_bool_ga_value_is_rejected(self):
        seen = self._seen_for("milestone", "PT-1.0")
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-1.0",
            data=json.dumps({"seen": seen, "patch": {"ga": "true"}}).encode("utf-8"),  # a STRING, not a JSON bool
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 400)

    def test_an_unknown_field_is_rejected(self):
        seen = self._seen_for("major", "PT-V1")
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-V1",
            data=json.dumps({"seen": seen, "patch": {"not_a_real_field": "x"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 400)

    def test_missing_seen_is_400(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-1.0",
            data=json.dumps({"patch": {"status": "paused"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 400)

    def test_unknown_record_id_is_404(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/record/PT-999.9",
            data=json.dumps({"seen": None, "patch": {"status": "paused"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        exc = self._expect_http_error(req)
        self.assertEqual(exc.code, 404)


class RecordMutationCommentTests(RecordServerTestCase):
    def test_comment_via_the_record_endpoint_is_appended_and_returned(self):
        seen = self._seen_for("milestone", "PT-1.0")
        resp = http_post(
            f"{self.base_url}/api/record/PT-1.0",
            {"seen": seen, "comment": {"author": "board", "body": "Board comment."}},
        )
        data = json.loads(resp.read())
        self.assertEqual(len(data["comments"]), 1)
        self.assertEqual(data["comments"][0]["body"].strip(), "Board comment.")
        self.assertEqual(data["comments"][0]["author"], "board")

    def test_a_record_comment_injects_no_updated_key(self):
        seen = self._seen_for("major", "PT-V1")
        http_post(f"{self.base_url}/api/record/PT-V1", {"seen": seen, "comment": {"author": "board", "body": "Hi."}})
        frontmatter, _ = cairn.parse_frontmatter((self.data_dir / "majors" / "PT-V1.md").read_text(encoding="utf-8"))
        self.assertNotIn("updated", frontmatter)


class RecordMutationReadOnlyRootTests(unittest.TestCase):
    """§1 step 1's 403/404 discrimination, record-endpoint half of PT-3's
    read-only guarantee -- mirrors MultiRootReadOnlyTests in
    test_multi_root.py, one root over."""

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.primary_dir = self._make_repo("repo_a", "AA")
        self.secondary_dir = self._make_repo("repo_b", "BB")
        (self.secondary_dir / "milestones" / "BB-1.0.md").write_text(
            "---\nid: BB-1.0\nname: Their milestone\nkind: product\nmajor: BB-V1\nstatus: planned\n"
            "target_tag: null\nga: false\n---\n\nDoD.\n",
            encoding="utf-8",
        )
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

    def _make_repo(self, dirname: str, prefix: str) -> Path:
        data_dir = self.tmp / dirname / "process" / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text(f"prefix: {prefix}\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        return data_dir

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

    def test_mutating_a_secondary_root_milestone_is_rejected_with_403_and_the_file_is_untouched(self):
        before = (self.secondary_dir / "milestones" / "BB-1.0.md").read_bytes()
        req = urllib.request.Request(
            f"{self.base_url}/api/record/BB-1.0",
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
            self.assertEqual(body["error"], "read_only_root")
        after = (self.secondary_dir / "milestones" / "BB-1.0.md").read_bytes()
        self.assertEqual(before, after)


# --------------------------------------------------------------------------
# Payload shape (§2)
# --------------------------------------------------------------------------

class BoardPayloadRecordCommentsAndSeenTests(unittest.TestCase):
    def test_a_milestone_in_the_board_payload_carries_seen_and_comments(self):
        data_dir = helpers.make_tmp_data_dir(self)
        payload = cairn.build_board_payload(data_dir)
        pt10 = next(m for m in payload["milestones"] if m["id"] == "PT-1.0")
        self.assertIn("seen", pt10)
        self.assertIn("comments", pt10)
        self.assertEqual(pt10["comments"], [])  # PT-1.0.md has no ## Comments section

    def test_a_major_in_the_board_payload_carries_seen_and_comments(self):
        data_dir = helpers.make_tmp_data_dir(self)
        payload = cairn.build_board_payload(data_dir)
        v1 = next(m for m in payload["majors"] if m["id"] == "PT-V1")
        self.assertIn("seen", v1)
        self.assertIn("comments", v1)

    def test_body_is_byte_identical_for_a_record_with_no_comments_section(self):
        # §2's own promise: for every record that exists today (none has
        # a Comments section), the `body` value must be byte-identical to
        # what it was before this change.
        data_dir = helpers.make_tmp_data_dir(self)
        raw = (data_dir / "milestones" / "PT-1.0.md").read_text(encoding="utf-8")
        _, expected_body = cairn.parse_frontmatter(raw)
        payload = cairn.build_board_payload(data_dir)
        pt10 = next(m for m in payload["milestones"] if m["id"] == "PT-1.0")
        self.assertEqual(pt10["body"], expected_body)

    def test_a_record_with_a_comments_section_splits_body_from_comments(self):
        data_dir = helpers.make_tmp_data_dir(self)
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            "---\nid: PT-1.0\nname: MVP\nkind: product\nmajor: PT-V1\nstatus: in-progress\n"
            "target_tag: v1.0.0\nga: true\n---\n\nDoD text.\n\n## Comments\n\n### @mosko — 2026-08-24\n\nA comment.\n",
            encoding="utf-8",
        )
        payload = cairn.build_board_payload(data_dir)
        pt10 = next(m for m in payload["milestones"] if m["id"] == "PT-1.0")
        self.assertEqual(pt10["body"].strip(), "DoD text.")
        self.assertEqual(len(pt10["comments"]), 1)
        self.assertEqual(pt10["comments"][0]["author"], "mosko")

    def test_issues_still_carry_no_comments_key_in_the_board_payload(self):
        # Unchanged (§2's own scoping): only records gain `comments` here.
        data_dir = helpers.make_tmp_data_dir(self)
        payload = cairn.build_board_payload(data_dir)
        for issue in payload["issues"]:
            self.assertNotIn("comments", issue)


class BuildRecordPayloadTests(unittest.TestCase):
    def test_returns_none_for_an_unknown_id(self):
        data_dir = helpers.make_tmp_data_dir(self)
        self.assertIsNone(cairn.build_record_payload(data_dir, "PT-999.9"))

    def test_returns_the_milestone_payload_with_seen_comments_body_path_archived(self):
        data_dir = helpers.make_tmp_data_dir(self)
        payload = cairn.build_record_payload(data_dir, "PT-1.0")
        self.assertEqual(payload["id"], "PT-1.0")
        for field in ("seen", "comments", "body", "path", "archived", "released"):
            self.assertIn(field, payload)

    def test_returns_the_major_payload_with_no_released_key(self):
        # Majors have no target_tag in their schema at all -- `released`
        # must never appear, not even as null (PT-44 §4's own posture,
        # extended here).
        data_dir = helpers.make_tmp_data_dir(self)
        payload = cairn.build_record_payload(data_dir, "PT-V1")
        self.assertEqual(payload["id"], "PT-V1")
        self.assertNotIn("released", payload)


# --------------------------------------------------------------------------
# CLI (§4)
# --------------------------------------------------------------------------

class CmdCommentOnRecordsTests(unittest.TestCase):
    def test_cairn_comment_succeeds_on_a_milestone(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = subprocess.run(
            [sys.executable, str(helpers.CAIRN_PY), "--data-dir", str(data_dir), "comment", "PT-1.0",
             "--author", "mosko", "--body", "A CLI comment."],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        frontmatter, body = cairn.parse_frontmatter((data_dir / "milestones" / "PT-1.0.md").read_text(encoding="utf-8"))
        self.assertNotIn("updated", frontmatter)
        _, comments = cairn.split_comments(body)
        self.assertEqual(comments[-1]["body"].strip(), "A CLI comment.")

    def test_cairn_comment_on_an_unknown_id_says_no_such_record(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = subprocess.run(
            [sys.executable, str(helpers.CAIRN_PY), "--data-dir", str(data_dir), "comment", "PT-999.9",
             "--author", "mosko", "--body", "x"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no such record", result.stderr)

    def test_cairn_comment_still_works_on_an_issue(self):
        # Regression guard -- cmd_comment's resolver widened from
        # find_issue_path to find_record_path, which must still resolve
        # every issue id it always did.
        data_dir = helpers.make_tmp_data_dir(self)
        result = subprocess.run(
            [sys.executable, str(helpers.CAIRN_PY), "--data-dir", str(data_dir), "comment", "PT-1",
             "--author", "mosko", "--body", "Still works."],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class SplitCommentsRecordRoundTripTests(unittest.TestCase):
    def test_split_comments_round_trips_a_record_body(self):
        body = "DoD text.\n\n## Comments\n\n### @mosko — 2026-08-24\n\nFirst.\n\n### @qa — 2026-08-25\n\nSecond.\n"
        pre, comments = cairn.split_comments(body)
        self.assertEqual(pre.strip(), "DoD text.")
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0]["author"], "mosko")
        self.assertEqual(comments[1]["author"], "qa")


if __name__ == "__main__":
    unittest.main()
