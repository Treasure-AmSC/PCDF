#!/usr/bin/env bash
# Start the interactive PCDF workflow from the directory containing this file.
set -euo pipefail

cd "$(dirname "$0")"
exec uv run ./run-pcdf.py
