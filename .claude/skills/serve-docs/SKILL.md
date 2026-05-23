---
name: serve-docs
description: Starts the local docs server (scripts/serve-docs.sh) in the background so the inline comment widget activates in the HTML docs. Use when you want to review a doc and leave comments without juggling a separate terminal. The server's lifecycle is bound to the Claude session — it dies on /exit. Optional argument opens a browser to that doc.
---

# serve-docs

Lifecycle wrapper around `scripts/serve-docs.sh`. Spawns the local docs server as a background process under the Claude harness so you can review HTML docs with the inline comment widget active, without managing a separate terminal pane.

## Usage

```
/serve-docs              # start server if not running; report URLs
/serve-docs PRD          # start (if needed) + open browser at PRD doc
/serve-docs ARCH         # same for ARCH
/serve-docs SECURITY     # same for SECURITY
/serve-docs status       # check if server is running
/serve-docs stop         # kill the running server
```

## When to use vs running the script directly

- **`/serve-docs`** — preferred for review sessions. Server lives as long as the Claude session; cleaned up on `/exit`. Server logs go to the harness background buffer (not your terminal).
- **`./scripts/serve-docs.sh`** in a dedicated terminal — when you want live request logs streaming to your eyes (debugging the server itself, watching POST traffic, etc.).

Both run the same server; you can't have both at once (port conflict).

## Steps

### 1. Parse the argument

`$ARGUMENTS` is one of:
- empty → `start` (no browser open)
- `PRD` / `ARCH` / `SECURITY` → `start` + open browser at the matching URL
- `start` → same as empty (start, no browser open)
- `stop` → kill the server, then exit
- `status` → report only, no action

Anything else → bail with usage hint.

### 2. Detect whether the server is already running

Probe with a short-timeout curl:

```bash
curl -sf --max-time 1 -o /dev/null "http://127.0.0.1:${PORT:-8765}/api/comments?doc=PRD"
```

- Exit code 0 → server is up and the comments API responds.
- Non-zero → server is not running (or not responsive at that port).

If the user passed `status`, **report and exit** — `connected` or `offline`, plus the configured port.

### 3. Handle `stop`

If `$ARGUMENTS == "stop"`:

```bash
# Find PID via the port, then kill. Two fallback paths.
pid="$(lsof -ti :${PORT:-8765} 2>/dev/null | head -1)"
if [ -z "$pid" ]; then
  pid="$(pgrep -f 'serve-docs\.py' | head -1)"
fi
if [ -n "$pid" ]; then
  kill "$pid" && echo "Stopped serve-docs (PID $pid)"
else
  echo "No serve-docs process found."
fi
```

Exit after the stop.

### 4. Start (if not already running)

If detection in step 2 succeeded, **skip the launch** — just proceed to step 5 (browser open if applicable).

Otherwise, launch the server **in the background** using the `Bash` tool's `run_in_background: true` flag:

```
Bash(
  command = "./scripts/serve-docs.sh",
  run_in_background = true,
  description = "Start docs server in background"
)
```

The harness returns a shell ID; the process is now alive and managed by Claude Code. Don't tail its output here — the next step polls for readiness via HTTP, which is more reliable than parsing stdout.

### 5. Poll for readiness

After launching, wait for the server to start accepting connections:

```bash
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf --max-time 1 -o /dev/null "http://127.0.0.1:${PORT:-8765}/api/comments?doc=PRD"; then
    echo "Server ready."
    break
  fi
  sleep 0.5
done
```

If the loop completes without success, the server failed to start. Surface the error (suggest checking the background shell's stdout via the harness, or running `./scripts/serve-docs.sh` in a terminal to see the failure directly). Common causes: port collision, missing python3, syntax error from a recent edit to `serve-docs.py`.

### 6. Report URLs

Print:

```
Server running at http://localhost:8765/
  PRD:      http://localhost:8765/PRD/
  ARCH:     http://localhost:8765/ARCH/
  SECURITY: http://localhost:8765/SECURITY/

Inline comment widget is active. Type to add comments; they save to docs/<DOC>/comments.md.
Run /refine-doc <DOC> when you're ready to address them.

Server will be cleaned up automatically when you /exit this session.
To stop manually: /serve-docs stop
```

### 7. Open the browser if a doc name was passed

If `$ARGUMENTS` is `PRD`, `ARCH`, or `SECURITY`:

```bash
open -a "Google Chrome" "http://localhost:${PORT:-8765}/${doc}/" 2>/dev/null \
  || open -a "Safari" "http://localhost:${PORT:-8765}/${doc}/"
```

(Same Chrome → Safari fallback pattern that `/open-doc` uses.)

## Failure modes

- **Invalid argument**: bail with `Usage: /serve-docs [PRD|ARCH|SECURITY|start|stop|status]`.
- **Server start times out**: surface the error; suggest running `./scripts/serve-docs.sh` directly in a terminal to see live error output. Don't pretend success.
- **Port already in use by a different process**: detection in step 2 returns 200 (something is up), but it might not be our server. If `status` was requested, just report the port is responsive; if `start` was requested, proceed (browser will reach whatever is listening). For sharper detection, future passes could probe `/api/comments` and verify the JSON shape, but step 2's curl-against-the-API endpoint already does this — a non-serve-docs server would 404 the path.
- **`scripts/serve-docs.sh` is missing or non-executable**: surface the error from the Bash launch; suggest checking the repo bootstrap (the script ships with the template).

## Notes

- **Server lifecycle is bound to the Claude session.** The harness manages the background process; quitting the session terminates it. This is intentional — review sessions are bounded, and we'd rather not leave dangling localhost processes cluttering the system.
- **Server logs go to the harness's background-shell buffer**, not your terminal. To see them, you'd need to read the background shell's output via the harness (typically via a `BashOutput` tool or similar). For most review sessions you don't need this; if you do, run the script directly in a terminal instead.
- **One server at a time.** The default port is 8765; override with `DOCS_PORT=8080 ./scripts/serve-docs.sh` if you need to run a separate instance. The skill doesn't currently expose the port override — edit the script invocation if you need it.
- **Pairs with `/refine-doc`.** Typical session: `/serve-docs PRD` → review in browser + add comments via the widget → `/refine-doc PRD` → `/start-doc-update` → `/finish-doc-update` → `/merge-pr`.
