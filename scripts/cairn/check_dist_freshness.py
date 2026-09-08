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
`dist/` and a short, deliberate noise list (`_NOISE_EXCLUDES`: README.md,
.gitignore, .vscode) -- the INVERSE of an enumerated by-name build-input
list (architect's non-blocking review suggestion, adopted as in-scope:
"did we remember to exclude it" beats "did we remember to list it"). An
enumerated INCLUDE list silently stops watching the day someone adds a
config file Vite picks up automatically (`.env`, `postcss.config.js`, a
reintroduced `tailwind.config.js`) -- the exclude-formulation can't drift
that way; only a handful of provably-inert paths are ever carved out, and
the asymmetry that makes this safe is the same one that made the inverse
formulation right in the first place: a forgotten EXCLUSION is a
false-stale (safe, visible, self-correcting), while a forgotten INCLUSION
would be a false-fresh (silent -- the exact failure this gate exists to
prevent). Beyond that noise list, this deliberately overreaches in the
safe direction: a types-only `tsconfig.json` edit still demands a rebuild
it doesn't strictly need. False-stale is the safe failure for a gate --
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

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

DASHBOARD_REL = Path("scripts") / "cairn" / "dashboard"
DIST_REL = DASHBOARD_REL / "dist"

# Paths that are part of the dashboard dir but provably CANNOT affect the
# build output -- excluded alongside dist/ (architect's non-blocking
# follow-up on the inverse formulation). This is a SMALL, deliberate
# exception, not a reopening of the enumeration hazard the inverse
# formulation exists to avoid: the asymmetry that made "exclude dist/"
# right in the first place still holds here -- a forgotten exclusion here
# is a false-stale (safe, visible, self-correcting: rebuild, commit,
# move on), while a forgotten INCLUSION would be a false-fresh (silent,
# the exact failure this gate exists to prevent). Without this, editing
# scripts/cairn/dashboard/README.md -- the file most likely to be edited
# BECAUSE it documents this very rebuild discipline -- forces a pointless
# rebuild commit every time, and a gate that cries wolf teaches people to
# bypass it.
_NOISE_EXCLUDES = ("README.md", ".gitignore", ".vscode")


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
    EXCEPT `dist/` and a short, deliberate noise list (`_NOISE_EXCLUDES`)
    of paths that provably cannot affect the build. `:(exclude)` is git
    pathspec magic (supported since git 1.9) -- N pathspecs given
    together mean "the first, minus every `:(exclude)` one". Static (no
    filesystem scan): every exclusion is by PATH, not by an enumerated,
    driftable list of build-input names."""
    pathspecs = [str(DASHBOARD_REL), f":(exclude){DIST_REL}"]
    pathspecs += [f":(exclude){DASHBOARD_REL / name}" for name in _NOISE_EXCLUDES]
    return pathspecs


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

    # PT-82 post-verdict delta 1: ancestry is only ever a PROXY for "does
    # the committed dist/ match what this source builds" -- an edit that
    # changes only the build's INVOCATION (delta 3, 037e6aa) can leave a
    # byte-identical rebuild with nothing to commit, so ancestry alone
    # would report stale forever. Measure the real predicate directly:
    # rebuild into an isolated tmp dir OUTSIDE the repo (never touching
    # the working tree's own dist/) and compare byte-for-byte. Three
    # guards: (1) a genuine difference stays stale, naming the files;
    # (2) an absent/failing toolchain FAILS with its own reason, never a
    # silent skip/pass (PT-24's defect returning); (3) the rebuild lives
    # entirely outside the repository and is removed afterward. Runs
    # only on this already-stale-by-ancestry path, so the common (fresh)
    # case pays nothing extra.
    rebuild = _rebuild_dashboard_and_compare(repo_root)
    if rebuild["match"]:
        return {
            "stale": False,
            "reason": "fresh",
            "message": (
                f"scripts/cairn/dashboard/dist/ looks stale by git ancestry (source last "
                f"committed at {src_ts or last_src_sha}, dist/'s last commit "
                f"({dist_ts or last_dist_sha}) does not include it), but an isolated rebuild "
                f"reproduces the committed dist/ byte-for-byte -- stale by ancestry, rebuilt "
                f"byte-identical."
            ),
        }
    return {
        "stale": True,
        "reason": "stale",
        "message": (
            f"scripts/cairn/dashboard/dist/ is stale: source was last committed at "
            f"{src_ts or last_src_sha}, but dist/'s last commit ({dist_ts or last_dist_sha}) does not "
            f"include it, and an isolated rebuild does not reproduce it byte-for-byte "
            f"({rebuild['detail']}). Rebuild the dashboard and commit dist/ before finishing this feature."
        ),
    }


def _diff_dist_trees(committed: Path, rebuilt: Path) -> List[str]:
    """Every file-level difference between two `dist/`-shaped trees,
    byte-for-byte -- present-only-in-one and content-mismatches alike.
    `[]` means byte-identical. Neither tree existing is itself a
    difference (an empty dist/ rebuild against a real committed one)."""
    committed_files = {p.relative_to(committed) for p in committed.rglob("*") if p.is_file()} if committed.is_dir() else set()
    rebuilt_files = {p.relative_to(rebuilt) for p in rebuilt.rglob("*") if p.is_file()} if rebuilt.is_dir() else set()
    diffs: List[str] = []
    for rel in sorted(committed_files - rebuilt_files):
        diffs.append(f"{rel} (only in the committed dist/)")
    for rel in sorted(rebuilt_files - committed_files):
        diffs.append(f"{rel} (only in the rebuild)")
    for rel in sorted(committed_files & rebuilt_files):
        if (committed / rel).read_bytes() != (rebuilt / rel).read_bytes():
            diffs.append(f"{rel} (content differs)")
    return diffs


def _rebuild_dashboard_and_compare(repo_root: Path) -> Dict[str, Any]:
    """Rebuilds the dashboard into an ISOLATED tmp dir outside the repo
    (guard 3) and compares the result to the committed `dist/` on disk,
    byte-for-byte. `{"match": bool, "reason": str, "detail": str}` --
    `reason` is `"fresh"` on a match, `"stale"` on a genuine content
    difference (guard 1), or `"rebuild-verification-failed"` when the
    toolchain itself couldn't be exercised (guard 2 -- copy/build
    failure, missing `npm`, a non-zero build exit, or a timeout). Never
    raises, and never treats a toolchain failure as a pass."""
    dashboard_dir = repo_root / DASHBOARD_REL
    committed_dist = repo_root / DIST_REL
    with tempfile.TemporaryDirectory(prefix="cairn-dist-rebuild-") as tmp:
        tmp_dashboard = Path(tmp) / "dashboard"
        try:
            # `shutil.ignore_patterns("dist")` was tried and rejected here:
            # it fnmatches "dist" at EVERY level, not just the top --
            # `node_modules/vite/dist/` (vite's own build output) matched
            # too and vanished from the copy, breaking the vite CLI
            # itself. Copy everything, then remove only the TOP-LEVEL
            # dist/ by path.
            shutil.copytree(dashboard_dir, tmp_dashboard, symlinks=True)
            old_dist = tmp_dashboard / "dist"
            if old_dist.exists():
                shutil.rmtree(old_dist)
        except OSError as exc:
            return {
                "match": False, "reason": "rebuild-verification-failed",
                "detail": f"could not copy dashboard source into an isolated tmp dir for rebuild: {exc}",
            }

        try:
            result = subprocess.run(
                ["npm", "run", "build"], cwd=str(tmp_dashboard),
                capture_output=True, text=True, timeout=180,
            )
        except FileNotFoundError:
            return {
                "match": False, "reason": "rebuild-verification-failed",
                "detail": "npm is not available on PATH -- could not verify the rebuild",
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "match": False, "reason": "rebuild-verification-failed",
                "detail": f"the isolated rebuild could not be run: {exc}",
            }
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "")[-2000:]
            return {
                "match": False, "reason": "rebuild-verification-failed",
                "detail": f"the isolated rebuild failed (exit {result.returncode}): {tail}",
            }

        diffs = _diff_dist_trees(committed_dist, tmp_dashboard / "dist")
        if diffs:
            return {"match": False, "reason": "stale", "detail": "rebuild differs from committed dist/: " + "; ".join(diffs)}
        return {"match": True, "reason": "fresh", "detail": "rebuild is byte-identical to the committed dist/"}


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
