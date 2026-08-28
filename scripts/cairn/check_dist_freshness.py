#!/usr/bin/env python3
"""
check_dist_freshness.py — PT-58: the `/finish-feature` dashboard dist-
freshness gate.

Follow-up from the architect's PT-54 build-output ruling: committed dist
accepts staleness as PR discipline. This script hardens that: it answers
"is scripts/cairn/dashboard/dist/ stale relative to the source it ships?"
so `/finish-feature` can refuse (or warn loudly) instead of trusting PR
discipline alone.

Git-aware, not raw mtime (the architect's own caveat, taken seriously): a
checkout/clone resets file mtimes arbitrarily, so `dist/`'s mtime vs
`src/`'s mtime would be unreliable the moment anyone re-clones or
re-checks-out the branch. Instead: the latest COMMIT that touches
dashboard source (src/, index.html, package.json/package-lock.json,
vite.config.*, svelte.config.*, tsconfig*.json, components.json, public/)
vs the latest commit that touches `dist/`, compared by commit timestamp,
not the working tree. A commit that touches neither (a doc-only PR) never
flips a previously-fresh repo to stale — if no commit in the repo's
history touches source at all, there is nothing to compare `dist/`'s
history against, so the gate reports fresh.

This is a standalone script (sibling of cairn.py), not a new `cairn`
subcommand — dist freshness is dashboard-specific, not tracker
functionality.

Stated failure modes, honestly:
  - Assumes COMMITTED state. An uncommitted edit to a source path is
    `stale` (reason `uncommitted-src-changes`) — this tool cannot know
    whether an uncommitted edit is reflected in the committed `dist/`,
    and `/finish-feature` runs before a PR is opened, so "commit your
    dashboard changes first" is the honest ask at that point in the
    workflow.
  - A `dist/` with NO commit history at all (never built/committed) is
    its own distinct reason (`dist-never-built`) — the fix ("build and
    commit dist/") differs from "rebuild dist/", and the message says so.
  - Never raises. A repo with no dashboard subtree at all (e.g. a spin-
    off) reports fresh with reason `no-dashboard` — same "degrade, don't
    crash" posture as cairn.py's read_git_tags/read_git_state.

Library contract:
    check_dist_freshness(repo_root: Path) -> dict
        {"stale": bool, "reason": str, "message": str}
    reason is one of:
        "fresh", "stale", "dist-never-built",
        "uncommitted-src-changes", "no-dashboard", "git-unavailable"

CLI contract:
    python3 scripts/cairn/check_dist_freshness.py [repo_root]
    Prints `message` and exits 1 if stale, 0 otherwise. `repo_root`
    defaults to the repo this script lives in.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DASHBOARD_REL = Path("scripts") / "cairn" / "dashboard"

# Source path fragments (relative to the dashboard dir) whose latest
# committed change we compare against dist/'s latest committed change.
_SOURCE_DIRS = ("src", "public")
_SOURCE_FILES = ("index.html", "package.json", "package-lock.json", "components.json")
_SOURCE_GLOBS = ("vite.config.*", "svelte.config.*", "tsconfig*.json")


def _run_git(repo_root: Path, *args: str) -> Optional[str]:
    """Same never-raise, `-C repo_root` contract as cairn.py's
    read_git_tags/read_git_state: `None` on a missing git binary or a
    non-zero exit, otherwise the stripped stdout (which may legitimately
    be an empty string — e.g. `log` finding no matching commit — that is
    NOT an error and callers must not conflate the two)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _existing_source_pathspecs(dashboard_dir: Path) -> List[str]:
    """Dashboard-source path fragments that currently exist, relative to
    the dashboard dir. Built from current working-tree presence (design
    latitude — the dashboard's own file layout is stable within the
    lifetime of a single freshness check; this is not a historical
    archaeology tool)."""
    found: List[str] = []
    for name in _SOURCE_DIRS:
        if (dashboard_dir / name).exists():
            found.append(name)
    for name in _SOURCE_FILES:
        if (dashboard_dir / name).exists():
            found.append(name)
    for pattern in _SOURCE_GLOBS:
        for match in sorted(dashboard_dir.glob(pattern)):
            found.append(match.name)
    return found


def _last_commit_timestamp(repo_root: Path, dashboard_rel: Path, fragments: List[str]) -> Optional[str]:
    """ISO-8601 committer date of the most recent commit touching any of
    `fragments` (each relative to `dashboard_rel`), or `None` if no commit
    in history touches any of them (distinct from a git failure, which is
    handled by the caller checking `_run_git`'s own `None` return for a
    baseline command first)."""
    if not fragments:
        return None
    pathspecs = [str(dashboard_rel / f) for f in fragments]
    out = _run_git(repo_root, "log", "-1", "--format=%cI", "--", *pathspecs)
    return out or None


def check_dist_freshness(repo_root: Path) -> Dict[str, Any]:
    repo_root = Path(repo_root)
    dashboard_dir = repo_root / DASHBOARD_REL

    if not dashboard_dir.is_dir():
        return {
            "stale": False,
            "reason": "no-dashboard",
            "message": f"no dashboard subtree at {DASHBOARD_REL} -- nothing to check.",
        }

    # Baseline git availability check (mirrors read_git_state's contract:
    # one failed call degrades the whole result, never raises).
    if _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") is None:
        return {
            "stale": False,
            "reason": "git-unavailable",
            "message": "git is unavailable or this isn't a git worktree -- dist freshness cannot be checked.",
        }

    source_fragments = _existing_source_pathspecs(dashboard_dir)
    source_pathspecs = [str(DASHBOARD_REL / f) for f in source_fragments]

    # Uncommitted working-tree edits to source paths are treated as stale,
    # honestly -- this tool cannot know whether they're reflected in the
    # committed dist/, and /finish-feature runs pre-PR.
    if source_pathspecs:
        dirty = _run_git(repo_root, "status", "--porcelain", "--untracked-files=no", "--", *source_pathspecs)
        if dirty:
            return {
                "stale": True,
                "reason": "uncommitted-src-changes",
                "message": (
                    "dashboard source has uncommitted changes -- commit them first so "
                    "dist freshness can be verified against the committed source:\n" + dirty
                ),
            }

    last_src_ts = _last_commit_timestamp(repo_root, DASHBOARD_REL, source_fragments)
    last_dist_ts = _last_commit_timestamp(repo_root, DASHBOARD_REL, ["dist"])

    if last_src_ts is None:
        # Nothing in history touches dashboard source at all -- nothing
        # to compare dist/'s history against. A doc-only PR falls here
        # too (its commit never touches source paths, so this reflects
        # the LATEST commit that did -- which may be an earlier commit
        # entirely; that's correct, not a miss).
        return {
            "stale": False,
            "reason": "fresh",
            "message": "no commit touches dashboard source -- dist/ has nothing to be stale against.",
        }

    if last_dist_ts is None:
        return {
            "stale": True,
            "reason": "dist-never-built",
            "message": (
                f"scripts/cairn/dashboard/dist/ has never been committed, but dashboard source "
                f"has (last touched {last_src_ts}) -- build the dashboard and commit dist/."
            ),
        }

    if last_src_ts > last_dist_ts:
        return {
            "stale": True,
            "reason": "stale",
            "message": (
                f"scripts/cairn/dashboard/dist/ is stale: source was last committed at "
                f"{last_src_ts}, but dist/ was last committed at {last_dist_ts}. Rebuild the "
                f"dashboard and commit dist/ before finishing this feature."
            ),
        }

    return {
        "stale": False,
        "reason": "fresh",
        "message": f"dist/ ({last_dist_ts}) is up to date with source (last touched {last_src_ts}).",
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        repo_root = Path(argv[0])
    else:
        # scripts/cairn/check_dist_freshness.py -> scripts/cairn -> scripts -> repo root
        repo_root = Path(__file__).resolve().parent.parent.parent

    result = check_dist_freshness(repo_root)
    print(result["message"])
    return 1 if result["stale"] else 0


if __name__ == "__main__":
    sys.exit(main())
