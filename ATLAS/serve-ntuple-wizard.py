#!/usr/bin/env python3
"""Serve the ATLAS ntuple wizard on localhost with split templates inlined.

The wizard is stored as inspectable static assets plus separate generated-script
templates.  This helper combines those pieces in memory for the browser and
serves them from a localhost-only HTTP server.  It intentionally never binds to
an external interface.
"""

from __future__ import annotations

import argparse
import html
import sys
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ATLAS_DIR = Path(__file__).resolve().parent
REPO_ROOT = ATLAS_DIR.parent
HTML_PATH = ATLAS_DIR / "ntuple-wizard.html"
INJECTIONS = {
    "<!-- pcdf-object-config -->": (
        "application/json",
        "object-config",
        ATLAS_DIR / "ntuple-wizard.objects.json",
    ),
    "<!-- pcdf-template-python -->": (
        "text/plain",
        "template-python",
        ATLAS_DIR / "templates" / "ntuple-maker.template.py",
    ),
    "<!-- pcdf-template-slurm -->": (
        "text/plain",
        "template-slurm",
        ATLAS_DIR / "templates" / "submit-pcdf-ntuple.template.slurm",
    ),
    "<!-- pcdf-template-transfer -->": (
        "text/plain",
        "template-transfer",
        ATLAS_DIR / "templates" / "download-atlas-opendata.template.sh",
    ),
    "<!-- pcdf-template-readme -->": (
        "text/plain",
        "template-readme",
        ATLAS_DIR / "templates" / "README_SUBMIT.template.md",
    ),
}


def script_payload(path: Path) -> str:
    """Return content safe to place inside a script tag."""
    return path.read_text().replace("</script", "<\\/script")


def combined_html() -> bytes:
    page = HTML_PATH.read_text()
    for placeholder, (mime_type, element_id, path) in INJECTIONS.items():
        payload = script_payload(path)
        tag = f'<script type="{mime_type}" id="{element_id}">\n{payload}\n  </script>'
        if placeholder not in page:
            raise RuntimeError(f"Missing placeholder in {HTML_PATH}: {placeholder}")
        page = page.replace(placeholder, tag)
    return page.encode("utf-8")


class WizardHandler(SimpleHTTPRequestHandler):
    """Static file handler that serves a combined wizard HTML page."""

    def do_GET(self) -> None:  # noqa: N802 - http.server API name
        route = self.path.split("?", 1)[0].rstrip("/")
        if route in {"", "/", "/ATLAS/ntuple-wizard.html", "/ntuple-wizard.html"}:
            self.serve_combined_wizard()
            return
        super().do_GET()

    def serve_combined_wizard(self) -> None:
        try:
            body = combined_html()
        except Exception as error:  # pragma: no cover - startup/config failure path
            message = f"Failed to combine ntuple wizard assets: {error}\n".encode("utf-8")
            self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve ATLAS/ntuple-wizard.html on localhost with templates inlined.",
    )
    parser.add_argument("--port", type=int, default=8000, help="localhost port to bind")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the wizard in the default browser",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not (1 <= args.port <= 65535):
        raise SystemExit("--port must be between 1 and 65535")

    handler = partial(WizardHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/ATLAS/ntuple-wizard.html"
    print(f"Serving ATLAS ntuple wizard at {url}")
    print("Listening on 127.0.0.1 only; press Ctrl-C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
