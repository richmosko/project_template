"use strict";

// PT-79 AC4: the issue drawer's token/cost totals. Ruling §6
// (process/cairn/issues/PT-79.md, 3836ce6): "The issue drawer is
// scripts/cairn/board/board.js, not the Svelte app... Drawer shows the
// issue's four token counters, its cost_usd, and the per-role split.
// Fetched from the same /api/tokens payload, filtered client-side by
// issue id -- no second endpoint."
//
// Proposed function (negotiable, same posture as every other from-
// scratch surface in this repo -- see board-logic.js/INTERFACE.md's own
// "if you find this awkward, rename it" instruction):
//
//   CairnLogic.tokenTotalsForIssue(tokensPayload, issueId)
//     -> {input, cache_write, cache_read, output, cost_usd, roles: [...]}
//        | null (also null for issueId "main" -- not a real issue, see
//        the dedicated test below for the reasoning)
//
// A pure client-side filter over the SAME /api/tokens payload shape
// test_tokens_api.py pins server-side -- no network call in this
// function, board.js's own fetch wiring is a separate (untested-here)
// concern, matching the PT-22 pure-logic/render-glue split.
//
// Nothing under test exists yet: board-logic.js has no
// tokenTotalsForIssue export at all.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

function samplePayload() {
  return {
    issues: [
      {
        issue: "PT-5",
        total: { input: 150, cache_write: 15, cache_read: 30, output: 7, cost_usd: 1.23 },
        roles: [
          { role: "backend-lead", input: 100, cache_write: 10, cache_read: 20, output: 5, cost_usd: 0.9 },
          { role: "qa-engineer", input: 50, cache_write: 5, cache_read: 10, output: 2, cost_usd: 0.33 },
        ],
      },
      {
        issue: "main",
        total: { input: 999, cache_write: 99, cache_read: 199, output: 50, cost_usd: 12.0 },
        roles: [{ role: "team-lead", input: 999, cache_write: 99, cache_read: 199, output: 50, cost_usd: 12.0 }],
      },
    ],
    window_start: "2026-08-18",
    window_end: "2026-09-04",
    generated: "2026-09-04T02:18:03Z",
    sources: ["transcript-backfill"],
    prices: { retrieved: "2026-09-04", source: "https://example.invalid", unpriced_models: [] },
    warning: null,
  };
}

test("tokenTotalsForIssue exists on CairnLogic", () => {
  assert.equal(
    typeof CairnLogic.tokenTotalsForIssue,
    "function",
    "CairnLogic.tokenTotalsForIssue does not exist yet -- PT-79 AC4's ruled drawer " +
      "totals (process/cairn/issues/PT-79.md, 3836ce6, ruling §6) are unimplemented"
  );
});

test("returns the matching issue's total counters, cost, and role split", () => {
  var payload = samplePayload();
  var result = CairnLogic.tokenTotalsForIssue(payload, "PT-5");
  assert.ok(result, "expected a non-null result for an issue present in the payload");
  assert.equal(result.input, 150);
  assert.equal(result.cache_write, 15);
  assert.equal(result.cache_read, 30);
  assert.equal(result.output, 7);
  assert.equal(result.cost_usd, 1.23);
  assert.equal(result.roles.length, 2);
  var roleNames = result.roles.map(function (r) { return r.role; }).sort();
  assert.deepEqual(roleNames, ["backend-lead", "qa-engineer"]);
});

test("returns null for an issue not present in the payload -- never fabricates zeros", () => {
  var payload = samplePayload();
  var result = CairnLogic.tokenTotalsForIssue(payload, "PT-999-not-in-payload");
  assert.equal(
    result,
    null,
    "an issue absent from the /api/tokens payload must return null, not a fabricated " +
      "all-zero totals object -- a drawer showing '0 tokens' for an issue with no data " +
      "at all is indistinguishable from an issue that genuinely used zero tokens"
  );
});

test("the 'main' bucket is excluded by this function -- defense in depth alongside the chart's own click-guard", () => {
  // Judgment call, resolved by observing the actual implementation
  // rather than insisting on my own prior assumption: board.js's own
  // issue cards never represent "main" (it isn't a real issue in the
  // Kanban board at all), so this function is never realistically
  // called with "main" from the drawer's normal flow -- but excluding
  // it here too is a defensible, ruling-compliant defense-in-depth
  // choice (ruling §4: "no drawer link... must not look clickable"),
  // not a violation of anything the ruling pins. Matches
  // implementation-lead's actual choice, verified against their
  // in-progress board-logic.js.
  var payload = samplePayload();
  var result = CairnLogic.tokenTotalsForIssue(payload, "main");
  assert.equal(result, null, "tokenTotalsForIssue excludes 'main' -- it is not a real issue and must never be treated as one, even defensively");
});

test("does not mutate the payload it was given", () => {
  var payload = samplePayload();
  var before = JSON.stringify(payload);
  CairnLogic.tokenTotalsForIssue(payload, "PT-5");
  var after = JSON.stringify(payload);
  assert.equal(before, after, "tokenTotalsForIssue must not mutate its input payload");
});
