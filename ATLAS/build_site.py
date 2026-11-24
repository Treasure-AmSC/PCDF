#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jinja2"]
# ///
"""Render the wizard page and, optionally, write a complete static site.

ntuple-wizard.html.j2 is a template. This program fills in its wording from
wizard-text.txt and embeds the object definitions and the generator templates,
so the browser needs no further requests once the page has loaded. Run it with
an output directory to get files that any static web host can serve:

    uv run ATLAS/build_site.py _site
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

from wizard_text import PLACEHOLDER, catalog

ATLAS_DIR = Path(__file__).resolve().parent
OBJECTS_PATH = ATLAS_DIR / "ntuple-wizard.objects.json"
TEMPLATE_IDS = {
    "python": "ntuple-maker.template.py",
    "slurm": "submit-pcdf-ntuple.template.slurm",
    "condor": "submit-pcdf-ntuple.template.condor",
    "condor-job": "run-pcdf-condor-job.template.sh",
    "readme": "README_SUBMIT.template.md",
    "manifest": "make-manifest.template.py",
    "workflow-shell": "run-pcdf.template.sh",
    "workflow-python": "run-pcdf.template.py",
}
DYNAMIC_PREFIXES = ("bundle.", "common.", "runner.", "manifest.", "converter.", "shell.", "dtn.")
CODE_SPAN = re.compile(r"`([^`]+)`")


def script_safe(text: str) -> Markup:
    """Make file content safe to place inside a script element."""
    return Markup(re.sub(r"</script", r"<\\/script", text, flags=re.IGNORECASE))


def text(key: str, **values: object) -> Markup:
    """Return a catalog entry as HTML, with `code` spans and {{NAME}} values filled in."""
    pieces = PLACEHOLDER.split(catalog()[key])
    html = []
    for index, piece in enumerate(pieces):
        if index % 2 == 0:
            html.append(CODE_SPAN.sub(r"<code>\1</code>", str(escape(piece))))
        elif piece in values:
            html.append(str(escape(values[piece])))
        else:
            html.append(str(escape("{{" + piece + "}}")))
    return Markup("".join(html))


def runtime_text() -> dict[str, str]:
    """Return the catalog entries that ntuple-wizard.js uses.

    An entry is included when its key appears as a quoted string in the script,
    when it is the -one or -many form of such a key (see pluralKey in the
    script), or when it starts with a prefix that the script builds up at run
    time.
    """
    script = (ATLAS_DIR / "ntuple-wizard.js").read_text()
    quoted = set(re.findall(r'["`]([a-z][a-z0-9.-]*)["`]', script))
    return {
        key: value
        for key, value in catalog().items()
        if key.startswith(DYNAMIC_PREFIXES) or key in quoted or re.sub(r"-(one|many)$", "", key) in quoted
    }


def json_for_script(value: object) -> Markup:
    """Return value as JSON, in its original key order, that is safe inside a script element."""
    text = json.dumps(value, ensure_ascii=False)
    for character, escape_code in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), ("'", "\\u0027")):
        text = text.replace(character, escape_code)
    return Markup(text)


def render_wizard_html(asset_prefix: str = "") -> str:
    """Return the finished page. asset_prefix is put before the CSS and JS file names."""
    environment = Environment(loader=FileSystemLoader(ATLAS_DIR), autoescape=True)
    template = environment.get_template("ntuple-wizard.html.j2")
    return template.render(
        t=text,
        asset_prefix=asset_prefix,
        objects_json=script_safe(OBJECTS_PATH.read_text()),
        runtime_text_json=json_for_script(runtime_text()),
        templates={
            name: script_safe((ATLAS_DIR / "templates" / filename).read_text())
            for name, filename in TEMPLATE_IDS.items()
        },
    )


def build_site(output: Path) -> None:
    """Write index.html and the files it links to into output."""
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(render_wizard_html())
    for name in ("ntuple-wizard.css", "ntuple-wizard.js"):
        shutil.copy2(ATLAS_DIR / name, output / name)
    shutil.copytree(ATLAS_DIR / "assets", output / "assets", dirs_exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path, help="directory to write the static site into")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    build_site(args.output)
    print(f"Wrote the wizard to {args.output}/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
