#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich"]
# ///
"""Create a manifest, submit the configured PCDF job, and follow its state."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm


CODE_DIRECTORY = Path(__file__).resolve().parent
BUNDLE_DIRECTORY = CODE_DIRECTORY.parent
MANIFEST_HELPER = CODE_DIRECTORY / "make-manifest.py"
SLURM_SCRIPT = CODE_DIRECTORY / "submit-pcdf-ntuple.slurm"
CONDOR_SUBMIT_FILE = CODE_DIRECTORY / "submit-pcdf-ntuple.condor"
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
        raise RuntimeError(f"Required command not found: {command[0]}") from error


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
            message = result.stderr.strip() or result.stdout.strip() or "no error details were reported"
            raise RuntimeError(f"Submission failed: {message}")
        match = re.search(pattern, result.stdout)
        if not match:
            raise RuntimeError(f"Could not read a job ID from submission output: {result.stdout.strip()}")
        return match.group(1)


def configured_scheduler() -> Scheduler:
    available = [Scheduler("SLURM", SLURM_SCRIPT), Scheduler("HTCondor", CONDOR_SUBMIT_FILE)]
    configured = [scheduler for scheduler in available if scheduler.submit_file.is_file()]
    if len(configured) != 1:
        names = ", ".join(path.name for path in (SLURM_SCRIPT, CONDOR_SUBMIT_FILE))
        raise RuntimeError(f"The bundle must contain exactly one scheduler file: {names}")
    return configured[0]


def slurm_queued_state(job_id: str) -> tuple[str, str] | None:
    result = command_output(["squeue", "--noheader", f"--jobs={job_id}", "--format=%T|%R"])
    if result.returncode:
        raise RuntimeError(f"Could not query SLURM: {result.stderr.strip() or 'no error details were reported'}")
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
        raise RuntimeError(f"Could not read SLURM accounting: {result.stderr.strip() or 'no error details were reported'}")
    for line in result.stdout.splitlines():
        fields = line.split("|")
        if len(fields) >= 3 and fields[0] == job_id:
            return fields[1].rstrip("+"), fields[2]
    return None


def condor_rows(command: str, job_id: str, attributes: list[str]) -> list[list[str]]:
    result = command_output([command, job_id, "-af", *attributes])
    if result.returncode:
        message = result.stderr.strip() or "no error details were reported"
        raise RuntimeError(f"Could not query HTCondor: {message}")
    return [line.split(None, len(attributes) - 1) for line in result.stdout.splitlines() if line.strip()]


def count_condor_states(rows: list[list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        name = CONDOR_STATUS_NAMES.get(row[0], f"state {row[0]}")
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
    progress.add_task("Input manifest is ready", total=1, completed=1)
    progress.add_task(f"Submitted {scheduler_name} job {job_id}", total=1, completed=1)
    start_task = progress.add_task("Waiting for work to start", total=None)
    finish_task = progress.add_task("Waiting for work to finish", total=None)
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
                        progress.update(start_task, completed=1, total=1, description="Job has started")
                        started = True
                    progress.update(finish_task, description=f"Job is running ({detail or 'no location reported'})")
                else:
                    progress.update(start_task, description=f"Job is {state.lower()} ({detail or 'no reason reported'})")
                time.sleep(POLL_SECONDS)
                continue
            accounting = slurm_completed_state(job_id)
            if accounting is None:
                progress.update(finish_task, description="Job left the queue. Waiting for SLURM accounting.")
                time.sleep(POLL_SECONDS)
                continue
            state, exit_code = accounting
            if not started:
                progress.update(start_task, completed=1, total=1, description="Job left the queue")
            if state not in SLURM_TERMINAL_STATES:
                progress.update(finish_task, description=f"Job state is {state.lower()}")
                time.sleep(POLL_SECONDS)
                continue
            if state == "COMPLETED" and exit_code.startswith("0:"):
                progress.update(finish_task, completed=1, total=1, description="Job completed successfully")
                return
            raise RuntimeError(f"SLURM job {job_id} ended with {state} ({exit_code})")
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
                    detail = reasons[0] if reasons else "no hold reason was reported"
                    raise RuntimeError(f"HTCondor cluster {job_id} has held jobs: {detail}")
                if counts.get("running") or counts.get("transferring output"):
                    if not started:
                        progress.update(start_task, completed=1, total=1, description="At least one job has started")
                        started = True
                    progress.update(finish_task, description=f"Cluster is active ({state_summary(counts)})")
                else:
                    progress.update(start_task, description=f"Cluster is waiting ({state_summary(counts)})")
                time.sleep(POLL_SECONDS)
                continue
            history = condor_rows("condor_history", job_id, ["JobStatus", "ExitCode"])
            if not history:
                progress.update(finish_task, description="Cluster left the queue. Waiting for HTCondor history.")
                time.sleep(POLL_SECONDS)
                continue
            if not started:
                progress.update(start_task, completed=1, total=1, description="Cluster left the queue")
            failed = [row for row in history if row[0] != "4" or len(row) < 2 or row[1] != "0"]
            if failed:
                raise RuntimeError(f"HTCondor cluster {job_id} finished with {len(failed)} failed job(s)")
            progress.update(finish_task, completed=1, total=1, description=f"All {len(history)} jobs completed successfully")
            return
    finally:
        progress.stop()


def main() -> int:
    console = Console()
    console.print(Panel(
        "This launcher creates the input manifest, submits the prepared batch "
        "job, then follows it until all work finishes. Stopping this launcher "
        "with Ctrl+C does not cancel submitted work.",
        title="PCDF job workflow",
    ))
    try:
        scheduler = configured_scheduler()
    except RuntimeError as error:
        console.print(f"[red]Workflow not started:[/red] {error}")
        return 2
    if not MANIFEST_HELPER.is_file():
        console.print("[red]Workflow not started:[/red] make-manifest.py is missing.")
        return 2

    console.print("[bold]1. Create the input manifest[/bold]")
    for directory in ("input", "output", "logs"):
        (BUNDLE_DIRECTORY / directory).mkdir(exist_ok=True)
    manifest_scheduler = "condor" if scheduler.name == "HTCondor" else "slurm"
    manifest_result = subprocess.run(
        [str(MANIFEST_HELPER), "--scheduler", manifest_scheduler],
        check=False,
        cwd=BUNDLE_DIRECTORY,
    )
    if manifest_result.returncode:
        console.print("[red]Workflow stopped:[/red] the manifest was not created.")
        return manifest_result.returncode

    if not Confirm.ask(f"Submit {scheduler.submit_file.name} now", default=False):
        console.print("The manifest is ready. The job was not submitted.")
        return 0
    job_id = ""
    try:
        job_id = scheduler.submit()
        console.print(f"[bold]2. Submitted {scheduler.name} job {job_id}[/bold]")
        if scheduler.name == "SLURM":
            wait_for_slurm(console, job_id)
        else:
            wait_for_condor(console, job_id)
    except RuntimeError as error:
        console.print(f"[red]Workflow stopped:[/red] {error}")
        return 2
    except KeyboardInterrupt:
        console.print(f"\nMonitoring stopped. Job {job_id} remains under {scheduler.name} control.")
        return 130
    console.print(f"[green]PCDF {scheduler.name} job {job_id} completed successfully.[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
