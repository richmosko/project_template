// Loads Mermaid from CDN and themes every diagram from the design-system tokens
// (docs/DESIGN/tokens.css): the amber CHART palette for nodes (chart-1 fill,
// chart-3 outline), the full chart ramp for series/pie, muted neutrals for edges.
// (Table headers carry the lime primary; diagrams carry the charts.)
//
// Mermaid's color parser (khroma) doesn't understand OKLCH, so we resolve each
// token to sRGB hex via a temp element + canvas before handing it over. Diagrams
// re-render on light/dark changes — both the OS scheme and the .light/.dark
// class toggled by toc.js.
//
// Used by docs/{PRD,ARCH,SECURITY,DESIGN}/index.html.

(function () {
  // This <script defer> runs after the DOM is parsed but before Mermaid loads,
  // so .mermaid elements still hold their RAW source here. Capture it now — once
  // Mermaid renders, textContent becomes SVG and the source is lost.
  document.querySelectorAll(".mermaid").forEach(function (el) {
    if (el.dataset.source == null) el.dataset.source = el.textContent;
  });

  var mod = [
    'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";',
    '',
    '// Disable auto-run immediately: the import may resolve after DOMContentLoaded,',
    '// so we drive rendering explicitly (and re-drive it on theme changes).',
    'mermaid.initialize({ startOnLoad: false });',
    '',
    '// Resolve any CSS color expression (var(), color-mix(), oklch()) to sRGB hex.',
    'function toHex(expr) {',
    '  var el = document.createElement("span");',
    '  el.style.color = expr; el.style.position = "absolute"; el.style.opacity = "0";',
    '  document.body.appendChild(el);',
    '  var resolved = getComputedStyle(el).color;',
    '  el.remove();',
    '  var cv = document.createElement("canvas"); cv.width = cv.height = 1;',
    '  var ctx = cv.getContext("2d", { willReadFrequently: true });',
    '  ctx.fillStyle = "#000"; ctx.fillStyle = resolved; ctx.fillRect(0, 0, 1, 1);',
    '  var d = ctx.getImageData(0, 0, 1, 1).data;',
    '  return "#" + [d[0], d[1], d[2]].map(function (x) { return ("0" + x.toString(16)).slice(-2); }).join("");',
    '}',
    '',
    'function themeVars() {',
    '  // Nodes use the CHART (amber) palette: chart-1 fill + dark text, outlined in',
    '  // the same muted color as the edges/arrows. (Table headers carry lime.)',
    '  var onAmber = toHex("var(--color-on-warning)");',
    '  var fg     = toHex("var(--color-text)");',
    '  var line   = toHex("var(--color-text-muted)");',
    '  var card   = toHex("var(--color-surface-raised)");',
    '  var muted  = toHex("var(--color-surface-muted)");',
    '  var border = toHex("var(--color-border)");',
    '  var c1 = toHex("var(--chart-1)"), c2 = toHex("var(--chart-2)"), c3 = toHex("var(--chart-3)"),',
    '      c4 = toHex("var(--chart-4)"), c5 = toHex("var(--chart-5)");',
    '  var c2bg = toHex("color-mix(in srgb, var(--chart-2) 16%, var(--color-surface-raised))");',
    '  var c3bg = toHex("color-mix(in srgb, var(--chart-3) 16%, var(--color-surface-raised))");',
    '  return {',
    '    darkMode: window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches,',
    '    fontFamily: "Inter, system-ui, -apple-system, sans-serif",',
    '    background: card,',
    '    primaryColor: c1, primaryBorderColor: line, primaryTextColor: onAmber,',
    '    secondaryColor: c2bg, secondaryBorderColor: line, secondaryTextColor: fg,',
    '    tertiaryColor: c3bg, tertiaryBorderColor: line, tertiaryTextColor: fg,',
    '    mainBkg: c1, nodeBorder: line, nodeTextColor: onAmber,',
    '    lineColor: line, textColor: fg, titleColor: fg,',
    '    clusterBkg: muted, clusterBorder: border,',
    '    edgeLabelBackground: card,',
    '    pie1: c1, pie2: c2, pie3: c3, pie4: c4, pie5: c5,',
    '    actorBorder: line, actorBkg: c1, actorTextColor: onAmber,',
    '    signalColor: line, signalTextColor: fg,',
    '    labelBoxBkgColor: c1, labelBoxBorderColor: line, labelTextColor: onAmber,',
    '    loopTextColor: fg, noteBkgColor: c2bg, noteBorderColor: line, noteTextColor: fg',
    '  };',
    '}',
    '',
    'function render() {',
    '  document.querySelectorAll(".mermaid").forEach(function (el) {',
    '    if (el.dataset.source != null) el.innerHTML = el.dataset.source;',
    '    el.removeAttribute("data-processed");',
    '  });',
    '  var tv = themeVars();',
    '  try { window.__mermaidThemeVars = tv; } catch (e) {}   // read by scripts/print-pdf.mjs for PDF export',
    '  mermaid.initialize({',
    '    startOnLoad: false,',
    '    securityLevel: "loose",',
    '    theme: "base",',
    '    // SVG <text> labels (not HTML <foreignObject>) so diagrams render in',
    '    // print/PDF output — Chrome does not paint foreignObject when printing.',
    '    htmlLabels: false,',
    '    // useMaxWidth:false gives the <svg> explicit width AND height attributes',
    '    // (not width:100% / no height), which Chrome needs to paint it when printing.',
    '    flowchart: { curve: "basis", htmlLabels: false, useMaxWidth: false },',
    '    sequence: { useMaxWidth: false }, gantt: { useMaxWidth: false }, er: { useMaxWidth: false },',
    '    themeVariables: tv',
    '  });',
    '  mermaid.run().catch(function (e) { console.warn("mermaid render error", e); });',
    '}',
    '',
    'if (document.readyState === "loading") {',
    '  document.addEventListener("DOMContentLoaded", render);',
    '} else {',
    '  render();',
    '}',
    '',
    '// Re-theme on OS scheme change and on explicit .light/.dark class toggles.',
    'if (window.matchMedia) {',
    '  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);',
    '}',
    'new MutationObserver(render).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });'
  ].join("\n");

  var s = document.createElement("script");
  s.type = "module";
  s.textContent = mod;
  document.head.appendChild(s);
})();
