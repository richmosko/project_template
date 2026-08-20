---
id: PT-4
title: Add rate limiting to the login endpoint
status: backlog
milestone: null
parent: null
assignee: null
labels: []
priority: null
pr: null
created: 2026-08-16
updated: 2026-08-16
---

Prevent credential-stuffing by rate limiting `/auth/login` per IP and per account.

## Comments

### @mosko — 2026-08-17

Ship it behind a flag once the rate-limit config lands.