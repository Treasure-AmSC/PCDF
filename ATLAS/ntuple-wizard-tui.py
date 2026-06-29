#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "textual>=8.2.7",
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
from textual.containers import Container, Grid, Horizontal, VerticalScroll
from textual.validation import Function, Number, Regex
from textual.widgets import Button, DirectoryTree, Footer, Header, Input, Label, RichLog, Select, SelectionList, Static, Switch, TabbedContent, TabPane

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

    TITLE = "ATLAS ntuple wizard"
    SUB_TITLE = "TREASURE → Parquet"

    STEPS = ("Input", "Objects", "Variables", "Perlmutter", "Generate")

    CSS_PATH = Path(__file__).with_name("ntuple-wizard-tui.tcss")

    BINDINGS = [("q", "quit", "Quit"), ("g", "generate", "Generate"), ("s", "submit", "Submit on Perlmutter")]

    def __init__(self, output_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state_data = WizardState()
        self.perlmutter = on_perlmutter()
        self.output_dir = output_dir
        self.current_step = 0
        self._syncing = False
        self._loading_accounts = False
        self._suppress_account_select_notice = False
        self.discovered_files: list[Path] = []

    @staticmethod
    def non_empty(value: str) -> bool:
        return bool(value.strip())

    @staticmethod
    def existing_directory(value: str) -> bool:
        return Path(os.path.expandvars(os.path.expanduser(value or "."))).is_dir()

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="page"):
            yield Static("✦ ATLAS TREASURE → Parquet script wizard", id="hero")
            with TabbedContent(initial="step-0", id="wizard-tabs", classes="wizard-shell"):
                with TabPane("1. Input", id="step-0", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static("Input format and sample type", classes="section-title")
                        yield Static("Choose the same core inputs as the HTML wizard. PHYSLITE disables TREASURE-only constituent output; data mode omits MC-only variables.", classes="hint")
                        yield Label("Input format", classes="field-label")
                        yield Select([(label, label) for label in ("TREASURE", "PHYSLITE")], value="TREASURE", id="format", classes="hidden-select")
                        with Horizontal(classes="choice-row"):
                            yield Button("TREASURE", id="set-format-TREASURE", classes="choice-button active-step")
                            yield Button("PHYSLITE", id="set-format-PHYSLITE", classes="choice-button")
                        yield Label("Sample type", classes="field-label")
                        yield Select([(label, label) for label in ("MC", "DATA")], value="MC", id="sample", classes="hidden-select")
                        with Horizontal(classes="choice-row"):
                            yield Button("MC", id="set-sample-MC", classes="choice-button active-step")
                            yield Button("DATA", id="set-sample-DATA", classes="choice-button")

                with TabPane("2. Objects", id="step-1", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static("Output objects", classes="section-title")
                        yield Static("Toggle objects interactively. Dependencies are selected automatically; turning off an object also turns off selected objects that depend on it.", classes="hint")
                        with Grid(classes="object-grid"):
                            for key, obj in self.state_data.objects.items():
                                selected = key in self.state_data.selected_objects
                                with Grid(id=f"obj-card-{key}", classes="toggle-card selected-choice" if selected else "toggle-card deselected-choice"):
                                    yield Switch(value=selected, id=f"obj-{key}", classes="toggle-switch", disabled=key == "Event")
                                    yield Label(obj["title"], id=f"obj-label-{key}", classes="toggle-label")

                with TabPane("3. Variables", id="step-2", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static("Output variables", classes="section-title")
                        yield Static("Required vector components stay locked on; MC-only labels are disabled for collision data.", classes="hint")
                        for key, obj in self.state_data.objects.items():
                            yield Static(obj["title"], classes="section-title")
                            required = set(obj.get("requiredVariables", []))
                            with Grid(classes="object-grid"):
                                for name in obj.get("aliases", {}):
                                    selected = name in self.state_data.selected_variables[key]
                                    with Grid(id=f"var-card-{key}-{name}", classes="toggle-card selected-choice" if selected else "toggle-card deselected-choice"):
                                        yield Switch(value=selected, id=f"var-{key}-{name}", classes="toggle-switch", disabled=name in required)
                                        suffix = " (required)" if name in required else ""
                                        yield Label(f"{name}{suffix}", id=f"var-label-{key}-{name}", classes="toggle-label")

                with TabPane("4. Perlmutter", id="step-3", classes="wizard-step"):
                    with Horizontal(classes="two-column"):
                        with VerticalScroll(classes="column"):
                            yield Static("SLURM / NERSC Perlmutter", classes="section-title")
                            yield Static("Configure the CPU-only Perlmutter wrapper and, on Perlmutter, use the picker to build the manifest before submitting.", classes="hint")
                            yield Label("NERSC account", classes="field-label")
                            if self.perlmutter:
                                yield Select([("Loading accounts from iris…", "")], value="", allow_blank=False, disabled=True, id="account_select")
                            else:
                                yield Input(placeholder="NERSC account", id="account_input", validators=[Function(self.non_empty, "Enter a NERSC account before submitting.")], validate_on=["blur", "submitted"])
                            yield Label("Queue / QOS", classes="field-label")
                            yield Select([(label, label) for label in ("regular", "debug", "premium", "shared")], value="regular", allow_blank=False, id="qos")
                            yield Label("Nodes", classes="field-label")
                            yield Input(value="1", placeholder="Nodes", id="nodes", validators=[Number(minimum=1, failure_description="Nodes must be at least 1.")], validate_on=["blur", "submitted"])
                            yield Label("Wall time", classes="field-label")
                            yield Input(value="00:30:00", placeholder="Wall time", id="time", validators=[Regex(r"^\d{1,2}:\d{2}:\d{2}$", failure_description="Use HH:MM:SS wall time, for example 00:30:00.")], validate_on=["blur", "submitted"])
                            yield Label("Output base", classes="field-label")
                            yield Input(value="$SCRATCH/pcdf-output", placeholder="Output base", id="output", validators=[Function(self.non_empty, "Output base may not be empty.")], validate_on=["blur", "submitted"])
                            yield Label("Input manifest", classes="field-label")
                            yield Input(value="$SCRATCH/pcdf-inputs.txt", placeholder="Input manifest", id="manifest", validators=[Function(self.non_empty, "Input manifest may not be empty.")], validate_on=["blur", "submitted"])
                            yield Static("Perlmutter detected: " + ("yes" if self.perlmutter else "no"), classes="hint")
                        with VerticalScroll(classes="column"):
                            yield Static("Interactive file and folder picker", classes="section-title")
                            yield Label("Directory to scan", classes="field-label")
                            yield Input(value="$SCRATCH", placeholder="Directory to scan", id="scan_root", validators=[Function(self.existing_directory, "Scan directory must exist.")], validate_on=["blur", "submitted"])
                            yield Label("File glob", classes="field-label")
                            yield Input(value="*.root*", placeholder="Glob, e.g. *.root*", id="glob", validators=[Function(self.non_empty, "Glob pattern may not be empty.")], validate_on=["blur", "submitted"])
                            tree_root = Path(os.path.expandvars(os.environ.get("SCRATCH", ""))).expanduser()
                            if not tree_root.exists():
                                tree_root = Path.cwd()
                            yield DirectoryTree(tree_root, id="tree")
                            yield Button("Find files", id="scan")
                            yield Static("Discovered files", classes="section-title")
                            yield SelectionList[str](id="files")
                            yield Button("Write selected manifest", id="manifest_write")

                with TabPane("5. Generate", id="step-4", classes="wizard-step"):
                    with Horizontal(classes="two-column"):
                        with VerticalScroll(classes="column"):
                            yield Static("Generate", classes="section-title")
                            yield Static("Generate the converter, SLURM wrapper, and tar bundle. On Perlmutter, submit directly after reviewing the settings.", classes="hint")
                            yield Static("", id="summary_panel")
                            with Horizontal(id="generate-actions"):
                                yield Button("Generate scripts", id="generate", variant="primary")
                                yield Button("Submit with sbatch", id="submit", variant="success", disabled=not self.perlmutter)
                        with VerticalScroll(classes="column"):
                            yield Static("Status", classes="section-title")
                            yield RichLog(id="log", wrap=True, highlight=True)
            with Horizontal(id="wizard-nav"):
                yield Button("Previous", id="prev_step")
                yield Button("Next", id="next_step", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_dependency_widgets()
        self.refresh_step()
        self.log_message("PCDF ntuple Textual wizard ready.")
        if self.perlmutter:
            self.log_message("Perlmutter detected: scan input files, generate scripts, then press submit.")
            self.load_accounts_with_iris(notify_user=False)
        else:
            self.log_message("Not on Perlmutter: generation is enabled; sbatch submission is disabled.")

    def log_message(self, message: str) -> None:
        self.query_one("#log", RichLog).write(message)

    def refresh_summary(self) -> None:
        state = self.state_data
        config = state.selected_config()
        object_lines = [
            f"• {state.objects[key]['title']}: {len(value['aliases'])} variable(s)"
            for key, value in config["objects"].items()
        ]
        slurm_status = (
            f"Perlmutter CPU job: {state.nodes} exclusive node(s), QOS {state.qos}, wall time {state.time}."
            if self.perlmutter
            else "Generation only on this host; submission is enabled automatically on Perlmutter."
        )
        summary = "\n".join([
            f"Input: {state.input_format} · {state.sample_type}",
            slurm_status,
            f"Manifest: {state.manifest}",
            f"Output: {state.output_base}",
            "Objects:",
            *(object_lines or ["• none selected"]),
        ])
        self.query_one("#summary_panel", Static).update(summary)

    def refresh_step(self) -> None:
        self.current_step = max(0, min(len(self.STEPS) - 1, self.current_step))
        tabs = self.query_one("#wizard-tabs", TabbedContent)
        target = f"step-{self.current_step}"
        if tabs.active != target:
            tabs.active = target
        self.query_one("#prev_step", Button).disabled = self.current_step == 0
        next_button = self.query_one("#next_step", Button)
        next_button.label = "Review" if self.current_step == len(self.STEPS) - 2 else "Next"
        next_button.disabled = self.current_step == len(self.STEPS) - 1
        self.refresh_choice_buttons()
        self.refresh_summary()

    def refresh_choice_buttons(self) -> None:
        for value in ("TREASURE", "PHYSLITE"):
            self.query_one(f"#set-format-{value}", Button).set_class(self.state_data.input_format == value, "active-step")
        for value in ("MC", "DATA"):
            self.query_one(f"#set-sample-{value}", Button).set_class(self.state_data.sample_type == value, "active-step")

    def object_control(self, key: str) -> Switch:
        return self.query_one(f"#obj-{key}", Switch)

    def variable_control(self, key: str, name: str) -> Switch:
        return self.query_one(f"#var-{key}-{name}", Switch)

    def sync_state(self) -> None:
        state = self.state_data
        state.input_format = str(self.query_one("#format", Select).value)
        state.sample_type = str(self.query_one("#sample", Select).value)
        if self.perlmutter:
            selected_account = self.query_one("#account_select", Select).value
            state.account = "" if selected_account in (Select.NULL, "") else str(selected_account)
        else:
            state.account = self.query_one("#account_input", Input).value.strip()
        qos = self.query_one("#qos", Select).value
        state.qos = "regular" if qos is Select.NULL else str(qos)
        try:
            state.nodes = max(1, int(self.query_one("#nodes", Input).value.strip()))
        except ValueError:
            state.nodes = 1
        state.time = self.query_one("#time", Input).value.strip() or "00:30:00"
        state.output_base = self.query_one("#output", Input).value.strip() or "$SCRATCH/pcdf-output"
        state.manifest = self.query_one("#manifest", Input).value.strip() or "$SCRATCH/pcdf-inputs.txt"
        state.scan_root = self.query_one("#scan_root", Input).value.strip() or "$SCRATCH"
        state.glob_pattern = self.query_one("#glob", Input).value.strip() or "*.root*"
        state.ensure_dependencies()

    def refresh_dependency_widgets(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            state = self.state_data
            for key, obj in state.objects.items():
                object_switch = self.object_control(key)
                object_card = self.query_one(f"#obj-card-{key}", Grid)
                available = state.object_available(key)
                object_selected = key in state.selected_objects and available
                object_switch.disabled = key == "Event" or not available
                object_switch.value = object_selected
                object_card.set_class(object_selected, "selected-choice")
                object_card.set_class(not object_selected, "deselected-choice")
                for name in obj.get("aliases", {}):
                    variable_switch = self.variable_control(key, name)
                    variable_card = self.query_one(f"#var-card-{key}-{name}", Grid)
                    required = name in obj.get("requiredVariables", [])
                    variable_available = available and state.variable_available(key, name)
                    variable_selected = variable_available and name in state.selected_variables.get(key, set())
                    variable_switch.disabled = required or not variable_available
                    variable_switch.value = variable_selected
                    variable_card.set_class(variable_selected, "selected-choice")
                    variable_card.set_class(not variable_selected, "deselected-choice")
        finally:
            self._syncing = False

    def apply_dependency_change(self) -> None:
        self.state_data.ensure_dependencies()
        self.refresh_dependency_widgets()

    def refresh_discovered_files(self) -> None:
        if not self.validate_scan_inputs():
            return
        self.sync_state()
        self.discovered_files = discover_files(self.state_data.scan_root, self.state_data.glob_pattern)
        files = self.query_one("#files", SelectionList)
        files.clear_options()
        files.add_options((str(path), str(path), True) for path in self.discovered_files)
        self.log_message(f"Found {len(self.discovered_files)} file(s) under {self.state_data.scan_root}")
        self.notify(f"Found {len(self.discovered_files)} file(s)", title="Discovery complete", severity="information", timeout=4)

    def selected_discovered_files(self) -> list[Path]:
        files = self.query_one("#files", SelectionList)
        return [Path(value) for value in files.selected]

    def write_selected_manifest(self) -> Path | None:
        if not self.validate_scan_inputs():
            return None
        self.sync_state()
        selected = self.selected_discovered_files()
        if not selected:
            self.log_message("No files selected; writing a manifest from the current scan instead.")
            manifest, count = scan_manifest(self.state_data)
        else:
            manifest, count = write_manifest(selected, self.state_data.manifest)
        self.log_message(f"Wrote {count} input file(s) to {manifest}")
        self.notify(f"Wrote {count} file(s) to {manifest}", title="Manifest written", severity="information", timeout=6)
        return manifest

    def parse_iris_accounts(self, output: str) -> list[str]:
        accounts: list[str] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.lower().startswith(("project", "account", "-")):
                continue
            first = stripped.split()[0]
            if first.replace("_", "").replace("-", "").isalnum() and first not in accounts:
                accounts.append(first)
        return accounts

    def load_accounts_with_iris(self, notify_user: bool = True) -> None:
        self._loading_accounts = True
        try:
            result = subprocess.run(["iris"], check=False, text=True, capture_output=True, timeout=15)
        except FileNotFoundError:
            if notify_user:
                self.notify("The iris command is not available on this host.", title="Iris unavailable", severity="warning", timeout=8)
            account_select = self.query_one("#account_select", Select)
            account_select.set_options([("iris command not found", "")])
            account_select.value = ""
            account_select.disabled = True
            self.log_message("iris command not found; account selection is unavailable.")
            self._loading_accounts = False
            return
        except subprocess.TimeoutExpired:
            account_select = self.query_one("#account_select", Select)
            account_select.set_options([("iris timed out", "")])
            account_select.value = ""
            account_select.disabled = True
            if notify_user:
                self.notify("iris did not finish within 15 seconds.", title="Iris timeout", severity="warning", timeout=8)
            self._loading_accounts = False
            return
        try:
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            accounts = self.parse_iris_accounts(output)
            account_select = self.query_one("#account_select", Select)
            if accounts:
                account_select.set_options((account, account) for account in accounts)
                self._suppress_account_select_notice = not notify_user
                account_select.value = accounts[0]
                account_select.disabled = False
                if notify_user:
                    self.notify(f"Found {len(accounts)} account(s) with iris.", title="Iris accounts loaded", severity="information", timeout=6)
                self.log_message("Iris accounts: " + ", ".join(accounts))
            else:
                account_select.set_options([("No iris accounts found", "")])
                account_select.value = ""
                account_select.disabled = True
                if notify_user:
                    self.notify("iris ran, but no account names were recognized.", title="No Iris accounts found", severity="warning", timeout=8)
                self.log_message("iris output did not contain recognizable accounts.")
        finally:
            self._loading_accounts = False

    def invalid_inputs(self, ids: tuple[str, ...]) -> list[str]:
        messages: list[str] = []
        for input_id in ids:
            widget = self.query_one(f"#{input_id}", Input)
            result = widget.validate(widget.value)
            widget.set_class(result.is_valid, "-valid")
            widget.set_class(not result.is_valid, "-invalid")
            if not result.is_valid:
                messages.extend(result.failure_descriptions)
        return messages

    def validate_slurm_inputs(self) -> bool:
        failures = self.invalid_inputs(("nodes", "time", "output", "manifest"))
        if self.perlmutter:
            if self.query_one("#account_select", Select).value in (Select.NULL, ""):
                failures.append("Choose a NERSC account.")
        else:
            failures.extend(self.invalid_inputs(("account_input",)))
        if failures:
            self.notify("\n".join(failures), title="Fix SLURM settings", severity="error", timeout=8)
            self.log_message("Validation failed: " + "; ".join(failures))
            return False
        return True

    def validate_scan_inputs(self) -> bool:
        failures = self.invalid_inputs(("scan_root", "glob", "manifest"))
        if failures:
            self.notify("\n".join(failures), title="Fix file discovery settings", severity="error", timeout=8)
            self.log_message("Validation failed: " + "; ".join(failures))
            return False
        return True

    def build_python(self) -> str:
        return build_python(self.state_data)

    def build_slurm(self) -> str:
        return build_slurm(self.state_data, self.output_dir)

    def generate(self) -> tuple[Path, Path, Path] | None:
        if not self.validate_slurm_inputs():
            return None
        self.sync_state()
        py_path, slurm_path, bundle_path = write_bundle(self.state_data, self.output_dir)
        self.log_message(f"Generated {py_path}")
        self.log_message(f"Generated {slurm_path}")
        self.log_message(f"Generated {bundle_path}")
        self.notify(f"Generated bundle in {self.output_dir}", title="Generation complete", severity="information", timeout=6)
        return py_path, slurm_path, bundle_path

    def scan_manifest(self) -> Path:
        self.refresh_discovered_files()
        return self.write_selected_manifest()

    def submit(self) -> None:
        if not self.perlmutter:
            self.log_message("Refusing to submit: this does not look like Perlmutter.")
            return
        generated = self.generate()
        if generated is None:
            return
        _, slurm_path, _ = generated
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

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "account_select":
            if self._suppress_account_select_notice and event.value not in (Select.NULL, ""):
                self._suppress_account_select_notice = False
                return
            if event.value not in (Select.NULL, "") and not self._loading_accounts:
                self.notify(f"Using account {event.value}", title="Account selected", severity="information", timeout=4)
            return
        if event.select.id == "qos":
            self.sync_state()
            return
        if event.select.id not in {"format", "sample"}:
            return
        self.state_data.input_format = str(self.query_one("#format", Select).value)
        self.state_data.sample_type = str(self.query_one("#sample", Select).value)
        self.apply_dependency_change()

    def on_input_blurred(self, event: Input.Blurred) -> None:
        if event.validation_result is None:
            return
        event.input.set_class(event.validation_result.is_valid, "-valid")
        event.input.set_class(not event.validation_result.is_valid, "-invalid")
        if not event.validation_result.is_valid:
            self.notify("\n".join(event.validation_result.failure_descriptions), title="Invalid input", severity="warning", timeout=5)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.validation_result is None:
            return
        event.input.set_class(event.validation_result.is_valid, "-valid")
        event.input.set_class(not event.validation_result.is_valid, "-invalid")
        if not event.validation_result.is_valid:
            self.notify("\n".join(event.validation_result.failure_descriptions), title="Invalid input", severity="warning", timeout=5)

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        path = str(event.path)
        scan_root = self.query_one("#scan_root", Input)
        scan_root.value = path
        self.state_data.scan_root = path
        self.log_message(f"Selected scan directory: {path}")

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content.id != "wizard-tabs" or event.pane.id is None:
            return
        if event.pane.id.startswith("step-"):
            self.current_step = int(event.pane.id.removeprefix("step-"))
            self.refresh_step()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if self._syncing:
            return
        if event.switch.id and event.switch.id.startswith("obj-"):
            key = event.switch.id.removeprefix("obj-")
            if key != "Event":
                if event.value:
                    self.state_data.selected_objects.add(key)
                else:
                    dependents = self.state_data.remove_object_with_dependents(key)
                    if dependents:
                        dependent_titles = ", ".join(self.state_data.objects[dependent]["title"] for dependent in dependents)
                        self.notify(
                            f"Also turned off dependent object(s): {dependent_titles}",
                            title=f"{self.state_data.objects[key]['title']} disabled",
                            severity="information",
                            timeout=6,
                        )
                self.apply_dependency_change()
        elif event.switch.id and event.switch.id.startswith("var-"):
            _, key, name = event.switch.id.split("-", 2)
            required = name in self.state_data.objects[key].get("requiredVariables", [])
            if not required:
                variables = self.state_data.selected_variables.setdefault(key, set())
                if event.value:
                    variables.add(name)
                else:
                    variables.discard(name)
                self.apply_dependency_change()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("set-format-"):
            value = event.button.id.removeprefix("set-format-")
            self.query_one("#format", Select).value = value
            self.state_data.input_format = value
            self.apply_dependency_change()
            self.refresh_choice_buttons()
        elif event.button.id and event.button.id.startswith("set-sample-"):
            value = event.button.id.removeprefix("set-sample-")
            self.query_one("#sample", Select).value = value
            self.state_data.sample_type = value
            self.apply_dependency_change()
            self.refresh_choice_buttons()
        elif event.button.id == "generate":
            self.generate()
        elif event.button.id == "scan":
            self.refresh_discovered_files()
        elif event.button.id == "manifest_write":
            self.write_selected_manifest()
        elif event.button.id == "submit":
            self.submit()
        elif event.button.id == "prev_step":
            self.current_step -= 1
            self.refresh_step()
        elif event.button.id == "next_step":
            self.current_step += 1
            self.refresh_step()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PCDF ATLAS ntuple Textual wizard.")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd(), help="Directory for generated scripts and bundle.")
    args = parser.parse_args()
    NtupleWizardTui(output_dir=args.output_dir).run()


if __name__ == "__main__":
    main()
