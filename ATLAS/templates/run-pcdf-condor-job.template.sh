#!/usr/bin/env bash
set -euo pipefail

INPUT_FILE=$1
OUTPUT_BASE=$2
PYTHON_SCRIPT=$3
CPUS=$4

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is not available on this HTCondor execute node." >&2
    exit 2
fi

mkdir -p "$OUTPUT_BASE"
export OMP_NUM_THREADS="$CPUS"
export NUMBA_NUM_THREADS="$CPUS"
export OPENBLAS_NUM_THREADS="$CPUS"
export MKL_NUM_THREADS="$CPUS"
export NUMEXPR_NUM_THREADS="$CPUS"

uv run "$PYTHON_SCRIPT" "$INPUT_FILE" -o "$OUTPUT_BASE"
