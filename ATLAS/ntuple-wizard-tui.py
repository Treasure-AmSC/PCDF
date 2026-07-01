#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "textual>=8.2.8",
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
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from textual.app import App, ComposeResult
from textual.containers import Container, Grid, Horizontal, VerticalScroll
from textual.validation import Function, Regex
from textual.timer import Timer
from textual.widgets import Button, Collapsible, DirectoryTree, Footer, Input, Label, Log, RichLog, Select, SelectionList, Static, Switch, TabbedContent, TabPane, TextArea

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


class VisibleDirectoryTree(DirectoryTree):
    """Directory tree that hides dot-prefixed files and directories."""

    def filter_paths(self, paths: Any) -> Any:
        return [path for path in paths if not path.name.startswith(".")]


class NtupleWizardTui(App[None]):
    """Interactive Textual app for PCDF ntuple job generation."""

    TITLE = "ATLAS ntuple wizard"
    SUB_TITLE = "TREASURE → Parquet"

    STEPS = ("Input", "Objects", "Variables", "Perlmutter", "Generate", "Status")

    CSS_PATH = Path(__file__).with_name("ntuple-wizard-tui.tcss")

    BINDINGS = [("q", "quit", "Quit"), ("g", "generate", "Generate"), ("s", "submit", "Submit on Perlmutter")]
    JOB_REFRESH_INTERVAL = 10.0

    def __init__(self, output_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state_data = WizardState()
        self.perlmutter = on_perlmutter()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_data.manifest = str(self.output_dir / "pcdf-inputs.txt")
        self.current_step = 0
        self._syncing = False
        self._loading_accounts = False
        self._suppress_account_select_notice = False
        self.review_confirmed = False
        self.job_id = ""
        self.stdout_path: Path | None = None
        self.stderr_path: Path | None = None
        self.job_refresh_timer: Timer | None = None
        self.file_scan_timer: Timer | None = None
        self.discovered_files: list[Path] = []

    @staticmethod
    def non_empty(value: str) -> bool:
        return bool(value.strip())

    @staticmethod
    def existing_directory(value: str) -> bool:
        return Path(os.path.expandvars(os.path.expanduser(value or "."))).is_dir()

    @staticmethod
    def positive_integer(value: str) -> bool:
        return value.strip().isdigit() and int(value.strip()) >= 1

    def compose(self) -> ComposeResult:
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
                                yield Input(placeholder="Manual NERSC account", id="account_input", validators=[Function(self.non_empty, "Enter a NERSC account before submitting.")], validate_on=["blur", "submitted"])
                            else:
                                yield Input(placeholder="NERSC account", id="account_input", validators=[Function(self.non_empty, "Enter a NERSC account before submitting.")], validate_on=["blur", "submitted"])
                            yield Label("Queue / QOS", classes="field-label")
                            yield Select([(label, label) for label in ("regular", "debug", "premium")], value="regular", allow_blank=False, id="qos")
                            yield Label("Nodes", classes="field-label")
                            yield Input(value="1", placeholder="Nodes", id="nodes", validators=[Function(self.positive_integer, "Nodes must be a positive integer.")], validate_on=["blur", "submitted"])
                            yield Label("Wall time", classes="field-label")
                            yield Input(value="00:30:00", placeholder="Wall time", id="time", validators=[Regex(r"^\d{1,2}:\d{2}:\d{2}$", failure_description="Use HH:MM:SS wall time, for example 00:30:00.")], validate_on=["blur", "submitted"])
                            yield Label("Output base", classes="field-label")
                            yield Input(value="$SCRATCH/pcdf-output", placeholder="Output base", id="output", validators=[Function(self.non_empty, "Output base may not be empty.")], validate_on=["blur", "submitted"])
                            yield Label("Input manifest", classes="field-label")
                            yield Input(value=self.state_data.manifest, placeholder="Input manifest", id="manifest", validators=[Function(self.non_empty, "Input manifest may not be empty.")], validate_on=["blur", "submitted"])
                            yield Static("Perlmutter detected: " + ("yes" if self.perlmutter else "no"), classes="hint")
                        with VerticalScroll(classes="column"):
                            yield Static("Interactive file and folder picker", classes="section-title")
                            yield Label("Directory to scan", classes="field-label")
                            yield Input(value="$SCRATCH", placeholder="Directory to scan", id="scan_root", validators=[Function(self.existing_directory, "Scan directory must exist.")], validate_on=["blur", "submitted"])
                            with Collapsible(title="Advanced manifest options", collapsed=True):
                                yield Label("File glob", classes="field-label")
                                yield Input(value="DAOD_*.pool.root*", placeholder="Glob, e.g. DAOD_*.pool.root*", id="glob", validators=[Function(self.non_empty, "Glob pattern may not be empty.")], validate_on=["blur", "submitted"])
                            tree_root = Path(os.path.expandvars(os.environ.get("SCRATCH", ""))).expanduser()
                            if not tree_root.exists():
                                tree_root = Path.cwd()
                            yield VisibleDirectoryTree(tree_root, id="tree")
                            yield Static("Discovered files", classes="section-title")
                            yield SelectionList[str](id="files")
                            yield Button("Write selected manifest", id="manifest_write")

                with TabPane("5. Generate", id="step-4", classes="wizard-step"):
                    with Horizontal(classes="two-column"):
                        with VerticalScroll(classes="column"):
                            yield Static("Generate", classes="section-title")
                            yield Static("Generate the converter, SLURM wrapper, and tar bundle. On Perlmutter, submit directly after reviewing the settings.", classes="hint")
                            yield Static("", id="summary_panel")
                            yield Static("Review generated scripts before submitting", classes="section-title")
                            with TabbedContent(initial="preview-python", id="review-tabs"):
                                with TabPane("Python", id="preview-python"):
                                    yield TextArea("", language="python", read_only=True, show_line_numbers=True, id="python_preview", classes="script-preview")
                                with TabPane("SLURM", id="preview-slurm"):
                                    yield TextArea("", language="bash", read_only=True, show_line_numbers=True, id="slurm_preview", classes="script-preview")
                            with Horizontal(id="generate-actions"):
                                yield Button("Generate scripts", id="generate", variant="primary")
                                yield Button("I reviewed scripts", id="confirm_review")
                                yield Button("Submit with sbatch", id="submit", variant="success", disabled=not self.perlmutter)
                with TabPane("6. Status", id="step-5", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static("Job status", classes="section-title")
                        yield Static("No job submitted yet.", id="job_status", classes="hint")
                        yield Static("", id="log_paths", classes="hint")
                        yield Button("Refresh now", id="refresh_job")
                        with Grid(classes="job-log-grid"):
                            yield Static("stdout", classes="section-title")
                            yield Static("stderr", classes="section-title")
                            yield Log(id="stdout_log", classes="job-log")
                            yield Log(id="stderr_log", classes="job-log")
                        yield Static("TUI log", classes="section-title")
                        yield RichLog(id="log", wrap=True, highlight=True)
            with Horizontal(id="wizard-nav"):
                yield Button("Previous", id="prev_step")
                yield Button("Next", id="next_step", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_dependency_widgets()
        self.refresh_step()
        self.log_message("PCDF ntuple Textual wizard ready.")
        self.log_message(f"Generated files will be written under {self.output_dir}.")
        if self.perlmutter:
            self.log_message("Perlmutter detected: scan input files, generate scripts, then press submit.")
            self.load_accounts_with_iris(notify_user=False)
        else:
            self.log_message("Not on Perlmutter: generation is enabled; sbatch submission is disabled.")
        self.refresh_log_locations()

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
        self.query_one("#python_preview", TextArea).load_text(self.build_python())
        self.query_one("#slurm_preview", TextArea).load_text(self.build_slurm())
        self.query_one("#submit", Button).disabled = (not self.perlmutter) or (not self.review_confirmed)

    def refresh_step(self) -> None:
        self.current_step = max(0, min(len(self.STEPS) - 1, self.current_step))
        tabs = self.query_one("#wizard-tabs", TabbedContent)
        target = f"step-{self.current_step}"
        if tabs.active != target:
            tabs.active = target
        self.query_one("#prev_step", Button).disabled = self.current_step == 0
        next_button = self.query_one("#next_step", Button)
        if self.current_step == 3:
            next_button.label = "Review"
        elif self.current_step == 4:
            next_button.label = "Status"
        else:
            next_button.label = "Next"
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
            account_select = self.query_one("#account_select", Select)
            selected_account = account_select.value
            manual_account = self.query_one("#account_input", Input).value.strip()
            state.account = str(selected_account) if (not account_select.disabled and selected_account not in (Select.NULL, "")) else manual_account
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
        state.glob_pattern = self.query_one("#glob", Input).value.strip() or "DAOD_*.pool.root*"
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
        self.mark_unreviewed()
        self.state_data.ensure_dependencies()
        self.refresh_dependency_widgets()

    def mark_unreviewed(self) -> None:
        self.review_confirmed = False
        if self.is_mounted:
            self.query_one("#submit", Button).disabled = True

    def schedule_file_discovery(self, delay: float = 0.6) -> None:
        if self.file_scan_timer is not None:
            self.file_scan_timer.stop()
        self.file_scan_timer = self.set_timer(delay, self.refresh_discovered_files)

    def refresh_discovered_files(self) -> None:
        if not self.validate_file_discovery_inputs():
            return
        self.sync_state()
        self.discovered_files = discover_files(self.state_data.scan_root, self.state_data.glob_pattern)
        files = self.query_one("#files", SelectionList)
        files.clear_options()
        files.add_options((str(path), str(path), True) for path in self.discovered_files)
        self.log_message(f"Found {len(self.discovered_files)} file(s) under {self.state_data.scan_root}")

    def selected_discovered_files(self) -> list[Path]:
        files = self.query_one("#files", SelectionList)
        return [Path(value) for value in files.selected]

    def manifest_path(self) -> Path:
        self.sync_state()
        return Path(os.path.expandvars(os.path.expanduser(self.state_data.manifest)))

    def manifest_has_work(self) -> bool:
        manifest = self.manifest_path()
        return manifest.is_file() and manifest.stat().st_size > 0

    def write_selected_manifest(self) -> Path | None:
        if not self.validate_scan_inputs():
            return None
        self.sync_state()
        selected = self.selected_discovered_files()
        if not selected:
            if self.discovered_files:
                self.log_message("No discovered files are selected; manifest was not changed.")
                self.notify("Select at least one discovered file before writing the manifest.", title="Manifest unchanged", severity="warning", timeout=8)
                return None
            self.log_message("No discovery list is loaded; writing a manifest from the current scan instead.")
            manifest, count = scan_manifest(self.state_data)
        else:
            manifest, count = write_manifest(selected, self.state_data.manifest)
        if count == 0:
            self.log_message(f"No input files matched {self.state_data.glob_pattern} under {self.state_data.scan_root}; manifest was not usable.")
            self.notify("No input files were found for the manifest.", title="Manifest empty", severity="warning", timeout=8)
            return None
        self.log_message(f"Wrote {count} input file(s) to {manifest}")
        self.notify(f"Wrote {count} file(s) to {manifest}", title="Manifest written", severity="information", timeout=6)
        return manifest

    def ensure_manifest_for_submit(self) -> bool:
        if self.discovered_files:
            self.log_message("Refreshing the manifest from the current discovered-file selection before submission.")
            manifest = self.write_selected_manifest()
            if manifest is None or not self.manifest_has_work():
                self.notify("Create a non-empty input manifest before submitting.", title="Submission blocked", severity="error", timeout=8)
                self.log_message("Submission blocked: input manifest is still missing or empty.")
                return False
            return True
        if self.manifest_has_work():
            return True
        self.log_message("Input manifest is missing or empty; writing it before submission.")
        manifest = self.write_selected_manifest()
        if manifest is None or not self.manifest_has_work():
            self.notify("Create a non-empty input manifest before submitting.", title="Submission blocked", severity="error", timeout=8)
            self.log_message("Submission blocked: input manifest is still missing or empty.")
            return False
        return True

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
            self.log_message("iris command not found; enter an account manually.")
            self._loading_accounts = False
            return
        except subprocess.TimeoutExpired:
            account_select = self.query_one("#account_select", Select)
            account_select.set_options([("iris timed out", "")])
            account_select.value = ""
            account_select.disabled = True
            if notify_user:
                self.notify("iris did not finish within 15 seconds; enter an account manually.", title="Iris timeout", severity="warning", timeout=8)
            self._loading_accounts = False
            return
        try:
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            accounts = [] if result.returncode else self.parse_iris_accounts(output)
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
            account_select = self.query_one("#account_select", Select)
            selected_account = account_select.value
            manual_account = self.query_one("#account_input", Input).value.strip()
            if account_select.disabled or selected_account in (Select.NULL, ""):
                failures.extend(self.invalid_inputs(("account_input",)))
            if account_select.disabled and not manual_account:
                failures.append("Enter a NERSC account.")
            elif (not account_select.disabled) and selected_account in (Select.NULL, "") and not manual_account:
                failures.append("Choose or enter a NERSC account.")
        else:
            failures.extend(self.invalid_inputs(("account_input",)))
        if failures:
            self.notify("\n".join(failures), title="Fix SLURM settings", severity="error", timeout=8)
            self.log_message("Validation failed: " + "; ".join(failures))
            return False
        return True

    def validate_file_discovery_inputs(self) -> bool:
        failures = self.invalid_inputs(("scan_root", "glob"))
        if failures:
            self.notify("\n".join(failures), title="Fix file discovery settings", severity="error", timeout=8)
            self.log_message("Validation failed: " + "; ".join(failures))
            return False
        return True

    def validate_scan_inputs(self) -> bool:
        failures = self.invalid_inputs(("scan_root", "glob", "manifest"))
        if failures:
            self.notify("\n".join(failures), title="Fix manifest settings", severity="error", timeout=8)
            self.log_message("Validation failed: " + "; ".join(failures))
            return False
        return True

    def build_python(self) -> str:
        return build_python(self.state_data)

    def build_slurm(self) -> str:
        return build_slurm(self.state_data, self.output_dir)

    def generate(self) -> tuple[Path, Path, Path] | None:
        if self.discovered_files and self.write_selected_manifest() is None:
            return None
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
        if not self.review_confirmed:
            self.notify("Review and confirm the generated Python and SLURM scripts before submitting.", title="Review required", severity="warning", timeout=8)
            self.log_message("Submission blocked: generated scripts have not been reviewed.")
            return
        if not self.ensure_manifest_for_submit():
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
            return
        self.job_id = self.parse_sbatch_job_id(result.stdout)
        if self.job_id:
            self.set_job_log_paths()
            self.query_one("#job_status", Static).update(f"Submitted SLURM job {self.job_id}.")
            self.start_job_auto_refresh()
            self.refresh_job_status()
        self.current_step = 5
        self.refresh_step()

    def parse_sbatch_job_id(self, output: str) -> str:
        for token in output.split():
            if token.isdigit():
                return token
        return ""

    def set_job_log_paths(self) -> None:
        if not self.job_id:
            self.stdout_path = None
            self.stderr_path = None
            return
        self.stdout_path = self.output_dir / f"pcdf-ntuple-{self.job_id}.out"
        self.stderr_path = self.output_dir / f"pcdf-ntuple-{self.job_id}.err"
        if self.is_mounted:
            self.refresh_log_locations()

    def update_log_widget(self, widget_id: str, path: Path | None) -> None:
        log = self.query_one(widget_id, Log)
        log.clear()
        if path is None:
            log.write_line("No job submitted yet.")
            return
        if not path.exists():
            log.write_line(f"Waiting for {path}")
            return
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError as error:
            log.write_line(f"Could not read {path}: {error}")
            return
        log.write_lines(lines or [f"{path} is empty."])

    def refresh_log_locations(self) -> None:
        if self.stdout_path is not None and self.stderr_path is not None:
            text = f"SLURM stdout: {self.stdout_path}\nSLURM stderr: {self.stderr_path}"
        else:
            text = f"Generated files directory: {self.output_dir}\nSLURM logs will be written here as pcdf-ntuple-<jobid>.out/.err after submission."
        self.query_one("#log_paths", Static).update(text)

    def refresh_job_logs(self) -> None:
        self.refresh_log_locations()
        self.update_log_widget("#stdout_log", self.stdout_path)
        self.update_log_widget("#stderr_log", self.stderr_path)

    def start_job_auto_refresh(self, interval: float | None = None) -> None:
        if self.job_refresh_timer is not None:
            self.job_refresh_timer.stop()
        self.job_refresh_timer = self.set_interval(interval or self.JOB_REFRESH_INTERVAL, self.refresh_job_status)

    def stop_job_auto_refresh(self) -> None:
        if self.job_refresh_timer is not None:
            self.job_refresh_timer.stop()
            self.job_refresh_timer = None

    def refresh_job_status(self) -> None:
        if not self.job_id:
            self.notify("Submit a job before refreshing status.", title="No job", severity="warning", timeout=5)
            self.refresh_job_logs()
            return
        try:
            result = subprocess.run(
                ["squeue", "--noheader", f"--jobs={self.job_id}", "--format=%.18i %.9T %.10M %.20R"],
                check=False,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError:
            self.query_one("#job_status", Static).update("squeue is not available on this host; showing log files only.")
            self.stop_job_auto_refresh()
            self.refresh_job_logs()
            return
        status = result.stdout.strip()
        if result.returncode == 0 and status:
            self.query_one("#job_status", Static).update(status)
            self.log_message(status)
        else:
            message = result.stderr.strip() or f"Job {self.job_id} is no longer in squeue."
            self.query_one("#job_status", Static).update(message)
            self.log_message(message)
            self.stop_job_auto_refresh()
        self.refresh_job_logs()

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
                self.mark_unreviewed()
                self.notify(f"Using account {event.value}", title="Account selected", severity="information", timeout=4)
            return
        if event.select.id == "qos":
            self.mark_unreviewed()
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
        if event.input.id in {"account_input", "nodes", "time", "output", "manifest"}:
            self.mark_unreviewed()
        if event.input.id in {"scan_root", "glob"} and event.validation_result.is_valid:
            self.schedule_file_discovery()
        if not event.validation_result.is_valid:
            self.notify("\n".join(event.validation_result.failure_descriptions), title="Invalid input", severity="warning", timeout=5)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.validation_result is None:
            return
        event.input.set_class(event.validation_result.is_valid, "-valid")
        event.input.set_class(not event.validation_result.is_valid, "-invalid")
        if event.input.id in {"account_input", "nodes", "time", "output", "manifest"}:
            self.mark_unreviewed()
        if event.input.id in {"scan_root", "glob"} and event.validation_result.is_valid:
            self.schedule_file_discovery()
        if not event.validation_result.is_valid:
            self.notify("\n".join(event.validation_result.failure_descriptions), title="Invalid input", severity="warning", timeout=5)

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        path = str(event.path)
        scan_root = self.query_one("#scan_root", Input)
        scan_root.value = path
        self.state_data.scan_root = path
        self.log_message(f"Selected scan directory: {path}")
        self.schedule_file_discovery(delay=0.1)

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
        elif event.button.id == "confirm_review":
            self.sync_state()
            if not self.validate_slurm_inputs():
                return
            self.refresh_summary()
            self.review_confirmed = True
            self.query_one("#submit", Button).disabled = not self.perlmutter
            self.notify("Generated Python and SLURM previews marked reviewed.", title="Review confirmed", severity="information", timeout=5)
        elif event.button.id == "manifest_write":
            self.write_selected_manifest()
        elif event.button.id == "submit":
            self.submit()
        elif event.button.id == "refresh_job":
            self.refresh_job_status()
        elif event.button.id == "prev_step":
            self.current_step -= 1
            self.refresh_step()
        elif event.button.id == "next_step":
            self.current_step += 1
            self.refresh_step()


def default_output_dir() -> Path:
    """Create a generated-file directory visible to Perlmutter compute nodes."""
    scratch = os.environ.get("SCRATCH")
    if scratch:
        scratch_path = Path(os.path.expandvars(os.path.expanduser(scratch)))
        if scratch_path.exists():
            return Path(tempfile.mkdtemp(prefix="pcdf-ntuple-", dir=scratch_path))
    return Path(tempfile.mkdtemp(prefix="pcdf-ntuple-", dir=Path.cwd()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PCDF ATLAS ntuple Textual wizard.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for generated scripts and bundle. Defaults to a temporary directory under $SCRATCH when available, otherwise under the current directory.")
    args = parser.parse_args()
    output_dir = args.output_dir or default_output_dir()
    print(f"PCDF ntuple wizard generated files/log directory: {output_dir}", file=sys.stderr)
    NtupleWizardTui(output_dir=output_dir).run()
    print(f"PCDF ntuple wizard generated files/log directory: {output_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
