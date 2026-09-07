"""PT-96 gate 2 (qa-engineer): failing tests for helpers.serve_in_thread,
pinned to the architect's gate-1 ruling (process/cairn/issues/PT-96.md @
fed43a4 -- "Seam" and "Guard thresholds").

The measured cost was never fixture construction (3.8-7.2 ms) -- it is
`socketserver.BaseServer.serve_forever()`'s default `poll_interval=0.5`,
which `shutdown()` blocks on (measured 501 ms at the default, 11.1 ms at
0.01). The fix is one helper in tests/helpers.py (implementation-lead's
file, not touched here) that every one of the 20 real call sites in 14
test files routes through instead of hand-rolling a raw daemon thread
around the server's own serve loop with no interval set.

Writer boundary (ruling): implementation-lead owns tests/helpers.py and
the 14 call-site files; qa-engineer owns this file, test_run_tests.py's
AC6 addition, and process/reviews/PT-96/mutations.md. Nothing here edits
helpers.py or a call-site file.
"""
from __future__ import annotations

import re
import time
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn

TESTS_DIR = helpers.TESTS_DIR
# threading.Thread(target=<anything>serve_forever ... -- deliberately
# narrow (real call shape only), so a comment mentioning serve_forever
# (test_server.py:618, test_cli.py:801/813) can never match.
_SITE_RE = re.compile(r"threading\.Thread\(\s*target\s*=\s*[\w.]*serve_forever")


def _non_comment_lines(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        yield line


def _sites_in(path: Path) -> int:
    return sum(1 for line in _non_comment_lines(path) for _ in _SITE_RE.finditer(line))


class NoRawServeForeverThreadOutsideHelpersTests(unittest.TestCase):
    """Guard threshold 1: zero raw server-thread-launch sites (the pattern
    _SITE_RE matches -- see its own definition above) outside helpers.py.
    Controlled against a string that must match (helpers.py's own site)
    so an empty result can't come from a pattern that's simply broken --
    at b0cc8bd (pre-fix) this scan finds 20 sites in 14 files outside
    helpers.py, and 0 inside (helpers.serve_in_thread doesn't exist yet).
    This file is excluded from the scan itself -- it necessarily discusses
    the pattern in prose (see the module docstring)."""

    def test_no_raw_site_remains_outside_helpers_py(self):
        offenders = {}
        for path in sorted(TESTS_DIR.glob("*.py")):
            if path.name in ("helpers.py", "test_serve_in_thread.py"):
                continue
            n = _sites_in(path)
            if n:
                offenders[path.name] = n
        self.assertEqual(
            offenders, {},
            f"every server-thread site must route through helpers.serve_in_thread -- "
            f"a raw site (see _SITE_RE) remains in: {offenders!r}",
        )

    def test_the_scan_pattern_itself_matches_helpers_pys_own_site(self):
        # Proves the regex isn't vacuously empty everywhere -- helpers.py
        # is the one place this call shape is SUPPOSED to live, inside
        # serve_in_thread's own implementation.
        n = _sites_in(TESTS_DIR / "helpers.py")
        self.assertGreaterEqual(
            n, 1,
            "helpers.py must contain the one real raw-site call (see _SITE_RE), inside "
            "serve_in_thread -- if this is 0, either serve_in_thread doesn't exist yet or "
            "the scan pattern is broken",
        )


class ServeInThreadPassesIntervalTests(unittest.TestCase):
    """Guard threshold 2: serve_in_thread passes the interval to
    serve_forever positionally via args (not a kwarg, not omitted)."""

    def test_interval_is_passed_positionally_to_serve_forever(self):
        calls = []

        class FakeServer:
            def serve_forever(self, poll_interval=0.5):
                calls.append(poll_interval)

        thread = helpers.serve_in_thread(FakeServer(), poll_interval=0.02)
        thread.join(timeout=2)
        self.assertEqual(calls, [0.02], "serve_forever must be invoked with the interval, not the 0.5 default")


class PollIntervalConstantTests(unittest.TestCase):
    """Guard threshold 4: helpers.SERVE_POLL_INTERVAL <= 0.05."""

    def test_default_poll_interval_is_small(self):
        self.assertLessEqual(helpers.SERVE_POLL_INTERVAL, 0.05)


class ShutdownLatencyTests(unittest.TestCase):
    """Guard threshold 3: a real cairn.make_server(port=0) started through
    the helper shuts down in < 100 ms (measured 11.1 ms at the fix, 9x
    margin; the unpatched default measured 501 ms -- 5x over budget).
    Mutation: serve_in_thread dropping `args=` falls back to
    serve_forever's own 0.5 s default -> this goes red."""

    def test_shutdown_after_serve_in_thread_is_fast(self):
        data_dir = helpers.make_tmp_data_dir(self)
        server = cairn.make_server(data_dir, port=0)
        thread = helpers.serve_in_thread(server)
        self.addCleanup(lambda: thread.join(timeout=5))
        t0 = time.time()
        server.shutdown()
        elapsed = time.time() - t0
        server.server_close()
        self.assertLess(
            elapsed, 0.1,
            f"shutdown() took {elapsed:.3f}s -- serve_in_thread must pass a small poll_interval "
            f"(measured 11.1ms fixed vs 501ms at the stock default)",
        )


if __name__ == "__main__":
    unittest.main()
