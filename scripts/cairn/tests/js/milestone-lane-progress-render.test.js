"use strict";

// PT-44 (joint PT-40/43/44 ruling §2/§3), remaining render-layer wiring
// not yet covered elsewhere in this suite -- milestoneLaneEl's status
// pill/progress-branch/release-chip/GA-chip, repoSectionEl/renderKanban
// calling appendMilestoneOnlyLanes, renderList's clickable milestone
// column, and renderRecordDrawer's isComplete/release-chip extension.
//
// Source-text guards, same brace-matching-extractor technique as the
// rest of this suite's board.js coverage (no jsdom). Anchored loosely
// (presence-within-function-body, not exact structural pins) where the
// exact element shape wasn't confirmed by implementation-lead before
// writing this -- team-lead's standing convention for this loop: if the
// implemented shape differs, these get reconciled together, same as
// PT-40's mid-flight signature updates.
//
// Nothing under test exists yet for any of these pieces (verified
// directly against the current board.js source before writing each
// anchor). Every test below is expected to fail until implementation-
// lead's remaining PT-44 slice lands.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BOARD_JS_PATH = path.join(__dirname, "..", "..", "board", "board.js");

class ExtractionError extends Error {}

function extractFunctionBody(source, functionName) {
  var match = source.match(new RegExp("function\\s+" + functionName + "\\s*\\([^)]*\\)\\s*\\{"));
  if (!match) {
    throw new ExtractionError(
      "could not find `function " + functionName + "(...) {` in board.js -- if this " +
        "function was renamed or restructured, this guard needs to be updated, not silenced."
    );
  }
  var start = match.index + match[0].length;
  var depth = 1;
  var i = start;
  for (; i < source.length && depth > 0; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}") depth--;
  }
  if (depth !== 0) {
    throw new ExtractionError("unbalanced braces while extracting `" + functionName + "`'s body.");
  }
  return source.slice(start, i - 1);
}

function readSource() {
  return fs.readFileSync(BOARD_JS_PATH, "utf8");
}

// ================= milestoneLaneEl: status pill, progress, chips =================

test("PT-44 §2/§3: milestoneLaneEl renders a status pill via recordStatusLabel", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "milestoneLaneEl");
  assert.match(body, /recordStatusLabel\(/, "expected a recordStatusLabel(...) call inside milestoneLaneEl");
});

test("PT-44 §3: milestoneLaneEl branches on isComplete for the progress display (no ratio when done/cancelled)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "milestoneLaneEl");
  assert.match(body, /isComplete/, "expected an isComplete branch inside milestoneLaneEl");
});

test("PT-44 §4: milestoneLaneEl renders a release chip via releaseChipLabel", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "milestoneLaneEl");
  assert.match(body, /releaseChipLabel\(/, "expected a releaseChipLabel(...) call inside milestoneLaneEl");
});

test('PT-44 §2: milestoneLaneEl renders a GA chip ("moves from the strip to the lane header")', () => {
  const source = readSource();
  const body = extractFunctionBody(source, "milestoneLaneEl");
  assert.match(body, /\.ga/, "expected milestoneLaneEl to read the milestone record's .ga field");
  assert.match(body, /"GA"/, 'expected a "GA" chip text inside milestoneLaneEl');
});

// ================= appendMilestoneOnlyLanes call sites =================

test("PT-44 §2: repoSectionEl calls appendMilestoneOnlyLanes after groupByMilestone (empty lanes for issue-less milestones)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "repoSectionEl");
  assert.match(body, /groupByMilestone\(/, "sanity: repoSectionEl must still call groupByMilestone");
  assert.match(body, /appendMilestoneOnlyLanes\(/, "expected repoSectionEl to call appendMilestoneOnlyLanes");
});

test("PT-44 §2: renderKanban's single-root branch calls appendMilestoneOnlyLanes after groupByMilestone", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderKanban");
  assert.match(body, /groupByMilestone\(/, "sanity: renderKanban must still call groupByMilestone");
  assert.match(body, /appendMilestoneOnlyLanes\(/, "expected renderKanban to call appendMilestoneOnlyLanes");
});

// ================= renderKanban: no empty shells, but not over-eager either =================
//
// implementation-lead's own finding (2026-08-23, PT-44 completion
// message), beyond what I'd verified directly before their pass: the
// multi-root branch's "nothing to show, skip this repo/board entirely"
// fast-paths originally checked ONLY issue counts -- a repo/board with
// real milestones but ZERO live issues (the exact fully-archived-away
// scenario this whole feature exists for) would have been dropped
// entirely, even with appendMilestoneOnlyLanes wired into repoSectionEl,
// since repoSectionEl itself would never get CALLED for it. Pinned here
// as the permanent regression guard for that fix.

test("PT-44 §2: renderKanban's multi-root empty-board fast-path also checks for milestones under the active major tab", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderKanban");
  // Anchored on the SPECIFIC widened condition, not just "the word
  // milestones appears somewhere" -- the fast-path's guard must combine
  // BOTH the issue-count check and a milestones check (else a milestone-
  // only, issue-less multi-root board still renders the empty-state message).
  assert.match(
    body,
    /issues\.length\s*===\s*0\s*&&\s*!\s*any\w*Milestones\w*/i,
    "expected the top-level empty-board fast-path to also check for milestones " +
      "(not just issues.length === 0) before rendering the empty-state message"
  );
});

test("PT-44 §2: renderKanban's per-repo skip also checks for that repo's milestones under the active major tab", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderKanban");
  assert.match(
    body,
    /repoIssues\.length\s*===\s*0\s*&&\s*!\s*repo\w*Milestones\w*/i,
    "expected the per-repo skip to also check for that repo's milestones " +
      "(not just repoIssues.length === 0) before skipping the repo entirely"
  );
});

// ================= renderList: clickable milestone column =================

test("PT-44 §2: renderList's milestone column opens the milestone's card, other columns stay plain", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderList");
  assert.match(
    body,
    /col\.key\s*===\s*"milestone"/,
    'expected renderList to branch on col.key === "milestone"'
  );
  assert.match(
    body,
    /openRecordDrawer\(\s*"milestone"/,
    'expected the milestone column branch to call openRecordDrawer("milestone", ...)'
  );
  assert.match(
    body,
    /stopPropagation\(\)/,
    "expected e.stopPropagation() on the milestone cell's click (so it doesn't also fire the row's own openDrawer)"
  );
});

// ================= renderRecordDrawer: isComplete + release chip =================

test("PT-44 §3: renderRecordDrawer's progress line branches on isComplete (✓ Done vs n/m)", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /isComplete/, "expected renderRecordDrawer to branch on isComplete for the progress line");
});

test("PT-44 §4: renderRecordDrawer renders a release chip via releaseChipLabel", () => {
  const source = readSource();
  const body = extractFunctionBody(source, "renderRecordDrawer");
  assert.match(body, /releaseChipLabel\(/, "expected renderRecordDrawer to call releaseChipLabel(...)");
});
