"""Tests for cairn.allocate_and_create_issue: atomic, collision-free ID
allocation over issues/ AND archive/ combined.
"""
from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed

import helpers  # noqa: F401

import cairn


def base_fields(title: str) -> dict:
    return {
        "title": title,
        "status": "backlog",
        "milestone": None,
        "parent": None,
        "assignee": None,
        "labels": [],
        "priority": None,
        "pr": None,
    }


class AllocationTests(unittest.TestCase):
    def test_next_id_is_max_plus_one_over_issues_and_archive(self):
        # Fixture: issues/ has PT-1, PT-3, PT-4 (max 4); archive/ has PT-9.
        # Archived IDs are never reused, so the next id must be PT-10, not PT-5.
        data_dir = helpers.make_tmp_data_dir(self)
        path = cairn.allocate_and_create_issue(data_dir, base_fields("New issue"))
        self.assertEqual(path.name, "PT-10.md")
        self.assertTrue(path.exists())
        frontmatter, _ = cairn.parse_frontmatter(path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["id"], "PT-10")

    def test_sequential_allocations_increment(self):
        data_dir = helpers.make_tmp_data_dir(self)
        first = cairn.allocate_and_create_issue(data_dir, base_fields("One"))
        second = cairn.allocate_and_create_issue(data_dir, base_fields("Two"))
        self.assertEqual(first.name, "PT-10.md")
        self.assertEqual(second.name, "PT-11.md")

    def test_created_file_has_id_matching_filename(self):
        data_dir = helpers.make_tmp_data_dir(self)
        path = cairn.allocate_and_create_issue(data_dir, base_fields("New issue"))
        frontmatter, _ = cairn.parse_frontmatter(path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["id"] + ".md", path.name)

    def test_created_and_updated_default_to_today(self):
        import datetime

        data_dir = helpers.make_tmp_data_dir(self)
        path = cairn.allocate_and_create_issue(data_dir, base_fields("New issue"))
        frontmatter, _ = cairn.parse_frontmatter(path.read_text(encoding="utf-8"))
        today = datetime.date.today().isoformat()
        self.assertEqual(frontmatter["created"], today)
        self.assertEqual(frontmatter["updated"], today)

    def test_collision_forces_retry_to_next_id(self):
        # Pre-create the file the naive max+1 computation would target, to
        # force allocate_and_create_issue to detect the O_EXCL collision and
        # retry rather than overwrite it.
        data_dir = helpers.make_tmp_data_dir(self)
        (data_dir / "issues" / "PT-10.md").write_text(
            "---\nid: PT-10\ntitle: Pre-existing\nstatus: todo\nmilestone: null\n"
            "parent: null\nassignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nDo not clobber me.\n",
            encoding="utf-8",
        )
        path = cairn.allocate_and_create_issue(data_dir, base_fields("New issue"))
        self.assertEqual(path.name, "PT-11.md")
        preexisting_text = (data_dir / "issues" / "PT-10.md").read_text(encoding="utf-8")
        self.assertIn("Do not clobber me.", preexisting_text)

    def test_allocation_on_directory_with_no_existing_issues_starts_at_one(self):
        empty = helpers.make_empty_tmp_dir(self)
        data_dir = empty / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        path = cairn.allocate_and_create_issue(data_dir, base_fields("First ever"))
        self.assertEqual(path.name, "PT-1.md")


class ConcurrentAllocationTests(unittest.TestCase):
    """Genuine concurrency test for the O_CREAT|O_EXCL race the spec describes:
    two callers computing max+1 concurrently must not both write the same
    filename.

    Threads, not processes: the race under test is a filesystem syscall race
    (open() with O_CREAT|O_EXCL), which real OS threads exercise correctly --
    the GIL is released around blocking I/O. Using multiprocessing here would
    add pickling/spawn fragility (worker functions must be module-level and
    re-importable under macOS's default 'spawn' start method) that has
    nothing to do with the thing this test is actually verifying.
    """

    def test_concurrent_allocation_produces_no_duplicate_ids(self):
        data_dir = helpers.make_tmp_data_dir(self)
        n_workers = 24

        def create_one(i: int):
            return cairn.allocate_and_create_issue(data_dir, base_fields(f"Race issue {i}"))

        paths = []
        errors = []
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [pool.submit(create_one, i) for i in range(n_workers)]
            for future in as_completed(futures):
                try:
                    paths.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        self.assertEqual(errors, [], f"allocation raised under concurrency: {errors}")
        self.assertEqual(len(paths), n_workers)

        names = [p.name for p in paths]
        self.assertEqual(len(names), len(set(names)), f"duplicate IDs allocated under concurrency: {names}")

        on_disk = sorted(p.name for p in (data_dir / "issues").glob("PT-*.md"))
        # 3 pre-existing (PT-1, PT-3, PT-4) + n_workers newly created.
        self.assertEqual(len(on_disk), 3 + n_workers)

        # Every allocated file must actually exist and contain a matching id.
        for path in paths:
            frontmatter, _ = cairn.parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(frontmatter["id"] + ".md", path.name)


if __name__ == "__main__":
    unittest.main()
