"""PT-90 gate-1 baseline: what does the receiver's own logfile contain today
for (a) a start/end self-stop and (b) a start that cancels an armed grace
window? Uses the test module's own helpers against a throwaway fake engine
root, so the real checkout's log and registry are never touched."""
import os, sys, time, unittest
CAIRN = "/Users/mosko/Projects/project_template/scripts/cairn"
sys.path.insert(0, CAIRN + "/tests")
sys.path.insert(0, CAIRN)
import test_otel_receiver_self_stop as T

GRACE = 0.4


class Case(unittest.TestCase):
    def runTest(self):
        pass


def log_lines(root):
    p = root / "process" / "cairn" / "metrics" / "otel_receiver.log"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").splitlines()


def scenario(name, cancel):
    tc = Case()
    port = T._free_port()
    root = T.make_fake_engine_root(tc, otel_port=port)
    env = T._base_env(port)
    T.run_fake_receiver(root, ["--ensure-running", "--session-id", "s1",
                               "--session-pid", str(os.getpid()),
                               "--grace-period-seconds", str(GRACE)], env=env)
    T._wait_for_status_running(root, env)
    T.run_fake_receiver(root, ["--session-ended", "s1"], env=env)
    if cancel:
        time.sleep(GRACE * 0.3)
        T.run_fake_receiver(root, ["--ensure-running", "--session-id", "s2",
                                   "--session-pid", str(os.getpid())], env=env)
        time.sleep(GRACE + 1.0)
        running = T.run_fake_receiver(root, ["--status"], env=env).returncode == 0
    else:
        T._wait_for_status_not_running(root, env, timeout=GRACE + 4.0)
        running = False
    lines = log_lines(root)
    print(f"--- {name}: still running={running}")
    print(f"    logfile lines = {len(lines) if lines is not None else 'NO FILE'}")
    for ln in (lines or []):
        print("      |", ln[:150])
    try:
        T._stop_fake_receiver(root, env)
    except Exception:
        pass
    for fn in getattr(tc, "_cleanups", []):
        pass


scenario("A self-stop (start, end, grace elapses)", cancel=False)
scenario("B cancel  (start, end, re-register inside grace)", cancel=True)
