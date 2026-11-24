"""Read the wording shared by the wizards from wizard-text.txt.

The file holds entries that start with a line "@@ key" and run to the next
one. Lines that start with "##" are comments. Blank lines around an entry are
not part of it. Python, the TUI, and the HTML build all read it through this
module, so there is one copy of each message.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "wizard-text.txt"
PLACEHOLDER = re.compile(r"{{([A-Z0-9_]+)}}")
KEY_PATTERN = re.compile(r"[a-z][a-z0-9.-]*")


def parse_catalog(text: str) -> dict[str, str]:
    """Split catalog text into its entries."""
    entries: dict[str, list[str]] = {}
    key = None
    for line in text.splitlines():
        if line.startswith("@@ "):
            key = line[3:].strip()
            if not KEY_PATTERN.fullmatch(key):
                raise ValueError(f"Invalid wizard text key: {key!r}")
            if key in entries:
                raise ValueError(f"Duplicate wizard text key: {key}")
            entries[key] = []
        elif key is not None and not line.startswith("##"):
            entries[key].append(line)
    return {name: "\n".join(lines).strip("\n") for name, lines in entries.items()}


@cache
def catalog() -> dict[str, str]:
    """Return every entry of the shared catalog."""
    return parse_catalog(CATALOG_PATH.read_text())


def wizard_text(key: str, **values: str) -> str:
    """Return one entry, with each {{NAME}} replaced by the matching keyword value.

    A name without a value stays in the text, so entries filled later (for
    example in the browser) pass through unchanged.
    """
    text = catalog()[key]
    return PLACEHOLDER.sub(lambda match: str(values.get(match.group(1), match.group(0))), text)
