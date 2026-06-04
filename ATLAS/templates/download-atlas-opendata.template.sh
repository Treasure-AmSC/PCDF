#!/bin/bash
# Download ATLAS Open Data files to scratch before submitting the SLURM job.
# Run this script on a Perlmutter data transfer node, not inside SLURM.

set -euo pipefail

API_BASE={{OPEN_DATA_API_BASE}}
OPEN_DATA_RELEASE={{OPEN_DATA_RELEASE}}
OPEN_DATA_DATASET={{OPEN_DATA_DATASET}}
OPEN_DATA_SEARCH={{OPEN_DATA_QUERY}}
OPEN_DATA_SKIM={{OPEN_DATA_SKIM}}
DOWNLOAD_DIR={{OPEN_DATA_DOWNLOAD_DIR}}
INPUT_MANIFEST={{INPUT_MANIFEST}}
DTN_HOST_PATTERN={{OPEN_DATA_DTN_PATTERN}}
EXPECTED_BYTES={{OPEN_DATA_EXPECTED_BYTES}}
EXPECTED_FILES={{OPEN_DATA_EXPECTED_FILES}}
EXPECTED_MBPS={{OPEN_DATA_EXPECTED_MBPS}}

if [[ -n "${SLURM_JOB_ID:-}" ]]; then
    echo "ERROR: do not download data from a compute job." >&2
    echo "Run this script on a Perlmutter data transfer node first." >&2
    exit 2
fi

host_name=$(hostname -f 2>/dev/null || hostname)
if [[ -n "$DTN_HOST_PATTERN" && "$host_name" != *"$DTN_HOST_PATTERN"* ]]; then
    echo "ERROR: this host does not look like a DTN: $host_name" >&2
    echo "Expected hostname text: $DTN_HOST_PATTERN" >&2
    echo "Log in to a Perlmutter data transfer node and rerun this script." >&2
    exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required on the DTN." >&2
    exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "ERROR: curl is required on the DTN." >&2
    exit 2
fi

mkdir -p "$DOWNLOAD_DIR"
mkdir -p "$(dirname "$INPUT_MANIFEST")"

python3 - "$API_BASE" "$OPEN_DATA_RELEASE" "$OPEN_DATA_DATASET" \
    "$OPEN_DATA_SEARCH" "$OPEN_DATA_SKIM" "$DOWNLOAD_DIR" \
    "$INPUT_MANIFEST" "$EXPECTED_BYTES" "$EXPECTED_FILES" \
    "$EXPECTED_MBPS" <<'PCDF_OPENDATA'
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

(
    api_base,
    release,
    dataset_key,
    search_text,
    skim,
    download_dir,
    manifest_path,
    expected_bytes,
    expected_files,
    expected_mbps,
) = sys.argv[1:]

api_base = api_base.rstrip("/")


def load_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "pcdf-atlas-opendata-transfer/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def https_url(root_url):
    if root_url.startswith("root://eospublic.cern.ch:1094/"):
        return root_url.replace(
            "root://eospublic.cern.ch:1094/",
            "https://opendata.cern.ch",
            1,
        )
    return root_url


def api_url(path, **params):
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return f"{api_base}{path}" + (f"?{query}" if query else "")


def fetch_datasets():
    try:
        count_data = load_json(api_url("/datasets/count", release_name=release))
        total = int(count_data.get("count") or 0)
        page_size = 1000
        datasets = []
        for skip in range(0, max(total, 1), page_size):
            page = load_json(
                api_url(
                    "/datasets",
                    release_name=release,
                    skip=skip,
                    limit=page_size,
                )
            )
            datasets.extend(page if isinstance(page, list) else page.get("datasets", []))
        return datasets
    except Exception as exc:
        print(f"Paginated dataset API failed: {exc}; trying release endpoint")
        release_data = load_json(
            api_url(f"/releases/{urllib.parse.quote(release)}")
        )
        return release_data.get("datasets", [])


def search_blob(dataset):
    values = [
        dataset.get("dataset_number"),
        dataset.get("physics_short"),
        dataset.get("process"),
        dataset.get("description"),
        dataset.get("job_path"),
        dataset.get("Release"),
        dataset.get("release.name"),
        *(dataset.get("keywords") or []),
    ]
    return " ".join(str(value) for value in values if value).lower()


def is_research_physlite(dataset):
    return release == "2024r-pp" and bool(dataset.get("file_list") or [])


def query_matches(dataset, query):
    normalized = query.strip().lower()
    if not normalized or normalized == "physlite":
        return True
    return normalized in search_blob(dataset)


def key_matches(dataset, key):
    selected = str(key).strip().lower()
    if not selected:
        return False
    dataset_number = str(dataset.get("dataset_number") or "").lower()
    physics_short = str(dataset.get("physics_short") or "").lower()
    return selected in {dataset_number, physics_short}


def find_dataset():
    query = search_text.lower()
    selected = str(dataset_key)
    first_match = None
    for dataset in fetch_datasets():
        if not is_research_physlite(dataset):
            continue
        if key_matches(dataset, selected):
            return dataset
        if query_matches(dataset, query) and first_match is None:
            first_match = dataset
    if first_match:
        return first_match
    raise SystemExit(
        f"No matching {release} research PHYSLITE dataset for '{selected}'"
    )


def select_file_list(metadata):
    files = metadata.get("file_list") or []
    available = {"noskim": files}
    for skim_info in metadata.get("skims", []) or []:
        available[skim_info.get("skim_type", "")] = skim_info.get("file_list") or []
    if skim not in available or not available[skim]:
        choices = ", ".join(sorted(k for k, v in available.items() if v))
        raise SystemExit(f"Skim '{skim}' has no files. Available: {choices}")
    return [https_url(url) for url in available[skim]]


def safe_name(url):
    parsed = urllib.parse.urlparse(url)
    name = os.path.basename(urllib.parse.unquote(parsed.path))
    if not name:
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", url)[-96:]
    return name


def file_size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


metadata = find_dataset()
dataset_key = str(metadata.get("dataset_number") or metadata.get("physics_short"))
urls = select_file_list(metadata)
if not urls:
    raise SystemExit(f"No files found for {release}/{dataset_key} skim {skim}")

print(f"Dataset: {release}/{dataset_key} skim={skim}")
print(f"Files:   {len(urls)}")
if expected_bytes.isdigit() and int(expected_bytes) > 0:
    gb = int(expected_bytes) / 1000**3
    print(f"Expected size from preview: {gb:.2f} GB")
if expected_mbps.isdigit() and int(expected_mbps) > 0:
    print(f"Expected throughput setting: {expected_mbps} MB/s")

Path(download_dir).mkdir(parents=True, exist_ok=True)
local_paths = []
for index, url in enumerate(urls, start=1):
    target = Path(download_dir) / safe_name(url)
    print(f"[{index}/{len(urls)}] {target.name}")
    subprocess.run(
        [
            "curl",
            "--fail",
            "--location",
            "--continue-at",
            "-",
            "--retry",
            "5",
            "--retry-delay",
            "10",
            "--output",
            str(target),
            url,
        ],
        check=True,
    )
    local_paths.append(str(target.resolve()))

manifest = Path(manifest_path)
manifest.write_text("\n".join(local_paths) + "\n")
actual_bytes = sum(file_size(path) for path in local_paths)
print(f"Wrote manifest: {manifest}")
print(f"Downloaded bytes: {actual_bytes}")
if expected_bytes.isdigit() and int(expected_bytes) > 0:
    diff = abs(actual_bytes - int(expected_bytes))
    if diff > max(1_000_000, int(expected_bytes) * 0.05):
        print("WARNING: downloaded size differs from browser preview.")
PCDF_OPENDATA
