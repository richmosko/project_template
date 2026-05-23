#!/usr/bin/env python3
"""
serve-docs.py — Local server for docs/ with a comments API.

Serves docs/ over http://localhost:PORT (default 8765) and adds:

  GET  /api/comments?doc=<PRD|ARCH|SECURITY>
       → returns the parsed comments from docs/<doc>/comments.md as JSON.

  POST /api/comments
       body: {"doc": "<PRD|ARCH|SECURITY>", "section": "<id>", "body": "..."}
       → appends a `## §<section>\n\n<body>` block to docs/<doc>/comments.md
         (creates the file with a standard preamble if missing).

Localhost-only — binds 127.0.0.1; no auth needed. Path-validates the `doc`
parameter against a whitelist so it can't be coerced into reading or writing
arbitrary files.

Run from the repo root:
    ./scripts/serve-docs.sh        # wrapper that calls this script
    python3 scripts/serve-docs.py  # direct invocation (cross-platform)

Override the port via env: DOCS_PORT=8080 ./scripts/serve-docs.sh
"""

import http.server
import json
import os
import re
import socketserver
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("DOCS_PORT", "8765"))
HOST = "127.0.0.1"

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

VALID_DOCS = {"PRD", "ARCH", "SECURITY"}
ANCHOR_RE = re.compile(r"^## §([a-z][a-z0-9-]*)\s*$")
SECTION_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def comments_path(doc: str) -> Path:
    if doc not in VALID_DOCS:
        raise ValueError(f"invalid doc: {doc!r}")
    return DOCS_DIR / doc / "comments.md"


def parse_comments(path: Path) -> list[dict]:
    """Return [{section, body}, ...] from a comments.md file (or [] if absent)."""
    if not path.exists():
        return []
    blocks: list[dict] = []
    current_section: str | None = None
    current_body: list[str] = []
    for line in path.read_text().splitlines():
        m = ANCHOR_RE.match(line)
        if m:
            if current_section is not None:
                blocks.append({"section": current_section, "body": "\n".join(current_body).strip()})
            current_section = m.group(1)
            current_body = []
        elif current_section is not None:
            current_body.append(line)
    if current_section is not None:
        blocks.append({"section": current_section, "body": "\n".join(current_body).strip()})
    return blocks


def append_comment(doc: str, section: str, body: str) -> None:
    """Append a `## §section\\n\\nbody` block to docs/<doc>/comments.md."""
    if not body.strip():
        raise ValueError("empty comment body")
    if not SECTION_ID_RE.match(section):
        raise ValueError(f"invalid section id: {section!r}")
    path = comments_path(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        preamble = (
            f"# {doc} Comments\n\n"
            f"Working notes for review of `docs/{doc}/index.html`. "
            f"Comments are removed when `/refine-doc` addresses them.\n\n---\n\n"
        )
        path.write_text(preamble)
    existing = path.read_text()
    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    with path.open("a") as f:
        f.write(f"{sep}## §{section}\n\n{body.strip()}\n")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DOCS_DIR), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.command} {self.path} → {args[1] if len(args) > 1 else '-'}\n")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/comments":
            qs = parse_qs(parsed.query)
            doc = qs.get("doc", [""])[0]
            try:
                comments = parse_comments(comments_path(doc))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, {"doc": doc, "comments": comments})
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/api/comments":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            append_comment(payload.get("doc", ""), payload.get("section", ""), payload.get("body", ""))
            self._send_json(200, {"status": "ok"})
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            self._send_json(500, {"error": str(e)})


def main():
    os.chdir(REPO_ROOT)
    print(f"Serving docs/ at http://{HOST}:{PORT}/")
    print(f"  PRD:      http://{HOST}:{PORT}/PRD/")
    print(f"  ARCH:     http://{HOST}:{PORT}/ARCH/")
    print(f"  SECURITY: http://{HOST}:{PORT}/SECURITY/")
    print(f"\nComments API:")
    print(f"  GET  /api/comments?doc=<PRD|ARCH|SECURITY>")
    print(f"  POST /api/comments  body={{doc, section, body}}")
    print(f"\nCtrl+C to stop.\n")
    with socketserver.TCPServer((HOST, PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
