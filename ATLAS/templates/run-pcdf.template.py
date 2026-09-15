#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich"]
# ///
"""Create a manifest, submit the PCDF job, and follow its SLURM state."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm


BUNDLE_DIRECTORY = Path(__file__).resolve().parent
MANIFEST_HELPER = BUNDLE_DIRECTORY / "make-manifest.py"
SLURM_SCRIPT = BUNDLE_DIRECTORY / "submit-pcdf-ntuple.slurm"
POLL_SECONDS = 10
TERMINAL_STATES = {"BOOT_FAIL", "CANCELLED", "COMPLETED", "DEADLINE", "FAILED", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED", "TIMEOUT"}


def command_output(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True, capture_output=True)


def submit_job() -> str:
    result = command_output(["sbatch", str(SLURM_SCRIPT)])
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "sbatch did not report an error"
        raise RuntimeError(f"Submission failed: {message}")
    match = re.search(r"Submitted batch job (\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not read a job ID from sbatch output: {result.stdout.strip()}")
    return match.group(1)


def queued_state(job_id: str) -> tuple[str, str] | None:
    result = command_output(["squeue", "--noheader", f"--jobs={job_id}", "--format=%T|%R"])
    if result.returncode:
        message = result.stderr.strip() or "squeue did not report an error"
        raise RuntimeError(f"Could not query SLURM: {message}")
    line = next((line for line in result.stdout.splitlines() if line.strip()), "")
    if not line:
        return None
    state, _, detail = line.partition("|")
    return state.strip(), detail.strip()


def completed_state(job_id: str) -> tuple[str, str] | None:
    result = command_output([
        "sacct",
        "--allocations",
        "--noheader",
        "--parsable2",
        f"--jobs={job_id}",
        "--format=JobIDRaw,State,ExitCode",
    ])
    if result.returncode:
        message = result.stderr.strip() or "sacct did not report an error"
        raise RuntimeError(f"Could not read SLURM accounting: {message}")
    for line in result.stdout.splitlines():
        fields = line.split("|")
        if len(fields) >= 3 and fields[0] == job_id:
            return fields[1].rstrip("+"), fields[2]
    return None


def wait_for_job(console: Console, job_id: str) -> None:
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        console=console,
        transient=False,
    ) as progress:
        manifest_task = progress.add_task("Input manifest is ready", total=1, completed=1)
        submit_task = progress.add_task(f"Submitted SLURM job {job_id}", total=1, completed=1)
        start_task = progress.add_task("Waiting for the job to start", total=None)
        finish_task = progress.add_task("Waiting for the job to finish", total=None)
        del manifest_task, submit_task
        started = False
        while True:
            queued = queued_state(job_id)
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

            accounting = completed_state(job_id)
            if accounting is None:
                progress.update(finish_task, description="Job left the queue. Waiting for SLURM accounting.")
                time.sleep(POLL_SECONDS)
                continue
            state, exit_code = accounting
            if not started:
                progress.update(start_task, completed=1, total=1, description="Job left the queue")
            if state not in TERMINAL_STATES:
                progress.update(finish_task, description=f"Job state is {state.lower()}")
                time.sleep(POLL_SECONDS)
                continue
            if state == "COMPLETED" and exit_code.startswith("0:"):
                progress.update(finish_task, completed=1, total=1, description="Job completed successfully")
                return
            progress.update(finish_task, completed=1, total=1, description=f"Job ended: {state} ({exit_code})")
            raise RuntimeError(f"SLURM job {job_id} ended with {state} ({exit_code})")


def main() -> int:
    console = Console()
    console.print(Panel(
        "This launcher creates the input manifest, submits the prepared SLURM "
        "job, then follows the queue until the job finishes. It does not cancel "
        "the job if you stop this launcher with Ctrl+C.",
        title="PCDF job workflow",
    ))
    if not MANIFEST_HELPER.is_file() or not SLURM_SCRIPT.is_file():
        console.print("[red]Workflow not started:[/red] bundle files are missing.")
        return 2

    console.print("[bold]1. Create the input manifest[/bold]")
    manifest_result = subprocess.run([str(MANIFEST_HELPER)], check=False)
    if manifest_result.returncode:
        console.print("[red]Workflow stopped:[/red] the manifest was not created.")
        return manifest_result.returncode

    if not Confirm.ask("Submit submit-pcdf-ntuple.slurm now", default=False):
        console.print("The manifest is ready. The job was not submitted.")
        return 0
    try:
        job_id = submit_job()
        console.print(f"[bold]2. Submitted job {job_id}[/bold]")
        wait_for_job(console, job_id)
    except RuntimeError as error:
        console.print(f"[red]Workflow stopped:[/red] {error}")
        return 2
    except KeyboardInterrupt:
        console.print(f"\nMonitoring stopped. Job {job_id} remains under SLURM control.")
        return 130
    console.print(f"[green]PCDF job {job_id} completed successfully.[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
