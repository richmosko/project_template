"""PT-49 failing tests: the running board-server process can serve stale
code after a `cairn.py` upgrade -- `?archived=1` silently doing nothing
(Mosko's 2026-08-24 report) traced back to exactly this: the Python
process itself, not the data files it reads fresh on every request, was
the stale half.

Architect's ruling (process/cairn/issues/PT-49.md, @architect comment)
is authoritative; this file pins its §9 test seam:

  (a) unchanged source -> stale: false
  (b) rewritten source -> stale: true
  (c) mtime touched, bytes identical -> stale: false
  (d) the etag differs between (a) and (b)

plus direct unit coverage of the two new pure functions the seam
requires (`engine_fingerprint`, `engine_is_stale`) and the payload/etag/
static-header plumbing (§4/§5/§7). (e) -- the JS banner -- lives in
tests/js/, not here.

Nothing under test exists yet: `engine_fingerprint`/`engine_is_stale`
don't exist, `make_server` has no `source_path` param, `/api/board`
carries no `engine` key, and `_send_static` sends no Cache-Control at
all. Every red test below is expected to fail until implementation-
lead's PT-49 slice lands.
"""
from __future__ import annotations

import json
import os
import threading
import time
import unittest
import urllib.request
from pathlib import Path

import helpers  # noqa: F401

import cairn


def http_get(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=5)


def write_source(testcase, content: str = "# fixture engine source v1\n") -> Path:
    """A throwaway 'cairn.py' stand-in -- tests must NEVER rewrite the
    real, running scripts/cairn/cairn.py (that would corrupt the actual
    test process's own imported module)."""
    tmp_dir = helpers.make_empty_tmp_dir(testcase)
    source_path = tmp_dir / "fake_engine.py"
    source_path.write_text(content, encoding="utf-8")
    return source_path


class EngineFingerprintTests(unittest.TestCase):
    def test_returns_sha_mtime_ns_and_size(self):
        source_path = write_source(self, "hello\n")
        fp = cairn.engine_fingerprint(source_path)
        self.assertIn("sha", fp)
        self.assertIn("mtime_ns", fp)
        self.assertIn("size", fp)
        self.assertEqual(fp["size"], len(b"hello\n"))

    def test_sha_is_a_12_char_hex_prefix(self):
        source_path = write_source(self, "hello\n")
        fp = cairn.engine_fingerprint(source_path)
        self.assertEqual(len(fp["sha"]), 12)
        int(fp["sha"], 16)  # raises ValueError if not hex

    def test_different_content_yields_a_different_sha(self):
        source_path = write_source(self, "version one\n")
        fp1 = cairn.engine_fingerprint(source_path)
        source_path.write_text("version two\n", encoding="utf-8")
        fp2 = cairn.engine_fingerprint(source_path)
        self.assertNotEqual(fp1["sha"], fp2["sha"])


class EngineIsStaleTests(unittest.TestCase):
    """The §3 two-tier self-check, called directly (not through HTTP)."""

    def test_a_unchanged_source_is_not_stale(self):
        source_path = write_source(self)
        boot = cairn.engine_fingerprint(source_path)
        self.assertFalse(cairn.engine_is_stale(source_path, boot))

    def test_b_rewritten_source_is_stale(self):
        source_path = write_source(self, "v1\n")
        boot = cairn.engine_fingerprint(source_path)
        # A real edit: different bytes AND (on virtually every filesystem)
        # a different mtime -- the ordinary "cairn.py was upgraded" case.
        time.sleep(0.01)
        source_path.write_text("v2, materially different content\n", encoding="utf-8")
        self.assertTrue(cairn.engine_is_stale(source_path, boot))

    def test_c_mtime_touched_bytes_identical_is_not_stale(self):
        # §3's whole reason for the two-tier design: a `git checkout` (or
        # any operation that only touches mtime) must never raise a false
        # alarm -- stat differing is not sufficient, only a differing sha is.
        source_path = write_source(self, "unchanged content\n")
        boot = cairn.engine_fingerprint(source_path)
        future = time.time() + 5
        os.utime(source_path, (future, future))
        st = source_path.stat()
        self.assertNotEqual(st.st_mtime_ns, boot["mtime_ns"], "test sanity: mtime must actually differ")
        self.assertFalse(cairn.engine_is_stale(source_path, boot))

    def test_missing_source_is_not_stale_and_does_not_raise(self):
        # §3: source missing/unreadable -> stale: false (never invent an
        # alarm), not an exception that would 500 the /api/board request.
        tmp_dir = helpers.make_empty_tmp_dir(self)
        missing = tmp_dir / "does_not_exist.py"
        boot = {"sha": "deadbeefcafe", "mtime_ns": 0, "size": 0}
        self.assertFalse(cairn.engine_is_stale(missing, boot))


class BuildMultiBoardPayloadEngineKeyTests(unittest.TestCase):
    def test_engine_param_is_embedded_verbatim_under_the_engine_key(self):
        data_dir = helpers.make_tmp_data_dir(self)
        roots, warnings = cairn.resolve_roots(data_dir, cairn.load_config(data_dir))
        engine_status = {"source_sha": "abc123abc123", "started_at": "2026-08-24T00:00:00", "stale": True}
        payload = cairn.build_multi_board_payload(roots, warnings, engine=engine_status)
        self.assertEqual(payload["engine"], engine_status)


class ComputeMultiEtagEngineFoldTests(unittest.TestCase):
    """§5: the etag must fold the boot sha + current source (mtime_ns,
    size) -- without this a stale flip with no DATA change leaves the
    etag equal, the client 304s, and the banner never appears."""

    def test_d_etag_differs_when_boot_sha_differs_same_data(self):
        data_dir = helpers.make_tmp_data_dir(self)
        roots, _ = cairn.resolve_roots(data_dir, cairn.load_config(data_dir))
        source_path = write_source(self, "v1\n")
        etag_a = cairn.compute_multi_etag(roots, boot_sha="sha_boot_a", source_path=source_path)
        etag_b = cairn.compute_multi_etag(roots, boot_sha="sha_boot_b", source_path=source_path)
        self.assertNotEqual(etag_a, etag_b, "a different boot sha must change the etag with no data change at all")

    def test_etag_differs_when_current_source_stat_differs_same_boot_sha(self):
        data_dir = helpers.make_tmp_data_dir(self)
        roots, _ = cairn.resolve_roots(data_dir, cairn.load_config(data_dir))
        source_path = write_source(self, "v1\n")
        etag_before = cairn.compute_multi_etag(roots, boot_sha="sha_boot", source_path=source_path)
        time.sleep(0.01)
        source_path.write_text("v2, a real edit\n", encoding="utf-8")
        etag_after = cairn.compute_multi_etag(roots, boot_sha="sha_boot", source_path=source_path)
        self.assertNotEqual(etag_before, etag_after)


class ServerEngineStatusTests(unittest.TestCase):
    """§9 (a)-(d), exercised end to end through a real make_server/HTTP
    round trip -- the actual shape a client sees."""

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        self.source_path = write_source(self, "v1, boot content\n")
        self.server = cairn.make_server(self.data_dir, port=0, source_path=self.source_path)
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

    def _board(self):
        resp = http_get(f"{self.base_url}/api/board")
        return json.loads(resp.read()), resp

    def test_a_unchanged_source_reports_stale_false(self):
        payload, _ = self._board()
        self.assertIn("engine", payload)
        self.assertIn("source_sha", payload["engine"])
        self.assertIn("started_at", payload["engine"])
        self.assertEqual(payload["engine"]["stale"], False)

    def test_b_rewritten_source_reports_stale_true(self):
        time.sleep(0.01)
        self.source_path.write_text("v2, a real post-boot edit\n", encoding="utf-8")
        payload, _ = self._board()
        self.assertEqual(payload["engine"]["stale"], True)

    def test_c_mtime_touched_bytes_identical_reports_stale_false(self):
        future = time.time() + 5
        os.utime(self.source_path, (future, future))
        payload, _ = self._board()
        self.assertEqual(payload["engine"]["stale"], False)

    def test_d_etag_differs_before_and_after_a_stale_flip(self):
        _, resp_a = self._board()
        etag_a = resp_a.headers.get("ETag")
        self.assertTrue(etag_a)

        time.sleep(0.01)
        self.source_path.write_text("v2, a real post-boot edit\n", encoding="utf-8")
        _, resp_b = self._board()
        etag_b = resp_b.headers.get("ETag")
        self.assertTrue(etag_b)
        self.assertNotEqual(etag_a, etag_b, "the stale flip must not be invisible to a client relying on ETag/304")

    def test_engine_key_is_always_present_single_root_included(self):
        # PT-3/PT-42's own "no conditional payload shape" precedent --
        # this key is per-process, present regardless of root count.
        payload, _ = self._board()
        self.assertIn("engine", payload)

    def test_static_assets_are_sent_with_cache_control_no_store(self):
        # §7: closes the browser-cache half cheaply -- with no-store, a
        # stale board.js/board.css is not a reachable state at all.
        resp = http_get(f"{self.base_url}/board/board.js")
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")


if __name__ == "__main__":
    unittest.main()
