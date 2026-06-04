#!/bin/bash
#SBATCH --job-name=pcdf-ntuple
{{ACCOUNT_LINE}}
#SBATCH --qos={{QOS}}
#SBATCH --constraint=cpu
#SBATCH --nodes={{NODES}}
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task={{CPUS_PER_TASK}}
#SBATCH --time={{TIME}}
#SBATCH --output=pcdf-ntuple-%j.out
#SBATCH --error=pcdf-ntuple-%j.err

# NERSC Perlmutter wrapper from ATLAS/ntuple-wizard.html.
# CPU-only: the generated converter does not use GPUs.
# Data must already be on scratch; do not download on compute nodes.
# Run download-atlas-opendata.sh on a DTN before submitting this job.

set -euo pipefail

module load python

PYTHON_SCRIPT={{PYTHON_PATH}}
INPUT_MANIFEST={{INPUT_MANIFEST}}
OUTPUT_BASE={{OUTPUT_BASE}}
JOBS_PER_NODE={{JOBS_PER_NODE}}
CONVERTER_CPUS_PER_CONVERSION={{CONVERTER_CPUS_PER_CONVERSION}}
PERLMUTTER_CPU_CORES={{PERLMUTTER_CPU_CORES}}
OPEN_DATA_DATASET={{OPEN_DATA_DATASET}}
OPEN_DATA_RELEASE={{OPEN_DATA_RELEASE}}

needs_edit=0
[[ "$PYTHON_SCRIPT" == *"<"* ]] && needs_edit=1
[[ "$INPUT_MANIFEST" == *"<"* ]] && needs_edit=1
[[ "$OUTPUT_BASE" == *"<"* ]] && needs_edit=1
if (( needs_edit )); then
    echo "ERROR: edit account/output/input settings." >&2
    exit 2
fi

if [[ -n "${PCDF_ALLOW_COMPUTE_DOWNLOAD:-}" ]]; then
    echo "WARNING: PCDF_ALLOW_COMPUTE_DOWNLOAD is ignored." >&2
fi

mkdir -p "$OUTPUT_BASE"

if [[ ! -s "$INPUT_MANIFEST" ]]; then
    echo "ERROR: missing or empty input manifest: $INPUT_MANIFEST" >&2
    echo "Run ./download-atlas-opendata.sh on a Perlmutter DTN first." >&2
    echo "Dataset: ${OPEN_DATA_RELEASE}/${OPEN_DATA_DATASET}" >&2
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
if (( CONVERTER_CPUS_PER_CONVERSION < 1 )); then
    echo "ERROR: CONVERTER_CPUS_PER_CONVERSION must be at least 1" >&2
    exit 2
fi

REQUIRED_CPUS=$((JOBS_PER_NODE * CONVERTER_CPUS_PER_CONVERSION))
if (( REQUIRED_CPUS > SLURM_CPUS_PER_TASK )); then
    echo "ERROR: requested parallel conversions need ${REQUIRED_CPUS} CPUs," >&2
    echo "but SLURM supplied ${SLURM_CPUS_PER_TASK} CPUs per task." >&2
    exit 2
fi
if (( REQUIRED_CPUS > PERLMUTTER_CPU_CORES )); then
    echo "ERROR: requested ${REQUIRED_CPUS} CPUs per node exceeds" >&2
    echo "the Perlmutter CPU-node size (${PERLMUTTER_CPU_CORES})." >&2
    exit 2
fi

CPUS_PER_CONVERSION="$CONVERTER_CPUS_PER_CONVERSION"
UNUSED_CPUS=$((SLURM_CPUS_PER_TASK - REQUIRED_CPUS))
if (( UNUSED_CPUS > 0 )); then
    echo "$UNUSED_CPUS allocated CPU(s) idle per node."
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
export NUMBA_NUM_THREADS="$CPUS_PER_CONVERSION"
export OPENBLAS_NUM_THREADS="$CPUS_PER_CONVERSION"
export MKL_NUM_THREADS="$CPUS_PER_CONVERSION"
export NUMEXPR_NUM_THREADS="$CPUS_PER_CONVERSION"
export VECLIB_MAXIMUM_THREADS="$CPUS_PER_CONVERSION"
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
export PAYLOAD_SCRIPT JOBS_PER_NODE CPUS_PER_CONVERSION

echo "Running on ${SLURM_NNODES} node(s)"
echo "Node list:      ${SLURM_JOB_NODELIST:-unknown}"
echo "Input manifest: $INPUT_MANIFEST"
echo "Open Data:      ${OPEN_DATA_RELEASE}/${OPEN_DATA_DATASET}"
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
