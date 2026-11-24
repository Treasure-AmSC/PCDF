#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich", "rucio-clients"]
# ///
"""Create a PCDF input manifest. The text it shows is in MESSAGES."""

from __future__ import annotations

import argparse
import glob
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile, gettempdir
from urllib.parse import parse_qs, unquote, urlsplit

try:
    import readline
except ImportError:
    readline = None

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.traceback import install as install_rich_traceback

MESSAGES = {{MESSAGES:manifest}}


def message(key: str, **values: object) -> str:
    """Return a user-facing message, filling in each double-brace placeholder from values."""
    return re.sub(r"{{([A-Z0-9_]+)}}", lambda match: str(values.get(match.group(1), match.group(0))), MESSAGES[key])


ATLAS_ROOT = Path(
    os.environ.get("ATLAS_LOCAL_ROOT_BASE", "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase")
)
DTN_HOSTS = tuple(f"dtn0{index}.nersc.gov" for index in range(1, 5))


def grid_tool(name: str) -> Path | None:
    """Find a grid-middleware command on PATH, falling back to ATLASLocalRootBase."""
    found = shutil.which(name)
    if found:
        return Path(found)
    wrapper = ATLAS_ROOT / "wrappers" / "gridMW" / name
    return wrapper if wrapper.is_file() else None


def rucio_config_path() -> Path | None:
    """Find a Rucio client configuration, or None when the client has none to read."""
    candidates = [os.environ.get("RUCIO_CONFIG")]
    if os.environ.get("RUCIO_HOME"):
        candidates.append(str(Path(os.environ["RUCIO_HOME"]) / "etc" / "rucio.cfg"))
    candidates += [
        str(Path.home() / ".rucio" / "etc" / "rucio.cfg"),
        "/opt/rucio/etc/rucio.cfg",
        str(ATLAS_ROOT / "x86_64" / "rucio-clients" / "current" / "etc" / "rucio.cfg"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().is_file():
            return Path(candidate).expanduser()
    return None


def rucio_sources_unavailable() -> str | None:
    """Explain why Rucio input sources cannot be offered, or return None when they can."""
    if rucio_config_path() is None:
        return message("manifest.no-rucio-config")
    auth_type = os.environ.get("RUCIO_AUTH_TYPE")
    if (not auth_type or auth_type == "x509_proxy") and not (
        local_x509_proxy() or grid_tool("voms-proxy-init")
    ):
        return message("manifest.no-proxy-tool")
    return None
REMOTE_DTN_DOWNLOAD = r'''set -euo pipefail

did="$1"
rucio_account="$2"
destination="$3"
proxy="$4"

atlas_root="${ATLAS_LOCAL_ROOT_BASE:-/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase}"
atlas_setup="$atlas_root/user/atlasLocalSetup.sh"
proxy_info=voms-proxy-info
rucio_config="${RUCIO_CONFIG:-}"
certificate_directory="${X509_CERT_DIR:-}"
if [[ -r "$atlas_setup" ]]; then
    source "$atlas_setup"
    lsetup rucio
    lsetup emi
    proxy_info="$atlas_root/wrappers/gridMW/voms-proxy-info"
    rucio_config="${rucio_config:-$atlas_root/x86_64/rucio-clients/current/etc/rucio.cfg}"
    certificate_directory="${certificate_directory:-$atlas_root/etc/grid-security-emi/certificates}"
fi

if ! command -v "$proxy_info" >/dev/null; then
    echo "{{@dtn.no-voms-info}}" >&2
    exit 2
fi
if [[ -n "$rucio_config" && ! -r "$rucio_config" ]]; then
    echo "{{@dtn.unreadable-config}}" >&2
    exit 2
fi
if [[ -n "$certificate_directory" && ! -d "$certificate_directory" ]]; then
    echo "{{@dtn.no-certificates}}" >&2
    exit 2
fi
if [[ ! -r "$proxy" ]]; then
    echo "{{@dtn.no-proxy}}" >&2
    exit 2
fi

"$proxy_info" -file "$proxy" -exists -valid 1:00
if ! "$proxy_info" -file "$proxy" -vo | grep -Fxq atlas; then
    echo "{{@dtn.no-vo}}" >&2
    exit 2
fi

export X509_USER_PROXY="$proxy"
export RUCIO_CLIENT_PROXY="$proxy"
export RUCIO_AUTH_TYPE=x509_proxy
export RUCIO_ACCOUNT="$rucio_account"
[[ -z "$rucio_config" ]] || export RUCIO_CONFIG="$rucio_config"
[[ -z "$certificate_directory" ]] || export X509_CERT_DIR="$certificate_directory"

if ! command -v rucio >/dev/null; then
    echo "{{@dtn.no-rucio}}" >&2
    exit 2
fi
mkdir -p "$destination"
echo "{{@dtn.downloading}}"
rucio download --dir "$destination" "$did"
'''


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
        raise RuntimeError(message("manifest.no-proxy-file"))
    proxy_path = str(proxy)
    os.environ["X509_USER_PROXY"] = proxy_path
    os.environ["RUCIO_CLIENT_PROXY"] = proxy_path
    return proxy


def proxy_setup_instructions() -> str:
    return message("manifest.proxy-instructions")


def create_x509_proxy(console: Console) -> None:
    """Offer to create a proxy without changing this process's environment."""
    initializer = grid_tool("voms-proxy-init")
    if initializer is None:
        raise RuntimeError(message("manifest.no-proxy-found", INSTRUCTIONS=proxy_setup_instructions()))

    console.print(message("manifest.proxy-notice"))
    if not Confirm.ask(message("manifest.proxy-prompt"), default=False):
        raise RuntimeError(message("manifest.no-proxy-found", INSTRUCTIONS=proxy_setup_instructions()))
    try:
        environment = os.environ.copy()
        environment.setdefault("ALRB_tmpScratch", gettempdir())
        result = subprocess.run(
            [str(initializer), "-voms", "atlas"],
            check=False,
            env=environment,
        )
    except OSError as error:
        raise RuntimeError(message("manifest.proxy-start-failed", ERROR=error)) from error
    if result.returncode:
        raise RuntimeError(message("manifest.proxy-create-failed"))
    if not local_x509_proxy():
        raise RuntimeError(message("manifest.proxy-missing"))


def configure_rucio(console: Console) -> None:
    """Locate the Rucio configuration and, for proxy authentication, a valid proxy."""
    if not os.environ.get("RUCIO_CONFIG"):
        config = rucio_config_path()
        if config is None:
            raise RuntimeError(message("manifest.set-rucio-config"))
        os.environ["RUCIO_CONFIG"] = str(config)

    certificate_directory = ATLAS_ROOT / "etc" / "grid-security-emi" / "certificates"
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


def validate_did(did: str) -> str:
    """Require an explicit Rucio scope and name without inferring their boundary."""
    if did.count(":") != 1 or any(not part for part in did.split(":", 1)):
        raise RuntimeError(message("manifest.bad-did"))
    return did


def shared_proxy_path() -> Path:
    """Return the private proxy path shared by Perlmutter and the DTNs."""
    credential_directory = Path.home() / ".cache" / "pcdf" / "credentials"
    credential_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    credential_directory.chmod(0o700)
    return credential_directory / f"x509up_u{os.getuid()}"


def proxy_is_usable(proxy: Path, minimum_seconds: int) -> bool:
    """Check the proxy lifetime and require ATLAS VOMS credentials."""
    proxy_info = grid_tool("voms-proxy-info")
    if not proxy.is_file() or proxy_info is None:
        return False
    lifetime = subprocess.run(
        [str(proxy_info), "-file", str(proxy), "-timeleft"],
        check=False,
        text=True,
        capture_output=True,
    )
    try:
        seconds_left = int(lifetime.stdout.strip())
    except ValueError:
        return False
    if lifetime.returncode or seconds_left < minimum_seconds:
        return False
    vo = subprocess.run(
        [str(proxy_info), "-file", str(proxy), "-vo"],
        check=False,
        text=True,
        capture_output=True,
    )
    return vo.returncode == 0 and "atlas" in vo.stdout.split()


def create_shared_x509_proxy(
    console: Console,
    proxy: Path,
    requested_validity: str,
    minimum_seconds: int,
) -> None:
    """Create an ATLAS proxy at a private path visible from the DTNs."""
    initializer = grid_tool("voms-proxy-init")
    if initializer is None:
        raise RuntimeError(message("manifest.no-voms-tool"))
    console.print(message("manifest.shared-proxy-notice"))
    if not Confirm.ask(message("manifest.shared-proxy-prompt", PATH=proxy), default=True):
        raise RuntimeError(message("manifest.shared-proxy-needed"))
    environment = os.environ.copy()
    environment.setdefault("ALRB_tmpScratch", gettempdir())
    try:
        result = subprocess.run(
            [
                str(initializer), "-voms", "atlas", "-valid", requested_validity,
                "-out", str(proxy),
            ],
            check=False,
            env=environment,
        )
    except OSError as error:
        raise RuntimeError(message("manifest.proxy-start-failed", ERROR=error)) from error
    if result.returncode:
        raise RuntimeError(message("manifest.shared-proxy-failed"))
    if proxy.is_file():
        proxy.chmod(0o600)
    if not proxy_is_usable(proxy, minimum_seconds):
        raise RuntimeError(message("manifest.shared-proxy-unusable"))


def ensure_shared_x509_proxy(
    console: Console,
    requested_validity: str,
    minimum_seconds: int,
) -> Path:
    """Return a verified shared proxy, creating or renewing it when needed."""
    proxy = shared_proxy_path()
    if not proxy_is_usable(proxy, minimum_seconds):
        create_shared_x509_proxy(console, proxy, requested_validity, minimum_seconds)
    os.environ["X509_USER_PROXY"] = str(proxy)
    os.environ["RUCIO_CLIENT_PROXY"] = str(proxy)
    return proxy


def _complete_path(text: str, state: int) -> str | None:
    """readline completer: complete filesystem paths, marking directories with a slash."""
    matches = sorted(glob.glob(os.path.expanduser(text) + "*"))
    if text.startswith("~"):
        home = os.path.expanduser("~")
        matches = ["~" + match[len(home):] if match.startswith(home) else match for match in matches]
    matches = [match + "/" if os.path.isdir(os.path.expanduser(match)) else match for match in matches]
    return matches[state] if state < len(matches) else None


def ask_path(label: str, default: str) -> str:
    """Prompt for a path with Tab completion where readline is available."""
    if readline is None:
        return Prompt.ask(label, default=default)
    previous = readline.get_completer(), readline.get_completer_delims()
    readline.set_completer(_complete_path)
    readline.set_completer_delims("\n")
    readline.parse_and_bind("bind ^I rl_complete" if "libedit" in (readline.__doc__ or "") else "tab: complete")
    try:
        return Prompt.ask(label, default=default)
    finally:
        readline.set_completer(previous[0])
        readline.set_completer_delims(previous[1])


def prompt_nonempty(label: str, default: str | None = None) -> str:
    while True:
        value = Prompt.ask(label, default=default or "", show_default=bool(default)).strip()
        if value:
            return value


def prompt_proxy_validity() -> tuple[str, int]:
    """Ask how long a proxy should remain valid and return its acceptance threshold."""
    while True:
        value = Prompt.ask(message("manifest.validity-prompt"), default="12:00").strip()
        match = re.fullmatch(r"([0-9]+):([0-9]{2})", value)
        if match and int(match.group(2)) < 60:
            seconds = (int(match.group(1)) * 60 + int(match.group(2))) * 60
            if seconds > 0:
                return value, max(60, seconds - 300)
        Console().print(message("manifest.validity-error"))


def prompt_download_directory() -> Path:
    """Ask for a bounded shared destination suitable for a Perlmutter job."""
    scratch = os.environ.get("SCRATCH") or os.environ.get("PSCRATCH")
    if not scratch:
        raise RuntimeError(message("manifest.scratch-required"))
    scratch_root = Path(scratch).expanduser().resolve(strict=False)
    cfs_root = Path("/global/cfs/cdirs")
    default = scratch_root / "pcdf-rucio"
    while True:
        destination = Path(
            ask_path(message("manifest.download-dir-prompt"), str(default))
        ).expanduser().resolve(strict=False)
        in_scratch = destination.is_relative_to(scratch_root)
        in_project_cfs = destination != cfs_root and destination.is_relative_to(cfs_root)
        if in_scratch or in_project_cfs:
            return destination
        Console().print(message("manifest.download-dir-error", SCRATCH=scratch_root, PROJECT=cfs_root))


def dtn_path(path: Path) -> Path:
    """Map the Perlmutter spelling of Scratch to the DTN mount path."""
    if path.parts[:2] == ("/", "pscratch"):
        return Path("/global") / path.relative_to("/")
    return path


def download_rucio_on_dtn(
    did: str,
    rucio_account: str,
    host: str,
    destination: Path,
    proxy: Path,
) -> None:
    """Run one Rucio download on a NERSC data transfer node over SSH."""
    arguments = [
        "bash", "-lc", REMOTE_DTN_DOWNLOAD, "pcdf-dtn-download",
        did, rucio_account, str(dtn_path(destination)), str(proxy),
    ]
    remote_command = shlex.join(arguments)
    try:
        result = subprocess.run(["ssh", "-t", host, remote_command], check=False)
    except OSError as error:
        raise RuntimeError(message("manifest.ssh-failed", HOST=host, ERROR=error)) from error
    if result.returncode:
        raise RuntimeError(message("manifest.download-failed", HOST=host))


def prompt_directory(console: Console) -> Path:
    while True:
        root = Path(ask_path(message("manifest.data-dir-prompt"), ".")).expanduser()
        if root.is_dir():
            return root
        console.print(message("manifest.not-a-directory", PATH=root))


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
    validate_did(did)
    try:
        from rucio.client import Client
    except ImportError as error:
        raise RuntimeError(message("manifest.rucio-client-missing")) from error

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
        raise RuntimeError(message("manifest.lookup-failed", ERROR=error)) from error
    if not paths:
        raise RuntimeError(message("manifest.no-replicas"))
    return sorted(paths)


def write_manifest(paths: list[Path], output: Path) -> None:
    if not paths:
        raise RuntimeError(message("manifest.no-files"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=output.parent) as temporary:
        temporary.writelines(f"{path}\n" for path in paths)
        temporary_path = Path(temporary.name)
    temporary_path.replace(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=message("manifest.description"))
    parser.add_argument("--scheduler", choices=("slurm", "condor"), default="slurm")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    console = Console()
    console.print(Panel(message("manifest.intro"), title=message("manifest.intro-title")))
    choices = Table(show_header=True, header_style="bold", box=None)
    choices.add_column(message("manifest.column-option"), style="bold cyan", no_wrap=True)
    choices.add_column(message("manifest.column-use"))
    choices.add_row("1", message("manifest.option-local"))
    source_choices = ["1"]
    hidden: list[str] = []
    unavailable = rucio_sources_unavailable()
    if unavailable is None:
        choices.add_row("2", message("manifest.option-replicas"))
        source_choices.append("2")
    else:
        hidden.append(message("manifest.hidden-option-2", REASON=unavailable))
    if args.scheduler == "slurm":
        if grid_tool("voms-proxy-init") and shutil.which("ssh"):
            choices.add_row("3", message("manifest.option-dtn"))
            source_choices.append("3")
        else:
            hidden.append(message("manifest.hidden-option-3"))
    console.print(choices)
    if hidden:
        console.print(message("manifest.hidden-sources", REASONS="; ".join(hidden)))
    source = Prompt.ask(message("manifest.source-prompt"), choices=source_choices, default="1")
    try:
        if source == "1":
            root = prompt_directory(console)
        elif source == "2":
            did = validate_did(prompt_nonempty(message("manifest.did-prompt")))
            configure_rucio(console)
        else:
            did = validate_did(prompt_nonempty(message("manifest.did-prompt")))
            rucio_account = prompt_nonempty(message("manifest.account-prompt"), os.environ.get("RUCIO_ACCOUNT"))
            host = Prompt.ask(message("manifest.dtn-prompt"), choices=list(DTN_HOSTS), default=DTN_HOSTS[0])
            root = prompt_download_directory()
            requested_validity, minimum_seconds = prompt_proxy_validity()
            proxy = ensure_shared_x509_proxy(console, requested_validity, minimum_seconds)
            download_rucio_on_dtn(did, rucio_account, host, root, proxy)
        output = Path(ask_path(message("manifest.path-prompt"), "pcdf-inputs.txt")).expanduser()
        if source in {"1", "3"}:
            paths = local_files(root)
        else:
            paths = rucio_replica_paths(did)
        write_manifest(paths, output)
    except RuntimeError as error:
        console.print(message("manifest.not-written", REASON=error))
        return 2
    console.print(message("manifest.wrote", COUNT=len(paths), PATH=output))
    return 0


if __name__ == "__main__":
    install_rich_traceback()
    raise SystemExit(main())
