"""PT-34 (E1): the concurrent-load harness -- coverage addition, NOT
red-first. This is the AC3 artifact the architect's investigation ruling
calls out as the one thing that survives regardless of how the
investigation resolves (process/cairn/issues/PT-34.md, 284ba36 § 3):

    "Build this regardless of E0's outcome -- a concurrent-load test
    against a threaded server with a long-lived stream open is coverage
    the suite genuinely lacks, and it is the one artifact of this
    investigation that survives if the answer turns out to be 'tooling
    artifact'. That converts a possibly-null investigation into a net
    gain."

E4 (team-lead, b7e7b1d) already confirmed the leading hypothesis (H1): the
Chrome MCP network log renders aborted/no-response fetches as a synthetic
503, and both PT-29/PT-32's sightings trace to that instrument, not to a
real HTTP response. There is no known server defect. These tests are
therefore expected GREEN on first run -- that IS the point: this is the
server-side null-result confirmation and the regression net the suite
lacked (before this commit, nothing exercised N concurrent /api/board
fetches against a live threaded server with an open SSE stream at all).

Threaded-server-in-a-background-thread pattern and the raw-socket SSE
helpers are test_server.py's own (ServerTestCase, _sse_connect,
_sse_read_headers) -- reused here via import rather than duplicated,
since "two independently-maintained copies of the same server-harness
plumbing" is exactly the class of drift this suite's own conventions
(PT-22/PT-23) exist to close.
"""
from __future__ import annotations

import concurrent.futures
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request

import helpers  # noqa: F401

import cairn
from test_server import ServerTestCase, _sse_connect, _sse_read_headers

# N >> request_queue_size (default 5, per the ruling's own framing) --
# large enough that a backlog-refusal (ECONNREFUSED) or a genuine
# concurrency defect would have room to surface, not just graze it.
CONCURRENT_FETCH_COUNT = 50


def _fetch_board_status(base_url: str) -> int:
    """One GET /api/board, returning the HTTP status code actually
    observed -- never raising for a non-2xx response (urllib raises
    HTTPError for those; caught and its own .code returned instead, since
    a 5xx IS the observation this harness exists to catch, not a test
    failure in itself)."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/board", timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


class ConcurrentBoardLoadTests(ServerTestCase):
    def test_n_concurrent_board_fetches_with_an_open_sse_stream_all_succeed(self):
        # Hold one SSE connection open for the duration -- the long-lived
        # stream is the condition under investigation (PT-29/PT-32's
        # sightings both occurred with /api/events open).
        sse_sock = _sse_connect(self.port)
        self.addCleanup(sse_sock.close)
        status_line, _headers, _leftover = _sse_read_headers(sse_sock)
        self.assertIn("200", status_line, f"SSE connection itself must establish cleanly: {status_line!r}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_FETCH_COUNT) as pool:
            statuses = list(pool.map(lambda _: _fetch_board_status(self.base_url), range(CONCURRENT_FETCH_COUNT)))

        self.assertEqual(len(statuses), CONCURRENT_FETCH_COUNT)
        bad = [s for s in statuses if s not in (200, 304)]
        self.assertEqual(
            bad, [],
            f"every /api/board response under {CONCURRENT_FETCH_COUNT}-way concurrent load with an open "
            f"SSE stream must be 200 or 304, observed server-side -- got: {statuses}",
        )

    def test_concurrent_board_fetches_survive_sse_connect_disconnect_churn(self):
        # The other half of the condition under investigation: not just a
        # long-lived stream, but the stream being established/torn down
        # WHILE fetches are in flight (PT-29's sighting was specifically
        # "at page load", i.e. during SSE connection setup).
        stop = threading.Event()
        churn_errors: list = []

        def churn_sse():
            while not stop.is_set():
                try:
                    sock = _sse_connect(self.port, timeout=2.0)
                    _sse_read_headers(sock)
                    time.sleep(0.02)
                    sock.close()
                except OSError as e:  # noqa: PERF203
                    churn_errors.append(str(e))

        churn_thread = threading.Thread(target=churn_sse, daemon=True)
        churn_thread.start()
        self.addCleanup(lambda: (stop.set(), churn_thread.join(timeout=5)))

        # Give the churn loop a moment to actually start connecting before
        # the fetch wave fires, so the two are genuinely overlapping, not
        # accidentally sequential.
        time.sleep(0.05)

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_FETCH_COUNT) as pool:
            statuses = list(pool.map(lambda _: _fetch_board_status(self.base_url), range(CONCURRENT_FETCH_COUNT)))

        stop.set()
        churn_thread.join(timeout=5)

        bad = [s for s in statuses if s not in (200, 304)]
        self.assertEqual(
            bad, [],
            f"every /api/board response during SSE connect/disconnect churn must be 200 or 304, "
            f"observed server-side -- got: {statuses}",
        )
        # The churn loop's own connection attempts must not themselves be
        # refused/erroring under the same concurrent fetch load -- a
        # failure here would itself be evidence of exactly the connection-
        # churn defect H4 hypothesized (backlog exhaustion), even though
        # it wouldn't produce a literal 503 (ECONNREFUSED does not, per
        # the ruling's own H4 analysis) -- recorded, not asserted strictly
        # empty, since a transient OSError here is plausible test-harness
        # noise (the churn loop opening/closing sockets in a tight loop is
        # not itself part of the server-under-test's contract) and
        # shouldn't fail the primary assertion above on its own.
        self.assertLess(
            len(churn_errors), CONCURRENT_FETCH_COUNT,
            f"the SSE churn loop itself failed on nearly every attempt, which would undermine this "
            f"test's premise that churn was actually happening concurrently: {churn_errors[:5]}",
        )

    def test_sequential_baseline_all_200_no_304_without_an_etag(self):
        # Sanity/control: without any If-None-Match header, every request
        # must be a real 200 (never a spurious 304) -- pins the "200 or
        # 304" assertion above to something that would actually fail if
        # the endpoint's ETag handling regressed to always-304 or similar.
        statuses = [_fetch_board_status(self.base_url) for _ in range(5)]
        self.assertTrue(all(s == 200 for s in statuses), statuses)


if __name__ == "__main__":
    unittest.main()
