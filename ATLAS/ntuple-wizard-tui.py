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
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, DirectoryTree, Footer, Header, Input, Label, RichLog, Select, SelectionList, Static

from ntuple_wizard_core import (
    WizardState,
    build_python,
    build_slurm,
    on_perlmutter,
    discover_files,
    scan_manifest,
    write_bundle,
    write_manifest,
)


class NtupleWizardTui(App[None]):
    """Interactive Textual app for PCDF ntuple job generation."""

    CSS = """
    /* Match ATLAS/ntuple-wizard.css: LBL dark blue page, teal primary,
       yellow focus, green submit, dark panels, and light-gray borders. */
    Screen {
        background: #00313c;
        color: #ffffff;
    }

    Header, Footer {
        background: #002832;
        color: #ffffff;
    }

    .column {
        width: 1fr;
        background: #001f26;
        border: round #63666a;
        padding: 1;
        margin: 1;
    }

    Static, Label, Checkbox {
        color: #ffffff;
    }

    Input, Select {
        background: #002832;
        color: #ffffff;
        border: tall #63666a;
        margin-bottom: 1;
    }

    Input:focus, Select:focus, Checkbox:focus {
        border: tall #eaaa00;
    }

    Button {
        margin: 1 1;
        background: #007681;
        color: #ffffff;
        border: tall #63666a;
        text-style: bold;
    }

    Button:hover, Button:focus {
        background: #4298b5;
        border: tall #eaaa00;
    }

    Button.-success {
        background: #74aa50;
        color: #ffffff;
    }

    Button:disabled {
        background: #63666a;
        color: #d8dedf;
    }

    Checkbox {
        margin: 0 1;
    }

    DirectoryTree, SelectionList, #log {
        background: #002832;
        color: #ffffff;
        border: round #007681;
    }

    DirectoryTree:focus, SelectionList:focus, #log:focus {
        border: round #eaaa00;
    }

    #log {
        height: 1fr;
    }

    .section-title {
        color: #eaaa00;
        text-style: bold;
    }
    """
    BINDINGS = [("q", "quit", "Quit"), ("g", "generate", "Generate"), ("s", "submit", "Submit on Perlmutter")]

    def __init__(self, output_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state_data = WizardState()
        self.perlmutter = on_perlmutter()
        self.output_dir = output_dir
        self._syncing = False
        self.discovered_files: list[Path] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with VerticalScroll(classes="column"):
                yield Static("Input and SLURM", classes="section-title")
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
                yield Button("Find files", id="scan")
                yield Button("Write selected manifest", id="manifest_write")
                yield Button("Submit with sbatch", id="submit", variant="success", disabled=not self.perlmutter)
            with VerticalScroll(classes="column", id="objects_box"):
                yield Static("Objects", classes="section-title")
                for key, obj in self.state_data.objects.items():
                    yield Checkbox(obj["title"], value=key in self.state_data.selected_objects, id=f"obj-{key}")
                yield Static("Variables", classes="section-title")
                for key, obj in self.state_data.objects.items():
                    yield Static(obj["title"])
                    required = set(obj.get("requiredVariables", []))
                    for name in obj.get("aliases", {}):
                        label = f"  {name}" + (" (required)" if name in required else "")
                        yield Checkbox(label, value=name in self.state_data.selected_variables[key], id=f"var-{key}-{name}", disabled=name in required)
            with VerticalScroll(classes="column"):
                yield Static("Perlmutter file discovery", classes="section-title")
                yield Input(value="$SCRATCH", placeholder="Directory to scan", id="scan_root")
                yield Input(value="*.root*", placeholder="Glob, e.g. *.root*", id="glob")
                tree_root = Path(os.path.expandvars(os.environ.get("SCRATCH", ""))).expanduser()
                if not tree_root.exists():
                    tree_root = Path.cwd()
                yield DirectoryTree(tree_root, id="tree")
                yield Static("Discovered files", classes="section-title")
                yield SelectionList[str](id="files")
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

    def object_checkbox(self, key: str) -> Checkbox:
        return self.query_one(f"#obj-{key}", Checkbox)

    def variable_checkbox(self, key: str, name: str) -> Checkbox:
        return self.query_one(f"#var-{key}-{name}", Checkbox)

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

    def refresh_dependency_widgets(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            state = self.state_data
            for key, obj in state.objects.items():
                object_box = self.object_checkbox(key)
                available = state.object_available(key)
                object_box.disabled = key == "Event" or not available
                object_box.value = key in state.selected_objects and available
                for name in obj.get("aliases", {}):
                    variable_box = self.variable_checkbox(key, name)
                    required = name in obj.get("requiredVariables", [])
                    variable_available = available and state.variable_available(key, name)
                    variable_box.disabled = required or not variable_available
                    variable_box.value = variable_available and name in state.selected_variables.get(key, set())
        finally:
            self._syncing = False

    def apply_dependency_change(self) -> None:
        self.state_data.ensure_dependencies()
        self.refresh_dependency_widgets()

    def refresh_discovered_files(self) -> None:
        self.sync_state()
        self.discovered_files = discover_files(self.state_data.scan_root, self.state_data.glob_pattern)
        files = self.query_one("#files", SelectionList)
        files.clear_options()
        files.add_options((str(path), str(path), True) for path in self.discovered_files)
        self.log_message(f"Found {len(self.discovered_files)} file(s) under {self.state_data.scan_root}")

    def selected_discovered_files(self) -> list[Path]:
        files = self.query_one("#files", SelectionList)
        return [Path(value) for value in files.selected]

    def write_selected_manifest(self) -> Path:
        self.sync_state()
        selected = self.selected_discovered_files()
        if not selected:
            self.log_message("No files selected; writing a manifest from the current scan instead.")
            manifest, count = scan_manifest(self.state_data)
        else:
            manifest, count = write_manifest(selected, self.state_data.manifest)
        self.log_message(f"Wrote {count} input file(s) to {manifest}")
        return manifest

    def build_python(self) -> str:
        return build_python(self.state_data)

    def build_slurm(self) -> str:
        return build_slurm(self.state_data, self.output_dir)

    def generate(self) -> tuple[Path, Path, Path]:
        self.sync_state()
        py_path, slurm_path, bundle_path = write_bundle(self.state_data, self.output_dir)
        self.log_message(f"Generated {py_path}")
        self.log_message(f"Generated {slurm_path}")
        self.log_message(f"Generated {bundle_path}")
        return py_path, slurm_path, bundle_path

    def scan_manifest(self) -> Path:
        self.refresh_discovered_files()
        return self.write_selected_manifest()

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

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if self._syncing or event.checkbox.id is None:
            return
        checkbox_id = event.checkbox.id
        state = self.state_data
        if checkbox_id.startswith("obj-"):
            key = checkbox_id.removeprefix("obj-")
            if event.value:
                state.selected_objects.add(key)
            elif key != "Event":
                state.selected_objects.discard(key)
            self.apply_dependency_change()
            return
        if checkbox_id.startswith("var-"):
            _, key, name = checkbox_id.split("-", 2)
            variables = state.selected_variables.setdefault(key, set())
            if event.value:
                variables.add(name)
            elif name not in state.objects[key].get("requiredVariables", []):
                variables.discard(name)
            self.apply_dependency_change()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id not in {"format", "sample"}:
            return
        self.state_data.input_format = str(self.query_one("#format", Select).value)
        self.state_data.sample_type = str(self.query_one("#sample", Select).value)
        self.apply_dependency_change()

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        path = str(event.path)
        scan_root = self.query_one("#scan_root", Input)
        scan_root.value = path
        self.state_data.scan_root = path
        self.log_message(f"Selected scan directory: {path}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "generate":
            self.generate()
        elif event.button.id == "scan":
            self.refresh_discovered_files()
        elif event.button.id == "manifest_write":
            self.write_selected_manifest()
        elif event.button.id == "submit":
            self.submit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PCDF ATLAS ntuple Textual wizard.")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd(), help="Directory for generated scripts and bundle.")
    args = parser.parse_args()
    NtupleWizardTui(output_dir=args.output_dir).run()


if __name__ == "__main__":
    main()
