#!/usr/bin/env python3
"""Serve the ATLAS ntuple wizard with split templates inlined.

The wizard is stored as inspectable static assets plus separate generated-script
templates.  This helper combines those pieces in memory for the browser and
serves them over HTTP. The default listener remains local-only. Container
deployments can select another bind address explicitly.
"""

from __future__ import annotations

import argparse
import re
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
    "<!-- pcdf-template-condor -->": (
        "text/plain",
        "template-condor",
        ATLAS_DIR / "templates" / "submit-pcdf-ntuple.template.condor",
    ),
    "<!-- pcdf-template-condor-job -->": (
        "text/plain",
        "template-condor-job",
        ATLAS_DIR / "templates" / "run-pcdf-condor-job.template.sh",
    ),
    "<!-- pcdf-template-readme -->": (
        "text/plain",
        "template-readme",
        ATLAS_DIR / "templates" / "README_SUBMIT.template.md",
    ),
    "<!-- pcdf-template-manifest -->": (
        "text/plain",
        "template-manifest",
        ATLAS_DIR / "templates" / "make-manifest.template.py",
    ),
    "<!-- pcdf-template-workflow-shell -->": (
        "text/plain",
        "template-workflow-shell",
        ATLAS_DIR / "templates" / "run-pcdf.template.sh",
    ),
    "<!-- pcdf-template-workflow-python -->": (
        "text/plain",
        "template-workflow-python",
        ATLAS_DIR / "templates" / "run-pcdf.template.py",
    ),
}


def script_payload(path: Path) -> str:
    """Return content safe to place inside a script tag."""
    return re.sub(r"</script", r"<\\/script", path.read_text(), flags=re.IGNORECASE)


def combined_html() -> bytes:
    page = HTML_PATH.read_text()
    for placeholder, (mime_type, element_id, path) in INJECTIONS.items():
        payload = script_payload(path)
        tag = f'<script type="{mime_type}" id="{element_id}">\n{payload}\n  </script>'
        if placeholder not in page:
            raise RuntimeError(f"Missing placeholder in {HTML_PATH}: {placeholder}")
        page = page.replace(placeholder, tag)

    # The source HTML lives under ATLAS/ for static deployments, where relative
    # assets such as ntuple-wizard.css work naturally. The localhost helper is
    # intentionally nicer to use: it serves the wizard at /, so rewrite those
    # asset URLs to their ATLAS paths in the combined response only.
    page = page.replace('href="ntuple-wizard.css"', 'href="/ATLAS/ntuple-wizard.css"')
    page = page.replace('src="ntuple-wizard.js"', 'src="/ATLAS/ntuple-wizard.js"')
    return page.encode("utf-8")


class WizardHandler(SimpleHTTPRequestHandler):
    """Static file handler that serves a combined wizard HTML page."""

    def do_GET(self) -> None:  # noqa: N802 - http.server API name
        route = self.path.split("?", 1)[0].rstrip("/")
        if route == "/healthz":
            self.serve_health()
            return
        if route in {"", "/"}:
            self.serve_combined_wizard()
            return
        super().do_GET()

    def serve_health(self) -> None:
        body = b"ok\n"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        description="Serve the ATLAS ntuple wizard at http://127.0.0.1:8000/.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to bind (default: 127.0.0.1)",
    )
    parser.add_argument("--port", type=int, default=8000, help="port to bind")
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
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving ATLAS ntuple wizard at {url}")
    print(f"Listening on {args.host}. Press Ctrl-C to stop.")
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
