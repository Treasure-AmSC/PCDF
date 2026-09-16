#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "textual>=8.2.8",
# ]
# ///
"""Textual TUI for generating PCDF ATLAS ntuple conversion bundles.

Run with::

    uv run ATLAS/ntuple-wizard-tui.py

The TUI can generate and submit either a NERSC Perlmutter SLURM job or an
HTCondor cluster that uses a shared filesystem.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from textual.app import App, ComposeResult
from textual.containers import Container, Grid, Horizontal, VerticalScroll
from textual.validation import Function, Regex
from textual.timer import Timer
from textual.widgets import Button, Collapsible, DirectoryTree, Footer, Input, Label, Log, RichLog, Select, SelectionList, Static, Switch, TabbedContent, TabPane, TextArea

from ntuple_wizard_core import (
    BUNDLE_ROOT_NAME,
    WizardState,
    build_condor,
    build_python,
    build_slurm,
    discover_files,
    on_perlmutter,
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
    SUB_TITLE = "JETM16 → Parquet"

    STEPS = ("Input", "Objects", "Variables", "Batch system", "Generate", "Status")

    CSS_PATH = Path(__file__).with_name("ntuple-wizard-tui.tcss")

    BINDINGS = [("q", "quit", "Quit"), ("g", "generate", "Generate"), ("s", "submit", "Submit batch job")]
    JOB_REFRESH_INTERVAL = 10.0

    def __init__(self, output_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state_data = WizardState()
        self.perlmutter = on_perlmutter()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.bundle_root = self.output_dir / BUNDLE_ROOT_NAME
        self.state_data.manifest = str(self.bundle_root / "pcdf-inputs.txt")
        self.state_data.output_base = str(self.bundle_root / "output")
        self.current_step = 0
        self._syncing = False
        self._loading_accounts = False
        self._suppress_account_select_notice = False
        self.review_confirmed = False
        self.job_id = ""
        self.job_scheduler = ""
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
            yield Static("ATLAS DAOD → Parquet wizard", id="hero")
            with TabbedContent(initial="step-0", id="wizard-tabs", classes="wizard-shell"):
                with TabPane("1. Input", id="step-0", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static("Input format and sample type", classes="section-title")
                        yield Static("PHYSLITE lacks jet-constituent inputs. Collision data excludes truth and flavor fields.", classes="hint")
                        with Collapsible(title="Terms used here", collapsed=True):
                            yield Static("DAOD: An ATLAS analysis data format stored in a ROOT file.\nJETM16: An ATLAS DAOD made for jet studies. It includes detailed jet content.\nPHYSLITE: A compact ATLAS DAOD with objects used in many analyses.", classes="hint")
                        yield Label("Input format", classes="field-label")
                        yield Select([(label, label) for label in ("JETM16", "PHYSLITE")], value="JETM16", id="format", classes="hidden-select")
                        with Horizontal(classes="choice-row"):
                            yield Button("JETM16", id="set-format-JETM16", classes="choice-button active-step")
                            yield Button("PHYSLITE", id="set-format-PHYSLITE", classes="choice-button")
                        yield Label("Sample type", classes="field-label")
                        yield Select([(label, label) for label in ("MC", "DATA")], value="MC", id="sample", classes="hidden-select")
                        with Horizontal(classes="choice-row"):
                            yield Button("Simulation / MC", id="set-sample-MC", classes="choice-button active-step")
                            yield Button("Collision data", id="set-sample-DATA", classes="choice-button")

                with TabPane("2. Objects", id="step-1", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static("Output objects", classes="section-title")
                        yield Static("Required tables remain selected. Turning off a table also turns off tables that depend on it.", classes="hint")
                        with Grid(classes="object-grid"):
                            for key, obj in self.state_data.objects.items():
                                selected = key in self.state_data.selected_objects
                                with Grid(id=f"obj-card-{key}", classes="toggle-card selected-choice" if selected else "toggle-card deselected-choice"):
                                    yield Switch(value=selected, id=f"obj-{key}", classes="toggle-switch", disabled=key == "Event")
                                    yield Label(obj["title"], id=f"obj-label-{key}", classes="toggle-label")

                with TabPane("3. Variables", id="step-2", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static("Output variables", classes="section-title")
                        yield Static("Four-vector fields are required. Truth labels are unavailable for collision data.", classes="hint")
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

                with TabPane("4. Batch system", id="step-3", classes="wizard-step"):
                    with Horizontal(classes="two-column"):
                        with VerticalScroll(classes="column"):
                            yield Static("Batch job", classes="section-title")
                            with Collapsible(title="Terms used here", collapsed=True):
                                yield Static("SLURM: The workload manager used on Perlmutter.\nHTCondor: A workload manager that queues independent jobs.\nManifest: A text file with one input file path on each line.\nShared filesystem: Storage visible at the same path from submit and execute nodes.", classes="hint")
                            yield Label("Batch system", classes="field-label")
                            yield Select([("SLURM on NERSC Perlmutter", "slurm"), ("HTCondor with a shared filesystem", "condor")], value="slurm", allow_blank=False, id="scheduler")
                            with Container(id="slurm_settings"):
                                yield Label("NERSC account", classes="field-label")
                                if self.perlmutter:
                                    yield Select([("Loading accounts from iris…", "")], value="", allow_blank=False, disabled=True, id="account_select")
                                    yield Input(placeholder="Manual NERSC account", id="account_input", validators=[Function(self.non_empty, "Enter a NERSC account before submitting.")], validate_on=["blur", "submitted"])
                                else:
                                    yield Input(placeholder="NERSC account", id="account_input", validators=[Function(self.non_empty, "Enter a NERSC account before submitting.")], validate_on=["blur", "submitted"])
                                yield Static("Most users can leave these settings unchanged.", id="advanced_slurm_help", classes="hint")
                                with Collapsible(title="Advanced Perlmutter settings", collapsed=True, id="advanced_slurm"):
                                    yield Label("Queue (QOS)", classes="field-label")
                                    yield Select([(label, label) for label in ("regular", "debug", "premium")], value="regular", allow_blank=False, id="qos")
                                    yield Label("Nodes", classes="field-label")
                                    yield Input(value="1", placeholder="Nodes", id="nodes", validators=[Function(self.positive_integer, "Nodes must be a positive integer.")], validate_on=["blur", "submitted"])
                                    yield Label("Wall time", classes="field-label")
                                    yield Input(value="00:30:00", placeholder="Wall time", id="time", validators=[Regex(r"^\d{1,2}:\d{2}:\d{2}$", failure_description="Use HH:MM:SS wall time, for example 00:30:00.")], validate_on=["blur", "submitted"])
                            with Container(id="condor_settings"):
                                yield Static("Most users can leave these settings unchanged.", id="advanced_condor_help", classes="hint")
                                with Collapsible(title="Advanced HTCondor settings", collapsed=True, id="advanced_condor"):
                                    yield Label("CPU cores per file", classes="field-label")
                                    yield Input(value="1", placeholder="CPU cores", id="condor_cpus", validators=[Function(self.positive_integer, "CPU cores must be a positive integer.")], validate_on=["blur", "submitted"])
                                    yield Label("Memory per file (MiB)", classes="field-label")
                                    yield Input(value="4096", placeholder="Memory in MiB", id="condor_memory", validators=[Function(self.positive_integer, "Memory must be a positive integer.")], validate_on=["blur", "submitted"])
                                    yield Label("Scratch disk per file (MiB)", classes="field-label")
                                    yield Input(value="4096", placeholder="Disk in MiB", id="condor_disk", validators=[Function(self.positive_integer, "Disk must be a positive integer.")], validate_on=["blur", "submitted"])
                                    yield Label("Worker requirements (optional)", classes="field-label")
                                    yield Input(placeholder="ClassAd expression", id="condor_requirements")
                            yield Label("Output dataset directory", classes="field-label")
                            yield Input(value=self.state_data.output_base, placeholder="Output dataset directory", id="output", validators=[Function(self.non_empty, "Enter an output dataset directory.")], validate_on=["blur", "submitted"])
                            yield Label("Input-file manifest", classes="field-label")
                            yield Input(value=self.state_data.manifest, placeholder="Input-file manifest", id="manifest", validators=[Function(self.non_empty, "Enter an input-file manifest path.")], validate_on=["blur", "submitted"])
                            yield Static("Perlmutter detected: " + ("Yes" if self.perlmutter else "No") + ". HTCondor submission is available when condor_submit is on PATH.", classes="hint")
                        with VerticalScroll(classes="column"):
                            yield Static("Manifest source", classes="section-title")
                            yield Static("The bundle helper can also find a Rucio dataset copied to NERSC_LOCALGROUPDISK.", classes="hint")
                            yield Label("Local data directory", classes="field-label")
                            yield Input(value="$SCRATCH", placeholder="Directory used with rucio download", id="scan_root", validators=[Function(self.existing_directory, "Data directory must exist.")], validate_on=["blur", "submitted"])
                            with Collapsible(title="Advanced manifest options", collapsed=True):
                                yield Label("Filename pattern", classes="field-label")
                                yield Input(value="DAOD_*.pool.root*", placeholder="For example: DAOD_*.pool.root*", id="glob", validators=[Function(self.non_empty, "Enter a filename pattern.")], validate_on=["blur", "submitted"])
                            tree_root = Path(os.path.expandvars(os.environ.get("SCRATCH", ""))).expanduser()
                            if not tree_root.exists():
                                tree_root = Path.cwd()
                            yield VisibleDirectoryTree(tree_root, id="tree")
                            yield Static("Discovered files", classes="section-title")
                            yield SelectionList[str](id="files")
                            yield Button("Save selected files to manifest", id="manifest_write")

                with TabPane("5. Generate", id="step-4", classes="wizard-step"):
                    with Horizontal(classes="two-column"):
                        with VerticalScroll(classes="column"):
                            yield Static("Generate", classes="section-title")
                            yield Static("", id="summary_panel")
                            yield Static("Review the generated scripts", classes="section-title")
                            with TabbedContent(initial="preview-python", id="review-tabs"):
                                with TabPane("Python", id="preview-python"):
                                    yield TextArea("", language="python", read_only=True, show_line_numbers=True, id="python_preview", classes="script-preview")
                                with TabPane("Batch file", id="preview-slurm"):
                                    yield TextArea("", language="bash", read_only=True, show_line_numbers=True, id="slurm_preview", classes="script-preview")
                            with Horizontal(id="generate-actions"):
                                yield Button("Generate scripts", id="generate", variant="primary")
                                yield Button("Confirm review", id="confirm_review")
                                yield Button("Submit batch job", id="submit", variant="success", disabled=True)
                with TabPane("6. Status", id="step-5", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static("Job status", classes="section-title")
                        yield Static("No job submitted yet.", id="job_status", classes="hint")
                        yield Static("", id="log_paths", classes="hint")
                        yield Button("Refresh now", id="refresh_job")
                        with Grid(classes="job-log-grid"):
                            yield Static("Standard output", classes="section-title")
                            yield Static("Standard error", classes="section-title")
                            yield Log(id="stdout_log", classes="job-log")
                            yield Log(id="stderr_log", classes="job-log")
                        yield Static("Wizard activity", classes="section-title")
                        yield RichLog(id="log", wrap=True, highlight=True)
            with Horizontal(id="wizard-nav"):
                yield Button("Previous", id="prev_step")
                yield Button("Next", id="next_step", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_dependency_widgets()
        self.refresh_step()
        self.log_message("The ATLAS ntuple wizard is ready.")
        self.log_message(f"The bundle will be saved in {self.bundle_root}.")
        if self.perlmutter:
            self.log_message("This is a Perlmutter login node. Choose input files, build the scripts, and then submit the job.")
            self.load_accounts_with_iris(notify_user=False)
        else:
            self.log_message("This host can generate either batch format. HTCondor submission is available when condor_submit is on PATH.")
        self.refresh_scheduler_controls()
        self.refresh_log_locations()

    def log_message(self, message: str) -> None:
        self.query_one("#log", RichLog).write(message)

    def refresh_summary(self) -> None:
        state = self.state_data
        config = state.selected_config()
        object_lines = [
            f"• {state.objects[key]['title']}: {len(value['aliases'])} "
            f"{'variable' if len(value['aliases']) == 1 else 'variables'}"
            for key, value in config["objects"].items()
        ]
        slurm_status = (
            f"HTCondor: one job per file, {state.condor_cpus} CPU core(s), "
            f"{state.condor_memory_mb} MiB memory, {state.condor_disk_mb} MiB disk."
            if state.scheduler == "condor"
            else f"Perlmutter SLURM: {state.nodes} exclusive CPU node(s), queue {state.qos}, wall time {state.time}."
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
        self.query_one("#slurm_preview", TextArea).load_text(self.build_batch_file())
        self.query_one("#submit", Button).disabled = (not self.submission_available()) or (not self.review_confirmed)

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
        for value in ("JETM16", "PHYSLITE"):
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
        scheduler = self.query_one("#scheduler", Select).value
        state.scheduler = "slurm" if scheduler is Select.NULL else str(scheduler)
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
        for widget_id, attribute, fallback in (
            ("condor_cpus", "condor_cpus", 1),
            ("condor_memory", "condor_memory_mb", 4096),
            ("condor_disk", "condor_disk_mb", 4096),
        ):
            try:
                setattr(state, attribute, max(1, int(self.query_one(f"#{widget_id}", Input).value.strip())))
            except ValueError:
                setattr(state, attribute, fallback)
        state.condor_requirements = self.query_one("#condor_requirements", Input).value.strip()
        state.output_base = self.query_one("#output", Input).value.strip() or str(self.bundle_root / "output")
        state.manifest = self.query_one("#manifest", Input).value.strip() or str(self.bundle_root / "pcdf-inputs.txt")
        state.scan_root = self.query_one("#scan_root", Input).value.strip() or "$SCRATCH"
        state.glob_pattern = self.query_one("#glob", Input).value.strip() or "DAOD_*.pool.root*"
        state.ensure_dependencies()

    def submission_available(self) -> bool:
        if self.state_data.scheduler == "condor":
            return shutil.which("condor_submit") is not None
        return self.perlmutter and shutil.which("sbatch") is not None

    def refresh_scheduler_controls(self) -> None:
        condor = self.state_data.scheduler == "condor"
        self.query_one("#slurm_settings", Container).display = not condor
        self.query_one("#condor_settings", Container).display = condor
        for widget_id in ("account_input", "qos", "nodes", "time"):
            self.query_one(f"#{widget_id}").disabled = condor
        if self.perlmutter and condor:
            self.query_one("#account_select", Select).disabled = True
        for widget_id in ("condor_cpus", "condor_memory", "condor_disk", "condor_requirements"):
            self.query_one(f"#{widget_id}").disabled = not condor
        self.query_one("#submit", Button).label = "Submit with condor_submit" if condor else "Submit with sbatch"
        self.query_one("#submit", Button).disabled = (not self.submission_available()) or (not self.review_confirmed)

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
        count = len(self.discovered_files)
        self.log_message(f"Found {count} {'file' if count == 1 else 'files'} under {self.state_data.scan_root}.")

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
                self.log_message("No discovered files are selected. The manifest was not changed.")
                self.notify("Select one or more discovered files, then save the manifest.", title="Manifest unchanged", severity="warning", timeout=8)
                return None
            self.log_message("No file list is loaded. Scanning the selected directory before writing the manifest.")
            manifest, count = scan_manifest(self.state_data)
        else:
            manifest, count = write_manifest(selected, self.state_data.manifest)
        if count == 0:
            self.log_message(f"No files matched {self.state_data.glob_pattern} under {self.state_data.scan_root}. The manifest was not written.")
            self.notify("No matching input files were found.", title="Manifest not written", severity="warning", timeout=8)
            return None
        count_text = f"{count} {'file' if count == 1 else 'files'}"
        self.log_message(f"Wrote {count_text} to {manifest}.")
        self.notify(f"Wrote {count_text} to {manifest}.", title="Manifest written", severity="information", timeout=6)
        return manifest

    def ensure_manifest_for_submit(self) -> bool:
        if self.discovered_files:
            self.log_message("Updating the manifest from the files selected here before submission.")
            manifest = self.write_selected_manifest()
            if manifest is None or not self.manifest_has_work():
                self.notify("Create a non-empty input manifest before submitting.", title="Submission blocked", severity="error", timeout=8)
                self.log_message("Submission blocked: input manifest is still missing or empty.")
                return False
            return True
        if self.manifest_has_work():
            return True
        self.log_message("The input manifest is missing or empty. Writing it before submission.")
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
                self.notify("This host does not provide the iris command. Enter an account manually.", title="Iris unavailable", severity="warning", timeout=8)
            account_select = self.query_one("#account_select", Select)
            account_select.set_options([("Enter an account manually", "")])
            account_select.value = ""
            account_select.disabled = True
            self.log_message("The iris command was not found. Enter a NERSC account manually.")
            self._loading_accounts = False
            return
        except subprocess.TimeoutExpired:
            account_select = self.query_one("#account_select", Select)
            account_select.set_options([("Enter an account manually", "")])
            account_select.value = ""
            account_select.disabled = True
            if notify_user:
                self.notify("The iris command did not finish within 15 seconds. Enter an account manually.", title="Iris timeout", severity="warning", timeout=8)
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
                    count = len(accounts)
                    self.notify(f"Loaded {count} NERSC {'account' if count == 1 else 'accounts'} from iris.", title="NERSC accounts loaded", severity="information", timeout=6)
                self.log_message("NERSC accounts loaded from iris: " + ", ".join(accounts))
            else:
                account_select.set_options([("No iris accounts found", "")])
                account_select.value = ""
                account_select.disabled = True
                if notify_user:
                    self.notify("The iris command returned no account names that the wizard could read.", title="No NERSC accounts found", severity="warning", timeout=8)
                self.log_message("The iris command returned no account names that the wizard could read.")
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
        self.sync_state()
        common_failures = self.invalid_inputs(("output", "manifest"))
        if self.state_data.scheduler == "condor":
            failures = common_failures + self.invalid_inputs(("condor_cpus", "condor_memory", "condor_disk"))
        else:
            failures = common_failures + self.invalid_inputs(("nodes", "time"))
        if self.state_data.scheduler == "slurm" and self.perlmutter:
            account_select = self.query_one("#account_select", Select)
            selected_account = account_select.value
            manual_account = self.query_one("#account_input", Input).value.strip()
            if account_select.disabled or selected_account in (Select.NULL, ""):
                failures.extend(self.invalid_inputs(("account_input",)))
            if account_select.disabled and not manual_account:
                failures.append("Enter a NERSC account.")
            elif (not account_select.disabled) and selected_account in (Select.NULL, "") and not manual_account:
                failures.append("Choose or enter a NERSC account.")
        elif self.state_data.scheduler == "slurm":
            failures.extend(self.invalid_inputs(("account_input",)))
        if failures:
            self.notify("\n".join(failures), title="Fix batch settings", severity="error", timeout=8)
            self.log_message("Validation failed:\n" + "\n".join(f"• {failure}" for failure in failures))
            return False
        return True

    def validate_file_discovery_inputs(self) -> bool:
        failures = self.invalid_inputs(("scan_root", "glob"))
        if failures:
            self.notify("\n".join(failures), title="Fix file discovery settings", severity="error", timeout=8)
            self.log_message("Validation failed:\n" + "\n".join(f"• {failure}" for failure in failures))
            return False
        return True

    def validate_scan_inputs(self) -> bool:
        failures = self.invalid_inputs(("scan_root", "glob", "manifest"))
        if failures:
            self.notify("\n".join(failures), title="Fix manifest settings", severity="error", timeout=8)
            self.log_message("Validation failed:\n" + "\n".join(f"• {failure}" for failure in failures))
            return False
        return True

    def build_python(self) -> str:
        return build_python(self.state_data)

    def build_slurm(self) -> str:
        return build_slurm(self.state_data, self.output_dir)

    def build_batch_file(self) -> str:
        if self.state_data.scheduler == "condor":
            return build_condor(self.state_data, self.output_dir)
        return self.build_slurm()

    def generate(self) -> tuple[Path, Path, Path] | None:
        if self.discovered_files and self.write_selected_manifest() is None:
            return None
        if not self.validate_slurm_inputs():
            return None
        self.sync_state()
        py_path, submit_path, bundle_path = write_bundle(self.state_data, self.output_dir)
        self.log_message(f"Created converter: {py_path}")
        self.log_message(f"Created batch file: {submit_path}")
        self.log_message(f"Created bundle: {bundle_path}")
        self.notify(
            f"Saved the working bundle in {self.bundle_root} and the archive in {bundle_path}.",
            title="Generation complete",
            severity="information",
            timeout=6,
        )
        return py_path, submit_path, bundle_path

    def scan_manifest(self) -> Path:
        self.refresh_discovered_files()
        return self.write_selected_manifest()

    def submit(self) -> None:
        self.sync_state()
        if not self.submission_available():
            command = "condor_submit" if self.state_data.scheduler == "condor" else "sbatch on a Perlmutter login node"
            self.notify(f"Submission needs {command}.", title="Submission unavailable", severity="warning", timeout=8)
            self.log_message(f"The job was not submitted because {command} is unavailable.")
            return
        if not self.review_confirmed:
            self.notify("Review and confirm the converter and batch file before you submit.", title="Review required", severity="warning", timeout=8)
            self.log_message("Submission blocked: generated scripts have not been reviewed.")
            return
        if not self.ensure_manifest_for_submit():
            return
        generated = self.generate()
        if generated is None:
            return
        _, submit_path, _ = generated
        if self.state_data.scheduler == "condor":
            command = ["condor_submit", "-terse", str(submit_path)]
        else:
            command = ["sbatch", str(submit_path)]
        result = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            cwd=self.bundle_root,
        )
        if result.stdout:
            self.log_message(result.stdout.strip())
        if result.stderr:
            self.log_message(result.stderr.strip())
        if result.returncode:
            self.log_message(f"The submission command failed with exit code {result.returncode}.")
            return
        self.job_id = self.parse_condor_cluster_id(result.stdout) if self.state_data.scheduler == "condor" else self.parse_sbatch_job_id(result.stdout)
        if self.job_id:
            self.job_scheduler = self.state_data.scheduler
            self.set_job_log_paths()
            scheduler_name = "HTCondor" if self.state_data.scheduler == "condor" else "SLURM"
            self.query_one("#job_status", Static).update(f"Submitted {scheduler_name} job {self.job_id}.")
            self.start_job_auto_refresh()
            self.refresh_job_status()
        self.current_step = 5
        self.refresh_step()

    def parse_sbatch_job_id(self, output: str) -> str:
        for token in output.split():
            if token.isdigit():
                return token
        return ""

    def parse_condor_cluster_id(self, output: str) -> str:
        match = re.search(r"^\s*(\d+)\.", output)
        return match.group(1) if match else ""

    def set_job_log_paths(self) -> None:
        if not self.job_id:
            self.stdout_path = None
            self.stderr_path = None
            return
        if self.job_scheduler == "condor":
            self.stdout_path = None
            self.stderr_path = None
        else:
            self.stdout_path = self.bundle_root / "logs" / f"pcdf-ntuple-{self.job_id}.out"
            self.stderr_path = self.bundle_root / "logs" / f"pcdf-ntuple-{self.job_id}.err"
        if self.is_mounted:
            self.refresh_log_locations()

    def update_log_widget(self, widget_id: str, path: Path | None) -> None:
        log = self.query_one(widget_id, Log)
        log.clear()
        if path is None:
            log.write_line("No job submitted yet.")
            return
        if not path.exists():
            log.write_line(f"Waiting for {path}.")
            return
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError as error:
            log.write_line(f"Could not read {path}: {error}")
            return
        log.write_lines(lines or [f"{path} is empty."])

    def refresh_log_locations(self) -> None:
        if self.stdout_path is not None and self.stderr_path is not None:
            text = f"Standard output log: {self.stdout_path}\nStandard error log: {self.stderr_path}"
        elif self.job_scheduler == "condor":
            text = f"Bundle directory: {self.bundle_root}\nHTCondor logs are under logs/ as pcdf-ntuple-{self.job_id or '<cluster>'}.<process>.out and .err."
        else:
            text = f"Bundle directory: {self.bundle_root}\nAfter submission, SLURM logs are saved under logs/ as pcdf-ntuple-<jobid>.out and .err."
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
            self.notify("Submit a job before refreshing its status.", title="No submitted job", severity="warning", timeout=5)
            self.refresh_job_logs()
            return
        try:
            command = (
                ["condor_q", self.job_id, "-af", "ClusterId", "ProcId", "JobStatus", "HoldReason"]
                if self.job_scheduler == "condor"
                else ["squeue", "--noheader", f"--jobs={self.job_id}", "--format=%.18i %.9T %.10M %.20R"]
            )
            result = subprocess.run(command, check=False, text=True, capture_output=True)
        except FileNotFoundError:
            self.query_one("#job_status", Static).update(f"The {command[0]} command is not available on this host.")
            self.stop_job_auto_refresh()
            self.refresh_job_logs()
            return
        status = result.stdout.strip()
        if result.returncode == 0 and status:
            self.query_one("#job_status", Static).update(status)
            self.log_message(status)
        else:
            scheduler = "HTCondor" if self.job_scheduler == "condor" else "SLURM"
            message = result.stderr.strip() or f"Job {self.job_id} is no longer listed by {scheduler}."
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
                self.notify(f"Using NERSC account {event.value}.", title="Account selected", severity="information", timeout=4)
            return
        if event.select.id == "qos":
            self.mark_unreviewed()
            self.sync_state()
            return
        if event.select.id == "scheduler":
            self.state_data.scheduler = "slurm" if event.value is Select.NULL else str(event.value)
            self.mark_unreviewed()
            if self.perlmutter and self.state_data.scheduler == "slurm":
                self.load_accounts_with_iris(notify_user=False)
            self.refresh_scheduler_controls()
            self.refresh_summary()
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
        if event.input.id in {"account_input", "nodes", "time", "condor_cpus", "condor_memory", "condor_disk", "condor_requirements", "output", "manifest"}:
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
        if event.input.id in {"account_input", "nodes", "time", "condor_cpus", "condor_memory", "condor_disk", "condor_requirements", "output", "manifest"}:
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
                            f"Also turned off the objects that require it: {dependent_titles}.",
                            title=f"{self.state_data.objects[key]['title']} turned off",
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
            self.query_one("#submit", Button).disabled = not self.submission_available()
            self.notify("The converter and batch files are ready to submit.", title="Review confirmed", severity="information", timeout=5)
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
    """Use the current directory as the parent of the generated bundle."""
    return Path.cwd()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PCDF ATLAS ntuple wizard in a terminal.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Parent directory for pcdf-ntuple/ and its archive. The default is the current directory.",
    )
    args = parser.parse_args()
    output_dir = args.output_dir or default_output_dir()
    print(f"The working bundle will be saved in: {output_dir / BUNDLE_ROOT_NAME}", file=sys.stderr)
    NtupleWizardTui(output_dir=output_dir).run()
    print(f"The working bundle was saved in: {output_dir / BUNDLE_ROOT_NAME}", file=sys.stderr)


if __name__ == "__main__":
    main()
