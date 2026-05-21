// Loads Mermaid from CDN and initializes it with theme-aware config.
// Used by docs/PRD.html, docs/ARCH.html, docs/SECURITY.html.

(function () {
  var script = document.createElement("script");
  script.type = "module";
  script.textContent = [
    'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";',
    'var darkMode = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;',
    'mermaid.initialize({',
    '  startOnLoad: true,',
    '  theme: darkMode ? "dark" : "default",',
    '  securityLevel: "loose",',
    '  flowchart: { curve: "basis" },',
    '  themeVariables: {',
    '    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Inter, system-ui, sans-serif"',
    '  }',
    '});',
    'window.addEventListener("DOMContentLoaded", function () { mermaid.run(); });',
    'window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {',
    '  document.querySelectorAll(".mermaid").forEach(function (el) {',
    '    el.removeAttribute("data-processed");',
    '    el.innerHTML = el.dataset.source || el.textContent;',
    '  });',
    '  location.reload();',
    '});'
  ].join("\n");
  document.head.appendChild(script);

  // Cache raw mermaid source before mermaid mutates it (used on theme switch).
  window.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".mermaid").forEach(function (el) {
      if (!el.dataset.source) el.dataset.source = el.textContent;
    });
  });
})();
