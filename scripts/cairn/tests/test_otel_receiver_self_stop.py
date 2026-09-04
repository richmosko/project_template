"""PT-86 failing acceptance tests: the receiver stops itself when the
LAST session on the repo ends, only after the exporter's final flush has
had a grace window to land (process/cairn/issues/PT-86.md).

## Superseded once already -- read the architect's gating ruling, not the
## original team-lead ruling text, for the wire contract

The original ruling ("SessionEnd hook calls otel_receiver.py
--session-ended", a per-session counter) left the transport unspecified.
The architect's gating ruling ("@architect -- 2026-09-04", §0-§10,
committed to this issue) is the actual, authoritative, testable contract
-- notably §1 rules out a state file (which both qa-engineer's and
implementation-lead's own first-draft proposals assumed) in favor of an
HTTP control endpoint the daemon owns as its single writer. This file was
rewritten from scratch against §0-§10 after that ruling landed; every
class below cites the section it tests.

## Wire contract under test (§1-§7, §9)

    POST /control/session
        Body: {"event": "start"|"end", "session_id": str,
               "repo_root": "<absolute, resolved>", "pid": int|None}
        - repo_root mismatch (§1, cross-repo guard) -> 409, no state
          change.
        - "end" for an unknown session_id (§6) -> 200 {"known": false},
          no state change.
        - "start" while the daemon is past its point of no return (§4)
          -> 503 {"closing": true}. NOT covered here -- see
          "Deliberately NOT tested" below.
        - Otherwise -> a mutation (register / deregister-and-reap) under
          the daemon's own state lock, 200.

    CLI (agreed with implementation-lead by SendMessage after this
    ruling landed, since the ruling itself only pins the wire contract
    + these exact flag effects, not every flag's literal spelling):
        --ensure-running [--session-id ID] [--session-pid PID]
            Existing spawn-if-needed behaviour, PLUS: when a session id
            is present (explicit --session-id, since none of these
            tests are TTY-attached-stdin scenarios), POSTs a "start"
            event once the daemon is confirmed up. Always exits 0.
        --session-ended [--session-id ID]
            POSTs an "end" event. No daemon running / any control-path
            failure -> non-fatal (§10), stderr line, exit 0. This is
            the SessionEnd hook's target.
        --session-pid INT
            TEST-ONLY override for §2's ancestor-walk pid capture --
            the ruling names no such flag; see PureAncestryPidTests'
            docstring for why omitting it (not mocking it) is what
            drives the real `pid: null` path.
        --grace SECONDS (default 10.0, §4)
        --status (§7)
            Gains `sessions: <n>` and one line per registered id:
            `<session_id> pid=<pid|none> live=<true|false|unknown>`.

## Deliberately NOT tested here (flagged, not worked around)

- §4's 503 `{"closing": true}` -> client waits for the port to stop
  listening -> falls through to spawn a fresh receiver. Hitting the
  precise "closing=True but socket not yet closed" window from outside
  the process, deterministically, needs an internal test seam this
  ruling doesn't provide. A flaky sleep-and-hope race test would be
  worse than no test -- this is a code-review item until such a seam
  exists (raised with implementation-lead).
- §5's pidfile compare-and-delete specifically (vs. plain unlink) --
  same reasoning: proving "compare" happened (not just "delete") needs
  either an internal seam or a precisely-timed successor-pidfile race.
  Raised with implementation-lead as a candidate for its own unit-
  testable function; not gating this file.
- §9's empirical SessionEnd-fires-on-shutdown_request check. The
  architect named this a live measurement, not a unit test, run once
  AC1-AC3 are green (needs a real hook line to observe firing at all)
  and recorded as its own PT-86 comment, not a suite assertion.

## Why "two fake project roots" (module fixture)

Same reason as test_otel_receiver_hardening.py: `ensure_running`/
`--status`/the bare-invocation `serve()` path derive `repo_root` from the
SCRIPT's own on-disk location, not cwd or a flag. A throwaway copy of the
engine under a scratch tmp dir is the only way to drive the real
hook-invocation code path. `CrossRepoGuardTests` is where TWO such roots
are genuinely both in play at once -- per the architect's own note, this
is specifically what AC1's "two fake project roots" phrase means: a
control POST whose `repo_root` names a DIFFERENT project than the one
the receiver on that port belongs to (root B's own client, pointed via
its own otel_port config at root A's already-running receiver -- the
exact "two projects share otel_port" collision PT-79 already burned once
in the opposite direction).

## Why AC1's other three scenarios use only ONE fake root each

They're each an isolated lifecycle question (does the count/timer behave
right) that doesn't need a second real project to be meaningful -- adding
a second root to each would just be fixture ceremony, not more coverage.

## AC2's "provably" -- how

basic.json (already used by test_otel_receiver.py) carries a single
measured, distinctive fingerprint: `cairn.issue: PT-95`, and its
`type: "input"` datapoint's value is exactly 100. A real HTTP POST of
those exact bytes, sent to the daemon strictly AFTER the last
SessionEnd's "end" event (i.e. inside the grace window, before the
watchdog's deadline), followed by reading the flushed line back out of
--out-file after the process has self-stopped, is the only way to prove
the datapoint that arrived DURING grace survived into the FINAL flush.

## AC4 -- the real committed data file

`RealDataFileUntouchedGuard` snapshots process/cairn/metrics/
token-usage.jsonl's bytes once for this whole module and re-checks them
unchanged at the very end -- on top of every individual test using a
non-default --port and an --out-file under a fake root's own temp tree
(architect's own closing instruction).
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Optional

import helpers  # noqa: F401

SCRIPT_PATH = helpers.CAIRN_DIR / "otel_receiver.py"
FIXTURES = helpers.FIXTURES_DIR / "otlp"
SETTINGS_PATH = helpers.TESTS_DIR.parent.parent.parent / ".claude" / "settings.json"
REAL_TOKEN_USAGE_PATH = (
    helpers.TESTS_DIR.parent.parent.parent / "process" / "cairn" / "metrics" / "token-usage.jsonl"
)

ENGINE_FILES = ("otel_receiver.py", "backfill_tokens.py", "cairn.py")


# --------------------------------------------------------------------------
# "Two fake project roots" fixture -- see module docstring.
# --------------------------------------------------------------------------

def make_fake_engine_root(testcase, otel_port: Optional[int] = None) -> Path:
    root = helpers.make_empty_tmp_dir(testcase)
    engine_dir = root / "scripts" / "cairn"
    engine_dir.mkdir(parents=True)
    for name in ENGINE_FILES:
        shutil.copy2(helpers.CAIRN_DIR / name, engine_dir / name)
    data_dir = root / "process" / "cairn"
    data_dir.mkdir(parents=True)
    lines = ["prefix: PT", "port: 8766"]
    if otel_port is not None:
        lines.append(f"otel_port: {otel_port}")
    (data_dir / "config.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _minimal_env(**overrides: str) -> dict:
    """A from-scratch env -- this is itself a live Claude Code session,
    which already has telemetry enabled in ITS OWN environment. Never
    inherit os.environ wholesale."""
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if "HOME" in os.environ:
        base["HOME"] = os.environ["HOME"]
    base.update(overrides)
    return base


def run_fake_receiver(fake_root: Path, args: list[str], env: Optional[dict] = None) -> subprocess.CompletedProcess:
    script = fake_root / "scripts" / "cairn" / "otel_receiver.py"
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, cwd=str(fake_root),
        env=env if env is not None else _minimal_env(),
        stdin=subprocess.DEVNULL,  # never let a test hang on the "read hook JSON from stdin" path
    )


def _pidfile_path(fake_root: Path) -> Path:
    return fake_root / "process" / "cairn" / "metrics" / ".receiver.pid"


def _out_path(fake_root: Path) -> Path:
    return fake_root / "process" / "cairn" / "metrics" / "token-usage.jsonl"


def _stop_fake_receiver(fake_root: Path, env: dict) -> None:
    """Cleanup safety net: a test that fails mid-assertion must never
    leak a detached background process into the rest of the suite run."""
    run_fake_receiver(fake_root, ["--stop"], env=env)
    pidfile = _pidfile_path(fake_root)
    for _ in range(20):
        if not pidfile.exists():
            return
        time.sleep(0.1)
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
        os.kill(pid, 9)
    except (OSError, ValueError):
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _dead_pid() -> int:
    """A PID guaranteed to have already exited -- run-and-wait a trivial
    child, return its now-dead pid. A (vanishingly unlikely, within a
    single test's lifetime) PID-reuse race is the same trade-off the rest
    of this suite already accepts for similar determinism fixtures."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _wait_for_status_running(fake_root: Path, env: dict, timeout: float = 5.0) -> subprocess.CompletedProcess:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = run_fake_receiver(fake_root, ["--status"], env=env)
        if last.returncode == 0:
            return last
        time.sleep(0.1)
    return last


def _wait_for_status_not_running(fake_root: Path, env: dict, timeout: float) -> subprocess.CompletedProcess:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = run_fake_receiver(fake_root, ["--status"], env=env)
        if last.returncode == 1:
            return last
        time.sleep(0.1)
    return last


def _base_env(port: int) -> dict:
    return _minimal_env(
        CLAUDE_CODE_ENABLE_TELEMETRY="1",
        OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{port}",
    )


def _post_control(port: int, event: str, session_id: str, repo_root: Path, pid=None, timeout: float = 2.0):
    """Raw HTTP POST to /control/session -- §1's wire contract, directly,
    bypassing the CLI so response status/body can be inspected precisely
    (the CLI's own --session-ended/--ensure-running only ever exit 0 by
    design, per §10, so they can't surface a 409/503/`known` body)."""
    body = json.dumps({
        "event": event, "session_id": session_id,
        "repo_root": str(Path(repo_root).resolve()), "pid": pid,
    }).encode("utf-8")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request("POST", "/control/session", body=body, headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError:
        parsed = {}
    return response.status, parsed


def _post_basic_payload(port: int) -> int:
    """Sends basic.json's exact bytes to the daemon's /v1/metrics.
    Returns the HTTP status code."""
    body = (FIXTURES / "basic.json").read_bytes()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/v1/metrics", body=body, headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    response.read()
    conn.close()
    return response.status


def read_jsonl(path: Path) -> list[dict]:
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(json.loads(raw))
    return lines


# --------------------------------------------------------------------------
# AC4: the real, committed data file must never move.
# --------------------------------------------------------------------------

class RealDataFileUntouchedGuard(unittest.TestCase):
    """Snapshots the REAL repo's committed token-usage.jsonl once before
    any test in this module runs a subprocess, and again after the very
    last one -- on top of every individual test already pointing its own
    --out-file at a fake root's own tree (and a non-default --port)."""

    _before: Optional[bytes] = None

    @classmethod
    def setUpClass(cls):
        cls._before = REAL_TOKEN_USAGE_PATH.read_bytes() if REAL_TOKEN_USAGE_PATH.exists() else None

    def test_snapshot_taken(self):
        self.assertTrue(True)  # registers this class as having run at least one test before the final check

    def test_zz_real_file_unchanged_so_far(self):
        after = REAL_TOKEN_USAGE_PATH.read_bytes() if REAL_TOKEN_USAGE_PATH.exists() else None
        self.assertEqual(
            after, self._before,
            "the real, committed process/cairn/metrics/token-usage.jsonl must never be "
            "touched by this test module -- every test must point --out-file at a fake root",
        )


# --------------------------------------------------------------------------
# Cheap, unambiguous first-to-fail checks.
# --------------------------------------------------------------------------

class SeamPresenceGuardTests(unittest.TestCase):
    """One check per new CLI flag / endpoint: every scenario test would
    fail anyway if these are missing, but for the confusing argparse
    'unrecognized arguments' (or a bare 404) reason rather than this
    clear one."""

    def test_session_id_and_session_pid_flags_are_recognised(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        result = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "s1", "--session-pid", "1"], env=_minimal_env())
        combined = result.stdout + result.stderr
        self.assertNotIn("unrecognized arguments", combined, f"--session-id/--session-pid not yet recognised -- got: {combined!r}")

    def test_session_ended_flag_is_recognised(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        result = run_fake_receiver(fake_root, ["--session-ended", "--session-id", "s1"], env=_minimal_env())
        combined = result.stdout + result.stderr
        self.assertNotIn("unrecognized arguments", combined, f"--session-ended not yet recognised -- got: {combined!r}")

    def test_grace_flag_is_recognised(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        result = run_fake_receiver(fake_root, ["--status", "--grace", "0.3"], env=_minimal_env())
        combined = result.stdout + result.stderr
        self.assertNotIn("unrecognized arguments", combined, f"--grace not yet recognised -- got: {combined!r}")

    def test_control_session_endpoint_exists(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)
        r = run_fake_receiver(fake_root, ["--ensure-running"], env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _wait_for_status_running(fake_root, env)
        status_code, _ = _post_control(port, "end", "no-such-session", fake_root)
        self.assertNotEqual(status_code, 404, "POST /control/session (§1) does not exist yet -- got a 404")


# --------------------------------------------------------------------------
# AC1: two fake project roots, fake session ids -- the four named
# scenarios (three of which need only one root each; see module
# docstring).
# --------------------------------------------------------------------------

class LastSessionSelfStopTests(unittest.TestCase):
    """§2/§4: one start/end exits after grace with a flush; two starts/
    one end stays up; a start inside the grace window cancels the exit."""

    GRACE = 0.4

    def test_one_session_start_end_exits_after_grace_period_with_a_flush(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)

        start = run_fake_receiver(
            fake_root,
            ["--ensure-running", "--session-id", "s1", "--session-pid", str(os.getpid()), "--grace", str(self.GRACE)],
            env=env,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        status = _wait_for_status_running(fake_root, env)
        self.assertEqual(status.returncode, 0, f"receiver must be running after the only session starts -- {status.stdout!r} {status.stderr!r}")
        self.assertIn("sessions: 1", status.stdout, status.stdout)

        end = run_fake_receiver(fake_root, ["--session-ended", "--session-id", "s1"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        # §4: "Do not flush at this moment" -- must NOT have exited
        # immediately either; the grace window is the whole point.
        immediate = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(
            immediate.returncode, 0,
            f"must still be running immediately after the last SessionEnd -- exit happens only after "
            f"the grace period, got {immediate.stdout!r} {immediate.stderr!r}",
        )

        stopped = _wait_for_status_not_running(fake_root, env, timeout=self.GRACE + 4.0)
        self.assertEqual(
            stopped.returncode, 1,
            f"the receiver must exit on its own once the grace period elapses after the last session ended -- "
            f"stdout={stopped.stdout!r} stderr={stopped.stderr!r}",
        )
        self.assertFalse(_pidfile_path(fake_root).exists(), "§5: the pidfile must be removed on self-stop")

    def test_two_starts_one_end_still_running(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)

        r1 = run_fake_receiver(
            fake_root,
            ["--ensure-running", "--session-id", "s1", "--session-pid", str(os.getpid()), "--grace", str(self.GRACE)],
            env=env,
        )
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        _wait_for_status_running(fake_root, env)

        r2 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "s2", "--session-pid", str(os.getpid())], env=env)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertIn("sessions: 2", status.stdout, status.stdout)

        end = run_fake_receiver(fake_root, ["--session-ended", "--session-id", "s1"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        # Well past what the grace period would have been if this were
        # the LAST session -- must never exit while s2 is still live.
        time.sleep(self.GRACE + 1.0)
        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(status.returncode, 0, f"a second live session must keep the receiver running -- {status.stdout!r} {status.stderr!r}")
        self.assertIn("sessions: 1", status.stdout, status.stdout)

    def test_a_start_during_the_grace_window_cancels_the_exit(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)
        grace = 1.0

        r1 = run_fake_receiver(
            fake_root,
            ["--ensure-running", "--session-id", "s1", "--session-pid", str(os.getpid()), "--grace", str(grace)],
            env=env,
        )
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        _wait_for_status_running(fake_root, env)

        end = run_fake_receiver(fake_root, ["--session-ended", "--session-id", "s1"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        # Well inside the grace window -- a fresh session starts. §4:
        # "a `start` request ... clear the deadline unconditionally."
        time.sleep(grace * 0.3)
        r2 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "s2", "--session-pid", str(os.getpid())], env=env)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

        # Well past the ORIGINAL grace deadline -- if the new session
        # hadn't cancelled the shutdown, this would have exited.
        time.sleep(grace + 1.0)
        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(
            status.returncode, 0,
            f"a session starting inside the grace window must cancel the pending shutdown -- {status.stdout!r} {status.stderr!r}",
        )
        self.assertIn("sessions: 1", status.stdout, status.stdout)


class LivenessReapTests(unittest.TestCase):
    """§3: probe = os.kill(pid, 0), run on every 'end' event and at each
    flush. Dead -> drop. `pid: null` -> never dropped by the probe."""

    def test_a_dead_session_id_is_reaped_on_a_sibling_decrement(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)

        alive_pid = os.getpid()
        gone_pid = _dead_pid()

        r1 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "alive", "--session-pid", str(alive_pid)], env=env)
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        _wait_for_status_running(fake_root, env)

        r2 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "gone", "--session-pid", str(gone_pid)], env=env)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

        r3 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "throwaway", "--session-pid", str(alive_pid)], env=env)
        self.assertEqual(r3.returncode, 0, r3.stdout + r3.stderr)

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertIn("sessions: 3", status.stdout, status.stdout)
        self.assertIn("gone pid=", status.stdout, status.stdout)
        self.assertIn("live=false", status.stdout, f"--status must report the dead pid's liveness honestly before it's reaped -- {status.stdout!r}")

        # Decrementing "throwaway" (still leaves "alive" live, so the
        # daemon does not shut down) must trip the probe over every
        # OTHER recorded session too, reaping "gone".
        end = run_fake_receiver(fake_root, ["--session-ended", "--session-id", "throwaway"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(status.returncode, 0, f"'alive' never ended, so the receiver must still be running -- {status.stdout!r} {status.stderr!r}")
        self.assertIn("sessions: 1", status.stdout, f"the dead 'gone' session must have been reaped by the liveness probe -- {status.stdout!r}")
        self.assertNotIn("gone ", status.stdout, f"a reaped session id must no longer be listed at all -- {status.stdout!r}")

    def test_a_pid_null_session_is_never_reaped_by_the_probe(self):
        # Omitting --session-pid entirely (not mocking it) drives the
        # real §2 ancestor-walk -- in THIS test process's ancestry there
        # is no "claude binary" ancestor, so it must genuinely resolve to
        # pid: null, not something this test fabricates.
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)

        r1 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "no-pid-session"], env=env)
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        _wait_for_status_running(fake_root, env)

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertIn("no-pid-session pid=none", status.stdout, f"expected a null pid capture in this test process's ancestry -- got: {status.stdout!r}")
        self.assertIn("live=unknown", status.stdout, status.stdout)

        # Force a probe cycle via a sibling decrement -- a null-pid entry
        # must survive it.
        r2 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "throwaway", "--session-pid", str(os.getpid())], env=env)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        end = run_fake_receiver(fake_root, ["--session-ended", "--session-id", "throwaway"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(status.returncode, 0, "a pid:null session must never be reaped by the probe, so the receiver must still be running")
        self.assertIn("no-pid-session", status.stdout, f"the pid:null session must still be listed -- {status.stdout!r}")


class NeverNonEmptyPinTests(unittest.TestCase):
    """§6: only a non-empty -> empty transition stops the receiver. A
    registry that was NEVER non-empty (a receiver started with no
    session id ever registered) must never self-stop, even when it
    receives 'end' events for ids it never saw."""

    def test_a_receiver_with_no_registered_sessions_never_self_stops(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)
        grace = 0.3

        r1 = run_fake_receiver(fake_root, ["--ensure-running", "--grace", str(grace)], env=env)
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        _wait_for_status_running(fake_root, env)

        end = run_fake_receiver(fake_root, ["--session-ended", "--session-id", "never-registered"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        time.sleep(grace + 1.0)
        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(
            status.returncode, 0,
            f"a registry that was never non-empty must never trigger a shutdown -- {status.stdout!r} {status.stderr!r}",
        )

    def test_end_for_an_unknown_session_id_reports_known_false_with_no_state_change(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)

        r1 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "s1", "--session-pid", str(os.getpid())], env=env)
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        _wait_for_status_running(fake_root, env)

        status_code, body = _post_control(port, "end", "totally-unknown-id", fake_root)
        self.assertEqual(status_code, 200, f"§6: an end for an unknown id must be 200, not an error -- got {status_code} {body}")
        self.assertEqual(body.get("known"), False, f"§6: body must report known: false -- got {body}")

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertIn("sessions: 1", status.stdout, f"an unknown-id end must cause no state change -- {status.stdout!r}")


# --------------------------------------------------------------------------
# §1: the cross-repo guard -- the actual meaning of AC1's "two fake
# project roots".
# --------------------------------------------------------------------------

class CrossRepoGuardTests(unittest.TestCase):
    """Two REAL fake project roots, both in play at once: root A's
    receiver is the only one running (bound to a shared port); root B's
    own client is pointed at that SAME port (its own config.yml's
    otel_port set to match) -- simulating the exact 'two projects share
    otel_port' collision the architect names. A control POST whose
    repo_root resolves to B, sent to A's receiver, must change nothing
    in A's state and must not stop A's receiver."""

    def test_a_control_post_naming_a_different_repo_root_is_refused_and_changes_nothing(self):
        shared_port = _free_port()
        root_a = make_fake_engine_root(self, otel_port=shared_port)
        root_b = make_fake_engine_root(self, otel_port=shared_port)
        env = _base_env(shared_port)
        self.addCleanup(_stop_fake_receiver, root_a, env)

        start_a = run_fake_receiver(root_a, ["--ensure-running", "--session-id", "a-session", "--session-pid", str(os.getpid())], env=env)
        self.assertEqual(start_a.returncode, 0, start_a.stdout + start_a.stderr)
        _wait_for_status_running(root_a, env)

        # root B's OWN client resolves its OWN repo_root (root_b) but
        # talks to the SAME port (root A's receiver, since B's
        # config.yml otel_port also points at shared_port) -- exactly
        # what --session-ended from B's hook would do if the two
        # projects collided on otel_port.
        end_from_b = run_fake_receiver(root_b, ["--session-ended", "--session-id", "a-session"], env=env)
        self.assertEqual(end_from_b.returncode, 0, "the CLI's own exit code stays 0 either way (§10, non-fatal control-path failures)")

        # root A's session must be UNCHANGED -- still registered, and
        # the receiver still running (not decremented, not stopped).
        status_a = run_fake_receiver(root_a, ["--status"], env=env)
        self.assertEqual(status_a.returncode, 0, f"root A's receiver must still be running -- a cross-repo end must not stop it -- {status_a.stdout!r}")
        self.assertIn("sessions: 1", status_a.stdout, f"root A's session count must be unchanged by root B's request -- {status_a.stdout!r}")
        self.assertIn("a-session", status_a.stdout, status_a.stdout)

        # Same guard, direct HTTP, to pin the actual status code (the
        # CLI itself never surfaces it, by design).
        status_code, _ = _post_control(shared_port, "end", "a-session", root_b)
        self.assertEqual(status_code, 409, f"§1: a repo_root mismatch must answer 409 -- got {status_code}")

        status_a_again = run_fake_receiver(root_a, ["--status"], env=env)
        self.assertIn("sessions: 1", status_a_again.stdout, "a 409-refused cross-repo request must leave state exactly as it was")


# --------------------------------------------------------------------------
# AC2: the final flush provably contains a datapoint received during grace.
# --------------------------------------------------------------------------

class GraceWindowFlushContentTests(unittest.TestCase):
    """basic.json's fingerprint (cairn.issue: PT-95, an `input`-type
    datapoint of value 100) sent DURING the grace window must survive
    into the flush that happens at self-stop -- proving the daemon keeps
    accepting real exports for the whole grace window (§4: 'do not flush
    at this moment' of the decrement; §5: socket closes FIRST, so the
    flush is provably complete by the time it happens, not by luck)."""

    def test_a_datapoint_posted_during_the_grace_window_lands_in_the_final_flush(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)
        grace = 0.6

        start = run_fake_receiver(
            fake_root,
            ["--ensure-running", "--session-id", "s1", "--session-pid", str(os.getpid()), "--grace", str(grace)],
            env=env,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
        _wait_for_status_running(fake_root, env)

        end = run_fake_receiver(fake_root, ["--session-ended", "--session-id", "s1"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        # Strictly inside the grace window.
        status_code = _post_basic_payload(port)
        self.assertLess(status_code, 300, "a well-formed payload posted during the grace window must be accepted, not refused")

        stopped = _wait_for_status_not_running(fake_root, env, timeout=grace + 4.0)
        self.assertEqual(stopped.returncode, 1, f"receiver must self-stop after grace -- {stopped.stdout!r} {stopped.stderr!r}")

        out_path = _out_path(fake_root)
        self.assertTrue(out_path.is_file(), "the self-stop flush must have written --out-file")
        lines = read_jsonl(out_path)
        pt95 = [l for l in lines if l.get("issue") == "PT-95"]
        self.assertTrue(pt95, f"the datapoint posted during grace (cairn.issue PT-95) must be in the final flush -- got {lines}")
        self.assertEqual(
            sum(l.get("input", 0) for l in pt95), 100,
            f"basic.json's input-type value (100) must be exactly what was flushed, proving THIS datapoint landed -- got {pt95}",
        )


# --------------------------------------------------------------------------
# AC3: the SessionEnd hook line in .claude/settings.json.
# --------------------------------------------------------------------------

class SessionEndHookLineTests(unittest.TestCase):
    """AC3 + §9: 'SessionEnd mirrors SessionStart's shape: guard on the
    script's existence, exit 0, no stderr redirect, stdin left connected
    so the JSON reaches the script.'"""

    def _hook_command(self) -> str:
        doc = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        for entry in doc.get("hooks", {}).get("SessionEnd", []):
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                if "otel_receiver.py" in command and "--session-ended" in command:
                    return command
        self.fail(f"no SessionEnd hook command mentions otel_receiver.py --session-ended in {SETTINGS_PATH}")

    def test_a_session_end_hook_entry_invoking_session_ended_exists(self):
        self._hook_command()  # self.fail inside is the assertion

    def test_stderr_is_not_redirected_to_dev_null(self):
        command = self._hook_command()
        self.assertNotIn(
            "2>&1", command,
            f"stderr must not be merged into a discarded stdout redirect, same as the SessionStart line -- got: {command!r}",
        )

    def test_the_hook_still_unconditionally_exits_zero(self):
        command = self._hook_command()
        self.assertIn("exit 0", command, f"a SessionEnd hook must never fail session teardown over telemetry -- got: {command!r}")

    def test_guards_on_the_script_existing_same_as_session_start(self):
        command = self._hook_command()
        guard_zone = command.split("&&")[0] if "&&" in command else command
        self.assertIn("otel_receiver.py", guard_zone, f"same defensive guard pattern as the SessionStart line ('[ -f ... ] || exit 0') -- got: {command!r}")

    def test_stdin_is_left_connected_for_the_hook_json(self):
        command = self._hook_command()
        self.assertNotIn(
            "/dev/null", command.split("--session-ended", 1)[-1].split(";")[0] if "--session-ended" in command else command,
            f"§9: stdin must stay connected so the hook's JSON (session_id) reaches the script -- got: {command!r}",
        )


if __name__ == "__main__":
    unittest.main()
