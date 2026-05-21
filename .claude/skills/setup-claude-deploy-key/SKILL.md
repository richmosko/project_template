---
name: setup-claude-deploy-key
description: Set up a passphrase-less SSH deploy key dedicated for Claude Code use, scoped to the current GitHub repo. Eliminates the `Permission denied (publickey)` friction that occurs when the user's main SSH key is passphrase-protected and Claude Code's bash has no TTY to unlock it. Use when the user asks to "set up Claude's deploy key", "give Claude its own SSH key", "stop the HTTPS fallback", "set up SSH for this repo", or any variant requesting Claude Code be able to push without the HTTPS temp-switch dance.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Write
---

# setup-claude-deploy-key — Per-repo passphrase-less SSH key for Claude Code

> **Bundled with the project template** so it travels with the repo. If you'd like it available across **all** your projects (not just those instantiated from this template), copy this file to `~/.claude/skills/setup-claude-deploy-key/SKILL.md` — Claude Code will pick it up at user-level. Both copies behave identically; the project-level copy wins inside this repo.

Generates a passphrase-less Ed25519 keypair dedicated for Claude Code use on the current repo, has the user add the public key as a GitHub deploy key (with write access), and pins the repo's git to use the new key. After running this once per repo, Claude's `git push` / `git fetch` will work directly without the SSH→HTTPS temp-switch fallback.

## When to use

The root cause this addresses: when the user's main SSH key (e.g., `~/.ssh/id_ed25519`) is passphrase-protected, SSH can't unlock it from Claude Code's bash environment (no TTY available, agent forwarding may not work). GitHub accepts the public key on its end — but the local private key can't be unlocked. Result: `Permission denied (publickey)` on every `git push`, forcing the HTTPS temp-switch workflow.

This skill solves it cleanly by generating a separate passphrase-less key scoped to one repo only via a GitHub **deploy key** (not added to the user's account; can't reach other repos).

**Run once per repo.** Not idempotent in the sense of fixing partial state automatically — but safe to run twice (will detect existing key file and prompt).

## How to run

### 1. Pre-flight checks

Run in parallel:

- `git rev-parse --show-toplevel` — confirm we're in a git repo. Bail with a clear message if not.
- `git remote get-url origin` — capture the origin URL. Bail if no `origin` remote.
- Parse the origin URL to extract `<owner>/<repo>`. Both SSH (`git@github.com:owner/repo.git`) and HTTPS (`https://github.com/owner/repo.git`) forms are valid; non-GitHub remotes bail with a clear message ("This skill is GitHub-specific; the current origin is X").
- Check `~/.ssh/id_ed25519_claude_<repo>` — if a key already exists for this repo, surface that and ask the user whether to (a) reuse the existing key (skip generation, jump to GitHub-add step), (b) regenerate (deletes the old key file), or (c) abort. Don't silently overwrite.

### 2. Generate the keypair

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_claude_<repo> -N "" -C "claude-code-<repo>"
```

- `-N ""` makes it passphrase-less. This is the core of the fix.
- `-C "claude-code-<repo>"` puts a descriptive comment in the key (and in the GitHub UI when added).
- Filename convention: `id_ed25519_claude_<repo>` where `<repo>` is the second part of `<owner>/<repo>`. Keeps the key file self-identifying.
- The key generator sets the right perms automatically (`600` on private, `644` on public). No manual `chmod` needed.

### 3. Display the public key for the user to paste into GitHub

```bash
cat ~/.ssh/id_ed25519_claude_<repo>.pub
```

Show the full single-line output. Provide a direct link to the deploy-keys settings page:

```
https://github.com/<owner>/<repo>/settings/keys
```

Instruct the user to:
- Click "Add deploy key"
- Title: `Claude Code (<repo>)` or similar (the user picks; this is the human label in the GitHub UI)
- Key: paste the public key line shown above
- **CRITICAL:** ✅ check **"Allow write access"** — otherwise push will fail with `remote: ERROR: ... read-only deploy key` and we'll have to come back to this step.

**Pause and ask the user to confirm the deploy key is added** before proceeding. Do not assume; the user clicks the button on GitHub, not Claude.

### 4. Pin the repo's git to use the new key

```bash
git config core.sshCommand "ssh -i ~/.ssh/id_ed25519_claude_<repo> -o IdentitiesOnly=yes"
```

- `git config` without `--global` sets this in the current repo's `.git/config`. Repo-scoped; doesn't affect other repos.
- `IdentitiesOnly=yes` is essential — without it, SSH will still offer the user's other keys (e.g., the passphrase-protected `~/.ssh/id_ed25519`) before reaching the new key, which can cause auth confusion or rate-limit issues.
- The setting persists across sessions for this repo.

Verify the setting landed:
```bash
git config --get core.sshCommand
```

### 5. Test the connection

```bash
ssh -i ~/.ssh/id_ed25519_claude_<repo> -o IdentitiesOnly=yes -T git@github.com
```

Expected response: `Hi <owner>/<repo>! You've successfully authenticated, but GitHub does not provide shell access.` Exit code 1 is normal — GitHub doesn't provide shell.

If the response is `Hi <username>!` (user's GitHub handle) instead of `<owner>/<repo>`, something is wrong: the auth is going through a user-scoped key, not the deploy key. Probably the deploy key wasn't added, or `IdentitiesOnly=yes` isn't being honored.

If the response is `Permission denied (publickey)`, the deploy key wasn't added correctly — check the GitHub settings page, confirm the public key is there and write access is enabled.

If auth succeeds:
```bash
git fetch origin
```
A clean exit (no output, no error) confirms the configured `core.sshCommand` is taking effect end-to-end. The repo is now set up.

### 6. Confirm to the user

Tell the user:
- The repo's git is now configured to use a dedicated passphrase-less deploy key.
- `git push` / `git fetch` / etc. will work directly without HTTPS fallback.
- The key is repo-scoped (deploy key on this repo only); it can't reach the user's other repos.
- The key can be revoked anytime from the GitHub repo settings page (Deploy keys → trash icon next to the relevant entry).

## Cleanup / revocation

If the user wants to undo:
- Delete the local key files: `rm ~/.ssh/id_ed25519_claude_<repo>{,.pub}`
- Remove the repo's git config: `git config --unset core.sshCommand`
- Delete the deploy key from GitHub: repo Settings → Deploy keys → trash icon.

## What this skill does NOT do

- It does NOT add a key to the user's GitHub account (that's a different setup with broader blast radius — use the regular `gh ssh-key add` or GitHub Settings → SSH keys for that).
- It does NOT install the deploy key on GitHub (the user does that step in the browser; Claude can't authenticate against GitHub on the user's behalf without an API token, which would itself need credential setup).
- It does NOT change commit attribution. Commits still attribute to whoever the user's `user.email` / `user.name` git config points to (typically the user). The deploy key is purely for transport-layer authentication.
- It does NOT touch the global `~/.ssh/config` (per-repo `core.sshCommand` is cleaner and self-contained).
- It does NOT delete or modify any existing keys. The user's main `~/.ssh/id_ed25519` (if any) stays exactly as it is.

## Security notes

- **Passphrase-less keys can be used by anyone who reads the file.** Mitigations: (a) the key is repo-scoped via deploy key — even if stolen, it can only access this one repo; (b) file perms are `600` (owner-only read); (c) the deploy key has a clear identifier in GitHub for easy revocation.
- **Deploy keys on private repos still expose the repo contents.** If the repo contains sensitive content (real financial figures, PHI, credentials accidentally committed, etc.), the deploy key is a meaningful credential. Same revocation guidance applies — delete from GitHub repo settings, then `rm` the local key files.
- **Don't generalize to the user's GitHub account.** This skill explicitly uses deploy keys (repo-scoped) rather than adding to the user's account. The reasoning: a passphrase-less account-scoped key would have full account access, defeating the blast-radius mitigation.

## Notes

- The naming convention `id_ed25519_claude_<repo>` is intentional — it makes the keypair self-identifying when listing `~/.ssh/`. Avoid generic names like `id_ed25519_claude` because those don't disambiguate when set up across multiple repos.
- If the user later wants to share a Claude Code deploy key across multiple repos in the same organization, they can either run this skill in each repo (cleanest blast radius) OR generate one key and add it as a deploy key in each repo separately (lower setup overhead but worse blast radius).
- This skill is **macOS / Linux first**. On Windows, paths and command syntax may differ; ssh-keygen invocation is the same but file perms and SSH agent integration vary.
