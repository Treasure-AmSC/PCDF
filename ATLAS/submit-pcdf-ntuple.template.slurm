#!/bin/bash
#SBATCH --job-name=pcdf-ntuple
{{ACCOUNT_LINE}}
#SBATCH --qos={{QOS}}
#SBATCH --constraint=cpu
#SBATCH --nodes={{NODES}}
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task={{PERLMUTTER_CPU_CORES}}
#SBATCH --time={{TIME}}
#SBATCH --output=pcdf-ntuple-%j.out
#SBATCH --error=pcdf-ntuple-%j.err

# NERSC Perlmutter wrapper from ATLAS/ntuple-wizard.html.
# CPU-only: the generated converter does not use GPUs.
# Packs conversions into one wide Slurm allocation.
# Uses GNU parallel instead of a large Slurm job array.
#
# Usage from a Perlmutter login node:
#   1. Put one input DAOD path per line in INPUT_MANIFEST.
#   2. Run: sbatch submit-pcdf-ntuple.slurm

set -euo pipefail

module load python

PYTHON_SCRIPT={{PYTHON_PATH}}
INPUT_MANIFEST={{INPUT_MANIFEST}}
RUCIO_DID={{RUCIO_DID}}
RUCIO_RSE={{RUCIO_RSE}}
OUTPUT_BASE={{OUTPUT_BASE}}
JOBS_PER_NODE={{JOBS_PER_NODE}}
PERLMUTTER_CPU_CORES={{PERLMUTTER_CPU_CORES}}

needs_edit=0
[[ "$PYTHON_SCRIPT" == *"<"* ]] && needs_edit=1
[[ "$INPUT_MANIFEST" == *"<"* ]] && needs_edit=1
[[ "$OUTPUT_BASE" == *"<"* ]] && needs_edit=1
if [[ ! -f "$INPUT_MANIFEST" ]]; then
    [[ "$RUCIO_DID" == *"<"* ]] && needs_edit=1
    [[ "$RUCIO_RSE" == *"<"* ]] && needs_edit=1
fi
if (( needs_edit )); then
    echo "ERROR: edit account/output/input settings." >&2
    exit 2
fi

mkdir -p "$OUTPUT_BASE"
mkdir -p "$(dirname "$INPUT_MANIFEST")"

if [[ ! -f "$INPUT_MANIFEST" ]]; then
    if ! command -v rucio >/dev/null 2>&1; then
        echo "ERROR: rucio is needed for the manifest." >&2
        exit 2
    fi

    echo "Input manifest not found; querying Rucio."
    echo "Rucio DID:       $RUCIO_DID"
    echo "Local RSE:       $RUCIO_RSE"
    REPLICA_REPORT="$OUTPUT_BASE/repl-${SLURM_JOB_ID}.txt"
    PFN_LIST="$OUTPUT_BASE/pfns-${SLURM_JOB_ID}.txt"

    rucio list-dataset-replicas "$RUCIO_DID" \
        | tee "$REPLICA_REPORT"
    availability=$(awk -v rse="$RUCIO_RSE" -F'|' '
        $2 ~ rse {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
            if ($2 == rse) {
                found = $3 + 0
                total = $4 + 0
                print found "/" total
            }
        }
    ' "$REPLICA_REPORT" | head -n 1)

    if [[ -n "$availability" ]]; then
        [[ "$availability" == */0 ]] && availability=""
    fi
    if [[ -n "$availability" ]]; then
        found=${availability%%/*}
        total=${availability##*/}
        if [[ "$found" != "$total" ]]; then
            echo "ERROR: only $availability at $RUCIO_RSE" >&2
            exit 2
        fi
    fi

    rucio list-file-replicas \
        --rse "$RUCIO_RSE" \
        --pfns \
        "$RUCIO_DID" > "$PFN_LIST"

    python - "$PFN_LIST" "$INPUT_MANIFEST" <<'PCDF_PFNS'
from pathlib import Path
from sys import argv
from urllib.parse import unquote, urlparse

pfns = Path(argv[1]).read_text().splitlines()
paths = []
for raw in pfns:
    line = raw.strip()
    if not line or line.startswith(("#", "-", "|")):
        continue
    if "://" not in line:
        paths.append(line)
        continue
    parsed = urlparse(line)
    if parsed.scheme == "file":
        paths.append(unquote(parsed.path))
    else:
        paths.append(line)

content = "\n".join(paths)
if paths:
    content += "\n"
Path(argv[2]).write_text(content)
PCDF_PFNS
fi

if [[ ! -s "$INPUT_MANIFEST" ]]; then
    echo "ERROR: no inputs in $INPUT_MANIFEST" >&2
    exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is not on PATH; load it first." >&2
    exit 2
fi

if ! command -v parallel >/dev/null 2>&1; then
    echo "ERROR: GNU parallel is not on PATH." >&2
    exit 2
fi

if (( JOBS_PER_NODE < 1 )); then
    echo "ERROR: JOBS_PER_NODE must be at least 1" >&2
    exit 2
fi
if (( JOBS_PER_NODE > SLURM_CPUS_PER_TASK )); then
    echo "ERROR: JOBS_PER_NODE exceeds available CPUs" >&2
    exit 2
fi

CPUS_PER_CONVERSION=$((
    SLURM_CPUS_PER_TASK / JOBS_PER_NODE
))
if (( CPUS_PER_CONVERSION < 1 )); then
    echo "ERROR: zero CPUs per conversion" >&2
    exit 2
fi

USED_CPUS=$((JOBS_PER_NODE * CPUS_PER_CONVERSION))
UNUSED_CPUS=$((SLURM_CPUS_PER_TASK - USED_CPUS))
if (( UNUSED_CPUS > 0 )); then
    echo "$UNUSED_CPUS CPU(s) idle per node."
fi

export UV_CACHE_DIR="${SCRATCH:-$HOME}/.cache/uv"
echo "Preparing uv environment once."
uv run "$PYTHON_SCRIPT" --help >/dev/null

PAYLOAD_SCRIPT="$OUTPUT_BASE/convert-${SLURM_JOB_ID}.sh"
cat > "$PAYLOAD_SCRIPT" <<'PCDF_PAYLOAD'
#!/bin/bash
set -euo pipefail

TASK_ID="$1"
INPUT_FILE="$2"

input_name=$(basename "$INPUT_FILE")
output_name="${input_name%.*}"
OUTPUT_DIR="$OUTPUT_BASE/${TASK_ID}_${output_name}"

if [[ -e "$OUTPUT_DIR" ]]; then
    echo "ERROR: output exists: $OUTPUT_DIR" >&2
    exit 2
fi

export OMP_NUM_THREADS="$CPUS_PER_CONVERSION"
echo "Task ${TASK_ID}: $INPUT_FILE -> $OUTPUT_DIR"
uv run --no-sync \
    "$PYTHON_SCRIPT" \
    "$INPUT_FILE" \
    -o "$OUTPUT_DIR"
PCDF_PAYLOAD
chmod +x "$PAYLOAD_SCRIPT"

DRIVER_SCRIPT="$OUTPUT_BASE/driver-${SLURM_JOB_ID}.sh"
cat > "$DRIVER_SCRIPT" <<'PCDF_DRIVER'
#!/bin/bash
set -euo pipefail

JOBLOG="$OUTPUT_BASE/p-${SLURM_JOB_ID}.${SLURM_NODEID}.log"

awk \
    -v N="$SLURM_NODEID" \
    -v T="$SLURM_NNODES" \
    'NF && ((NR - 1) % T == N) {print NR "	" $0}' \
    "$INPUT_MANIFEST" |
parallel \
    --colsep "	" \
    --jobs "$JOBS_PER_NODE" \
    --line-buffer \
    --joblog "$JOBLOG" \
    "$PAYLOAD_SCRIPT" {1} {2}
PCDF_DRIVER
chmod +x "$DRIVER_SCRIPT"

export PYTHON_SCRIPT INPUT_MANIFEST OUTPUT_BASE
export RUCIO_DID RUCIO_RSE
export PAYLOAD_SCRIPT JOBS_PER_NODE CPUS_PER_CONVERSION

echo "Running on ${SLURM_NNODES} node(s)"
echo "Node list:      ${SLURM_JOB_NODELIST:-unknown}"
echo "Input manifest: $INPUT_MANIFEST"
echo "Rucio DID:       $RUCIO_DID"
echo "Local RSE:       $RUCIO_RSE"
echo "Output base:    $OUTPUT_BASE"
echo "Parallelism:    $JOBS_PER_NODE job(s)/node," \
     "$CPUS_PER_CONVERSION CPU(s) each"

srun \
    --no-kill \
    --ntasks="${SLURM_NNODES}" \
    --ntasks-per-node=1 \
    --cpus-per-task="${SLURM_CPUS_PER_TASK}" \
    --wait=0 \
    "$DRIVER_SCRIPT"
