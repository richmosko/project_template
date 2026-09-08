# PT-82 worktree spike record (steps 4–11)

Ruling: process/cairn/issues/PT-82.md @ 6316a9b, section (b) Spike; addendum @ b0287db.
Executed by: spike-qa (fresh qa-engineer teammate), 2026-09-08.

## Step 4 — EnterWorktree

- Called `EnterWorktree(name: "pt82-spike")`.
- Result: worktree created at `/Users/mosko/Projects/project_template/.claude/worktrees/pt82-spike`, branch `worktree-pt82-spike`.
- PASS.

## Step 5 — HEAD equals feature tip

```
$ git rev-parse HEAD
c485a55b5854b2c9eee42cb4be54dfd74eb0dace
```

- Expected feature tip: c485a55. Equal. PASS.

## Step 6 — Mailbox works from worktree

- Sent `SendMessage` to team-lead: "spike step 6: mailbox works from /Users/mosko/Projects/project_template/.claude/worktrees/pt82-spike".
- `SendMessage` tool returned `success: true`, msg_id delivered. PASS.

## Step 7 — Shared task list visible

- `TaskList` returned: `#13 [in_progress] Every teammate in its own git worktree; one branch per issue is the sole integration point (qa-engineer)`.
- Task #13 IS visible from the worktree session. PASS.

## Step 8 — node_modules delivery + dashboard build

```
$ ls scripts/cairn/dashboard/node_modules | head -3
@dagrejs/
@floating-ui/
@fontsource-variable/
```

- Package directories present (delivered via `.worktreeinclude`). PARTIAL — see below.

```
$ cd scripts/cairn/dashboard && npm run build
> dashboard@0.0.0 build
> vite build

sh: vite: command not found
```

- Build FAILS. Root cause: `node_modules/.bin` does not exist in the worktree copy (checked directly: `ls node_modules/.bin` → "No such file or directory"), even though the `vite` package itself is present under `node_modules/vite/`. The package directories were delivered but the bin symlinks that `npm`/`node_modules/.bin` normally provides were not — so `vite` is not resolvable on PATH.
- **FAIL: node_modules delivered (package contents present), but the dashboard build does not succeed as-is.**

## Step 8 repeat — .worktreeinclude fix (9b50083)

New worktree `pt82-spike-2`, entered after `git pull --rebase origin feature/pt-82-teammate-worktrees` on the prior worktree brought HEAD to `9b50083` (confirmed via `git rev-parse HEAD` in the new worktree: `9b5008347f8939250bc26fdd783d2c90a52f8af3`).

`.worktreeinclude` now lists both patterns:

```
scripts/cairn/dashboard/node_modules/**
scripts/cairn/dashboard/node_modules/.bin/**
```

Result:

```
$ ls scripts/cairn/dashboard/node_modules/.bin | head -3
ls: scripts/cairn/dashboard/node_modules/.bin: No such file or directory
```

Confirmed no `.bin` entry at all under `node_modules` (`ls -la node_modules | grep -i bin` → empty; `find node_modules -maxdepth 1 -name ".*"` → only `.package-lock.json`). Source (main checkout) does have `node_modules/.bin/` with real symlinks (e.g. `acorn -> ../acorn/bin/acorn`).

```
$ cd scripts/cairn/dashboard && npm run build
> dashboard@0.0.0 build
> vite build

sh: vite: command not found
```

**FAIL — same failure as before the fix.** The explicit `.bin/**` pattern added at 9b50083 did not deliver `node_modules/.bin` into this fresh worktree; `vite` remains unresolvable and the build still fails identically.

## Step 9 — Metrics write / go-no-go

Command as given (`--gate red` combined with `-p`) was rejected by the harness itself:

```
$ python3 run_tests.py -p "test_gate_head.py" --gate red
run_tests.py: error: --gate is a full-suite gate run and cannot be combined with -p/--pattern
(a narrowed run is not a gate run, PT-94 C9) -- drop --gate for a tiered mid-loop run,
or drop -p/--pattern to run the full suite at this gate.
```

Per instruction "never run a bare full suite", dropped `--gate` and kept `-p` (a narrowed, non-gate run):

```
$ python3 run_tests.py -p "test_gate_head.py"
Ran 3 tests in 1.085s (1 files, 8 workers)
OK (skipped=0)
```

Line counts before/after (worktree's own file vs. main checkout's file):

| File | Before | After |
|---|---|---|
| worktree `process/cairn/metrics/test-runs.jsonl` | 161 | 162 |
| main checkout `/Users/mosko/Projects/project_template/process/cairn/metrics/test-runs.jsonl` | 185 | 186 |

**Both files gained a line**, same timestamp (`2026-09-08T09:45:03.000Z`):

- Worktree copy's new line: `"who": null, "branch": "worktree-pt82-spike", "session": null, "cmd": ".../python3.14 run_tests.py -p test_gate_head.py"`
- Main checkout's new line: `"who": "qa-engineer", "branch": "feature/pt-82-teammate-worktrees", "session": "c2a545ab-3714-498b-8314-b9e1630b7de3", "cmd": "python3 run_tests.py -p \"test_gate_head.py\" 2>&1 | tail -40"`

**Go/no-go per (c): the authoritative record landed in the MAIN checkout's file, with `who` populated ("qa-engineer") and session populated. GO on that criterion.**

Secondary finding (not blocking, flagged for the ruling): the worktree's own local copy of `test-runs.jsonl` *also* received a stray line with `who: null` and `branch` set to the scaffolding branch name (`worktree-pt82-spike`) rather than the feature branch — i.e. metrics-path resolution redirects the authoritative write to the main checkout correctly, but does not suppress a second, incomplete local write into the worktree's own tracked copy of the file. This second write pollutes the worktree's git-tracked metrics file with a spurious diff and should be addressed (either suppress the local write entirely, or resolve `who`/`branch` correctly there too) before this is load-bearing.

## Step 10 — Commit and push

(recorded after this file is committed and pushed — see team-lead report for the sha.)

## Step 11 — Cross-checkout refusal

```
$ git -C /Users/mosko/Projects/project_template status
This session is isolated in the worktree /Users/mosko/Projects/project_template/.claude/worktrees/pt82-spike,
but this command redirects git to the shared checkout via -C. Refusing to run it — a worktree-isolated
session's git operations must target its own worktree. Run the equivalent from
/Users/mosko/Projects/project_template/.claude/worktrees/pt82-spike without the redirect.
```

- Refused as expected. PASS.
