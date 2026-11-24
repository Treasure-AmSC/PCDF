#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jinja2"]
# ///
"""Serve the ATLAS ntuple wizard.

By default the page is rendered once at startup from ntuple-wizard.html.j2, so
the browser receives it with its wording, object definitions, and generator
templates already embedded. With --site DIR the program instead serves a
folder that build_site.py wrote earlier and does not need Jinja at all, which
is how the container image runs. The default listener is local-only. Container
deployments can select another bind address explicitly.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ATLAS_DIR = Path(__file__).resolve().parent
REPO_ROOT = ATLAS_DIR.parent


class WizardHandler(SimpleHTTPRequestHandler):
    """Static file handler with a health check and an optional rendered page at /."""

    def __init__(self, *args, page: bytes | None = None, **kwargs) -> None:
        self.page = page
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - http.server API name
        route = self.path.split("?", 1)[0].rstrip("/")
        if route == "/healthz":
            self.send_body(b"ok\n", "text/plain; charset=utf-8")
        elif route in {"", "/"} and self.page is not None:
            self.send_body(self.page, "text/html; charset=utf-8")
        else:
            super().do_GET()

    def send_body(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
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
        "--site",
        type=Path,
        help="serve this folder from build_site.py instead of rendering the page",
    )
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

    if args.site:
        if not (args.site / "index.html").is_file():
            raise SystemExit(f"{args.site} has no index.html. Create it with build_site.py.")
        handler = partial(WizardHandler, directory=str(args.site))
    else:
        from build_site import render_wizard_html

        # The repository root is served, so the page's CSS and JS live under /ATLAS/.
        page = render_wizard_html(asset_prefix="/ATLAS/").encode("utf-8")
        handler = partial(WizardHandler, page=page, directory=str(REPO_ROOT))
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
