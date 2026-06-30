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


def load_object_config() -> dict[str, dict[str, Any]]:
    return json.loads(OBJECT_CONFIG_PATH.read_text())


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


def build_python(state: WizardState) -> str:
    config = state.selected_config()
    format_note = (
        "PHYSLITE selected: jet constituents are disabled."
        if config["inputFormat"] == "PHYSLITE"
        else "TREASURE selected: jet constituents can be read."
    )
    sample_note = (
        "Data selected: MC-only truth/flavor branches are omitted; lumiBlock is included in Events."
        if config["sampleType"] == "DATA"
        else "MC selected: truth/flavor branches can be included when selected."
    )
    return apply_template((TEMPLATE_DIR / "ntuple-maker.template.py").read_text(), {
        "INPUT_FORMAT": config["inputFormat"],
        "INPUT_NOTE": f"{format_note} {sample_note}",
        "OBJECTS": python_literal(config["objects"]),
    })


def build_slurm(state: WizardState, output_dir: Path) -> str:
    return apply_template((TEMPLATE_DIR / "submit-pcdf-ntuple.template.slurm").read_text(), {
        "ACCOUNT_LINE": f"#SBATCH --account={state.account}",
        "QOS": state.qos,
        "NODES": str(state.nodes),
        "TIME": state.time,
        "PYTHON_PATH": json.dumps(str(output_dir / generated_python_name(state.input_format))),
        "INPUT_MANIFEST": json.dumps(state.manifest),
        "OUTPUT_BASE": json.dumps(state.output_base),
        "CONVERTER_CPUS_PER_CONVERSION": "1",
        "PERLMUTTER_PHYSICAL_CORES": str(PERLMUTTER_PHYSICAL_CORES),
        "PERLMUTTER_LOGICAL_CPUS_PER_NODE": str(PERLMUTTER_LOGICAL_CPUS),
    })


def write_bundle(state: WizardState, output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    py_path = output_dir / generated_python_name(state.input_format)
    slurm_path = output_dir / "submit-pcdf-ntuple.slurm"
    bundle_path = output_dir / "pcdf-ntuple-bundle.tar"
    py_path.write_text(build_python(state))
    slurm_path.write_text(build_slurm(state, output_dir))
    py_path.chmod(0o755)
    slurm_path.chmod(0o755)
    with tarfile.open(bundle_path, "w") as archive:
        archive.add(py_path, arcname=py_path.name)
        archive.add(slurm_path, arcname=slurm_path.name)
    return py_path, slurm_path, bundle_path


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
    return write_manifest(discover_files(state.scan_root, state.glob_pattern), state.manifest)
