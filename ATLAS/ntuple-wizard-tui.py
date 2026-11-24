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
from wizard_text import wizard_text


def plural_text(key: str, count: int, **values: object) -> str:
    """Return the -one or -many form of a catalog entry, with {{COUNT}} filled in."""
    form = "one" if count == 1 else "many"
    return wizard_text(f"{key}-{form}", COUNT=count, **values)


def term_lines(*keys: str) -> str:
    """Return one "Term: definition" line for each glossary key."""
    return "\n".join(f"{wizard_text(key)}: {wizard_text(key + '.help')}" for key in keys)


class VisibleDirectoryTree(DirectoryTree):
    """Directory tree that hides dot-prefixed files and directories."""

    def filter_paths(self, paths: Any) -> Any:
        return [path for path in paths if not path.name.startswith(".")]


class NtupleWizardTui(App[None]):
    """Interactive Textual app for PCDF ntuple job generation."""

    TITLE = wizard_text("tui.title")
    SUB_TITLE = wizard_text("tui.subtitle")

    STEPS = ("input", "objects", "variables", "batch", "generate", "status")

    CSS_PATH = Path(__file__).with_name("ntuple-wizard-tui.tcss")

    BINDINGS = [
        ("q", "quit", wizard_text("tui.binding-quit")),
        ("g", "generate", wizard_text("tui.binding-generate")),
        ("s", "submit", wizard_text("tui.submit-button")),
    ]
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
            yield Static(wizard_text("page.heading"), id="hero")
            with TabbedContent(initial="step-0", id="wizard-tabs", classes="wizard-shell"):
                with TabPane(wizard_text("nav.step-input"), id="step-0", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static(wizard_text("tui.input-title"), classes="section-title")
                        yield Static(wizard_text("tui.input-hint"), classes="hint")
                        with Collapsible(title=wizard_text("tui.terms-title"), collapsed=True):
                            yield Static(term_lines("term.atlas-daod", "term.jetmod1", "term.physlite"), classes="hint")
                        yield Label(wizard_text("tui.input-format-label"), classes="field-label")
                        yield Select([(label, label) for label in ("JETMOD1", "PHYSLITE")], value="JETMOD1", id="format", classes="hidden-select")
                        with Horizontal(classes="choice-row"):
                            yield Button(wizard_text("term.jetmod1"), id="set-format-JETMOD1", classes="choice-button active-step")
                            yield Button(wizard_text("term.physlite"), id="set-format-PHYSLITE", classes="choice-button")
                        yield Label(wizard_text("sample.legend"), classes="field-label")
                        yield Select([(label, label) for label in ("MC", "DATA")], value="MC", id="sample", classes="hidden-select")
                        with Horizontal(classes="choice-row"):
                            yield Button(wizard_text("sample.mc"), id="set-sample-MC", classes="choice-button active-step")
                            yield Button(wizard_text("sample.data"), id="set-sample-DATA", classes="choice-button")

                with TabPane(wizard_text("nav.step-objects"), id="step-1", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static(wizard_text("objects.output-label"), classes="section-title")
                        yield Static(wizard_text("tui.objects-hint"), classes="hint")
                        with Grid(classes="object-grid"):
                            for key, obj in self.state_data.objects.items():
                                selected = key in self.state_data.selected_objects
                                with Grid(id=f"obj-card-{key}", classes="toggle-card selected-choice" if selected else "toggle-card deselected-choice"):
                                    yield Switch(value=selected, id=f"obj-{key}", classes="toggle-switch", disabled=key == "Event")
                                    yield Label(obj["title"], id=f"obj-label-{key}", classes="toggle-label")

                with TabPane(wizard_text("nav.step-variables"), id="step-2", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static(wizard_text("tui.variables-title"), classes="section-title")
                        yield Static(wizard_text("tui.variables-hint"), classes="hint")
                        for key, obj in self.state_data.objects.items():
                            yield Static(obj["title"], classes="section-title")
                            required = set(obj.get("requiredVariables", []))
                            with Grid(classes="object-grid"):
                                for name in obj.get("aliases", {}):
                                    selected = name in self.state_data.selected_variables[key]
                                    with Grid(id=f"var-card-{key}-{name}", classes="toggle-card selected-choice" if selected else "toggle-card deselected-choice"):
                                        yield Switch(value=selected, id=f"var-{key}-{name}", classes="toggle-switch", disabled=name in required)
                                        label = wizard_text("tui.variable-required", NAME=name) if name in required else name
                                        yield Label(label, id=f"var-label-{key}-{name}", classes="toggle-label")

                with TabPane(wizard_text("nav.step-batch"), id="step-3", classes="wizard-step"):
                    with Horizontal(classes="two-column"):
                        with VerticalScroll(classes="column"):
                            yield Static(wizard_text("batch.heading"), classes="section-title")
                            with Collapsible(title=wizard_text("tui.terms-title"), collapsed=True):
                                yield Static(term_lines("term.slurm", "term.htcondor", "term.input-manifest", "term.shared-filesystem"), classes="hint")
                            yield Label(wizard_text("batch.system-label"), classes="field-label")
                            yield Select([(wizard_text("scheduler.slurm"), "slurm"), (wizard_text("scheduler.condor"), "condor")], value="slurm", allow_blank=False, id="scheduler")
                            with Container(id="slurm_settings"):
                                yield Label(wizard_text("field.account-label"), classes="field-label")
                                if self.perlmutter:
                                    yield Select([(wizard_text("tui.accounts-loading"), "")], value="", allow_blank=False, disabled=True, id="account_select")
                                    yield Input(placeholder=wizard_text("tui.account-manual-placeholder"), id="account_input", validators=[Function(self.non_empty, wizard_text("field.account-error"))], validate_on=["blur", "submitted"])
                                else:
                                    yield Input(placeholder=wizard_text("field.account-label"), id="account_input", validators=[Function(self.non_empty, wizard_text("field.account-error"))], validate_on=["blur", "submitted"])
                                yield Static(wizard_text("tui.advanced-help"), id="advanced_slurm_help", classes="hint")
                                with Collapsible(title=wizard_text("tui.advanced-slurm-title"), collapsed=True, id="advanced_slurm"):
                                    yield Label(wizard_text("field.qos-label"), classes="field-label")
                                    yield Select([(label, label) for label in ("regular", "debug", "premium")], value="regular", allow_blank=False, id="qos")
                                    yield Label(wizard_text("tui.nodes-label"), classes="field-label")
                                    yield Input(value="1", placeholder=wizard_text("tui.nodes-label"), id="nodes", validators=[Function(self.positive_integer, wizard_text("field.nodes-error"))], validate_on=["blur", "submitted"])
                                    yield Label(wizard_text("field.walltime-label"), classes="field-label")
                                    yield Input(value="00:30:00", placeholder=wizard_text("field.walltime-label"), id="time", validators=[Regex(r"^\d{1,2}:\d{2}:\d{2}$", failure_description=wizard_text("field.walltime-error"))], validate_on=["blur", "submitted"])
                            with Container(id="condor_settings"):
                                yield Static(wizard_text("tui.advanced-help"), id="advanced_condor_help", classes="hint")
                                with Collapsible(title=wizard_text("tui.advanced-condor-title"), collapsed=True, id="advanced_condor"):
                                    yield Label(wizard_text("field.cpus-label"), classes="field-label")
                                    yield Input(value="1", placeholder=wizard_text("field.cpus-placeholder"), id="condor_cpus", validators=[Function(self.positive_integer, wizard_text("field.cpus-error"))], validate_on=["blur", "submitted"])
                                    yield Label(wizard_text("field.memory-label"), classes="field-label")
                                    yield Input(value="2048", placeholder=wizard_text("field.memory-placeholder"), id="condor_memory", validators=[Function(self.positive_integer, wizard_text("field.memory-error"))], validate_on=["blur", "submitted"])
                                    yield Label(wizard_text("field.disk-label"), classes="field-label")
                                    yield Input(value="4096", placeholder=wizard_text("field.disk-placeholder"), id="condor_disk", validators=[Function(self.positive_integer, wizard_text("field.disk-error"))], validate_on=["blur", "submitted"])
                                    yield Label(wizard_text("field.requirements-label"), classes="field-label")
                                    yield Input(placeholder=wizard_text("field.requirements-placeholder"), id="condor_requirements")
                            with Collapsible(title=wizard_text("tui.advanced-paths-title"), collapsed=True, id="advanced_paths"):
                                yield Label(wizard_text("field.output-label"), classes="field-label")
                                yield Input(value=self.state_data.output_base, placeholder=wizard_text("field.output-label"), id="output", validators=[Function(self.non_empty, wizard_text("field.output-error"))], validate_on=["blur", "submitted"])
                                yield Label(wizard_text("common.input-manifest-path"), classes="field-label")
                                yield Input(value=self.state_data.manifest, placeholder=wizard_text("common.input-manifest-path"), id="manifest", validators=[Function(self.non_empty, wizard_text("field.manifest-error"))], validate_on=["blur", "submitted"])
                            yield Static(wizard_text("tui.perlmutter-yes" if self.perlmutter else "tui.perlmutter-no"), classes="hint")
                        with VerticalScroll(classes="column"):
                            yield Static(wizard_text("tui.manifest-source-title"), classes="section-title")
                            yield Static(wizard_text("tui.manifest-source-hint"), classes="hint")
                            yield Label(wizard_text("tui.scan-root-label"), classes="field-label")
                            yield Input(value="$SCRATCH", placeholder=wizard_text("tui.scan-root-placeholder"), id="scan_root", validators=[Function(self.existing_directory, wizard_text("tui.scan-root-error"))], validate_on=["blur", "submitted"])
                            with Collapsible(title=wizard_text("tui.advanced-manifest-title"), collapsed=True):
                                yield Label(wizard_text("tui.glob-label"), classes="field-label")
                                yield Input(value="DAOD_*.pool.root*", placeholder=wizard_text("tui.glob-placeholder"), id="glob", validators=[Function(self.non_empty, wizard_text("tui.glob-error"))], validate_on=["blur", "submitted"])
                            tree_root = Path(os.path.expandvars(os.environ.get("SCRATCH", ""))).expanduser()
                            if not tree_root.exists():
                                tree_root = Path.cwd()
                            yield VisibleDirectoryTree(tree_root, id="tree")
                            yield Static(wizard_text("tui.discovered-title"), classes="section-title")
                            yield SelectionList[str](id="files")
                            yield Button(wizard_text("tui.manifest-write"), id="manifest_write")

                with TabPane(wizard_text("nav.step-generate"), id="step-4", classes="wizard-step"):
                    with Horizontal(classes="two-column"):
                        with VerticalScroll(classes="column"):
                            yield Static(wizard_text("tui.generate-title"), classes="section-title")
                            yield Static("", id="summary_panel")
                            yield Static(wizard_text("tui.review-title"), classes="section-title")
                            with TabbedContent(initial="preview-python", id="review-tabs"):
                                with TabPane(wizard_text("tui.preview-python"), id="preview-python"):
                                    yield TextArea("", language="python", read_only=True, show_line_numbers=True, id="python_preview", classes="script-preview")
                                with TabPane(wizard_text("tui.preview-batch"), id="preview-slurm"):
                                    yield TextArea("", language="bash", read_only=True, show_line_numbers=True, id="slurm_preview", classes="script-preview")
                            with Horizontal(id="generate-actions"):
                                yield Button(wizard_text("tui.generate-button"), id="generate", variant="primary")
                                yield Button(wizard_text("tui.confirm-review"), id="confirm_review")
                                yield Button(wizard_text("tui.submit-button"), id="submit", variant="success", disabled=True)
                with TabPane(wizard_text("tui.step-status"), id="step-5", classes="wizard-step"):
                    with VerticalScroll(classes="step-body"):
                        yield Static(wizard_text("tui.status-title"), classes="section-title")
                        yield Static(wizard_text("tui.no-job"), id="job_status", classes="hint")
                        yield Static("", id="log_paths", classes="hint")
                        yield Button(wizard_text("tui.refresh-button"), id="refresh_job")
                        with Grid(classes="job-log-grid"):
                            yield Static(wizard_text("tui.stdout-title"), classes="section-title")
                            yield Static(wizard_text("tui.stderr-title"), classes="section-title")
                            yield Log(id="stdout_log", classes="job-log")
                            yield Log(id="stderr_log", classes="job-log")
                        yield Static(wizard_text("tui.activity-title"), classes="section-title")
                        yield RichLog(id="log", wrap=True, highlight=True)
            with Horizontal(id="wizard-nav"):
                yield Button(wizard_text("ui.back"), id="prev_step")
                yield Button(wizard_text("ui.next"), id="next_step", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_dependency_widgets()
        self.refresh_step()
        self.log_message(wizard_text("tui.ready"))
        self.log_message(wizard_text("tui.bundle-location", PATH=self.bundle_root))
        if self.perlmutter:
            self.log_message(wizard_text("tui.perlmutter-login"))
            self.load_accounts_with_iris(notify_user=False)
        else:
            self.log_message(wizard_text("tui.generic-host"))
        self.refresh_scheduler_controls()
        self.refresh_log_locations()

    def log_message(self, message: str) -> None:
        self.query_one("#log", RichLog).write(message)

    def refresh_summary(self) -> None:
        state = self.state_data
        config = state.selected_config()
        object_lines = [
            wizard_text(
                "tui.summary-object",
                TITLE=state.objects[key]["title"],
                VARIABLES=plural_text("objects.variable-count", len(value["aliases"])),
            )
            for key, value in config["objects"].items()
        ]
        slurm_status = (
            plural_text(
                "tui.summary-condor",
                state.condor_cpus,
                MEMORY=state.condor_memory_mb,
                DISK=state.condor_disk_mb,
            )
            if state.scheduler == "condor"
            else plural_text("tui.summary-slurm", state.nodes, QOS=state.qos, TIME=state.time)
        )
        summary = "\n".join([
            wizard_text("tui.summary-input", FORMAT=state.input_format, SAMPLE=state.sample_type),
            slurm_status,
            wizard_text("tui.summary-manifest", PATH=state.manifest),
            wizard_text("tui.summary-output", PATH=state.output_base),
            wizard_text("tui.summary-objects-label"),
            *(object_lines or [wizard_text("tui.summary-none")]),
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
            next_button.label = wizard_text("ui.review")
        elif self.current_step == 4:
            next_button.label = wizard_text("tui.status-name")
        else:
            next_button.label = wizard_text("ui.next")
        next_button.disabled = self.current_step == len(self.STEPS) - 1
        self.refresh_choice_buttons()
        self.refresh_summary()

    def refresh_choice_buttons(self) -> None:
        for value in ("JETMOD1", "PHYSLITE"):
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
            ("condor_memory", "condor_memory_mb", 2048),
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
        self.query_one("#submit", Button).label = wizard_text("tui.submit-condor" if condor else "tui.submit-slurm")
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
        self.log_message(plural_text("tui.found-files", count, PATH=self.state_data.scan_root))

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
                self.log_message(wizard_text("tui.manifest-none-selected"))
                self.notify(wizard_text("tui.manifest-unchanged"), title=wizard_text("tui.manifest-unchanged-title"), severity="warning", timeout=8)
                return None
            self.log_message(wizard_text("tui.manifest-scanning"))
            manifest, count = scan_manifest(self.state_data)
        else:
            manifest, count = write_manifest(selected, self.state_data.manifest)
        if count == 0:
            self.log_message(wizard_text("tui.manifest-no-match-log", PATTERN=self.state_data.glob_pattern, ROOT=self.state_data.scan_root))
            self.notify(wizard_text("tui.manifest-no-match"), title=wizard_text("tui.manifest-no-match-title"), severity="warning", timeout=8)
            return None
        wrote = wizard_text("tui.manifest-wrote", FILES=plural_text("tui.file-count", count), MANIFEST=manifest)
        self.log_message(wrote)
        self.notify(wrote, title=wizard_text("tui.manifest-wrote-title"), severity="information", timeout=6)
        return manifest

    def ensure_manifest_for_submit(self) -> bool:
        if self.discovered_files:
            self.log_message(wizard_text("tui.manifest-updating"))
            manifest = self.write_selected_manifest()
            if manifest is None or not self.manifest_has_work():
                self.notify(wizard_text("tui.manifest-required"), title=wizard_text("tui.submission-blocked-title"), severity="error", timeout=8)
                self.log_message(wizard_text("tui.manifest-still-empty"))
                return False
            return True
        if self.manifest_has_work():
            return True
        self.log_message(wizard_text("tui.manifest-writing"))
        manifest = self.write_selected_manifest()
        if manifest is None or not self.manifest_has_work():
            self.notify(wizard_text("tui.manifest-required"), title=wizard_text("tui.submission-blocked-title"), severity="error", timeout=8)
            self.log_message(wizard_text("tui.manifest-still-empty"))
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
                self.notify(wizard_text("tui.iris-missing-notice"), title=wizard_text("tui.iris-missing-title"), severity="warning", timeout=8)
            account_select = self.query_one("#account_select", Select)
            account_select.set_options([(wizard_text("tui.account-manual-option"), "")])
            account_select.value = ""
            account_select.disabled = True
            self.log_message(wizard_text("tui.iris-missing-log"))
            self._loading_accounts = False
            return
        except subprocess.TimeoutExpired:
            account_select = self.query_one("#account_select", Select)
            account_select.set_options([(wizard_text("tui.account-manual-option"), "")])
            account_select.value = ""
            account_select.disabled = True
            if notify_user:
                self.notify(wizard_text("tui.iris-timeout-notice"), title=wizard_text("tui.iris-timeout-title"), severity="warning", timeout=8)
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
                    self.notify(plural_text("tui.accounts-loaded", len(accounts)), title=wizard_text("tui.accounts-loaded-title"), severity="information", timeout=6)
                self.log_message(wizard_text("tui.accounts-loaded-log", ACCOUNTS=", ".join(accounts)))
            else:
                account_select.set_options([(wizard_text("tui.iris-none-option"), "")])
                account_select.value = ""
                account_select.disabled = True
                if notify_user:
                    self.notify(wizard_text("tui.iris-none-notice"), title=wizard_text("tui.iris-none-title"), severity="warning", timeout=8)
                self.log_message(wizard_text("tui.iris-none-notice"))
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
        if common_failures:
            self.query_one("#advanced_paths", Collapsible).collapsed = False
        if self.state_data.scheduler == "condor":
            scheduler_failures = self.invalid_inputs(("condor_cpus", "condor_memory", "condor_disk"))
            if scheduler_failures:
                self.query_one("#advanced_condor", Collapsible).collapsed = False
        else:
            scheduler_failures = self.invalid_inputs(("nodes", "time"))
            if scheduler_failures:
                self.query_one("#advanced_slurm", Collapsible).collapsed = False
        failures = common_failures + scheduler_failures
        if self.state_data.scheduler == "slurm" and self.perlmutter:
            account_select = self.query_one("#account_select", Select)
            selected_account = account_select.value
            manual_account = self.query_one("#account_input", Input).value.strip()
            if account_select.disabled or selected_account in (Select.NULL, ""):
                failures.extend(self.invalid_inputs(("account_input",)))
            if account_select.disabled and not manual_account:
                failures.append(wizard_text("tui.account-enter"))
            elif (not account_select.disabled) and selected_account in (Select.NULL, "") and not manual_account:
                failures.append(wizard_text("tui.account-choose"))
        elif self.state_data.scheduler == "slurm":
            failures.extend(self.invalid_inputs(("account_input",)))
        if failures:
            self.notify("\n".join(failures), title=wizard_text("tui.fix-batch-title"), severity="error", timeout=8)
            self.log_message(wizard_text("tui.validation-failed") + "\n" + "\n".join(f"• {failure}" for failure in failures))
            return False
        return True

    def validate_file_discovery_inputs(self) -> bool:
        failures = self.invalid_inputs(("scan_root", "glob"))
        if failures:
            self.notify("\n".join(failures), title=wizard_text("tui.fix-discovery-title"), severity="error", timeout=8)
            self.log_message(wizard_text("tui.validation-failed") + "\n" + "\n".join(f"• {failure}" for failure in failures))
            return False
        return True

    def validate_scan_inputs(self) -> bool:
        failures = self.invalid_inputs(("scan_root", "glob", "manifest"))
        if failures:
            self.notify("\n".join(failures), title=wizard_text("tui.fix-manifest-title"), severity="error", timeout=8)
            self.log_message(wizard_text("tui.validation-failed") + "\n" + "\n".join(f"• {failure}" for failure in failures))
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
        self.log_message(wizard_text("tui.created-converter", PATH=py_path))
        self.log_message(wizard_text("tui.created-batch", PATH=submit_path))
        self.log_message(wizard_text("tui.created-bundle", PATH=bundle_path))
        self.notify(
            wizard_text("tui.generation-complete", BUNDLE=self.bundle_root, ARCHIVE=bundle_path),
            title=wizard_text("tui.generation-complete-title"),
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
            command = wizard_text("tui.command-condor" if self.state_data.scheduler == "condor" else "tui.command-slurm")
            self.notify(wizard_text("tui.submission-unavailable", COMMAND=command), title=wizard_text("tui.submission-unavailable-title"), severity="warning", timeout=8)
            self.log_message(wizard_text("tui.submission-unavailable-log", COMMAND=command))
            return
        if not self.review_confirmed:
            self.notify(wizard_text("tui.review-required"), title=wizard_text("tui.review-required-title"), severity="warning", timeout=8)
            self.log_message(wizard_text("tui.review-required-log"))
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
            self.log_message(wizard_text("tui.submission-failed", COMMAND=command[0], CODE=result.returncode))
            return
        self.job_id = self.parse_condor_cluster_id(result.stdout) if self.state_data.scheduler == "condor" else self.parse_sbatch_job_id(result.stdout)
        if self.job_id:
            self.job_scheduler = self.state_data.scheduler
            self.set_job_log_paths()
            scheduler_name = wizard_text("term.htcondor" if self.state_data.scheduler == "condor" else "term.slurm")
            self.query_one("#job_status", Static).update(wizard_text("tui.submitted", SCHEDULER=scheduler_name, JOB=self.job_id))
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
            log.write_line(wizard_text("tui.no-job"))
            return
        if not path.exists():
            log.write_line(wizard_text("tui.log-waiting", PATH=path))
            return
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError as error:
            log.write_line(wizard_text("tui.log-unreadable", PATH=path, ERROR=error))
            return
        log.write_lines(lines or [wizard_text("tui.log-empty", PATH=path)])

    def refresh_log_locations(self) -> None:
        if self.stdout_path is not None and self.stderr_path is not None:
            text = wizard_text("tui.log-paths", OUT=self.stdout_path, ERR=self.stderr_path)
        elif self.job_scheduler == "condor":
            text = wizard_text("tui.log-paths-condor", BUNDLE=self.bundle_root, JOB=self.job_id or "<cluster>")
        else:
            text = wizard_text("tui.log-paths-slurm", BUNDLE=self.bundle_root)
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
            self.notify(wizard_text("tui.no-submitted-job"), title=wizard_text("tui.no-submitted-job-title"), severity="warning", timeout=5)
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
            self.query_one("#job_status", Static).update(wizard_text("tui.command-missing", COMMAND=command[0]))
            self.stop_job_auto_refresh()
            self.refresh_job_logs()
            return
        status = result.stdout.strip()
        if result.returncode == 0 and status:
            self.query_one("#job_status", Static).update(status)
            self.log_message(status)
        else:
            scheduler = wizard_text("term.htcondor" if self.job_scheduler == "condor" else "term.slurm")
            message = result.stderr.strip() or wizard_text("tui.job-gone", JOB=self.job_id, SCHEDULER=scheduler)
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
                self.notify(wizard_text("tui.account-selected", ACCOUNT=event.value), title=wizard_text("tui.account-selected-title"), severity="information", timeout=4)
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
            self.notify("\n".join(event.validation_result.failure_descriptions), title=wizard_text("tui.invalid-input-title"), severity="warning", timeout=5)

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
            self.notify("\n".join(event.validation_result.failure_descriptions), title=wizard_text("tui.invalid-input-title"), severity="warning", timeout=5)

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        path = str(event.path)
        scan_root = self.query_one("#scan_root", Input)
        scan_root.value = path
        self.state_data.scan_root = path
        self.log_message(wizard_text("tui.scan-directory-selected", PATH=path))
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
                            wizard_text("tui.object-off-dependents", OBJECTS=dependent_titles),
                            title=wizard_text("tui.object-off-title", OBJECT=self.state_data.objects[key]["title"]),
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
            self.notify(wizard_text("tui.review-confirmed"), title=wizard_text("tui.review-confirmed-title"), severity="information", timeout=5)
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
    parser = argparse.ArgumentParser(description=wizard_text("tui.cli-description"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=wizard_text("tui.cli-output-help"),
    )
    args = parser.parse_args()
    output_dir = args.output_dir or default_output_dir()
    print(wizard_text("tui.cli-will-save", PATH=output_dir / BUNDLE_ROOT_NAME), file=sys.stderr)
    NtupleWizardTui(output_dir=output_dir).run()
    print(wizard_text("tui.cli-saved", PATH=output_dir / BUNDLE_ROOT_NAME), file=sys.stderr)


if __name__ == "__main__":
    main()
