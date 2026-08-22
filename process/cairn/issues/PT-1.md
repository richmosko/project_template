---
id: PT-1
title: Board phase 2: SSE live push (fs-scan watcher + EventSource, poll fallback)
status: done
milestone: PT-0.4
parent: null
assignee: null
labels: []
priority: P2
pr: https://github.com/richmosko/project_template/pull/42
created: 2026-08-20
updated: 2026-08-20
---


## Comments

### @team-lead — 2026-08-20

Feature started. Branch: `feature/pt-1-sse-live-push`. The 0.4 closer.

Acceptance criteria (team-lead):
1. Server: an SSE endpoint (GET /api/events, text/event-stream) that emits a change
   event when anything under the data dir changes, driven by a periodic fs-scan
   watcher (mtime/fileset comparison — no external deps, stdlib only per the
   boring-stack principle). Scan cadence ≤2s.
2. Stateless-lens preserved: no durable state; in-memory connection bookkeeping
   only; killing the server loses nothing; concurrent SSE clients + normal API
   requests must not block each other (the server is already threaded — prove it
   stays true).
3. Client: EventSource subscribes on load; a change event triggers the existing
   refreshBoardSilently path. While SSE is connected the 4s poll is suspended;
   on SSE error/close the client falls back to polling and retries SSE with
   backoff. No behavior change for browsers/environments where EventSource fails.
4. End-to-end: an external file edit (CLI write, agent edit) appears on the board
   without user interaction within ~2× scan cadence.
5. Tests: watcher scan logic unit-tested (change detected, no-change quiet,
   file-added/removed); SSE endpoint integration-tested at the HTTP level (event
   arrives after a mutation, with a read timeout so the test can't hang).
   Existing 171 stay green. `cairn check` ok.
6. Board UI shows connection state minimally (e.g. the existing header/status area
   notes "live" vs "polling") so a human can tell which mode they're in.

### @team-lead — 2026-08-20

AC #2 correction (team-lead, on qa-engineer's finding): the premise "the server is
already threaded" was wrong — Server is a plain http.server.HTTPServer; a held-open
SSE connection would block the single accept loop. The design therefore includes
switching to per-connection threading (ThreadingHTTPServer / ThreadingMixIn with
daemon threads) as a first-class part of this feature, proven by the concurrency
tests. Also ruled: watcher lifecycle binds to make_server (exists ⇒ watching,
close ⇒ stopped), and the event contract is the COARSE variant (any-change event →
full client refresh) — TRACKER.md's per-id sketch is recorded here as a deliberate
deferral, a future refinement (candidate for 0.5), not this ticket.

### @team-lead — 2026-08-20

Browser-level verification of the client half performed by team-lead (2026-08-20,
throwaway data dir on :18801, real Chrome): SSE connects on load, indicator shows
"● live"; an external CLI edit moved the card TODO→IN PROGRESS with zero user
interaction (single SSE-triggered /api/board fetch in the window — poll suspended);
killing the server flipped the indicator to "○ polling"; restarting flipped it back
to "● live" via EventSource auto-reconnect. Items 6/8 of QA's checklist remain
code-audit-verified (EventSource-less browsers aren't reproducible in real Chrome).
This closes the browser-verification gap QA disclosed. Incident during the probe,
disclosed: an over-broad `lsof -ti :port | head -1` kill took out a Chrome tab
process instead of the server once — corrected to `-sTCP:LISTEN` scoping; no data
affected.
