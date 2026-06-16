#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "textual>=0.89",
# ]
# ///
"""Textual TUI for generating PCDF ATLAS ntuple conversion bundles.

Run with::

    uv run ATLAS/ntuple-wizard-tui.py

On NERSC Perlmutter login nodes the TUI enables a seamless workflow: pick or
scan input files, write a manifest on scratch, generate the converter and SLURM
wrapper, and optionally submit the job with ``sbatch``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, RichLog, Select, Static

ATLAS_DIR = Path(__file__).resolve().parent
OBJECT_CONFIG_PATH = ATLAS_DIR / "ntuple-wizard.objects.json"
TEMPLATE_DIR = ATLAS_DIR / "templates"
PERLMUTTER_PHYSICAL_CORES = 128
PERLMUTTER_LOGICAL_CPUS = 256


def on_perlmutter() -> bool:
    """Return true when the process appears to be running on Perlmutter."""
    nersc_host = os.environ.get("NERSC_HOST", "").lower()
    hostname = socket.gethostname().lower()
    return nersc_host == "perlmutter" or "perlmutter" in hostname or hostname.startswith("nid")


def generated_python_name(input_format: str) -> str:
    return f"ntuple-maker-{input_format.lower()}.py"


def apply_template(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Missing template value: {key}")
        return values[key]

    return re.sub(r"{{([A-Z0-9_]+)}}", replace, template)


def split_python_string(value: str, indent: int) -> str:
    prefix = " " * (indent + 4)
    chunks: list[str] = []
    remaining = value
    while len(remaining) > 38:
        split_at = remaining.rfind(".", 0, 38)
        if split_at < 12:
            split_at = 38
        end = split_at + (1 if remaining[split_at] == "." else 0)
        chunks.append(remaining[:end])
        remaining = remaining[end:]
    if remaining:
        chunks.append(remaining)
    return f"(\n{chr(10).join(f'{prefix}{json.dumps(chunk)}' for chunk in chunks)}\n{' ' * indent})"


def python_literal(value: Any, indent: int = 0) -> str:
    pad = " " * indent
    if value is None:
        return "None"
    if isinstance(value, str):
        quoted = json.dumps(value)
        return split_python_string(value, indent) if len(quoted) > 28 else quoted
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = [" " * (indent + 4) + python_literal(item, indent + 4) for item in value]
        body = ",\n".join(lines)
        return f"[\n{body}\n{pad}]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = [" " * (indent + 4) + f"{json.dumps(key)}: {python_literal(item, indent + 4)}" for key, item in value.items()]
        body = ",\n".join(lines)
        return f"{{\n{body}\n{pad}}}"
    return str(value)


@dataclass
class WizardState:
    objects: dict[str, dict[str, Any]]
    input_format: str = "TREASURE"
    sample_type: str = "MC"
    selected_objects: set[str] = field(default_factory=set)
    selected_variables: dict[str, set[str]] = field(default_factory=dict)
    account: str = ""
    qos: str = "regular"
    nodes: int = 1
    time: str = "00:30:00"
    output_base: str = "$SCRATCH/pcdf-output"
    manifest: str = "$SCRATCH/pcdf-inputs.txt"
    scan_root: str = "$SCRATCH"
    glob_pattern: str = "*.root*"

    def __post_init__(self) -> None:
        if not self.selected_objects:
            self.selected_objects = {key for key, obj in self.objects.items() if obj.get("recommended")}
        if not self.selected_variables:
            self.selected_variables = {key: set(obj.get("aliases", {})) for key, obj in self.objects.items()}
        self.ensure_dependencies()

    def variable_available(self, key: str, name: str) -> bool:
        return not (self.sample_type == "DATA" and name in self.objects[key].get("mcOnlyVariables", []))

    def object_available(self, key: str) -> bool:
        return not (self.objects[key].get("requiresTreasure") and self.input_format == "PHYSLITE")

    def add_dependencies(self, key: str) -> None:
        for dependency in self.objects[key].get("dependsOn", []):
            if self.object_available(dependency):
                self.selected_objects.add(dependency)
                self.add_dependencies(dependency)

    def ensure_dependencies(self) -> None:
        if self.input_format == "PHYSLITE":
            self.selected_objects.discard("Const")
        for key in list(self.selected_objects):
            if not self.object_available(key):
                self.selected_objects.discard(key)
            else:
                self.add_dependencies(key)
        self.selected_objects.add("Event")
        for key, obj in self.objects.items():
            self.selected_variables.setdefault(key, set())
            self.selected_variables[key].update(obj.get("requiredVariables", []))

    def selected_config(self) -> dict[str, Any]:
        objects: dict[str, Any] = {}
        for key, obj in self.objects.items():
            if key not in self.selected_objects or not self.object_available(key):
                continue
            aliases = {
                name: obj["aliases"][name]
                for name in self.selected_variables.get(key, set())
                if name in obj.get("aliases", {}) and self.variable_available(key, name)
            }
            objects[key] = {"folder": obj["folder"], "index_name": obj.get("indexName"), "aliases": aliases}
        return {"inputFormat": self.input_format, "sampleType": self.sample_type, "objects": objects}


class NtupleWizardTui(App[None]):
    """Interactive Textual app for PCDF ntuple job generation."""

    CSS = """
    #log { height: 1fr; border: round $accent; }
    .column { width: 1fr; }
    Button { margin: 1 1; }
    Checkbox { margin: 0 1; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("g", "generate", "Generate"), ("s", "submit", "Submit on Perlmutter")]

    def __init__(self, output_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        objects = json.loads(OBJECT_CONFIG_PATH.read_text())
        self.state_data = WizardState(objects=objects)
        self.perlmutter = on_perlmutter()
        self.output_dir = output_dir

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with VerticalScroll(classes="column"):
                yield Static("Input and SLURM")
                yield Label("Input format")
                yield Select([(label, label) for label in ("TREASURE", "PHYSLITE")], value="TREASURE", id="format")
                yield Label("Sample type")
                yield Select([(label, label) for label in ("MC", "DATA")], value="MC", id="sample")
                yield Input(placeholder="NERSC account", id="account")
                yield Input(value="regular", placeholder="QOS", id="qos")
                yield Input(value="1", placeholder="Nodes", id="nodes")
                yield Input(value="00:30:00", placeholder="Wall time", id="time")
                yield Input(value="$SCRATCH/pcdf-output", placeholder="Output base", id="output")
                yield Input(value="$SCRATCH/pcdf-inputs.txt", placeholder="Input manifest", id="manifest")
                yield Static("Perlmutter detected: " + ("yes" if self.perlmutter else "no"))
                yield Button("Generate scripts", id="generate", variant="primary")
                yield Button("Scan files → manifest", id="scan")
                yield Button("Submit with sbatch", id="submit", variant="success", disabled=not self.perlmutter)
            with VerticalScroll(classes="column", id="objects_box"):
                yield Static("Objects")
                for key, obj in self.state_data.objects.items():
                    yield Checkbox(obj["title"], value=key in self.state_data.selected_objects, id=f"obj-{key}")
                yield Static("Variables")
                for key, obj in self.state_data.objects.items():
                    yield Static(obj["title"])
                    required = set(obj.get("requiredVariables", []))
                    for name in obj.get("aliases", {}):
                        label = f"  {name}" + (" (required)" if name in required else "")
                        yield Checkbox(label, value=name in self.state_data.selected_variables[key], id=f"var-{key}-{name}", disabled=name in required)
            with VerticalScroll(classes="column"):
                yield Static("Perlmutter file discovery")
                yield Input(value="$SCRATCH", placeholder="Directory to scan", id="scan_root")
                yield Input(value="*.root*", placeholder="Glob, e.g. *.root*", id="glob")
                yield RichLog(id="log", wrap=True, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self.log_message("PCDF ntuple Textual wizard ready.")
        if self.perlmutter:
            self.log_message("Perlmutter detected: scan input files, generate scripts, then press submit.")
        else:
            self.log_message("Not on Perlmutter: generation is enabled; sbatch submission is disabled.")

    def log_message(self, message: str) -> None:
        self.query_one("#log", RichLog).write(message)

    def sync_state(self) -> None:
        state = self.state_data
        state.input_format = str(self.query_one("#format", Select).value)
        state.sample_type = str(self.query_one("#sample", Select).value)
        state.account = self.query_one("#account", Input).value.strip()
        state.qos = self.query_one("#qos", Input).value.strip() or "regular"
        try:
            state.nodes = max(1, int(self.query_one("#nodes", Input).value.strip()))
        except ValueError:
            state.nodes = 1
        state.time = self.query_one("#time", Input).value.strip() or "00:30:00"
        state.output_base = self.query_one("#output", Input).value.strip() or "$SCRATCH/pcdf-output"
        state.manifest = self.query_one("#manifest", Input).value.strip() or "$SCRATCH/pcdf-inputs.txt"
        state.scan_root = self.query_one("#scan_root", Input).value.strip() or "$SCRATCH"
        state.glob_pattern = self.query_one("#glob", Input).value.strip() or "*.root*"
        selected = set()
        selected_variables: dict[str, set[str]] = {}
        for key, obj in state.objects.items():
            if self.query_one(f"#obj-{key}", Checkbox).value:
                selected.add(key)
            selected_variables[key] = {
                name
                for name in obj.get("aliases", {})
                if self.query_one(f"#var-{key}-{name}", Checkbox).value
            }
        state.selected_objects = selected
        state.selected_variables = selected_variables
        state.ensure_dependencies()

    def build_python(self) -> str:
        config = self.state_data.selected_config()
        format_note = "PHYSLITE selected: jet constituents are disabled." if config["inputFormat"] == "PHYSLITE" else "TREASURE selected: jet constituents can be read."
        sample_note = "Data selected: MC-only truth/flavor branches are omitted; lumiBlock is included in Events." if config["sampleType"] == "DATA" else "MC selected: truth/flavor branches can be included when selected."
        return apply_template((TEMPLATE_DIR / "ntuple-maker.template.py").read_text(), {
            "INPUT_FORMAT": config["inputFormat"],
            "INPUT_NOTE": f"{format_note} {sample_note}",
            "OBJECTS": python_literal(config["objects"]),
        })

    def build_slurm(self) -> str:
        state = self.state_data
        return apply_template((TEMPLATE_DIR / "submit-pcdf-ntuple.template.slurm").read_text(), {
            "ACCOUNT_LINE": f"#SBATCH --account={state.account}",
            "QOS": state.qos,
            "NODES": str(state.nodes),
            "TIME": state.time,
            "PYTHON_PATH": json.dumps(str(self.output_dir / generated_python_name(state.input_format))),
            "INPUT_MANIFEST": json.dumps(state.manifest),
            "OUTPUT_BASE": json.dumps(state.output_base),
            "CONVERTER_CPUS_PER_CONVERSION": "1",
            "PERLMUTTER_PHYSICAL_CORES": str(PERLMUTTER_PHYSICAL_CORES),
            "PERLMUTTER_LOGICAL_CPUS_PER_NODE": str(PERLMUTTER_LOGICAL_CPUS),
        })

    def generate(self) -> tuple[Path, Path, Path]:
        self.sync_state()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        py_path = self.output_dir / generated_python_name(self.state_data.input_format)
        slurm_path = self.output_dir / "submit-pcdf-ntuple.slurm"
        bundle_path = self.output_dir / "pcdf-ntuple-bundle.tar"
        py_path.write_text(self.build_python())
        slurm_path.write_text(self.build_slurm())
        py_path.chmod(0o755)
        slurm_path.chmod(0o755)
        with tarfile.open(bundle_path, "w") as archive:
            archive.add(py_path, arcname=py_path.name)
            archive.add(slurm_path, arcname=slurm_path.name)
        self.log_message(f"Generated {py_path}")
        self.log_message(f"Generated {slurm_path}")
        self.log_message(f"Generated {bundle_path}")
        return py_path, slurm_path, bundle_path

    def scan_manifest(self) -> Path:
        self.sync_state()
        root = Path(os.path.expandvars(os.path.expanduser(self.state_data.scan_root)))
        manifest = Path(os.path.expandvars(os.path.expanduser(self.state_data.manifest)))
        files = sorted(path for path in root.rglob(self.state_data.glob_pattern) if path.is_file())
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", delete=False, dir=manifest.parent) as tmp:
            for path in files:
                tmp.write(str(path) + "\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(manifest)
        self.log_message(f"Wrote {len(files)} input file(s) to {manifest}")
        return manifest

    def submit(self) -> None:
        if not self.perlmutter:
            self.log_message("Refusing to submit: this does not look like Perlmutter.")
            return
        _, slurm_path, _ = self.generate()
        result = subprocess.run(["sbatch", str(slurm_path)], check=False, text=True, capture_output=True)
        if result.stdout:
            self.log_message(result.stdout.strip())
        if result.stderr:
            self.log_message(result.stderr.strip())
        if result.returncode:
            self.log_message(f"sbatch failed with exit code {result.returncode}")

    def action_generate(self) -> None:
        self.generate()

    def action_submit(self) -> None:
        self.submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "generate":
            self.generate()
        elif event.button.id == "scan":
            self.scan_manifest()
        elif event.button.id == "submit":
            self.submit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PCDF ATLAS ntuple Textual wizard.")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd(), help="Directory for generated scripts and bundle.")
    args = parser.parse_args()
    NtupleWizardTui(output_dir=args.output_dir).run()


if __name__ == "__main__":
    main()
