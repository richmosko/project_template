"""PT-86 failing acceptance tests: the receiver stops itself when the
LAST session on the repo ends, only after the exporter's final flush has
had a grace window to land (process/cairn/issues/PT-86.md, ruling
2026-09-04).

## Seam, agreed with implementation-lead before this file was written
(SendMessage, 2026-09-04) -- if the actual build lands under different
names, only this file's helpers/flag lists need to change, not the
acceptance shape:

CLI (`otel_receiver.py`):
    --ensure-running --session-id ID --session-pid PID
        Registers a live session (in addition to ensure_running's
        existing spawn-if-needed behaviour) and cancels any pending
        grace-shutdown in an already-running daemon. Still exits 0
        always.
    --session-ended ID
        Deregisters a session, reaps any OTHER recorded session whose
        pid has died (the crash backstop -- ruling's "liveness probe...
        run on every decrement"), and pings the daemon to re-evaluate.
        No daemon running -> no-op, exit 0. Same exit-0 discipline as
        --ensure-running (this is the SessionEnd hook's target).
    --grace-period-seconds N (default 10; bare/serve invocation)
        The wait, after the LAST session ends, before flush + exit.
        Threaded through ensure_running's spawn args. Tests always pass
        something short (<1s) -- never the real 10s default.
    --status
        Gains `sessions: N` and one `session <id>: alive|dead` line per
        RECORDED id (sorted), on top of the existing running/port/
        out-file lines. A fresh, non-mutating probe every call --- only
        --session-ended and a flush actually reap stale entries.

Pure, socket-free functions (mirrors the parse_export/fold/flush
seam-discipline this module already follows):
    _sessions_dir(pidfile: Path) -> Path
    register_session(sessions_dir, session_id: str, pid: int) -> None
    deregister_session(sessions_dir, session_id: str) -> None
    reap_dead_sessions(sessions_dir, is_alive=_pid_is_alive) -> List[str]
    live_session_ids(sessions_dir) -> Dict[str, int]

## Why "two fake project roots" again

Same reason as test_otel_receiver_hardening.py's module docstring:
`ensure_running`/`--status`/the bare-invocation `serve()` path all derive
`repo_root` from the SCRIPT's own on-disk location, not cwd or
--repo-root. A throwaway copy of the engine under a scratch tmp dir is
the only way to drive the real hook-invocation code path (spawn, pidfile,
signals, self-stop) against an isolated tracker. `make_fake_engine_root`/
`run_fake_receiver`/`_minimal_env`/`_free_port` below are a deliberate
near-duplicate of that file's versions (same project convention: each
otel_receiver test module carries its own copy rather than sharing
scaffolding across files that must stay independently readable).

## AC2's "provably" -- how

basic.json (already used by test_otel_receiver.py for the one other
socket-touching test in this suite) carries a single measured,
distinctive fingerprint: `cairn.issue: PT-95`, and its `type: "input"`
datapoint's value is exactly 100. A real HTTP POST of those exact bytes,
sent to the daemon's bound port strictly AFTER the last SessionEnd fires
(i.e. inside the grace window, before the timer's deadline), followed by
reading the flushed line back out of --out-file after the process has
self-stopped, is the only way to prove the datapoint that arrived DURING
grace survived into the FINAL flush rather than being dropped on exit.

## AC4 -- the real committed data file

`RealDataFileUntouchedGuard` snapshots process/cairn/metrics/
token-usage.jsonl's bytes once for this whole module (setUpClass) and
re-checks them unchanged at the very end (tearDownClass) -- on top of
every individual test's own --out-file pointing at a fake root's own
tree, never the real one.
"""
from __future__ import annotations

import contextlib
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

import otel_receiver

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
    inherit os.environ wholesale (same reasoning as the hardening
    suite's helper of the same name)."""
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
    of this suite already accepts for `held_unlistening_port`-style
    determinism-over-perfect-purity fixtures."""
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
    --out-file at a fake root. This is the module-wide backstop against a
    seam mistake (e.g. a spawned daemon resolving repo_root wrong and
    writing into the real checkout)."""

    _before: Optional[bytes] = None

    @classmethod
    def setUpClass(cls):
        cls._before = REAL_TOKEN_USAGE_PATH.read_bytes() if REAL_TOKEN_USAGE_PATH.exists() else None

    def test_snapshot_taken(self):
        # A trivial always-passing assertion so this class registers as
        # having run at least one test -- the real check is in
        # test_zz_real_file_unchanged, ordered last by unittest's default
        # alphabetical test method sort within the class.
        self.assertTrue(True)

    def test_zz_real_file_unchanged_so_far(self):
        after = REAL_TOKEN_USAGE_PATH.read_bytes() if REAL_TOKEN_USAGE_PATH.exists() else None
        self.assertEqual(
            after, self._before,
            "the real, committed process/cairn/metrics/token-usage.jsonl must never be "
            "touched by this test module -- every test must point --out-file at a fake root",
        )


# --------------------------------------------------------------------------
# Pure, socket-free session-bookkeeping functions.
# --------------------------------------------------------------------------

class PureSessionBookkeepingTests(unittest.TestCase):
    """Unit-level, no subprocess, no daemon -- the same test-seam
    discipline test_otel_receiver.py already applies to parse_export/
    fold/flush. Confirms the functions named in this file's module
    docstring exist and behave, independent of the CLI/daemon wiring
    around them."""

    def _sessions_dir(self, testcase) -> Path:
        root = helpers.make_empty_tmp_dir(testcase)
        return root / ".sessions"

    def test_register_session_writes_a_file_containing_the_pid(self):
        self.assertTrue(
            hasattr(otel_receiver, "register_session"),
            "otel_receiver.register_session does not exist yet -- PT-86's session-bookkeeping seam is unimplemented",
        )
        sessions_dir = self._sessions_dir(self)
        otel_receiver.register_session(sessions_dir, "s1", 12345)
        entry = sessions_dir / "s1"
        self.assertTrue(entry.is_file(), "register_session must create a file named for the session id")
        self.assertIn("12345", entry.read_text(encoding="utf-8"), "the registered pid must be recoverable from the file")

    def test_deregister_session_removes_the_file_and_is_a_noop_if_absent(self):
        self.assertTrue(hasattr(otel_receiver, "deregister_session"), "otel_receiver.deregister_session does not exist yet")
        sessions_dir = self._sessions_dir(self)
        otel_receiver.register_session(sessions_dir, "s1", 12345)
        otel_receiver.deregister_session(sessions_dir, "s1")
        self.assertFalse((sessions_dir / "s1").exists(), "deregister_session must remove the file")
        # Must not raise on a session id that was never registered.
        otel_receiver.deregister_session(sessions_dir, "never-registered")

    def test_live_session_ids_reflects_current_directory_state_without_mutating(self):
        self.assertTrue(hasattr(otel_receiver, "live_session_ids"), "otel_receiver.live_session_ids does not exist yet")
        sessions_dir = self._sessions_dir(self)
        otel_receiver.register_session(sessions_dir, "s1", 111)
        otel_receiver.register_session(sessions_dir, "s2", 222)
        ids = otel_receiver.live_session_ids(sessions_dir)
        self.assertEqual(ids, {"s1": 111, "s2": 222}, ids)
        # Calling it again must not have deleted anything.
        self.assertEqual(otel_receiver.live_session_ids(sessions_dir), {"s1": 111, "s2": 222})

    def test_reap_dead_sessions_removes_only_dead_ones_and_returns_their_ids(self):
        self.assertTrue(hasattr(otel_receiver, "reap_dead_sessions"), "otel_receiver.reap_dead_sessions does not exist yet")
        sessions_dir = self._sessions_dir(self)
        otel_receiver.register_session(sessions_dir, "alive", 111)
        otel_receiver.register_session(sessions_dir, "dead", 222)

        removed = otel_receiver.reap_dead_sessions(sessions_dir, is_alive=lambda pid: pid == 111)

        self.assertEqual(removed, ["dead"], removed)
        self.assertTrue((sessions_dir / "alive").exists(), "a session whose pid is still alive must survive reaping")
        self.assertFalse((sessions_dir / "dead").exists(), "a session whose pid is dead must be removed by reaping")

    def test_sessions_dir_is_a_sibling_of_the_pidfile(self):
        self.assertTrue(hasattr(otel_receiver, "_sessions_dir"), "otel_receiver._sessions_dir does not exist yet")
        pidfile = Path("/tmp/some/root/process/cairn/metrics/.receiver.pid")
        sessions_dir = otel_receiver._sessions_dir(pidfile)
        self.assertEqual(sessions_dir.parent, pidfile.parent, "the sessions dir must live alongside the pidfile, not somewhere unrelated")


# --------------------------------------------------------------------------
# CLI flag presence -- cheap, unambiguous first-to-fail checks.
# --------------------------------------------------------------------------

class CLIFlagPresenceGuardTests(unittest.TestCase):
    """One cheap check per new flag: every other test in this file would
    fail anyway if these are missing, but for the confusing argparse
    'unrecognized arguments' reason rather than this clear one."""

    def _assert_recognised(self, args: list[str]):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        result = run_fake_receiver(fake_root, args, env=_minimal_env())
        combined = result.stdout + result.stderr
        self.assertNotIn(
            "unrecognized arguments", combined,
            f"{args} is not yet recognised -- see PT-86. Got: {combined!r}",
        )

    def test_session_id_and_session_pid_flags_are_recognised(self):
        self._assert_recognised(["--ensure-running", "--session-id", "s1", "--session-pid", "1"])

    def test_session_ended_flag_is_recognised(self):
        self._assert_recognised(["--session-ended", "s1"])

    def test_grace_period_seconds_flag_is_recognised(self):
        self._assert_recognised(["--status", "--grace-period-seconds", "0.3"])


# --------------------------------------------------------------------------
# AC1: two fake project roots, fake session ids.
# --------------------------------------------------------------------------

class LastSessionSelfStopTests(unittest.TestCase):
    """The four scenarios AC1 names verbatim: one start/end exits after
    grace with a flush; two starts/one end stays up; a dead session id is
    reaped; a start inside the grace window cancels the exit."""

    GRACE = 0.4

    def test_one_session_start_end_exits_after_grace_period_with_a_flush(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)

        start = run_fake_receiver(
            fake_root,
            ["--ensure-running", "--session-id", "s1", "--session-pid", str(os.getpid()),
             "--grace-period-seconds", str(self.GRACE)],
            env=env,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        status = _wait_for_status_running(fake_root, env)
        self.assertEqual(status.returncode, 0, f"receiver must be running after the only session starts -- {status.stdout!r} {status.stderr!r}")
        self.assertIn("sessions: 1", status.stdout, status.stdout)

        end = run_fake_receiver(fake_root, ["--session-ended", "s1"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        # Must NOT have exited immediately -- the whole point of the
        # grace period is that the exporter's final batch needs time.
        immediate = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(
            immediate.returncode, 0,
            f"the receiver must still be running immediately after the last SessionEnd -- exit happens only "
            f"after the grace period, got {immediate.stdout!r} {immediate.stderr!r}",
        )

        stopped = _wait_for_status_not_running(fake_root, env, timeout=self.GRACE + 4.0)
        self.assertEqual(
            stopped.returncode, 1,
            f"the receiver must exit on its own once the grace period elapses after the last session ended -- "
            f"stdout={stopped.stdout!r} stderr={stopped.stderr!r}",
        )
        self.assertFalse(_pidfile_path(fake_root).exists(), "the pidfile must be removed on self-stop")

    def test_two_starts_one_end_still_running(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)

        r1 = run_fake_receiver(
            fake_root,
            ["--ensure-running", "--session-id", "s1", "--session-pid", str(os.getpid()),
             "--grace-period-seconds", str(self.GRACE)],
            env=env,
        )
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        _wait_for_status_running(fake_root, env)

        r2 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "s2", "--session-pid", str(os.getpid())], env=env)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertIn("sessions: 2", status.stdout, status.stdout)

        end = run_fake_receiver(fake_root, ["--session-ended", "s1"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        # Wait well past what the grace period would have been if this
        # were the LAST session -- it must never exit while s2 is live.
        time.sleep(self.GRACE + 1.0)
        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(
            status.returncode, 0,
            f"a second live session must keep the receiver running -- {status.stdout!r} {status.stderr!r}",
        )
        self.assertIn("sessions: 1", status.stdout, status.stdout)

    def test_a_start_during_the_grace_window_cancels_the_exit(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)
        grace = 1.0

        r1 = run_fake_receiver(
            fake_root,
            ["--ensure-running", "--session-id", "s1", "--session-pid", str(os.getpid()),
             "--grace-period-seconds", str(grace)],
            env=env,
        )
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        _wait_for_status_running(fake_root, env)

        end = run_fake_receiver(fake_root, ["--session-ended", "s1"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        # Well inside the grace window -- a fresh session starts.
        time.sleep(grace * 0.3)
        r2 = run_fake_receiver(fake_root, ["--ensure-running", "--session-id", "s2", "--session-pid", str(os.getpid())], env=env)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

        # Wait well past the ORIGINAL grace deadline -- if the new
        # session hadn't cancelled the shutdown, this would have exited.
        time.sleep(grace + 1.0)
        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(
            status.returncode, 0,
            f"a session starting inside the grace window must cancel the pending shutdown -- "
            f"{status.stdout!r} {status.stderr!r}",
        )
        self.assertIn("sessions: 1", status.stdout, status.stdout)


class LivenessReapTests(unittest.TestCase):
    """AC1's crash backstop: a session id whose process is gone must be
    reaped by the liveness probe, which the ruling pins to run "on every
    decrement and at each flush" -- exercised here via a decrement of a
    SIBLING (still-live) session, so the daemon never shuts down and the
    reap is the only thing under test."""

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
        self.assertIn("session gone: dead", status.stdout, f"--status must report the dead pid's liveness honestly before it's reaped -- {status.stdout!r}")

        # Decrementing "throwaway" (still leaves "alive" live, so the
        # daemon does not shut down) must trip the liveness probe over
        # every OTHER recorded session too, reaping "gone".
        end = run_fake_receiver(fake_root, ["--session-ended", "throwaway"], env=env)
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(
            status.returncode, 0,
            f"the receiver must still be running -- 'alive' never ended -- {status.stdout!r} {status.stderr!r}",
        )
        self.assertIn("sessions: 1", status.stdout, f"the dead 'gone' session must have been reaped by the liveness probe -- {status.stdout!r}")
        self.assertNotIn("gone", status.stdout, f"a reaped session id must no longer be listed at all -- {status.stdout!r}")


# --------------------------------------------------------------------------
# AC2: the final flush provably contains a datapoint received during grace.
# --------------------------------------------------------------------------

class GraceWindowFlushContentTests(unittest.TestCase):
    """basic.json's fingerprint (cairn.issue: PT-95, an `input`-type
    datapoint of value 100) sent DURING the grace window must survive
    into the flush that happens at self-stop -- proving the daemon keeps
    accepting real exports for the whole grace window, not just idling
    until the timer fires."""

    def test_a_datapoint_posted_during_the_grace_window_lands_in_the_final_flush(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _base_env(port)
        self.addCleanup(_stop_fake_receiver, fake_root, env)
        grace = 0.6

        start = run_fake_receiver(
            fake_root,
            ["--ensure-running", "--session-id", "s1", "--session-pid", str(os.getpid()),
             "--grace-period-seconds", str(grace)],
            env=env,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
        _wait_for_status_running(fake_root, env)

        end = run_fake_receiver(fake_root, ["--session-ended", "s1"], env=env)
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
    """AC3: 'SessionEnd hook line ... same shape and exit-0 discipline as
    the SessionStart line; no stderr redirect.'

    Judgment call, flagged (open question sent to implementation-lead
    2026-09-04, unresolved as of writing this file): the exact
    env-var/stdin field Claude Code hands a SessionEnd hook for the
    ending session's id isn't pinned yet in this codebase. Rather than
    guess a specific variable name and risk a wrong-reason red/green,
    these assertions check only the shape this ticket's ruling actually
    specifies verbatim -- the command exists, invokes --session-ended,
    drops any stderr-to-/dev/null merge, and still unconditionally exits
    0. Whatever the real id-plumbing turns out to be is implementation-
    lead's to land; if it changes the command's shape in a way that
    breaks these greps, that's this test doing its job, not a false
    failure -- update the assertions together with the hook line, not
    around it.
    """

    def _hook_command(self) -> str:
        doc = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        for entry in doc.get("hooks", {}).get("SessionEnd", []):
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                if "otel_receiver.py" in command and "--session-ended" in command:
                    return command
        self.fail(f"no SessionEnd hook command mentions otel_receiver.py --session-ended in {SETTINGS_PATH}")

    def test_a_session_end_hook_entry_invoking_session_ended_exists(self):
        # _hook_command's own self.fail is the assertion here -- calling
        # it at all is the test.
        self._hook_command()

    def test_stderr_is_not_redirected_to_dev_null(self):
        command = self._hook_command()
        self.assertNotIn(
            "2>&1", command,
            f"the receiver's stderr must not be merged into a discarded stdout redirect, same as the SessionStart line -- got: {command!r}",
        )

    def test_the_hook_still_unconditionally_exits_zero(self):
        command = self._hook_command()
        self.assertIn(
            "exit 0", command,
            f"a SessionEnd hook must never fail session teardown over telemetry, same discipline as SessionStart -- got: {command!r}",
        )

    def test_guards_on_the_script_existing_same_as_session_start(self):
        command = self._hook_command()
        self.assertIn(
            "otel_receiver.py", command.split("&&")[0] if "&&" in command else command,
            f"same defensive guard pattern as the SessionStart line ('[ -f ... ] || exit 0') -- got: {command!r}",
        )


if __name__ == "__main__":
    unittest.main()
