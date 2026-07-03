#!/usr/bin/env node
// print-pdf.mjs — render a URL to PDF, waiting until Mermaid diagrams have
// actually rendered before capturing.
//
// Why this exists: `chrome --headless --print-to-pdf` snapshots the page before
// Mermaid's async render (it lazy-loads its diagram renderer at runtime), so
// diagrams come out blank. This drives Chrome over the DevTools Protocol and
// polls until every .mermaid element contains an <svg> (and webfonts are ready),
// then prints — deterministic, no timing guesswork.
//
// Uses Node's built-in WebSocket + child_process (Node >= 22). No npm deps.
//
// Usage: node print-pdf.mjs <chrome-binary> <url> <out.pdf>

import { spawn, execFileSync } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { writeFileSync, readFileSync, rmSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";

const [, , chromePath, url, outPath] = process.argv;
if (!chromePath || !url || !outPath) {
  console.error("usage: print-pdf.mjs <chrome-binary> <url> <out.pdf>");
  process.exit(2);
}

const userDataDir = `/tmp/print-pdf-${process.pid}-${Date.now()}`;
let chrome, ws;
let servedPngs = []; // temp PNGs written into the served docs dir
function cleanup() {
  try { ws && ws.close(); } catch {}
  try { chrome && chrome.kill("SIGTERM"); } catch {}
  try { rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  try { servedPngs.forEach((p) => rmSync(p, { force: true })); } catch {}
}
function fail(msg) { console.error(msg); cleanup(); process.exit(1); }

// ── Launch headless Chrome with a debugging endpoint ────────────────────────
chrome = spawn(chromePath, [
  "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
  "--no-default-browser-check", "--disable-background-networking",
  `--user-data-dir=${userDataDir}`, "--remote-debugging-port=0", "about:blank",
], { stdio: ["ignore", "ignore", "pipe"] });

const wsUrl = await new Promise((resolve, reject) => {
  let buf = "";
  const to = setTimeout(() => reject(new Error("timeout waiting for DevTools endpoint")), 20000);
  chrome.stderr.on("data", (d) => {
    buf += d.toString();
    const m = buf.match(/ws:\/\/[^\s]+\/devtools\/browser\/[a-f0-9-]+/);
    if (m) { clearTimeout(to); resolve(m[0]); }
  });
  chrome.on("exit", (c) => { clearTimeout(to); reject(new Error(`chrome exited early (${c})`)); });
}).catch((e) => fail(String(e.message || e)));

// ── Minimal CDP client over the browser WebSocket ───────────────────────────
let msgId = 0;
const pending = new Map();
ws = new WebSocket(wsUrl);
await new Promise((res, rej) => { ws.addEventListener("open", res); ws.addEventListener("error", rej); })
  .catch(() => fail("failed to open DevTools WebSocket"));
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const { resolve, reject } = pending.get(m.id);
    pending.delete(m.id);
    m.error ? reject(new Error(m.error.message)) : resolve(m.result);
  }
});
function send(method, params = {}, sessionId) {
  const id = ++msgId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
}

try {
  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  const S = (method, params) => send(method, params, sessionId);

  await S("Page.enable");
  await S("Runtime.enable");
  await S("Page.navigate", { url });

  // Wait (real time) for the target page to load and mermaid-init to have run.
  // We don't need the INLINE diagrams to finish rendering — they're replaced
  // below — only dataset.source (set synchronously at parse) and the computed
  // __mermaidThemeVars (set at the top of render()). The http:// guard skips the
  // initial about:blank context.
  const READY =
    "(function(){" +
    "if(!/^https?:/.test(location.href))return false;" +
    "if(document.readyState!=='complete')return false;" +
    "var m=document.querySelectorAll('.mermaid');if(m.length===0)return true;" +
    "return !!window.__mermaidThemeVars&&[].every.call(m,function(e){return e.dataset.source!=null;});})()";
  const deadline = Date.now() + 30000;
  let ready = false;
  while (Date.now() < deadline) {
    const r = await S("Runtime.evaluate", { expression: READY, returnByValue: true });
    if (r.result && r.result.value === true) { ready = true; break; }
    await sleep(150);
  }
  if (!ready) console.error("warning: page-ready timeout; proceeding");

  // Chrome does not paint INLINE <svg> into printed PDFs (diagrams render on
  // screen but come out blank). Re-render each Mermaid diagram with mermaid-cli
  // (mmdc) — its own bundled Chromium renders reliably to PNG — using the page's
  // own computed theme, then swap the inline svg for the PNG <img>, which Chrome
  // paints when printing. Diagram-free docs skip this entirely.
  const info = await S("Runtime.evaluate", {
    expression:
      "JSON.stringify({sources:[].map.call(document.querySelectorAll('.mermaid')," +
      "function(e){return e.dataset.source||e.textContent;}),theme:window.__mermaidThemeVars||null})",
    returnByValue: true,
  });
  const { sources, theme } = JSON.parse(info.result.value || '{"sources":[]}');
  if (sources.length) {
    // Tag hosts with a stable index — the injection removes the `mermaid` class
    // (so mermaid-init's re-render, which fires on print and resets .mermaid to
    // its source, can't wipe our image), which would otherwise shift a class query.
    await S("Runtime.evaluate", {
      expression: "[].forEach.call(document.querySelectorAll('.mermaid'),function(e,i){e.setAttribute('data-print-idx',i);});",
    });
    const dir = mkdtempSync(join(tmpdir(), "mmdc-"));
    const outDir = dirname(outPath); // e.g. docs/DESIGN — served by the docs server
    writeFileSync(join(dir, "pptr.json"), JSON.stringify({ args: ["--no-sandbox"] }));
    writeFileSync(join(dir, "cfg.json"), JSON.stringify({
      theme: "base",
      themeVariables: theme || {},
      flowchart: { htmlLabels: false, useMaxWidth: false },
    }));
    for (let i = 0; i < sources.length; i++) {
      const mmd = join(dir, `d${i}.mmd`);
      // Write the PNG next to the doc so it's reachable by a same-dir HTTP URL.
      // Chrome's printToPDF fails to paint large data: URI images but renders
      // http/file-served images fine, so we reference by relative URL.
      const pngName = `.mmdprint-${i}.png`;
      const pngPath = join(outDir, pngName);
      writeFileSync(mmd, sources[i]);
      try {
        execFileSync("npx", ["-y", "@mermaid-js/mermaid-cli",
          "-i", mmd, "-o", pngPath, "-c", join(dir, "cfg.json"), "-p", join(dir, "pptr.json"),
          "-b", "white", "-s", "2"], { stdio: "ignore", timeout: 90000 });
        servedPngs.push(pngPath);
        await S("Runtime.evaluate", {
          expression:
            "(function(src){var host=document.querySelector('[data-print-idx=\"" + i + "\"]');" +
            "if(!host)return;var img=new Image();img.src=src;img.style.maxWidth='100%';" +
            "img.style.height='auto';host.innerHTML='';host.appendChild(img);" +
            "host.classList.remove('mermaid');})(" +
            JSON.stringify(pngName + "?t=" + msgId) + ")",
        });
      } catch (e) {
        console.error("mmdc failed for diagram " + i + ": " + (e.message || e));
      }
    }
    rmSync(dir, { recursive: true, force: true });
  }
  // Let the PNG images decode and paint before capture.
  await S("Runtime.evaluate", {
    expression: "Promise.all([].map.call(document.images,function(i){return i.decode?i.decode().catch(function(){}):null}))",
    awaitPromise: true,
  });
  await sleep(400);

  const { data } = await S("Page.printToPDF", { printBackground: true, preferCSSPageSize: false });
  writeFileSync(outPath, Buffer.from(data, "base64"));
} catch (e) {
  fail(`CDP error: ${e.message || e}`);
}

cleanup();
process.exit(0);
