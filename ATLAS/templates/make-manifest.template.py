#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich", "rucio-clients"]
# ///
"""Interactively create a PCDF input manifest before submitting the SLURM job."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile, gettempdir
from urllib.parse import parse_qs, unquote, urlsplit

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table


def local_x509_proxy() -> Path | None:
    """Return an available X.509 proxy, if the user has one."""
    candidates = (
        os.environ.get("RUCIO_CLIENT_PROXY"),
        os.environ.get("X509_USER_PROXY"),
        f"/tmp/x509up_u{os.getuid()}",
    )
    for candidate in candidates:
        if candidate:
            proxy = Path(candidate).expanduser()
            if proxy.is_file():
                return proxy
    return None


def select_x509_proxy() -> Path:
    """Tell supported Rucio client versions which usable proxy to use."""
    proxy = local_x509_proxy()
    if proxy is None:
        raise RuntimeError("no valid X.509 proxy file was found")
    proxy_path = str(proxy)
    os.environ["X509_USER_PROXY"] = proxy_path
    os.environ["RUCIO_CLIENT_PROXY"] = proxy_path
    return proxy


def proxy_setup_instructions() -> str:
    return (
        "To create one yourself in a Perlmutter login-node shell, run:\n"
        "  setupATLAS\n"
        "  lsetup emi\n"
        "  voms-proxy-init -voms atlas\n"
        "Then verify it with:\n"
        "  voms-proxy-info -all"
    )


def create_x509_proxy(console: Console) -> None:
    """Offer to create a proxy without changing this process's environment."""
    atlas_root = Path(
        os.environ.get("ATLAS_LOCAL_ROOT_BASE", "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase")
    )
    initializer = atlas_root / "wrappers" / "gridMW" / "voms-proxy-init"
    if not initializer.is_file():
        raise RuntimeError(f"no valid X.509 proxy was found. {proxy_setup_instructions()}")

    console.print(
        "A Rucio lookup needs an ATLAS VOMS proxy. Creating one will prompt for "
        "your grid-certificate passphrase."
    )
    if not Confirm.ask("Create an ATLAS VOMS proxy now", default=False):
        raise RuntimeError(f"no valid X.509 proxy was found. {proxy_setup_instructions()}")
    try:
        environment = os.environ.copy()
        environment.setdefault("ALRB_tmpScratch", gettempdir())
        result = subprocess.run(
            [str(initializer), "-voms", "atlas"],
            check=False,
            env=environment,
        )
    except OSError as error:
        raise RuntimeError(f"could not start voms-proxy-init: {error}") from error
    if result.returncode:
        raise RuntimeError("voms-proxy-init did not create a proxy")
    if not local_x509_proxy():
        raise RuntimeError("voms-proxy-init completed, but no proxy file was found")


def configure_atlas_rucio(console: Console) -> None:
    """Load ATLAS settings and require a valid login-node X.509 proxy."""
    atlas_root = Path(
        os.environ.get("ATLAS_LOCAL_ROOT_BASE", "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase")
    )
    if not os.environ.get("RUCIO_CONFIG"):
        config = atlas_root / "x86_64" / "rucio-clients" / "current" / "etc" / "rucio.cfg"
        if not config.is_file():
            raise RuntimeError(f"ATLAS Rucio configuration is unavailable at {config}")
        os.environ["RUCIO_CONFIG"] = str(config)

    certificate_directory = atlas_root / "etc" / "grid-security-emi" / "certificates"
    if certificate_directory.is_dir():
        os.environ.setdefault("X509_CERT_DIR", str(certificate_directory))

    auth_type = os.environ.get("RUCIO_AUTH_TYPE")
    if auth_type and auth_type != "x509_proxy":
        return
    if not local_x509_proxy():
        create_x509_proxy(console)
    select_x509_proxy()
    if not auth_type:
        os.environ["RUCIO_AUTH_TYPE"] = "x509_proxy"


def prompt_directory(console: Console) -> Path:
    while True:
        root = Path(Prompt.ask("Downloaded-data directory", default=".")).expanduser()
        if root.is_dir():
            return root
        console.print(f"[red]Not a directory:[/red] {root}")


def local_files(root: Path) -> list[Path]:
    """Find usable ROOT files below the user-selected local root."""
    paths: list[Path] = []
    for path in root.rglob("DAOD_*.pool.root*"):
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts):
            try:
                if path.stat().st_size > 1024:
                    paths.append(path)
            except OSError:
                continue
    return sorted(paths)


def rucio_replica_paths(did: str) -> list[Path]:
    if did.count(":") != 1 or any(not part for part in did.split(":", 1)):
        raise RuntimeError("enter the Rucio dataset as scope:name")
    try:
        from rucio.client import Client
    except ImportError as error:
        raise RuntimeError("the Rucio Python client is unavailable. Run this bundled script with uv") from error

    paths: list[Path] = []
    scope, name = did.split(":", 1)
    try:
        replicas = Client().list_replicas(
            [{"scope": scope, "name": name}],
            rse_expression="NERSC_LOCALGROUPDISK",
        )
        for replica in replicas:
            for pfn in replica.get("pfns", {}):
                parsed = urlsplit(pfn)
                query_path = parse_qs(parsed.query).get("SFN", [""])[0]
                path = query_path or parsed.path
                if path.startswith("/"):
                    local_path = Path("/" + unquote(path).lstrip("/"))
                    if local_path not in paths:
                        paths.append(local_path)
    except Exception as error:
        raise RuntimeError(f"Rucio lookup failed: {error}") from error
    if not paths:
        raise RuntimeError("Rucio returned no replica paths at NERSC_LOCALGROUPDISK")
    return sorted(paths)


def write_manifest(paths: list[Path], output: Path) -> None:
    if not paths:
        raise RuntimeError("no usable local ROOT files were found. The manifest was not written")
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=output.parent) as temporary:
        temporary.writelines(f"{path}\n" for path in paths)
        temporary_path = Path(temporary.name)
    temporary_path.replace(output)


def main() -> int:
    console = Console()
    console.print(Panel(
        "Choose DAOD files that are already local. The SLURM job reads the "
        "manifest and does not download data on compute nodes.",
        title="PCDF input manifest",
    ))
    choices = Table(show_header=True, header_style="bold", box=None)
    choices.add_column("Option", style="bold cyan", no_wrap=True)
    choices.add_column("Use when")
    choices.add_row("1", "You used rucio download and have the files in a directory.")
    choices.add_row("2", "The dataset is already copied to NERSC_LOCALGROUPDISK.")
    console.print(choices)
    source = Prompt.ask("Choose an input source", choices=["1", "2"], default="1")
    try:
        if source == "1":
            root = prompt_directory(console)
        else:
            did = Prompt.ask("Dataset DID (scope:name)", default="", show_default=False).strip()
            configure_atlas_rucio(console)
        output = Path(Prompt.ask("Manifest path", default="pcdf-inputs.txt")).expanduser()
        if source == "1":
            paths = local_files(root)
        else:
            paths = rucio_replica_paths(did)
        write_manifest(paths, output)
    except RuntimeError as error:
        console.print(f"[red]Manifest not written:[/red] {error}")
        return 2
    console.print(f"[green]Wrote {len(paths)} local paths to {output}.[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
