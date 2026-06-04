#!/bin/bash
#SBATCH --job-name=pcdf-ntuple
{{ACCOUNT_LINE}}
#SBATCH --qos={{QOS}}
#SBATCH --constraint=cpu
#SBATCH --nodes={{NODES}}
#SBATCH --exclusive
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task={{PERLMUTTER_LOGICAL_CPUS_PER_NODE}}
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
CONVERTER_CPUS_PER_CONVERSION={{CONVERTER_CPUS_PER_CONVERSION}}
PERLMUTTER_PHYSICAL_CORES={{PERLMUTTER_PHYSICAL_CORES}}
PERLMUTTER_LOGICAL_CPUS={{PERLMUTTER_LOGICAL_CPUS_PER_NODE}}
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

if (( CONVERTER_CPUS_PER_CONVERSION < 1 )); then
    echo "ERROR: CONVERTER_CPUS_PER_CONVERSION must be at least 1" >&2
    exit 2
fi

physical_cores_on_node() {
    if command -v lscpu >/dev/null 2>&1; then
        local cores_per_socket sockets threads_per_core logical_cpus
        cores_per_socket=$(lscpu | awk -F: '/^Core\(s\) per socket:/ {gsub(/ /, "", $2); print $2; exit}')
        sockets=$(lscpu | awk -F: '/^Socket\(s\):/ {gsub(/ /, "", $2); print $2; exit}')
        threads_per_core=$(lscpu | awk -F: '/^Thread\(s\) per core:/ {gsub(/ /, "", $2); print $2; exit}')
        if [[ "$cores_per_socket" =~ ^[0-9]+$ && "$sockets" =~ ^[0-9]+$ ]]; then
            echo $((cores_per_socket * sockets))
            return
        fi
        if [[ -n "${SLURM_CPUS_ON_NODE:-}" && "$threads_per_core" =~ ^[0-9]+$ && "$threads_per_core" -gt 0 ]]; then
            echo $((SLURM_CPUS_ON_NODE / threads_per_core))
            return
        fi
        logical_cpus=$(nproc 2>/dev/null || true)
        if [[ "$logical_cpus" =~ ^[0-9]+$ && "$threads_per_core" =~ ^[0-9]+$ && "$threads_per_core" -gt 0 ]]; then
            echo $((logical_cpus / threads_per_core))
            return
        fi
    fi
    echo "$PERLMUTTER_PHYSICAL_CORES"
}

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
NODE_MANIFEST="$OUTPUT_BASE/node-${SLURM_JOB_ID}.${SLURM_NODEID}.manifest"

awk \
    -v N="$SLURM_NODEID" \
    -v T="$SLURM_NNODES" \
    'NF && ((NR - 1) % T == N) {print NR "	" $0}' \
    "$INPUT_MANIFEST" > "$NODE_MANIFEST"

NODE_WORK=$(wc -l < "$NODE_MANIFEST")
if (( NODE_WORK == 0 )); then
    echo "Node ${SLURM_NODEID}: no input files assigned; exiting."
    exit 0
fi

PHYSICAL_CORES=$(physical_cores_on_node)
if (( PHYSICAL_CORES < 1 )); then
    echo "ERROR: could not determine physical CPU cores on this node" >&2
    exit 2
fi

JOBS_ON_NODE=$((PHYSICAL_CORES / CPUS_PER_CONVERSION))
if (( JOBS_ON_NODE < 1 )); then
    echo "ERROR: ${CPUS_PER_CONVERSION} CPU(s) per conversion exceeds" >&2
    echo "available physical cores (${PHYSICAL_CORES}) on this node." >&2
    exit 2
fi
if (( JOBS_ON_NODE > NODE_WORK )); then
    JOBS_ON_NODE="$NODE_WORK"
fi

export OMP_NUM_THREADS="$CPUS_PER_CONVERSION"
export NUMBA_NUM_THREADS="$CPUS_PER_CONVERSION"
export OPENBLAS_NUM_THREADS="$CPUS_PER_CONVERSION"
export MKL_NUM_THREADS="$CPUS_PER_CONVERSION"
export NUMEXPR_NUM_THREADS="$CPUS_PER_CONVERSION"
export VECLIB_MAXIMUM_THREADS="$CPUS_PER_CONVERSION"

echo "Node ${SLURM_NODEID}: ${NODE_WORK} file(s), ${PHYSICAL_CORES}" \
     "physical core(s), ${JOBS_ON_NODE} concurrent conversion(s)."

parallel \
    --colsep "	" \
    --jobs "$JOBS_ON_NODE" \
    --line-buffer \
    --joblog "$JOBLOG" \
    "$PAYLOAD_SCRIPT" {1} {2} :::: "$NODE_MANIFEST"
PCDF_DRIVER
chmod +x "$DRIVER_SCRIPT"

TOTAL_WORK=$(awk 'NF {count += 1} END {print count + 0}' "$INPUT_MANIFEST")
export PYTHON_SCRIPT INPUT_MANIFEST OUTPUT_BASE
export PAYLOAD_SCRIPT CPUS_PER_CONVERSION
export -f physical_cores_on_node

CPUS_PER_CONVERSION="$CONVERTER_CPUS_PER_CONVERSION"

if (( TOTAL_WORK == 0 )); then
    echo "ERROR: input manifest contains no work." >&2
    exit 2
fi

MAX_CONCURRENT=$((SLURM_NNODES * PERLMUTTER_PHYSICAL_CORES / CPUS_PER_CONVERSION))
if (( MAX_CONCURRENT > TOTAL_WORK )); then
    MAX_CONCURRENT="$TOTAL_WORK"
fi

echo "Running on ${SLURM_NNODES} exclusive CPU node(s)"
echo "Node list:      ${SLURM_JOB_NODELIST:-unknown}"
echo "Input manifest: $INPUT_MANIFEST"
echo "Work items:     $TOTAL_WORK input file(s)"
echo "Open Data:      ${OPEN_DATA_RELEASE}/${OPEN_DATA_DATASET}"
echo "Output base:    $OUTPUT_BASE"
echo "CPU model:      ${PERLMUTTER_PHYSICAL_CORES} physical core(s) /" \
     "${PERLMUTTER_LOGICAL_CPUS} logical CPU(s) per Perlmutter CPU node"
echo "Parallelism:    up to ${MAX_CONCURRENT} concurrent conversion(s)," \
     "${CPUS_PER_CONVERSION} physical core(s) each"

srun \
    --no-kill \
    --ntasks="${SLURM_NNODES}" \
    --ntasks-per-node=1 \
    --cpus-per-task="${SLURM_CPUS_PER_TASK}" \
    --cpu-bind=cores \
    --wait=0 \
    "$DRIVER_SCRIPT"
