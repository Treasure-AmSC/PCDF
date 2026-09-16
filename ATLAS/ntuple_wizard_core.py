"""Shared generation helpers for the ATLAS ntuple wizards."""

from __future__ import annotations

import json
import os
import re
import socket
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

ATLAS_DIR = Path(__file__).resolve().parent
OBJECT_CONFIG_PATH = ATLAS_DIR / "ntuple-wizard.objects.json"
TEMPLATE_DIR = ATLAS_DIR / "templates"
PERLMUTTER_PHYSICAL_CORES = 128
PERLMUTTER_LOGICAL_CPUS = 256
BUNDLE_ROOT_NAME = "pcdf-ntuple"
CODE_DIR_NAME = "code"


def load_object_config() -> dict[str, dict[str, Any]]:
    return json.loads(OBJECT_CONFIG_PATH.read_text())


def on_perlmutter() -> bool:
    """Return true when the process appears to be running on Perlmutter."""
    nersc_host = os.environ.get("NERSC_HOST", "").lower()
    hostname = socket.gethostname().lower()
    return nersc_host == "perlmutter" or "perlmutter" in hostname


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
    body = "\n".join(f"{prefix}{json.dumps(chunk)}" for chunk in chunks)
    return f"(\n{body}\n{' ' * indent})"


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
    objects: dict[str, dict[str, Any]] = field(default_factory=load_object_config)
    input_format: str = "JETM16"
    sample_type: str = "MC"
    selected_objects: set[str] = field(default_factory=set)
    selected_variables: dict[str, set[str]] = field(default_factory=dict)
    scheduler: str = "slurm"
    account: str = ""
    qos: str = "regular"
    nodes: int = 1
    time: str = "00:30:00"
    condor_cpus: int = 1
    condor_memory_mb: int = 4096
    condor_disk_mb: int = 4096
    condor_requirements: str = ""
    output_base: str = "./output"
    manifest: str = "./pcdf-inputs.txt"
    scan_root: str = "$SCRATCH"
    glob_pattern: str = "DAOD_*.pool.root*"

    def __post_init__(self) -> None:
        if self.scheduler not in {"slurm", "condor"}:
            raise ValueError(f"Unsupported scheduler: {self.scheduler}")
        if not self.selected_objects:
            self.selected_objects = {key for key, obj in self.objects.items() if obj.get("recommended")}
        if not self.selected_variables:
            self.selected_variables = {key: set(obj.get("aliases", {})) for key, obj in self.objects.items()}
        self.ensure_dependencies()

    def variable_available(self, key: str, name: str) -> bool:
        return not (self.sample_type == "DATA" and name in self.objects[key].get("mcOnlyVariables", []))

    def object_available(self, key: str) -> bool:
        return not (self.objects[key].get("requiresJetm16") and self.input_format == "PHYSLITE")

    def add_dependencies(self, key: str) -> None:
        for dependency in self.objects[key].get("dependsOn", []):
            if self.object_available(dependency):
                self.selected_objects.add(dependency)
                self.add_dependencies(dependency)

    def dependent_objects(self, key: str) -> list[str]:
        """Return selected objects that directly or indirectly depend on key."""
        dependents: list[str] = []
        remaining = [key]
        while remaining:
            dependency = remaining.pop()
            for candidate in sorted(self.selected_objects):
                if candidate in dependents or candidate == key:
                    continue
                if dependency in self.objects[candidate].get("dependsOn", []):
                    dependents.append(candidate)
                    remaining.append(candidate)
        return dependents

    def remove_object_with_dependents(self, key: str) -> list[str]:
        """Remove key plus selected dependent objects and return removed dependents."""
        dependents = self.dependent_objects(key)
        self.selected_objects.discard(key)
        for dependent in dependents:
            self.selected_objects.discard(dependent)
        return dependents

    def ensure_dependencies(self) -> None:
        for key in list(self.selected_objects):
            if not self.object_available(key):
                self.selected_objects.discard(key)
            else:
                self.add_dependencies(key)
        self.selected_objects.add("Event")
        for key, obj in self.objects.items():
            variables = self.selected_variables.setdefault(key, set())
            variables.update(obj.get("requiredVariables", []))
            if key in self.selected_objects and not variables and obj.get("aliases"):
                variables.add(next(iter(obj["aliases"])))

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


def build_python(state: WizardState) -> str:
    config = state.selected_config()
    format_note = (
        "PHYSLITE does not contain the data needed for jet constituents, so "
        "that output is off."
        if config["inputFormat"] == "PHYSLITE"
        else "JETM16 contains the data needed for jet constituents."
    )
    sample_note = (
        "For collision data, truth and flavor fields are skipped. Events include "
        "lumiBlock."
        if config["sampleType"] == "DATA"
        else "Simulation input can include the truth and flavor fields you select."
    )
    return apply_template((TEMPLATE_DIR / "ntuple-maker.template.py").read_text(), {
        "INPUT_FORMAT": config["inputFormat"],
        "INPUT_NOTE": f"{format_note} {sample_note}",
        "OBJECTS": python_literal(config["objects"]),
    })


def expanded_path(value: str) -> str:
    return str(Path(os.path.expandvars(os.path.expanduser(value))))


def build_slurm(state: WizardState, output_dir: Path) -> str:
    return apply_template((TEMPLATE_DIR / "submit-pcdf-ntuple.template.slurm").read_text(), {
        "ACCOUNT_LINE": f"#SBATCH --account={state.account}",
        "QOS": state.qos,
        "NODES": str(state.nodes),
        "TIME": state.time,
        "LOG_OUT": json.dumps("logs/pcdf-ntuple-%j.out"),
        "LOG_ERR": json.dumps("logs/pcdf-ntuple-%j.err"),
        "PYTHON_PATH": json.dumps(f"./{CODE_DIR_NAME}/" + generated_python_name(state.input_format)),
        "INPUT_MANIFEST": json.dumps(expanded_path(state.manifest)),
        "OUTPUT_BASE": json.dumps(expanded_path(state.output_base)),
        "CONVERTER_CPUS_PER_CONVERSION": "1",
        "PERLMUTTER_PHYSICAL_CORES": str(PERLMUTTER_PHYSICAL_CORES),
        "PERLMUTTER_LOGICAL_CPUS_PER_NODE": str(PERLMUTTER_LOGICAL_CPUS),
    })


def condor_value(value: str) -> str:
    """Quote a string for use as one HTCondor argument or path value."""
    return '"' + value.replace('"', '\\"') + '"'


def build_condor(state: WizardState, output_dir: Path) -> str:
    del output_dir
    requirements_line = f"requirements = {state.condor_requirements}" if state.condor_requirements else ""
    return apply_template((TEMPLATE_DIR / "submit-pcdf-ntuple.template.condor").read_text(), {
        "PYTHON_PATH": condor_value(f"./{CODE_DIR_NAME}/" + generated_python_name(state.input_format)),
        "INPUT_MANIFEST": condor_value(expanded_path(state.manifest)),
        "OUTPUT_BASE": condor_value(expanded_path(state.output_base)),
        "REQUEST_CPUS": str(state.condor_cpus),
        "REQUEST_MEMORY_MB": str(state.condor_memory_mb),
        "REQUEST_DISK_MB": str(state.condor_disk_mb),
        "REQUIREMENTS_LINE": requirements_line,
    })


def build_readme(state: WizardState) -> str:
    python_name = generated_python_name(state.input_format)
    if state.scheduler == "condor":
        batch_file_line = "- code/submit-pcdf-ntuple.condor describes one HTCondor job for each manifest entry.\n- code/run-pcdf-condor-job.sh runs one file conversion on an execute node.\n"
        batch_section = """\
HTCondor run
------------
1. Extract the bundle on a filesystem shared by the access point and execute
   nodes:
   tar -xf pcdf-ntuple-bundle.tar
   cd pcdf-ntuple
2. Check code/submit-pcdf-ntuple.condor. Its input manifest, converter, and output
   directory must be visible at the same paths on every execute node. The
   submit file does not copy DAOD inputs through HTCondor file transfer.
3. Start the included workflow:
   ./run-pcdf.sh
   It creates the manifest, asks before submitting, then follows all jobs in
   the cluster until they finish. Stopping the monitor does not remove jobs.
4. To run each step yourself, use code/make-manifest.py, condor_submit
   code/submit-pcdf-ntuple.condor, and condor_q.
"""
    else:
        batch_file_line = "- code/submit-pcdf-ntuple.slurm is the executable CPU job script for NERSC Perlmutter.\n"
        batch_section = """\
Perlmutter run
--------------
1. Copy this bundle to Perlmutter and extract it:
   tar -xf pcdf-ntuple-bundle.tar
   cd pcdf-ntuple
   The Python and SLURM scripts are marked executable.
2. On a login node, check the account, manifest, output directory, and node
   count in code/submit-pcdf-ntuple.slurm. The job writes all tables below the same
   output directory. It runs one file conversion on each physical CPU core.
3. Start the included workflow:
   ./run-pcdf.sh
   It creates the manifest, asks before submitting, then shows the queued,
   running, and completed job states. It does not cancel the job if you stop
   monitoring with Ctrl+C.
   The manifest helper can scan a directory populated by `rucio download` or
   look up a `scope:name` dataset at `NERSC_LOCALGROUPDISK`. It removes the
   access proxy's scheme, host, and port from each replica PFN, retaining its
   local path. The transform does not require Rucio.
4. To run each step yourself, use code/make-manifest.py, sbatch
   code/submit-pcdf-ntuple.slurm, and squeue -u $USER.
"""
    return apply_template((TEMPLATE_DIR / "README_SUBMIT.template.md").read_text(), {
        "PYTHON_NAME": python_name,
        "INPUT_FORMAT": state.input_format,
        "SLURM_FILE_LINE": batch_file_line,
        "WORKFLOW_FILE_LINE": "- run-pcdf.sh starts the interactive manifest, submission, and monitoring workflow.\n",
        "SLURM_SECTION": batch_section,
    })


def write_bundle(state: WizardState, output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_root = output_dir / BUNDLE_ROOT_NAME
    code_dir = bundle_root / CODE_DIR_NAME
    runtime_output_dir = bundle_root / "output"
    logs_dir = bundle_root / "logs"
    for directory in (code_dir, runtime_output_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    py_path = code_dir / generated_python_name(state.input_format)
    if state.scheduler == "condor":
        submit_path = code_dir / "submit-pcdf-ntuple.condor"
        submit_text = build_condor(state, output_dir)
    else:
        submit_path = code_dir / "submit-pcdf-ntuple.slurm"
        submit_text = build_slurm(state, output_dir)
    readme_path = bundle_root / "README_SUBMIT.md"
    manifest_helper_path = code_dir / "make-manifest.py"
    workflow_shell_path = bundle_root / "run-pcdf.sh"
    workflow_python_path = code_dir / "run-pcdf.py"
    condor_job_path = code_dir / "run-pcdf-condor-job.sh"
    bundle_path = output_dir / "pcdf-ntuple-bundle.tar"
    py_path.write_text(build_python(state))
    submit_path.write_text(submit_text)
    readme_path.write_text(build_readme(state))
    manifest_helper_path.write_text((TEMPLATE_DIR / "make-manifest.template.py").read_text())
    workflow_shell_path.write_text((TEMPLATE_DIR / "run-pcdf.template.sh").read_text())
    workflow_python_path.write_text((TEMPLATE_DIR / "run-pcdf.template.py").read_text())
    if state.scheduler == "condor":
        condor_job_path.write_text((TEMPLATE_DIR / "run-pcdf-condor-job.template.sh").read_text())
    py_path.chmod(0o755)
    submit_path.chmod(0o755)
    manifest_helper_path.chmod(0o755)
    workflow_shell_path.chmod(0o755)
    workflow_python_path.chmod(0o755)
    if state.scheduler == "condor":
        condor_job_path.chmod(0o755)
    with tarfile.open(bundle_path, "w") as archive:
        for directory in (bundle_root, code_dir, runtime_output_dir, logs_dir):
            info = tarfile.TarInfo(str(directory.relative_to(output_dir)) + "/")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for path in (py_path, submit_path, readme_path, manifest_helper_path, workflow_shell_path, workflow_python_path):
            archive.add(path, arcname=path.relative_to(output_dir))
        if state.scheduler == "condor":
            archive.add(condor_job_path, arcname=condor_job_path.relative_to(output_dir))
    return py_path, submit_path, bundle_path


def discover_files(scan_root: str, glob_pattern: str) -> list[Path]:
    root = Path(os.path.expandvars(os.path.expanduser(scan_root)))
    def visible(path: Path) -> bool:
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path
        return not any(part.startswith(".") for part in relative.parts)

    def usable(path: Path) -> bool:
        try:
            return path.stat().st_size > 1024
        except OSError:
            return False

    return sorted(path for path in root.rglob(glob_pattern) if path.is_file() and visible(path) and usable(path))


def write_manifest(paths: list[Path], manifest_path: str) -> tuple[Path, int]:
    manifest = Path(os.path.expandvars(os.path.expanduser(manifest_path)))
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=manifest.parent) as tmp:
        for path in paths:
            tmp.write(str(path) + "\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(manifest)
    return manifest, len(paths)


def scan_manifest(state: WizardState) -> tuple[Path, int]:
    paths = discover_files(state.scan_root, state.glob_pattern)
    if not paths:
        return Path(os.path.expandvars(os.path.expanduser(state.manifest))), 0
    return write_manifest(paths, state.manifest)
