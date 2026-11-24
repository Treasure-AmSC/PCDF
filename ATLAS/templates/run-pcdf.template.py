#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich"]
# ///
"""Launcher for a generated PCDF bundle. The text it shows is in MESSAGES."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, IntPrompt
from rich.traceback import install as install_rich_traceback


MESSAGES = {{MESSAGES:common}} | {{MESSAGES:runner}}


def message(key: str, **values: object) -> str:
    """Return a user-facing message, filling in each double-brace placeholder from values."""
    return re.sub(r"{{([A-Z0-9_]+)}}", lambda match: str(values.get(match.group(1), match.group(0))), MESSAGES[key])


CODE_DIRECTORY = Path(__file__).resolve().parent
BUNDLE_DIRECTORY = CODE_DIRECTORY.parent
MANIFEST_HELPER = CODE_DIRECTORY / "make-manifest.py"
SLURM_SCRIPT = CODE_DIRECTORY / "submit-pcdf-ntuple.slurm"
CONDOR_SUBMIT_FILE = CODE_DIRECTORY / "submit-pcdf-ntuple.condor"
CONDOR_JOB_SCRIPT = CODE_DIRECTORY / "run-pcdf-condor-job.sh"
POLL_SECONDS = 10
SLURM_TERMINAL_STATES = {
    "BOOT_FAIL", "CANCELLED", "COMPLETED", "DEADLINE", "FAILED",
    "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED", "TIMEOUT",
}
CONDOR_STATUS_NAMES = {
    "1": "idle", "2": "running", "3": "removing", "4": "completed",
    "5": "held", "6": "transferring output", "7": "suspended",
}


def command_output(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            cwd=BUNDLE_DIRECTORY,
        )
    except FileNotFoundError as error:
        raise RuntimeError(message("runner.command-not-found", COMMAND=command[0])) from error


@dataclass(frozen=True)
class Scheduler:
    name: str
    submit_file: Path

    def submit(self) -> str:
        if self.name == "SLURM":
            result = command_output(["sbatch", str(self.submit_file)])
            pattern = r"Submitted batch job (\d+)"
        else:
            result = command_output(["condor_submit", "-terse", str(self.submit_file)])
            pattern = r"^\s*(\d+)\."
        if result.returncode:
            message = result.stderr.strip() or result.stdout.strip() or message("runner.no-error-details")
            raise RuntimeError(message("runner.submission-failed", DETAIL=message))
        match = re.search(pattern, result.stdout)
        if not match:
            raise RuntimeError(message("runner.no-job-id", OUTPUT=result.stdout.strip()))
        return match.group(1)


def configured_scheduler() -> Scheduler:
    available = [Scheduler("SLURM", SLURM_SCRIPT), Scheduler("HTCondor", CONDOR_SUBMIT_FILE)]
    configured = [scheduler for scheduler in available if scheduler.submit_file.is_file()]
    if len(configured) != 1:
        names = ", ".join(path.name for path in (SLURM_SCRIPT, CONDOR_SUBMIT_FILE))
        raise RuntimeError(message("runner.one-scheduler-file", NAMES=names))
    return configured[0]


def slurm_queued_state(job_id: str) -> tuple[str, str] | None:
    result = command_output(["squeue", "--noheader", f"--jobs={job_id}", "--format=%T|%R"])
    if result.returncode:
        raise RuntimeError(message("runner.slurm-query-failed", DETAIL=result.stderr.strip() or message("runner.no-error-details")))
    line = next((line for line in result.stdout.splitlines() if line.strip()), "")
    if not line:
        return None
    state, _, detail = line.partition("|")
    return state.strip(), detail.strip()


def slurm_completed_state(job_id: str) -> tuple[str, str] | None:
    result = command_output([
        "sacct", "--allocations", "--noheader", "--parsable2", f"--jobs={job_id}",
        "--format=JobIDRaw,State,ExitCode",
    ])
    if result.returncode:
        raise RuntimeError(message("runner.slurm-accounting-failed", DETAIL=result.stderr.strip() or message("runner.no-error-details")))
    for line in result.stdout.splitlines():
        fields = line.split("|")
        if len(fields) >= 3 and fields[0] == job_id:
            return fields[1].rstrip("+"), fields[2]
    return None


def condor_rows(command: str, job_id: str, attributes: list[str]) -> list[list[str]]:
    result = command_output([command, job_id, "-af", *attributes])
    if result.returncode:
        message = result.stderr.strip() or message("runner.no-error-details")
        raise RuntimeError(message("runner.condor-query-failed", DETAIL=message))
    return [line.split(None, len(attributes) - 1) for line in result.stdout.splitlines() if line.strip()]


def count_condor_states(rows: list[list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        name = CONDOR_STATUS_NAMES.get(row[0], message("runner.condor-unknown-state", CODE=row[0]))
        counts[name] = counts.get(name, 0) + 1
    return counts


def state_summary(counts: dict[str, int]) -> str:
    return ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))


def progress_context(console: Console, scheduler_name: str, job_id: str):
    progress = Progress(
        SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
        console=console, transient=False,
    )
    progress.start()
    progress.add_task(message("runner.manifest-ready"), total=1, completed=1)
    progress.add_task(message("runner.submitted", SCHEDULER=scheduler_name, JOB=job_id), total=1, completed=1)
    start_task = progress.add_task(message("runner.waiting-start"), total=None)
    finish_task = progress.add_task(message("runner.waiting-finish"), total=None)
    return progress, start_task, finish_task


def wait_for_slurm(console: Console, job_id: str) -> None:
    progress, start_task, finish_task = progress_context(console, "SLURM", job_id)
    started = False
    try:
        while True:
            queued = slurm_queued_state(job_id)
            if queued:
                state, detail = queued
                if state == "RUNNING":
                    if not started:
                        progress.update(start_task, completed=1, total=1, description=message("runner.job-started"))
                        started = True
                    progress.update(finish_task, description=message("runner.job-running", DETAIL=detail or message("runner.no-location")))
                else:
                    progress.update(start_task, description=message("runner.job-pending", STATE=state.lower(), DETAIL=detail or message("runner.no-reason")))
                time.sleep(POLL_SECONDS)
                continue
            accounting = slurm_completed_state(job_id)
            if accounting is None:
                progress.update(finish_task, description=message("runner.left-queue-accounting"))
                time.sleep(POLL_SECONDS)
                continue
            state, exit_code = accounting
            if not started:
                progress.update(start_task, completed=1, total=1, description=message("runner.left-queue"))
            if state not in SLURM_TERMINAL_STATES:
                progress.update(finish_task, description=message("runner.job-state", STATE=state.lower()))
                time.sleep(POLL_SECONDS)
                continue
            if state == "COMPLETED" and exit_code.startswith("0:"):
                progress.update(finish_task, completed=1, total=1, description=message("runner.job-completed"))
                return
            raise RuntimeError(message("runner.slurm-ended", JOB=job_id, STATE=state, EXIT=exit_code))
    finally:
        progress.stop()


def wait_for_condor(console: Console, job_id: str) -> None:
    progress, start_task, finish_task = progress_context(console, "HTCondor", job_id)
    started = False
    try:
        while True:
            active = condor_rows("condor_q", job_id, ["JobStatus", "HoldReason"])
            if active:
                counts = count_condor_states(active)
                if counts.get("held"):
                    reasons = sorted({" ".join(row[1:]) for row in active if row[0] == "5" and len(row) > 1})
                    detail = reasons[0] if reasons else message("runner.no-hold-reason")
                    raise RuntimeError(message("runner.condor-held", JOB=job_id, DETAIL=detail))
                if counts.get("running") or counts.get("transferring output"):
                    if not started:
                        progress.update(start_task, completed=1, total=1, description=message("runner.any-started"))
                        started = True
                    progress.update(finish_task, description=message("runner.cluster-active", SUMMARY=state_summary(counts)))
                else:
                    progress.update(start_task, description=message("runner.cluster-waiting", SUMMARY=state_summary(counts)))
                time.sleep(POLL_SECONDS)
                continue
            history = condor_rows("condor_history", job_id, ["JobStatus", "ExitCode"])
            if not history:
                progress.update(finish_task, description=message("runner.cluster-left-history"))
                time.sleep(POLL_SECONDS)
                continue
            if not started:
                progress.update(start_task, completed=1, total=1, description=message("runner.cluster-left"))
            failed = [row for row in history if row[0] != "4" or len(row) < 2 or row[1] != "0"]
            if failed:
                raise RuntimeError(message("runner.condor-failed", JOB=job_id, COUNT=len(failed)))
            progress.update(finish_task, completed=1, total=1, description=message("runner.condor-all-done", COUNT=len(history)))
            return
    finally:
        progress.stop()


@dataclass(frozen=True)
class LocalRun:
    manifest: Path
    output_base: str
    python_script: str
    cpus_per_file: int


def local_run_settings() -> LocalRun:
    """Read the per-file job settings from the generated HTCondor submit file.

    The wizards write the arguments line as "$(input_file)" output converter
    cpus and the queue line as queue input_file from manifest. Relative paths
    are relative to the bundle directory, as they are for condor_submit.
    """
    arguments: list[str] | None = None
    manifest: str | None = None
    for line in CONDOR_SUBMIT_FILE.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "arguments":
            arguments = shlex.split(value)
        queue = re.match(r"\s*queue\s+input_file\s+from\s+(.+?)\s*$", line)
        if queue:
            manifest = shlex.split(queue.group(1))[0]
    if not arguments or len(arguments) != 4 or manifest is None:
        raise RuntimeError(message("runner.bad-submit-file", FILE=CONDOR_SUBMIT_FILE.name))
    try:
        cpus_per_file = int(arguments[3])
    except ValueError as error:
        raise RuntimeError(message("runner.bad-cpu-count", FILE=CONDOR_SUBMIT_FILE.name, VALUE=arguments[3])) from error
    return LocalRun(BUNDLE_DIRECTORY / manifest, arguments[1], arguments[2], max(1, cpus_per_file))


def available_cpus() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1


def run_locally(console: Console, settings: LocalRun) -> None:
    """Run one conversion per manifest entry on this machine and wait for all of them."""
    if not settings.manifest.is_file():
        raise RuntimeError(message("runner.manifest-missing", PATH=settings.manifest))
    inputs = [line.strip() for line in settings.manifest.read_text().splitlines() if line.strip()]
    if not inputs:
        raise RuntimeError(message("runner.manifest-no-work", PATH=settings.manifest))
    if shutil.which("uv") is None:
        raise RuntimeError(message("runner.no-uv"))

    default_workers = max(1, min(len(inputs), available_cpus() // settings.cpus_per_file))
    workers = IntPrompt.ask(
        message("runner.workers-prompt", CORES=settings.cpus_per_file),
        default=default_workers,
    )
    workers = max(1, min(workers, len(inputs)))

    # Build the converter's environment once, so parallel runs do not all
    # resolve the same dependencies at the same time.
    console.print(message("common.preparing-environment"))
    prepared = command_output(["uv", "run", settings.python_script, "--help"])
    if prepared.returncode:
        raise RuntimeError(message("runner.prepare-failed", DETAIL=prepared.stderr.strip() or prepared.stdout.strip()))

    logs = BUNDLE_DIRECTORY / "logs"
    logs.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    def convert(number: int, input_file: str) -> tuple[int, int]:
        stem = logs / f"pcdf-ntuple-local-{stamp}.{number}"
        with open(f"{stem}.out", "w") as stdout, open(f"{stem}.err", "w") as stderr:
            result = subprocess.run(
                [
                    str(CONDOR_JOB_SCRIPT), input_file, settings.output_base,
                    settings.python_script, str(settings.cpus_per_file),
                ],
                check=False,
                stdout=stdout,
                stderr=stderr,
                cwd=BUNDLE_DIRECTORY,
            )
        return number, result.returncode

    failed: list[int] = []
    progress = Progress(
        SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(),
        console=console, transient=False,
    )
    with progress, ThreadPoolExecutor(max_workers=workers) as pool:
        task = progress.add_task(message("runner.converting", WORKERS=workers), total=len(inputs))
        futures = [pool.submit(convert, number, path) for number, path in enumerate(inputs)]
        try:
            for future in as_completed(futures):
                number, returncode = future.result()
                if returncode:
                    failed.append(number)
                progress.advance(task)
        except KeyboardInterrupt:
            # Ctrl+C also reaches the running conversions, which share this
            # process group. Drop the conversions that have not started.
            pool.shutdown(wait=True, cancel_futures=True)
            raise
    console.print(message("runner.logs-location", LOGS=logs, STAMP=stamp))
    if failed:
        raise RuntimeError(message("runner.some-failed", FAILED=len(failed), TOTAL=len(inputs), FIRST=min(failed)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=message("runner.description"))
    parser.add_argument(
        "--local",
        action="store_true",
        help=message("runner.help-local"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    console = Console()
    console.print(Panel(message("runner.intro"), title=message("runner.intro-title")))
    try:
        scheduler = configured_scheduler()
    except RuntimeError as error:
        console.print(message("runner.not-started", REASON=error))
        return 2
    run_here = scheduler.name == "HTCondor" and (args.local or shutil.which("condor_submit") is None)
    if args.local and scheduler.name != "HTCondor":
        console.print(message("runner.not-started", REASON=message("runner.local-condor-only")))
        return 2
    if not MANIFEST_HELPER.is_file():
        console.print(message("runner.not-started", REASON=message("runner.helper-missing")))
        return 2

    console.print(message("runner.step-manifest"))
    for directory in ("input", "logs"):
        (BUNDLE_DIRECTORY / directory).mkdir(exist_ok=True)
    manifest_scheduler = "condor" if scheduler.name == "HTCondor" else "slurm"
    manifest_result = subprocess.run(
        [str(MANIFEST_HELPER), "--scheduler", manifest_scheduler],
        check=False,
        cwd=BUNDLE_DIRECTORY,
    )
    if manifest_result.returncode:
        console.print(message("runner.manifest-not-created"))
        return manifest_result.returncode

    if run_here:
        if not args.local:
            console.print(message("runner.no-condor-submit"))
        if not Confirm.ask(message("runner.run-here-prompt"), default=False):
            console.print(message("runner.nothing-run"))
            return 0
        try:
            console.print(message("runner.step-local"))
            run_locally(console, local_run_settings())
        except RuntimeError as error:
            console.print(message("runner.workflow-stopped", REASON=error))
            return 2
        except KeyboardInterrupt:
            console.print("\n" + message("runner.local-interrupted"))
            return 130
        console.print(message("runner.local-done"))
        return 0

    if not Confirm.ask(message("runner.submit-prompt", FILE=scheduler.submit_file.name), default=False):
        console.print(message("runner.not-submitted"))
        return 0
    job_id = ""
    try:
        job_id = scheduler.submit()
        console.print(message("runner.step-submitted", SCHEDULER=scheduler.name, JOB=job_id))
        if scheduler.name == "SLURM":
            wait_for_slurm(console, job_id)
        else:
            wait_for_condor(console, job_id)
    except RuntimeError as error:
        console.print(message("runner.workflow-stopped", REASON=error))
        return 2
    except KeyboardInterrupt:
        console.print("\n" + message("runner.monitoring-stopped", JOB=job_id, SCHEDULER=scheduler.name))
        return 130
    console.print(message("runner.job-done", SCHEDULER=scheduler.name, JOB=job_id))
    return 0


if __name__ == "__main__":
    install_rich_traceback()
    raise SystemExit(main())
