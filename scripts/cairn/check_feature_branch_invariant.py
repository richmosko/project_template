#!/usr/bin/env python3
"""
check_feature_branch_invariant.py — PT-82: the `/finish-feature` and
`/merge-pr` invariant gate.

Ruling (architect, process/cairn/issues/PT-82.md @ 6316a9b, item (e)):
"one branch per issue, that every agent integrates on; it gets exactly
one PR to main" is enforced, not advised. Every teammate worktree pushes
fast-forward to `feature/<id>` on origin; the local scaffolding branch a
worktree creates (`worktree-<name>`) is never supposed to reach origin.
This script is the loud check that it didn't: origin must hold exactly
one `feature/<id>-*` branch for the current issue, zero `worktree-*`
branches, and exactly one open PR for that branch.

The `worktree-*` check is the one that matters (architect, verbatim): "a
pushed worktree-* branch is what would produce a second PR" — the other
two checks are corroborating evidence of the same failure class.

Library contract:
    check_feature_branch_invariant(repo_root: Path, phase: str = "strict") -> dict
        {"ok": bool, "reason": str, "message": str}
    reason is one of:
        "ok", "not-a-feature-branch", "duplicate-feature-branch",
        "worktree-branch-on-origin", "pr-count"

    `phase` (architect's ruling, PT-82.md @ 778300b, post-verdict delta
    2): the invariant is meaningful at two different lifecycle moments
    and a single fixed predicate cannot express both. `"pre-pr"` -- for
    a sanity check made BEFORE `gh pr create` runs -- tolerates AT MOST
    one open PR (zero, or one from a re-run after the PR already
    exists); `"finish"` and `"merge"` require EXACTLY one, matching the
    two real call sites (`/finish-feature`, after `gh pr create`;
    `/merge-pr`, after the PR exists). The default, `"strict"`, is
    identical to `"finish"`/`"merge"` -- an unflagged call can never
    silently weaken to the tolerant predicate. The `worktree-*` branch
    check is unchanged across every phase; it is never relaxed.

CLI contract:
    python3 scripts/cairn/check_feature_branch_invariant.py [--phase {pre-pr,finish,merge}] [repo_root]
    Prints `message` and exits 1 unless `result["ok"]`. `repo_root`
    defaults to the repo this script lives in. No `--phase` is the
    strict (exactly-one-PR) predicate.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_FEATURE_BRANCH_RE = re.compile(r"^feature/([A-Za-z]+-\d+)-")


def _run(repo_root: Path, *args: str, timeout: float = 15) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(args, cwd=str(repo_root), capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def _current_branch(repo_root: Path) -> Optional[str]:
    result = _run(repo_root, "git", "rev-parse", "--abbrev-ref", "HEAD")
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _remote_branch_names(repo_root: Path) -> Optional[List[str]]:
    """Every branch name on `origin` (`git ls-remote --heads`), or `None`
    if the remote can't be queried -- distinct from an empty list (a
    remote with no branches, which is itself a finding elsewhere)."""
    result = _run(repo_root, "git", "ls-remote", "--heads", "origin")
    if result is None or result.returncode != 0:
        return None
    names = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        ref = parts[1]
        prefix = "refs/heads/"
        if ref.startswith(prefix):
            names.append(ref[len(prefix):])
    return names


def _open_pr_count(repo_root: Path, branch: str) -> Optional[int]:
    """Number of open PRs `gh` reports for `branch`, or `None` if `gh`
    itself could not be run/parsed -- distinct from a real zero."""
    result = _run(repo_root, "gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number")
    if result is None or result.returncode != 0:
        return None
    try:
        prs = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(prs, list):
        return None
    return len(prs)


def check_feature_branch_invariant(repo_root: Path, phase: str = "strict") -> Dict[str, Any]:
    repo_root = Path(repo_root)

    branch = _current_branch(repo_root)
    match = _FEATURE_BRANCH_RE.match(branch) if branch else None
    if not match:
        return {
            "ok": False,
            "reason": "not-a-feature-branch",
            "message": (
                f"current branch {branch!r} does not look like feature/<id>-<slug> -- cannot "
                f"derive the issue id this invariant check is for."
            ),
        }
    issue_id = match.group(1)

    remote_branches = _remote_branch_names(repo_root)
    if remote_branches is None:
        return {
            "ok": False,
            "reason": "remote-unreachable",
            "message": "could not read origin's branch list (git ls-remote --heads origin failed).",
        }

    feature_branches = [b for b in remote_branches if b.startswith(f"feature/{issue_id}-")]
    if len(feature_branches) != 1:
        return {
            "ok": False,
            "reason": "duplicate-feature-branch",
            "message": (
                f"expected exactly one feature/{issue_id}-* branch on origin, found "
                f"{len(feature_branches)}: {sorted(feature_branches)} -- every agent must "
                f"integrate on the SAME branch for issue {issue_id}."
            ),
        }

    worktree_branches = [b for b in remote_branches if b.startswith("worktree-")]
    if worktree_branches:
        return {
            "ok": False,
            "reason": "worktree-branch-on-origin",
            "message": (
                f"found worktree-* branch(es) on origin: {sorted(worktree_branches)} -- a "
                f"teammate's local scaffolding branch must never reach origin (it is what would "
                f"produce a second PR for issue {issue_id})."
            ),
        }

    pr_count = _open_pr_count(repo_root, feature_branches[0])
    if pr_count is None:
        return {
            "ok": False,
            "reason": "pr-count-unreachable",
            "message": f"could not read the open PR count for {feature_branches[0]!r} (gh pr list failed).",
        }
    if phase == "pre-pr":
        if pr_count > 1:
            return {
                "ok": False,
                "reason": "pr-count",
                "message": (
                    f"expected at most one open PR for {feature_branches[0]!r} before it is "
                    f"created, found {pr_count} -- issue {issue_id} must have at most one PR to "
                    f"main."
                ),
            }
    elif pr_count != 1:
        return {
            "ok": False,
            "reason": "pr-count",
            "message": (
                f"expected exactly one open PR for {feature_branches[0]!r}, found {pr_count} -- "
                f"issue {issue_id} must have exactly one PR to main, at merge time."
            ),
        }

    return {
        "ok": True,
        "reason": "ok",
        "message": (
            f"one feature/{issue_id}-* branch, zero worktree-* branches, one open PR -- "
            f"invariant holds."
        ),
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=["pre-pr", "finish", "merge"], default=None,
        help="pre-pr: at most one open PR (before gh pr create); finish/merge: exactly one "
             "(today's behaviour). No flag: the strict (exactly-one) predicate, same as "
             "finish/merge -- never silently weaker.",
    )
    parser.add_argument("repo_root", nargs="?", default=None)
    args = parser.parse_args(argv)

    if args.repo_root:
        repo_root = Path(args.repo_root)
    else:
        # scripts/cairn/check_feature_branch_invariant.py -> scripts/cairn -> scripts -> repo root
        repo_root = Path(__file__).resolve().parent.parent.parent

    phase = args.phase or "strict"
    result = check_feature_branch_invariant(repo_root, phase=phase)
    print(result["message"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
