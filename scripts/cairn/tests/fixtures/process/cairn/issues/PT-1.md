---
id: PT-1
title: Google OAuth login
status: in-progress
milestone: PT-1.0
parent: null
assignee: backend-lead
labels: [auth, api]
priority: P1
pr: null
created: 2026-08-14
updated: 2026-08-19
---

A returning user should be able to sign in with their Google account instead of
a password, so first-run friction drops and we stop storing credentials.

## Acceptance criteria

- [ ] `GET /auth/google` redirects to Google's consent screen with the correct scopes
- [ ] Callback exchanges the code and creates or links a local user record

## Comments

### @qa-engineer — 2026-08-18

Failing acceptance test committed: `tests/auth/test_google.py::test_consent_redirect`.

A delimiter-looking line inside a fence must NOT be parsed as a comment boundary:

```
### @not-a-real-author — 2026-01-01
```

Still part of this same comment.

### @architect — 2026-08-19

Reuse `lib/session/store.py` rather than introducing a second session abstraction.

### Not a delimiter

This heading has no em dash and no trailing date, so it is body content, not
a new comment boundary. It stays attached to @architect's comment above.
