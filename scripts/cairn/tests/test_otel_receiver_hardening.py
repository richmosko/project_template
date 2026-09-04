"""PT-81 failing acceptance tests: `otel_receiver.py`'s three hardening
rulings (process/cairn/issues/PT-81.md, H1-H3), each verified "by
construction with two fake project roots" per AC1.

## Why "fake project roots" means copying the engine, not `--repo-root`

`ensure_running`/`--status` (and the bare-invocation `serve()` path the
detached child runs) all derive `repo_root` from
`backfill_tokens._repo_root()` -- `Path(__file__).resolve().parent.parent
.parent`, i.e. wherever *this script itself* lives on disk. `--repo-root`
exists but only ever steers `_current_branch`'s branch read (see
`otel_receiver.py`'s own comment above that line); it does NOT redirect
`repo_root` for `--ensure-running`/`--status`, and there is no `cwd`
dependency to exploit either. So the only way to drive these two flags
against an isolated, throwaway tracker is to give the CLI a throwaway
*copy of the engine* to run: `<fake_root>/scripts/cairn/{otel_receiver,
backfill_tokens,cairn}.py` + `<fake_root>/process/cairn/config.yml`. That
copy is invoked as `python3 <fake_root>/scripts/cairn/otel_receiver.py
--ensure-running`, exactly the shape the SessionStart hook itself uses,
just anchored somewhere disposable. This also means every test here
exercises the REAL hook-invocation code path end to end, not a mocked
substitute.

## The unset-`OTEL_EXPORTER_OTLP_ENDPOINT` branch of H3

Settled by empirical check (team-lead relayed the result: `claude -p`
with telemetry on and the endpoint variable unset genuinely POSTs to
`127.0.0.1:4318`, a real scratch-sink capture, confirming the OTel spec's
documented fallback is what Claude Code's exporter actually does, not
just what the spec says it should do). The architect's amendment
(4c1b751) stands: an unset endpoint is NOT "nothing to compare" -- it
resolves to the OTLP protocol default, 4318, same as any other endpoint
value would.

`UnsetEndpointFallbackTests` covers this. The one true-4318 assertion
(`test_effective_endpoint_port_defaults_to_the_real_otlp_default_4318`)
is a pure-function check against `otel_receiver._effective_endpoint_port`
directly, no socket involved. The two integration-level cases (does
`ensure_running` actually start/refuse based on that default) do NOT
bind the real port 4318 -- per team-lead's "use scratch ports in every
test regardless" instruction, they run against a FAKE engine copy whose
own `DEFAULT_OTEL_PORT` constant has been text-patched to a scratch
port before invocation (`make_fake_engine_root_with_default_port`), so
the fallback MECHANISM is proven without ever touching the one port a
real, concurrently-running Claude Code session in this same repo might
legitimately be exporting real telemetry to at the same moment.

## What's covered

- H1 (`TelemetryGateTests`): `CLAUDE_CODE_ENABLE_TELEMETRY` unset or
  falsy -> `ensure_running` declines, spawns nothing, `--ensure-running`
  still exits 0.
- H2 (`BindVerificationTests`): a port already LISTENING (a live rival
  receiver) is refused pre-spawn, naming the port, with no subprocess
  ever spawned (no logfile write) -- vs. a port that is bound-but-
  unreachable (nothing "listening" by the pre-check's own probe, so a
  spawn IS attempted) whose child then fails its own bind and is
  reported as "spawned but never came up", a DIFFERENT message than the
  held-port case. These two must never collapse to the same text, or
  an operator reading stderr can't tell "someone else already has this"
  from "something is actually broken here".
- H3, settled half (`PortEndpointAgreementTests`): `otel_port` vs. the
  receiver's own inherited `OTEL_EXPORTER_OTLP_ENDPOINT`, when BOTH are
  present -- mismatch refuses naming both, match starts.
- H3, unset-endpoint half (`UnsetEndpointFallbackTests`): an unset
  `OTEL_EXPORTER_OTLP_ENDPOINT` resolves to the OTLP default port 4318
  for comparison purposes, not "nothing to compare".
- AC2 (`StatusCommandTests`): `--status` reports running/port/out-file,
  exit 0 running / 1 not, and its own `repo_root` resolution never
  leaks into the real checkout's actual data file.
- AC3, hook half (`SessionStartHookStderrTests`): `.claude/settings.json`'s
  SessionStart line no longer redirects the receiver's stderr to
  /dev/null, while still unconditionally exiting 0.
"""
from __future__ import annotations

import contextlib
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


def make_fake_engine_root_with_default_port(testcase, default_port: int, otel_port: Optional[int] = None) -> Path:
    """Same as `make_fake_engine_root`, plus one text patch to the COPIED
    otel_receiver.py: `DEFAULT_OTEL_PORT = 4318` -> `DEFAULT_OTEL_PORT =
    <default_port>`. Exists solely so `UnsetEndpointFallbackTests` can
    prove the "unset endpoint falls back to the default port" MECHANISM
    without ever binding the real, reserved port 4318 -- which, in this
    very repo, a concurrently-running Claude Code session's own real
    OTel exporter may legitimately be posting to at any moment. The
    real literal value 4318 is pinned separately, by a pure-function
    test with no I/O at all (see `_effective_endpoint_port` above the
    class in question)."""
    root = make_fake_engine_root(testcase, otel_port=otel_port)
    script = root / "scripts" / "cairn" / "otel_receiver.py"
    original = script.read_text(encoding="utf-8")
    patched = original.replace("DEFAULT_OTEL_PORT = 4318", f"DEFAULT_OTEL_PORT = {default_port}", 1)
    if patched == original:
        testcase.fail("DEFAULT_OTEL_PORT = 4318 not found verbatim in the copied otel_receiver.py -- patch target moved")
    script.write_text(patched, encoding="utf-8")
    return root


def _minimal_env(**overrides: str) -> dict:
    """A from-scratch env, never `os.environ` inherited wholesale -- this
    is itself a live Claude Code session, which per the architect's own
    2026-09-03 comment already has telemetry enabled in ITS environment
    (settings.local.json or shell, not settings.json). Inheriting
    `os.environ` into these subprocesses would make every "telemetry
    off" test flaky-or-wrong depending on who is running the suite."""
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


def _logfile_path(fake_root: Path) -> Path:
    return fake_root / "process" / "cairn" / "metrics" / "otel_receiver.log"


def _stop_fake_receiver(fake_root: Path, env: dict) -> None:
    """Cleanup: signal a real stop, then force-kill via the pidfile as a
    safety net -- a test that fails mid-assertion must never leak a
    detached background process into the rest of the suite run."""
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


@contextlib.contextmanager
def held_listening_port(port: int):
    """Simulates a DIFFERENT project's already-running receiver: a real
    socket actively accepting connections on `port`. This is what
    `_port_is_listening`'s own connect-probe detects."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        yield s
    finally:
        s.close()


@contextlib.contextmanager
def held_unlistening_port(port: int):
    """Simulates a port that is unavailable to bind but NOT accepting
    connections -- deliberately NOT `listen()`ing. `_port_is_listening`'s
    connect-probe sees this as free (connection refused), so
    `ensure_running`'s pre-spawn check does not trip; the SPAWNED CHILD's
    own `bind()` call is what fails here, with a real `OSError: Address
    already in use` -- a portable (no root needed, unlike a privileged
    low port), deterministic way to force the genuine "spawned but never
    came up" path without racing a timing window."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        yield s
    finally:
        s.close()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_status_running(fake_root: Path, env: dict, timeout: float = 5.0) -> subprocess.CompletedProcess:
    """Poll `--status` until it reports running (exit 0) or `timeout`
    elapses -- `ensure_running`'s own post-spawn wait window is short
    (~0.5s) but this gives the child process a little more slack than
    that under load without turning a real failure into a 5s hang for no
    reason (returns the LAST observed result either way, so a genuine
    failure's assertion message still shows real stdout/stderr)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = run_fake_receiver(fake_root, ["--status"], env=env)
        if last.returncode == 0:
            return last
        time.sleep(0.1)
    return last


class OtelReceiverStatusFlagPresenceGuard(unittest.TestCase):
    """One cheap, unambiguous first-to-fail check: AC2 requires a new
    `--status` flag that does not exist in the pre-PT-81 script at all.
    Every other StatusCommandTests assertion would fail anyway if it's
    missing, but for a confusing reason (argparse's own "unrecognized
    arguments" rejection) rather than this clear one."""

    def test_status_flag_is_a_recognised_argument(self):
        fake_root = make_fake_engine_root(self, otel_port=_free_port())
        result = run_fake_receiver(fake_root, ["--status"], env=_minimal_env())
        combined = result.stdout + result.stderr
        self.assertNotIn(
            "unrecognized arguments", combined,
            f"--status is not yet a recognised flag -- see PT-81 AC2. Got: {combined!r}",
        )


class TelemetryGateTests(unittest.TestCase):
    """H1: `ensure_running` requires `CLAUDE_CODE_ENABLE_TELEMETRY`
    truthy in its own environment; otherwise it declines quietly,
    spawns nothing, and `--ensure-running` still exits 0 (a SessionStart
    hook must never fail a session over telemetry)."""

    def test_telemetry_unset_declines_and_spawns_nothing(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _minimal_env()  # no CLAUDE_CODE_ENABLE_TELEMETRY key at all
        result = run_fake_receiver(fake_root, ["--ensure-running"], env=env)
        self.assertEqual(result.returncode, 0, "the hook must still exit 0 even when it declines")

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(status.returncode, 1, f"nothing should be running -- stdout={status.stdout!r}")
        self.assertIn("running: False", status.stdout, status.stdout)
        self.assertFalse(_logfile_path(fake_root).exists(), "declining before the telemetry gate must never spawn a child at all")

    def test_telemetry_falsy_value_declines(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _minimal_env(CLAUDE_CODE_ENABLE_TELEMETRY="0")
        result = run_fake_receiver(fake_root, ["--ensure-running"], env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(status.returncode, 1, status.stdout)
        self.assertFalse(_logfile_path(fake_root).exists(), "a falsy telemetry value must decline exactly like an unset one")


class BindVerificationTests(unittest.TestCase):
    """H2: distinguish "a different process already holds this port"
    from "we spawned a child but it never came up" -- two different
    refusals, two different messages, only one of which ever attempts a
    spawn at all."""

    def test_a_port_already_held_by_a_listening_process_declines_without_spawning(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _minimal_env(
            CLAUDE_CODE_ENABLE_TELEMETRY="1",
            OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{port}",
        )
        with held_listening_port(port):
            result = run_fake_receiver(fake_root, ["--ensure-running"], env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn(str(port), combined, f"the refusal must name the held port -- got: {combined!r}")
        self.assertFalse(_logfile_path(fake_root).exists(), "a port already held by a LIVE listener must be refused before any spawn is attempted")

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(status.returncode, 1, "no pidfile was ever written by us, so --status must report not-running even though the port itself is occupied")

    def test_a_spawn_that_never_binds_is_reported_distinctly_from_a_held_port(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _minimal_env(
            CLAUDE_CODE_ENABLE_TELEMETRY="1",
            OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{port}",
        )
        with held_unlistening_port(port):
            result = run_fake_receiver(fake_root, ["--ensure-running"], env=env)
            combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertTrue(_logfile_path(fake_root).exists(), "a port that is merely bound (not listening) must not trip the pre-spawn probe -- a spawn attempt must actually happen")

        held_message = "already held"
        self.assertNotIn(
            held_message, combined.lower().replace("-", " "),
            f"a genuine bind failure must not be reported with the SAME wording as an already-listening rival -- got: {combined!r}",
        )
        self.assertIn(str(port), combined, f"the message must still name the port -- got: {combined!r}")

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(status.returncode, 1, "a child that never bound must never be reported as running")


class PortEndpointAgreementTests(unittest.TestCase):
    """H3, settled half: when `OTEL_EXPORTER_OTLP_ENDPOINT` IS set, its
    port must agree with `otel_port`. The unset-endpoint half is
    `UnsetEndpointFallbackTests`, just below."""

    def test_a_port_endpoint_mismatch_refuses_naming_both(self):
        otel_port = _free_port()
        endpoint_port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=otel_port)
        env = _minimal_env(
            CLAUDE_CODE_ENABLE_TELEMETRY="1",
            OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{endpoint_port}",
        )
        result = run_fake_receiver(fake_root, ["--ensure-running"], env=env)
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn(str(otel_port), combined, f"must name otel_port -- got: {combined!r}")
        self.assertIn(str(endpoint_port), combined, f"must name the endpoint's port -- got: {combined!r}")
        self.assertFalse(_logfile_path(fake_root).exists(), "a mismatch must refuse before ever spawning")

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(status.returncode, 1, "a refused mismatch must never be reported as running")

    def test_matching_port_and_endpoint_starts_the_receiver(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _minimal_env(
            CLAUDE_CODE_ENABLE_TELEMETRY="1",
            OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{port}",
        )
        self.addCleanup(_stop_fake_receiver, fake_root, env)
        result = run_fake_receiver(fake_root, ["--ensure-running"], env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        status = _wait_for_status_running(fake_root, env)
        self.assertEqual(status.returncode, 0, f"a matching port/endpoint pair must start the receiver -- stdout={status.stdout!r} stderr={status.stderr!r}")
        self.assertIn("running: True", status.stdout, status.stdout)
        self.assertIn(f"port: {port}", status.stdout, status.stdout)


class UnsetEndpointFallbackTests(unittest.TestCase):
    """H3, unset-endpoint half (architect's amendment 4c1b751, empirically
    confirmed): an unset `OTEL_EXPORTER_OTLP_ENDPOINT` is not "nothing to
    compare" -- Claude Code's exporter genuinely falls back to posting at
    the OTLP protocol default, 127.0.0.1:4318, so `otel_port` must be
    compared against that default too, or a project with `otel_port` set
    to anything else silently gets exactly H3's contamination shape with
    telemetry nominally "on" the whole time."""

    def test_effective_endpoint_port_defaults_to_the_real_otlp_default_4318(self):
        # Pure-function check against the REAL, committed (well, WIP but
        # loaded from this actual checkout, not a fake copy) otel_receiver
        # module -- no socket, no subprocess. Pins the literal value the
        # empirical check confirmed, independent of whatever scratch
        # value the integration tests below patch it to.
        self.assertTrue(
            hasattr(otel_receiver, "_effective_endpoint_port"),
            "otel_receiver._effective_endpoint_port does not exist yet -- PT-81 H3's "
            "unset-endpoint fallback (architect amendment 4c1b751) is unimplemented",
        )
        self.assertEqual(otel_receiver._effective_endpoint_port(None), 4318, "an unset endpoint must fall back to the real OTLP default, 4318")
        self.assertEqual(otel_receiver._effective_endpoint_port(""), 4318, "an empty endpoint must fall back the same way as a genuinely unset one")

    def test_unset_endpoint_matching_the_default_port_starts(self):
        # Scratch default, not the real 4318 -- see module docstring and
        # make_fake_engine_root_with_default_port's own docstring for why.
        scratch_default = _free_port()
        fake_root = make_fake_engine_root_with_default_port(self, default_port=scratch_default, otel_port=scratch_default)
        env = _minimal_env(CLAUDE_CODE_ENABLE_TELEMETRY="1")  # OTEL_EXPORTER_OTLP_ENDPOINT deliberately absent
        self.addCleanup(_stop_fake_receiver, fake_root, env)

        result = run_fake_receiver(fake_root, ["--ensure-running"], env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        status = _wait_for_status_running(fake_root, env)
        self.assertEqual(
            status.returncode, 0,
            f"otel_port matching the (patched) OTLP default must start the receiver even with the endpoint var unset -- stdout={status.stdout!r} stderr={status.stderr!r}",
        )
        self.assertIn("running: True", status.stdout, status.stdout)

    def test_unset_endpoint_not_matching_the_default_port_refuses_naming_both_and_the_fallback(self):
        scratch_default = _free_port()
        scratch_otel_port = _free_port()
        fake_root = make_fake_engine_root_with_default_port(self, default_port=scratch_default, otel_port=scratch_otel_port)
        env = _minimal_env(CLAUDE_CODE_ENABLE_TELEMETRY="1")  # endpoint deliberately absent

        result = run_fake_receiver(fake_root, ["--ensure-running"], env=env)
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn(str(scratch_otel_port), combined, f"must name otel_port -- got: {combined!r}")
        self.assertIn(
            str(scratch_default), combined,
            f"must name the (fallback) default port the unset endpoint effectively resolves to -- got: {combined!r}",
        )
        self.assertFalse(_logfile_path(fake_root).exists(), "an unset-endpoint mismatch against the default must refuse before ever spawning, exactly like an explicit mismatch")

        status = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(status.returncode, 1, "a refused unset-endpoint mismatch must never be reported as running")


class StatusCommandTests(unittest.TestCase):
    """AC2: `--status` reports running/port/out-file, exit 0 running / 1
    not -- and its own repo_root resolution (same `__file__`-anchored
    derivation as everything else in this script) must never leak into
    the REAL checkout's actual committed data file."""

    def test_status_when_nothing_is_running_names_the_configured_port_and_out_file(self):
        port = _free_port()
        fake_root = make_fake_engine_root(self, otel_port=port)
        env = _minimal_env()
        result = run_fake_receiver(fake_root, ["--status"], env=env)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("running: False", result.stdout, result.stdout)
        self.assertIn(f"port: {port}", result.stdout, result.stdout)
        self.assertIn("token-usage.jsonl", result.stdout, result.stdout)
        self.assertIn(
            str(fake_root), result.stdout,
            f"--status's reported out-file must be anchored under the FAKE root, never the real checkout -- got: {result.stdout!r}",
        )
        self.assertNotEqual(
            Path(result.stdout.split("out-file: ", 1)[-1].strip()), REAL_TOKEN_USAGE_PATH,
            "a fake project's --status must never resolve to this repo's real committed token-usage.jsonl",
        )


class SessionStartHookStderrTests(unittest.TestCase):
    """AC3, hook half: the SessionStart line must keep stderr (drop the
    `2>&1`-into-`/dev/null` merge) while still unconditionally exiting 0
    -- a source-text guard, scoped to the one command line, not the
    whole settings file."""

    def _hook_command(self) -> str:
        doc = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        for entry in doc.get("hooks", {}).get("SessionStart", []):
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                if "otel_receiver.py" in command and "--ensure-running" in command:
                    return command
        self.fail(f"no SessionStart hook command mentions otel_receiver.py --ensure-running in {SETTINGS_PATH}")

    def test_stderr_is_no_longer_redirected_to_dev_null(self):
        command = self._hook_command()
        self.assertNotIn(
            "2>&1", command,
            f"the receiver's stderr must no longer be merged into the (discarded) stdout redirect -- got: {command!r}",
        )

    def test_the_hook_still_unconditionally_exits_zero(self):
        command = self._hook_command()
        self.assertIn(
            "exit 0", command,
            f"a SessionStart hook must never fail a session over telemetry -- got: {command!r}",
        )


if __name__ == "__main__":
    unittest.main()
