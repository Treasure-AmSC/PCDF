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
#SBATCH --output={{LOG_OUT}}
#SBATCH --error={{LOG_ERR}}

# NERSC Perlmutter wrapper from ATLAS/ntuple-wizard.html.
# CPU-only: the generated converter does not use GPUs.
# Data must already be on scratch; do not download on compute nodes.

set -euo pipefail

module load python

PYTHON_SCRIPT={{PYTHON_PATH}}
INPUT_MANIFEST={{INPUT_MANIFEST}}
OUTPUT_BASE={{OUTPUT_BASE}}
CONVERTER_CPUS_PER_CONVERSION={{CONVERTER_CPUS_PER_CONVERSION}}
PERLMUTTER_PHYSICAL_CORES={{PERLMUTTER_PHYSICAL_CORES}}
PERLMUTTER_LOGICAL_CPUS={{PERLMUTTER_LOGICAL_CPUS_PER_NODE}}
RUN_DIR="${SCRATCH:-$HOME}/pcdf-generated/${SLURM_JOB_ID}"

needs_edit=0
[[ "$PYTHON_SCRIPT" == *"<"* ]] && needs_edit=1
[[ "$INPUT_MANIFEST" == *"<"* ]] && needs_edit=1
[[ "$OUTPUT_BASE" == *"<"* ]] && needs_edit=1
if (( needs_edit )); then
    echo "{{@shell.slurm-needs-edit}}" >&2
    exit 2
fi

if [[ -n "${PCDF_ALLOW_COMPUTE_DOWNLOAD:-}" ]]; then
    echo "{{@shell.slurm-download-ignored}}" >&2
fi

mkdir -p "$OUTPUT_BASE" "$RUN_DIR"
cleanup_run_dir() {
    if [[ -z "${PCDF_KEEP_RUN_DIR:-}" && -d "$RUN_DIR" ]]; then
        rm -rf "$RUN_DIR"
    else
        echo "{{@shell.slurm-keeping-helpers}}"
    fi
}
trap cleanup_run_dir EXIT

if [[ ! -s "$INPUT_MANIFEST" ]]; then
    echo "{{@shell.slurm-no-manifest}}" >&2
    echo "{{@shell.slurm-create-manifest}}" >&2
    exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "{{@shell.slurm-no-uv}}" >&2
    exit 2
fi

if ! command -v parallel >/dev/null 2>&1; then
    echo "{{@shell.slurm-no-parallel}}" >&2
    exit 2
fi

if (( CONVERTER_CPUS_PER_CONVERSION < 1 )); then
    echo "{{@shell.slurm-bad-cpus}}" >&2
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
echo "{{@common.preparing-environment}}"
uv run "$PYTHON_SCRIPT" --help >/dev/null

PAYLOAD_SCRIPT="$RUN_DIR/convert-${SLURM_JOB_ID}.sh"
cat > "$PAYLOAD_SCRIPT" <<'PCDF_PAYLOAD'
#!/bin/bash
set -euo pipefail

TASK_ID="$1"
INPUT_FILE="$2"

export OMP_NUM_THREADS="$CPUS_PER_CONVERSION"
export NUMBA_NUM_THREADS="$CPUS_PER_CONVERSION"
export OPENBLAS_NUM_THREADS="$CPUS_PER_CONVERSION"
export MKL_NUM_THREADS="$CPUS_PER_CONVERSION"
export NUMEXPR_NUM_THREADS="$CPUS_PER_CONVERSION"
export VECLIB_MAXIMUM_THREADS="$CPUS_PER_CONVERSION"
echo "{{@shell.slurm-task}}"
uv run --no-sync \
    "$PYTHON_SCRIPT" \
    "$INPUT_FILE" \
    -o "$OUTPUT_BASE"
PCDF_PAYLOAD
chmod +x "$PAYLOAD_SCRIPT"

DRIVER_SCRIPT="$RUN_DIR/driver-${SLURM_JOB_ID}.sh"
cat > "$DRIVER_SCRIPT" <<'PCDF_DRIVER'
#!/bin/bash
set -euo pipefail

JOBLOG="$RUN_DIR/p-${SLURM_JOB_ID}.${SLURM_NODEID}.log"
NODE_MANIFEST="$RUN_DIR/node-${SLURM_JOB_ID}.${SLURM_NODEID}.manifest"

awk \
    -v N="$SLURM_NODEID" \
    -v T="$SLURM_NNODES" \
    'NF && ((NR - 1) % T == N) {print NR "	" $0}' \
    "$INPUT_MANIFEST" > "$NODE_MANIFEST"

NODE_WORK=$(wc -l < "$NODE_MANIFEST")
if (( NODE_WORK == 0 )); then
    echo "{{@shell.slurm-no-node-work}}"
    exit 0
fi

PHYSICAL_CORES=$(physical_cores_on_node)
if (( PHYSICAL_CORES < 1 )); then
    echo "{{@shell.slurm-no-cores}}" >&2
    exit 2
fi

JOBS_ON_NODE=$((PHYSICAL_CORES / CPUS_PER_CONVERSION))
if (( JOBS_ON_NODE < 1 )); then
    echo "{{@shell.slurm-too-many-cpus}}" >&2
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

echo "{{@shell.slurm-node-summary}}"

parallel \
    --colsep "	" \
    --jobs "$JOBS_ON_NODE" \
    --line-buffer \
    --joblog "$JOBLOG" \
    "$PAYLOAD_SCRIPT" {1} {2} :::: "$NODE_MANIFEST"
PCDF_DRIVER
chmod +x "$DRIVER_SCRIPT"

TOTAL_WORK=$(awk 'NF {count += 1} END {print count + 0}' "$INPUT_MANIFEST")
CPUS_PER_CONVERSION="$CONVERTER_CPUS_PER_CONVERSION"
export PYTHON_SCRIPT INPUT_MANIFEST OUTPUT_BASE RUN_DIR
export PAYLOAD_SCRIPT CPUS_PER_CONVERSION
export PERLMUTTER_PHYSICAL_CORES
export -f physical_cores_on_node

if (( TOTAL_WORK == 0 )); then
    echo "{{@shell.slurm-empty-manifest}}" >&2
    exit 2
fi

MAX_CONCURRENT=$((SLURM_NNODES * PERLMUTTER_PHYSICAL_CORES / CPUS_PER_CONVERSION))
if (( MAX_CONCURRENT > TOTAL_WORK )); then
    MAX_CONCURRENT="$TOTAL_WORK"
fi

echo "{{@shell.slurm-nodes}}"
echo "{{@shell.slurm-node-list}}"
echo "{{@shell.slurm-manifest}}"
echo "{{@shell.slurm-files}}"
echo "{{@shell.slurm-output}}"
echo "{{@shell.slurm-helpers}}"
echo "{{@shell.slurm-topology}}"
echo "{{@shell.slurm-concurrency}}"

srun \
    --no-kill \
    --ntasks="${SLURM_NNODES}" \
    --ntasks-per-node=1 \
    --cpus-per-task="${SLURM_CPUS_PER_TASK}" \
    --cpu-bind=cores \
    --wait=0 \
    "$DRIVER_SCRIPT"
