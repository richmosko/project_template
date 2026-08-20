---
name: cairn
description: Starts the cairn board server (scripts/cairn/cairn serve) in the background so the Kanban/list board is viewable at http://localhost:8766/. Use when you want to see or edit the issue board — drag cards between columns, open the detail drawer, add comments, create issues. The server is a stateless lens over process/cairn/ (agents never need it — they read/write the files directly); its lifecycle is bound to the Claude session and it dies on /exit. Arguments: none/start, open (also opens the browser), status, stop.
---

# cairn

Lifecycle wrapper around `scripts/cairn/cairn serve` — the board server for **cairn**, the file-based issue tracker (spec: [`process/TRACKER.md`](../../../process/TRACKER.md)). Mirrors `/serve-docs`: background process under the Claude harness, probed before launch, cleaned up on `/exit`.

The server is a **lens, not a source of truth**: it parses `process/cairn/` at request time, holds no state, and nothing is lost if it dies. Agents never use it — they work the files directly (or via the `cairn` CLI).

## Usage

```
/cairn            # start server if not running; report the URL
/cairn open       # start (if needed) + open the board in the browser
/cairn status     # is it running?
/cairn stop       # kill the running server
```

## Steps

### 1. Parse the argument

`$ARGUMENTS`: empty/`start` → start; `open` → start + browser; `status` → report only; `stop` → kill and exit. Anything else → bail with the usage block.

### 2. Detect a running instance

```bash
curl -sf --max-time 1 -o /dev/null "http://127.0.0.1:${CAIRN_PORT:-8766}/api/board"
```

Exit 0 → already up (skip launch). For `status`: report `connected` / `offline` + port, then exit.

### 3. Handle `stop`

```bash
pid="$(lsof -ti :${CAIRN_PORT:-8766} 2>/dev/null | head -1)"
[ -z "$pid" ] && pid="$(pgrep -f 'cairn(\.py)? serve' | head -1)"
if [ -n "$pid" ]; then kill "$pid" && echo "Stopped cairn board (PID $pid)"; else echo "No cairn server found."; fi
```

### 4. Start in the background (if not running)

```
Bash(command = "./scripts/cairn/cairn serve", run_in_background = true,
     description = "Start cairn board server in background")
```

Then poll for readiness (same pattern as `/serve-docs`): curl `/api/board` up to 10 × 0.5s. If it never comes up, surface the failure — the loudest common cause is a missing `process/cairn/config.yml`, and the engine's error will say to run `/setup-tracker`. Don't pretend success.

### 5. Report

```
Board running at http://localhost:8766/          (Kanban)
List view:        http://localhost:8766/list

Edits on the board (drag, drawer, + New) write straight to process/cairn/ —
they dirty the working tree like any other edit and commit via the normal flow.
Server dies on /exit; /cairn stop to kill it manually.
```

### 6. Open the browser (`open` only)

```bash
open -a "Google Chrome" "http://localhost:${CAIRN_PORT:-8766}/" 2>/dev/null \
  || open -a "Safari" "http://localhost:${CAIRN_PORT:-8766}/"
```

## Failure modes

- **`/setup-tracker` never ran** — the server exits loudly naming the missing `config.yml`; relay that and suggest `/setup-tracker`.
- **Port 8766 taken by something else** — the readiness probe hits a non-cairn responder; `/api/board` 404s → treat as offline and surface the collision (override: `CAIRN_PORT=8899 ./scripts/cairn/cairn serve`).
- **Server start times out** — surface it; suggest running `./scripts/cairn/cairn serve` in a terminal for live logs.

## Notes

- **Coexists with `/serve-docs`** — separate servers, separate ports (docs 8765, board 8766), by design (see `process/TRACKER.md` → Coexistence).
- **No auto-commit** — board edits accumulate in the working tree and are committed by the session/feature-close discipline, exactly like agent edits.
- **Persistent option** — for a board that outlives the session, run `./scripts/cairn/cairn serve` in your own terminal (or under launchd) instead; the data can't tell the difference.
