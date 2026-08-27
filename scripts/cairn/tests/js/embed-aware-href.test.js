"use strict";

// PT-55 (Validate-phase fix): team-lead's browser-tested repro found that
// clicking the board's own Kanban/List view tabs inside the dashboard's
// embedded frame lost `?embed=1` entirely -- board.html's static
// `<a href="/">`/`<a href="/list">` markup carries no query string, so
// navigating dropped embed mode the instant a viewer switched views,
// un-suppressing the wordmark/#tab-dashboard one click after they were
// hidden. `embedAwareHref(path, embedOn)` is the pure fix: appends
// `?embed=1` to `path` when `embedOn` is true, returns `path` unchanged
// otherwise. board.js calls it once in `init()` to rewrite both tabs'
// `href`s when `isEmbedMode` is true.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadCairnLogic } = require("./helpers.js");

const CairnLogic = loadCairnLogic();

test("embedOn true appends ?embed=1 to the kanban root path", () => {
  assert.equal(CairnLogic.embedAwareHref("/", true), "/?embed=1");
});

test("embedOn true appends ?embed=1 to the list path", () => {
  assert.equal(CairnLogic.embedAwareHref("/list", true), "/list?embed=1");
});

test("embedOn false returns the path unchanged", () => {
  assert.equal(CairnLogic.embedAwareHref("/", false), "/");
  assert.equal(CairnLogic.embedAwareHref("/list", false), "/list");
});

test("round-trips through isEmbedMode -- the produced href reads back as embed mode on", () => {
  const href = CairnLogic.embedAwareHref("/list", true);
  const search = href.slice(href.indexOf("?"));
  assert.equal(CairnLogic.isEmbedMode(search), true);
});
