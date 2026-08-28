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
dashboard source vs the latest commit that touches `dist/`, compared by
ANCESTRY (`git merge-base --is-ancestor <src-commit> <dist-commit>`), not
commit timestamp. Architect's blocking finding on the first cut (peer
review 8bd6896): comparing `%cI` strings directly has two failure modes
--- same-second commits (common when agents commit programmatically in
rapid succession) tie, and a strict `>` resolves a tie toward "fresh" --
exactly backwards for a gate; and ISO-8601 offsets compare LEXICALLY, so
ordering can invert across timezones. Ancestry dissolves both: it asks
git "is the source commit reachable from the dist commit's history"
rather than "which clock reading is bigger", so identical timestamps and
cross-timezone commits stop mattering entirely. A commit that touches
neither (a doc-only PR) never flips a previously-fresh repo to stale --
if no commit in the repo's history touches source at all, there is
nothing to compare `dist/`'s history against, so the gate reports fresh.

"Dashboard source" is the whole `scripts/cairn/dashboard/` subtree EXCEPT
`dist/` itself (`git ... -- scripts/cairn/dashboard ':(exclude)
scripts/cairn/dashboard/dist'`) -- the INVERSE of an enumerated by-name
list (architect's non-blocking review suggestion, adopted as in-scope:
"did we remember to exclude it" beats "did we remember to list it"). An
enumerated list silently stops watching the day someone adds a config
file Vite picks up automatically (`.env`, `postcss.config.js`, a
reintroduced `tailwind.config.js`) -- the exclude-formulation can't drift
that way; only `dist/` is ever carved out. This deliberately overreaches
in the safe direction: a types-only `tsconfig.json` edit, or even
`.gitignore`/`README.md` inside the dashboard dir, demands a rebuild it
doesn't strictly need. False-stale is the safe failure for a gate --
don't optimize it away.

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
DIST_REL = DASHBOARD_REL / "dist"


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


def _source_pathspecs() -> List[str]:
    """The inverse-formulation pathspec: all of `scripts/cairn/dashboard/`
    EXCEPT `dist/`. `:(exclude)` is git pathspec magic (supported since
    git 1.9) -- two pathspecs given together mean "the first, minus the
    second". Static (no filesystem scan): the exclusion is by PATH, not
    by an enumerated, driftable list of names."""
    return [str(DASHBOARD_REL), f":(exclude){DIST_REL}"]


def _last_commit_sha(repo_root: Path, pathspecs: List[str]) -> Optional[str]:
    """Full SHA of the most recent commit touching `pathspecs`, or `None`
    if no commit in history touches any of them (distinct from a git
    failure, which is handled by the caller checking `_run_git`'s own
    `None` return for a baseline command first)."""
    out = _run_git(repo_root, "log", "-1", "--format=%H", "--", *pathspecs)
    return out or None


def _commit_timestamp(repo_root: Path, sha: str) -> Optional[str]:
    """ISO-8601 committer date for a known commit SHA -- display only,
    never used for freshness ordering (see `_is_ancestor`)."""
    return _run_git(repo_root, "show", "-s", "--format=%cI", sha) or None


def _is_ancestor(repo_root: Path, ancestor_sha: str, descendant_sha: str) -> bool:
    """Whether `ancestor_sha` is reachable from `descendant_sha` (or is the
    same commit -- a commit is its own ancestor, which is exactly what
    makes "src + dist rebuilt in one commit" read as fresh). Ancestry, not
    a timestamp comparison (architect's peer-review fix, 8bd6896): a `%cI`
    string compare ties on same-second commits -- resolving toward
    "fresh", backwards for a gate -- and inverts across timezones, since
    ISO-8601 offsets sort lexically, not chronologically. `git merge-base
    --is-ancestor` sidesteps both by asking a history-reachability
    question instead of a clock question. Conservatively `False` (i.e.
    stale, never silently fresh) if the check itself can't run.

    Known failure mode (architect, peer review): after a merge, the src
    and dist commits can sit on divergent branches with NEITHER an
    ancestor of the other -- `--is-ancestor` returns `False` and the gate
    reports `stale`. That's genuinely ambiguous (git can't order two
    commits that never shared a line of descent) and this resolves it
    conservatively, which is correct -- but it is not a bug if a future
    reader finds a "false" stale here on such a repo shape.

    What this proves, and what it doesn't (architect): ancestry shows the
    dist commit came AFTER the source commit in history, not that dist's
    BYTES were actually built from that source -- it is a reliable
    heuristic, not a content guarantee. A stronger property (a hash of
    source inputs recorded in the dist commit) is deliberately out of
    scope for this gate."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, OSError):
        return False
    return result.returncode == 0


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

    source_pathspecs = _source_pathspecs()

    # Uncommitted working-tree changes to source paths are treated as
    # stale, honestly -- this tool cannot know whether they're reflected
    # in the committed dist/, and /finish-feature runs pre-PR. No
    # --untracked-files=no here (unlike read_git_state's "dirty" check,
    # which deliberately ignores untracked files because an untracked
    # issue file mid-`cairn new` is the routine case there -- a DIFFERENT
    # question, "is the tree dirty for display", not "can we trust dist/
    # matches source"; team-lead's ruling: don't harmonize these): a
    # brand-new, never-`git add`ed source file is the strongest possible
    # signal that dist is out of date, so untracked source files count as
    # dirty too. Scoped to the watched path set via the same pathspecs --
    # untracked noise elsewhere in the repo (or elsewhere in dashboard/,
    # e.g. a stray file directly in dist/) never triggers this.
    dirty = _run_git(repo_root, "status", "--porcelain", "--", *source_pathspecs)
    if dirty:
        return {
            "stale": True,
            "reason": "uncommitted-src-changes",
            "message": (
                "dashboard source has uncommitted (or untracked) changes -- commit them "
                "first so dist freshness can be verified against the committed source:\n" + dirty
            ),
        }

    last_src_sha = _last_commit_sha(repo_root, source_pathspecs)
    last_dist_sha = _last_commit_sha(repo_root, [str(DIST_REL)])

    if last_src_sha is None:
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

    if last_dist_sha is None:
        src_ts = _commit_timestamp(repo_root, last_src_sha)
        return {
            "stale": True,
            "reason": "dist-never-built",
            "message": (
                f"scripts/cairn/dashboard/dist/ has never been committed, but dashboard source "
                f"has (last touched {src_ts or last_src_sha}) -- build the dashboard and commit dist/."
            ),
        }

    # Ancestry, not timestamp comparison (architect's peer-review fix,
    # 8bd6896): dist is fresh iff the latest source-touching commit is an
    # ancestor of (or identical to) the latest dist-touching commit.
    if _is_ancestor(repo_root, last_src_sha, last_dist_sha):
        dist_ts = _commit_timestamp(repo_root, last_dist_sha)
        src_ts = _commit_timestamp(repo_root, last_src_sha)
        return {
            "stale": False,
            "reason": "fresh",
            "message": f"dist/ ({dist_ts or last_dist_sha}) is up to date with source (last touched {src_ts or last_src_sha}).",
        }

    src_ts = _commit_timestamp(repo_root, last_src_sha)
    dist_ts = _commit_timestamp(repo_root, last_dist_sha)
    return {
        "stale": True,
        "reason": "stale",
        "message": (
            f"scripts/cairn/dashboard/dist/ is stale: source was last committed at "
            f"{src_ts or last_src_sha}, but dist/'s last commit ({dist_ts or last_dist_sha}) does not "
            f"include it. Rebuild the dashboard and commit dist/ before finishing this feature."
        ),
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
