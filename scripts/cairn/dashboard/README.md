# Project Dashboard (PT-54)

A real Svelte 5 + Tailwind v4 + shadcn-svelte SPA, served by the cairn
board server (`scripts/cairn/cairn.py`) at `/dashboard`. Not SvelteKit —
plain Vite, since there's no SSR/routing need here: the Python server is
the backend. See the PT-54 architect ruling
(`process/cairn/issues/PT-54.md`) for the full rationale on every
decision below.

## Stack

- Svelte 5 + TypeScript, plain Vite (no SvelteKit)
- Tailwind CSS v4 (`@tailwindcss/vite`)
- shadcn-svelte (Style **Mira**, Base **Stone**, preset `b6XadDxmQS` — see
  `docs/DESIGN/design-system-spec.md`)
- Fonts: self-hosted via `@fontsource-variable/*` (Merriweather, Space
  Grotesk, Geist Mono) — no CDN, ever. Imported as JS side-effect imports
  in `src/main.ts`, not a CSS `@import` (keeps `@import "tailwindcss";`
  first in `app.css`, which Tailwind v4 requires).

## Local development

```sh
npm ci
npm run dev
```

`vite.config.ts` proxies `/api/*` to `http://127.0.0.1:8766`, so run the
real board server alongside (`python3 ../cairn.py serve` from
`scripts/cairn/`, or `scripts/cairn/cairn serve` from the repo root) to
develop against real repo/tracker data instead of nothing.

`npm run check` runs `svelte-check` + a `tsc` project-reference check —
this is the app-side gate for this feature (no vitest/testing-library
yet; a component-test harness is a follow-up once there's component logic
worth testing beyond what `svelte-check` + `npm run build` already catch).

## Build output is committed

**`dist/` is committed to the repo** (the root `.gitignore`'s `dist/`
rule is explicitly negated for this path) — this is the one deliberate
exception to "build artifacts aren't committed" in this template.

Why: the template's strongest property is that a fresh clone runs
`python3 scripts/cairn/cairn serve` with nothing but python3. Requiring
`npm ci` before `/dashboard` renders would break that for every cloner,
on the one surface most meant to be seen immediately. When `dist/` is
missing or stale, `cairn serve` does **not** build it for you — `/dashboard`
returns a 503 naming the fix (`npm ci && npm run build`), while
`/api/dashboard` keeps working (it's pure Python, no build dependency).

Filenames are unhashed (`vite.config.ts`'s `rollupOptions.output.*FileNames`,
set to stable `[name]` forms) — the server already sends
`Cache-Control: no-store` on every asset, so a content hash would buy
nothing while making the committed `dist/` grow with every rebuild.

**Discipline: any PR touching dashboard source rebuilds and commits `dist/`
in the same PR.** Run `npm run build` and commit the diff. There is no
automated staleness check yet (a `dist` vs. `src` mtime check at
`/finish-feature` time is a reasonable, not-yet-built follow-up) — this is
an honor-system cost accepted at design time, same class as the vendored
Mermaid bundle.

## Two Vite settings that are load-bearing, not incidental

- `base: '/dashboard/'` — every emitted asset URL must be absolute under
  the prefix the board server mounts this app at.
- `build.rollupOptions.output.{entryFileNames,chunkFileNames,assetFileNames}`
  — stable filenames, no content hash (see above).

Don't "clean up" either of these without re-reading the PT-54 ruling.
