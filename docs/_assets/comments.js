// docs/_assets/comments.js
//
// Inline comment widget for the HTML docs (PRD / ARCH / SECURITY / DESIGN).
//
// Requires the local server (scripts/serve-docs.sh) running at
// http://localhost:8765/. When served from there, this widget:
//   - fetches existing comments from /api/comments?doc=<DOC>
//   - shows a small "💬 N" count next to any <section> that has comments
//   - shows a "+ Comment" button next to each <section> heading on hover
//   - opens an inline panel under the heading for adding a new comment
//   - POSTs new comments to /api/comments → appends to docs/<DOC>/comments.md
//
// When opened via file:// (no server), the widget degrades gracefully —
// shows a small status indicator explaining how to enable inline comments.
//
// See WORKFLOW.md → "Doc review loop" for the full pattern.

(function () {
  "use strict";

  // Detect doc name from the URL path: /PRD/, /ARCH/, /SECURITY/, /DESIGN/
  const docMatch = window.location.pathname.match(/\/(PRD|ARCH|SECURITY|DESIGN)\//);
  if (!docMatch) return; // not a recognized doc — bail silently
  const DOC = docMatch[1];

  const API = window.location.origin + "/api/comments";
  /** @type {Object<string, Array<{section: string, body: string}>>} */
  let commentsBySection = {};
  let serverOnline = false;

  // ── Status indicator (small persistent corner badge) ─────────────────────

  function createStatusIndicator() {
    const el = document.createElement("div");
    el.id = "comments-status";
    el.className = "comments-status";
    el.innerHTML = '<span class="dot"></span><span class="label">checking…</span>';
    document.body.appendChild(el);
  }

  function setStatus(online, message) {
    serverOnline = online;
    const el = document.getElementById("comments-status");
    if (!el) return;
    el.classList.toggle("online", online);
    el.classList.toggle("offline", !online);
    el.querySelector(".label").textContent = message;
  }

  // ── Loading + rendering ──────────────────────────────────────────────────

  async function loadComments() {
    try {
      const res = await fetch(`${API}?doc=${DOC}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      commentsBySection = {};
      (data.comments || []).forEach((c) => {
        if (!commentsBySection[c.section]) commentsBySection[c.section] = [];
        commentsBySection[c.section].push(c);
      });
      const total = (data.comments || []).length;
      setStatus(true, total === 0 ? "connected (no comments yet)" : `connected (${total} comment${total === 1 ? "" : "s"})`);
      return true;
    } catch (err) {
      setStatus(false, "offline — run ./scripts/serve-docs.sh");
      return false;
    }
  }

  function renderSectionWidgets() {
    // Clear any previous widget controls (re-render after a save)
    document.querySelectorAll(".comments-controls").forEach((el) => el.remove());

    const sections = document.querySelectorAll("section[id]");
    sections.forEach((section) => {
      const id = section.id;
      const heading = section.querySelector("h2, h3");
      if (!heading) return;

      const existing = commentsBySection[id] || [];
      const controls = document.createElement("span");
      controls.className = "comments-controls";

      // Count badge — only shown when comments exist
      if (existing.length > 0) {
        const badge = document.createElement("button");
        badge.className = "comments-count";
        badge.title = `${existing.length} comment${existing.length === 1 ? "" : "s"} on this section — click to view`;
        badge.innerHTML = `💬 ${existing.length}`;
        badge.addEventListener("click", (e) => {
          e.stopPropagation();
          openPanel(section, id, /* showExisting */ true);
        });
        controls.appendChild(badge);
      }

      // "+ Comment" button — hidden by default, visible on heading hover
      const addBtn = document.createElement("button");
      addBtn.className = "comments-add-btn";
      addBtn.textContent = "+ Comment";
      addBtn.title = "Add a review comment to this section";
      addBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openPanel(section, id, /* showExisting */ existing.length > 0);
      });
      controls.appendChild(addBtn);

      heading.appendChild(controls);
    });
  }

  // ── Inline panel ─────────────────────────────────────────────────────────

  function openPanel(section, sectionId, showExisting) {
    // Close any other open panel
    document.querySelectorAll(".comments-panel").forEach((p) => p.remove());

    const panel = document.createElement("div");
    panel.className = "comments-panel";
    panel.dataset.section = sectionId;

    // Existing comments list (read-only)
    const existing = commentsBySection[sectionId] || [];
    if (showExisting && existing.length > 0) {
      const list = document.createElement("div");
      list.className = "comments-existing";
      const label = document.createElement("div");
      label.className = "comments-existing-label";
      label.textContent = `${existing.length} existing comment${existing.length === 1 ? "" : "s"} (edit via comments.md):`;
      list.appendChild(label);
      existing.forEach((c) => {
        const item = document.createElement("div");
        item.className = "comments-existing-item";
        item.textContent = c.body;
        list.appendChild(item);
      });
      panel.appendChild(list);
    }

    // New-comment textarea
    const textarea = document.createElement("textarea");
    textarea.className = "comments-textarea";
    textarea.placeholder = `Add a comment to §${sectionId}…`;
    textarea.rows = 4;
    panel.appendChild(textarea);

    // Buttons
    const buttons = document.createElement("div");
    buttons.className = "comments-buttons";

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "comments-cancel-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", () => panel.remove());

    const saveBtn = document.createElement("button");
    saveBtn.className = "comments-save-btn";
    saveBtn.textContent = "Save";
    saveBtn.addEventListener("click", () => saveComment(sectionId, textarea, panel, saveBtn));

    buttons.appendChild(cancelBtn);
    buttons.appendChild(saveBtn);
    panel.appendChild(buttons);

    // Insert after the section heading
    const heading = section.querySelector("h2, h3");
    heading.insertAdjacentElement("afterend", panel);

    textarea.focus();

    // Cmd/Ctrl+Enter to save
    textarea.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        saveComment(sectionId, textarea, panel, saveBtn);
      } else if (e.key === "Escape") {
        e.preventDefault();
        panel.remove();
      }
    });
  }

  async function saveComment(sectionId, textarea, panel, saveBtn) {
    const body = textarea.value.trim();
    if (!body) {
      panel.remove();
      return;
    }
    if (!serverOnline) {
      alert("Comment server is offline. Run ./scripts/serve-docs.sh to enable inline comments.");
      return;
    }
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving…";
    try {
      const res = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc: DOC, section: sectionId, body }),
      });
      if (!res.ok) {
        const errPayload = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        throw new Error(errPayload.error || `HTTP ${res.status}`);
      }
      panel.remove();
      await loadComments();
      renderSectionWidgets();
    } catch (err) {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
      alert(`Save failed: ${err.message}`);
    }
  }

  // ── Bootstrap ────────────────────────────────────────────────────────────

  window.addEventListener("DOMContentLoaded", async () => {
    createStatusIndicator();

    // The widget only activates when served from localhost
    const isLocalhost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    if (!isLocalhost) {
      setStatus(false, "open via http://localhost:8765/ to enable comments");
      return;
    }

    const ok = await loadComments();
    if (ok) renderSectionWidgets();
  });
})();
