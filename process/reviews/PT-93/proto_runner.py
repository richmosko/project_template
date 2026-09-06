"""Prototype file-level parallel runner (PT-93 measurement only)."""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TESTS = Path(__file__).resolve()
CAIRN = Path("/Users/mosko/Projects/project_template/scripts/cairn")
files = sorted(p.name for p in (CAIRN / "tests").glob("test_*.py"))
workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
order = sys.argv[2] if len(sys.argv) > 2 else "name"

if order == "longest":
    prev = json.loads(Path(sys.argv[3]).read_text())
    files.sort(key=lambda f: -prev.get(f, 0.0))

SUMMARY = re.compile(r"^(OK|FAILED)")
RAN = re.compile(r"^Ran (\d+) tests? in")


def run(name):
    t0 = time.time()
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", name],
                       cwd=CAIRN, capture_output=True, text=True)
    dt = time.time() - t0
    err = p.stderr
    ran = 0
    m = RAN.search(err) if False else None
    for line in err.splitlines():
        mm = RAN.match(line)
        if mm:
            ran = int(mm.group(1))
    skipped = 0
    for line in err.splitlines():
        s = re.search(r"skipped=(\d+)", line)
        if s:
            skipped += int(s.group(1))
    return name, dt, p.returncode, ran, skipped


t0 = time.time()
with ThreadPoolExecutor(max_workers=workers) as ex:
    results = list(ex.map(run, files))
wall = time.time() - t0

times = {n: round(d, 2) for n, d, _, _, _ in results}
total_tests = sum(r[3] for r in results)
total_skip = sum(r[4] for r in results)
fails = [r[0] for r in results if r[2] != 0]
out = {"workers": workers, "order": order, "wall": round(wall, 2), "tests": total_tests,
       "skipped": total_skip, "failed_files": fails, "times": times}
print(json.dumps(out, indent=1))
