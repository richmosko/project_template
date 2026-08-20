"""Shared test scaffolding: sys.path shim, fixture-copying.

Every test module imports from here first so that `import cairn` works
regardless of the caller's cwd, and so that no test ever mutates the
checked-in fixtures in tests/fixtures/ in place.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
CAIRN_DIR = TESTS_DIR.parent  # scripts/cairn/
FIXTURES_DIR = TESTS_DIR / "fixtures"
FIXTURE_DATA_DIR = FIXTURES_DIR / "process" / "cairn"
CAIRN_BIN = CAIRN_DIR / "cairn"  # bash shim, invoked by CLI subprocess tests
CAIRN_PY = CAIRN_DIR / "cairn.py"

if str(CAIRN_DIR) not in sys.path:
    sys.path.insert(0, str(CAIRN_DIR))


def copy_fixture_data_dir(dest_root: Path) -> Path:
    """Copy the checked-in fixtures/process/cairn tree into dest_root.

    Returns the path to the copy (a `process/cairn`-shaped data_dir). Tests
    must never write into FIXTURE_DATA_DIR directly -- always operate on
    this copy so the suite is order-independent and repeatable.
    """
    dest = Path(dest_root) / "cairn"
    shutil.copytree(FIXTURE_DATA_DIR, dest)
    return dest


def make_tmp_data_dir(testcase) -> Path:
    """Create a fresh temp copy of the fixture data dir, auto-cleaned up.

    `testcase` is the unittest.TestCase instance -- cleanup is registered
    via addCleanup so it runs even on failure.
    """
    tmp = tempfile.mkdtemp(prefix="cairn-test-")
    testcase.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return copy_fixture_data_dir(Path(tmp))


def make_empty_tmp_dir(testcase) -> Path:
    """A bare temp dir with no cairn tree at all, for CLI-bootstrap-style tests."""
    tmp = tempfile.mkdtemp(prefix="cairn-test-empty-")
    testcase.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return Path(tmp)
