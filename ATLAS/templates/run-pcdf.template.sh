#!/usr/bin/env bash
# Start the interactive PCDF workflow from the directory containing this file.
set -euo pipefail

cd "$(dirname "$0")"
if ! command -v uv >/dev/null; then
    echo "{{@shell.uv-required}}" >&2
    echo "{{@shell.uv-install}}" >&2
    exit 1
fi
mkdir -p input logs
exec uv run ./code/run-pcdf.py "$@"
