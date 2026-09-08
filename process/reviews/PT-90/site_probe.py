"""PT-90 addendum: which shutdown_deadline=None site actually fires when a
session registers during an armed grace window? Patches a COPY of the
receiver inside a throwaway fake engine root (never the real file), marking
each of the three sites, then runs the AC2 scenario."""
import os, sys, time, unittest
CAIRN = "/Users/mosko/Projects/project_template/scripts/cairn"
sys.path.insert(0, CAIRN + "/tests")
sys.path.insert(0, CAIRN)
import test_otel_receiver_self_stop as T

GRACE = 0.4


class Case(unittest.TestCase):
    def runTest(self):
        pass


MARKS = [
    ("                ever_nonempty = True\n                shutdown_deadline = None\n",
     "                ever_nonempty = True\n"
     "                print(f'SITE-1800 armed={shutdown_deadline is not None}', file=sys.stderr)\n"
     "                shutdown_deadline = None\n"),
    ("            if live_session_ids(sessions_dir):\n                shutdown_deadline = None\n                continue\n",
     "            if live_session_ids(sessions_dir):\n"
     "                print(f'SITE-1818 armed={shutdown_deadline is not None}', file=sys.stderr)\n"
     "                shutdown_deadline = None\n                continue\n"),
    ("                shutdown_deadline = None\n                continue\n            # Nothing after this aborts",
     "                print(f'SITE-1829 armed={shutdown_deadline is not None}', file=sys.stderr)\n"
     "                shutdown_deadline = None\n                continue\n            # Nothing after this aborts"),
]

tc = Case()
port = T._free_port()
root = T.make_fake_engine_root(tc, otel_port=port)
script = root / "scripts" / "cairn" / "otel_receiver.py"
src = script.read_text()
for old, new in MARKS:
    if old not in src:
        print("PATCH MISS:", repr(old[:60]))
        sys.exit(1)
    src = src.replace(old, new, 1)
script.write_text(src)
print("all three sites patched in the COPY")

env = T._base_env(port)
T.run_fake_receiver(root, ["--ensure-running", "--session-id", "s1",
                           "--session-pid", str(os.getpid()),
                           "--grace-period-seconds", str(GRACE)], env=env)
T._wait_for_status_running(root, env)
T.run_fake_receiver(root, ["--session-ended", "s1"], env=env)
time.sleep(GRACE * 0.6)          # inside the armed window
T.run_fake_receiver(root, ["--ensure-running", "--session-id", "s2",
                           "--session-pid", str(os.getpid())], env=env)
time.sleep(GRACE + 1.5)
still = T.run_fake_receiver(root, ["--status"], env=env).returncode == 0
log = (root / "process" / "cairn" / "metrics" / "otel_receiver.log")
lines = log.read_text().splitlines() if log.exists() else []
print("receiver still running:", still)
print("logfile lines:", len(lines))
for ln in lines:
    print("   |", ln[:120])
try:
    T._stop_fake_receiver(root, env)
except Exception:
    pass
