// docs/_assets/toc.js
//
// Two small enhancements for the HTML docs (PRD / ARCH / SECURITY / DESIGN):
//
//   1. Scroll-spy — highlights the nav.toc link for the section currently in
//      view (adds/removes `.active`). Pairs with the sticky TOC rail in
//      doc.css so long docs always show "where am I".
//
//   2. Print/PDF expansion — force-opens every <details> before printing (and
//      before headless-Chrome PDF export, which fires the same beforeprint
//      event) so collapsed content isn't silently dropped from the snapshot,
//      then restores the prior open/closed state afterward.
//
// No dependencies, no network. Safe on file:// and localhost alike.

(function () {
  "use strict";

  // ── 1. Scroll-spy ──────────────────────────────────────────────────────────
  function initScrollSpy() {
    var toc = document.querySelector("nav.toc");
    if (!toc || !("IntersectionObserver" in window)) return;

    var links = Array.prototype.slice.call(toc.querySelectorAll('a[href^="#"]'));
    var linkById = {};
    var targets = []; // in document order
    links.forEach(function (a) {
      var id = decodeURIComponent(a.getAttribute("href").slice(1));
      var el = id && document.getElementById(id);
      if (el) {
        linkById[id] = a;
        targets.push(el);
      }
    });
    if (!targets.length) return;

    var active = null;
    function setActive(id) {
      if (id === active) return;
      active = id;
      links.forEach(function (a) { a.classList.remove("active"); });
      if (linkById[id]) linkById[id].classList.add("active");
    }

    var visible = {};
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) visible[e.target.id] = true;
          else delete visible[e.target.id];
        });
        // Highlight the topmost section currently in the viewport band.
        for (var i = 0; i < targets.length; i++) {
          if (visible[targets[i].id]) { setActive(targets[i].id); return; }
        }
      },
      // Trigger when a section's top reaches the upper ~30% of the viewport.
      { rootMargin: "0px 0px -70% 0px", threshold: 0 }
    );
    targets.forEach(function (t) { observer.observe(t); });
  }

  // ── 2. Expand <details> for print / PDF export ──────────────────────────────
  function initPrintExpand() {
    var saved = [];
    window.addEventListener("beforeprint", function () {
      saved = [];
      document.querySelectorAll("details").forEach(function (d) {
        saved.push([d, d.open]);
        d.open = true;
      });
    });
    window.addEventListener("afterprint", function () {
      saved.forEach(function (pair) { pair[0].open = pair[1]; });
      saved = [];
    });
  }

  // ── 3. Theme toggle (Auto / Light / Dark) ───────────────────────────────────
  // tokens.css themes on prefers-color-scheme plus explicit `.light` / `.dark`
  // classes on <html>. This adds a corner button that cycles Auto → Light → Dark
  // and remembers the choice in localStorage. "Auto" removes both classes and
  // falls back to the OS setting.
  function initThemeToggle() {
    var KEY = "doc-theme";
    var root = document.documentElement;
    var ORDER = ["auto", "light", "dark"];

    function stored() {
      var v = null;
      try { v = localStorage.getItem(KEY); } catch (e) {}
      return v === "light" || v === "dark" ? v : "auto";
    }
    function apply(mode) {
      root.classList.remove("light", "dark");
      if (mode === "light" || mode === "dark") root.classList.add(mode);
    }
    function effective(mode) {
      if (mode !== "auto") return mode;
      return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    apply(stored());

    var btn = document.createElement("button");
    btn.className = "theme-toggle";
    btn.type = "button";

    function render() {
      var mode = stored();
      var label = { auto: "◐ Auto", light: "☀ Light", dark: "☾ Dark" }[mode];
      btn.textContent = label;
      btn.title = "Theme: " + mode + " (showing " + effective(mode) + ") — click to cycle Auto → Light → Dark";
      btn.setAttribute("aria-label", btn.title);
    }

    btn.addEventListener("click", function () {
      var next = ORDER[(ORDER.indexOf(stored()) + 1) % ORDER.length];
      try {
        if (next === "auto") localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, next);
      } catch (e) {}
      apply(next);
      render();
    });

    render();
    document.body.appendChild(btn);

    // Keep the label's "(showing …)" hint fresh if the OS theme changes in Auto.
    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
    }
  }

  window.addEventListener("DOMContentLoaded", function () {
    initScrollSpy();
    initPrintExpand();
    initThemeToggle();
  });
})();
