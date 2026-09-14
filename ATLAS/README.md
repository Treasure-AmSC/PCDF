ATLAS PCDF Maker
================

This directory contains the Python converter and interactive generators used to turn JETM16 or PHYSLITE DAOD files into a set of Parquet files. The historical TREASURE derivation definition remains under `Derivation/` for reference.

Other formats such as HDF5 can later be produced from the Parquet dataset.

Interactive ntuple wizard
-------------------------

Serve the browser wizard locally with `python ATLAS/serve-ntuple-wizard.py`, which listens only on `127.0.0.1` and opens `http://127.0.0.1:8000/`. For generic static hosting, deploy `ntuple-wizard.html`, `ntuple-wizard.css`, `ntuple-wizard.js`, `ntuple-wizard.objects.json`, and the `templates/` files together. The generated-script templates are split into separate files for review, while the local server combines them into the HTML it serves. The wizard configures which ATLAS JETM16/PHYSLITE objects and variables should be written to Parquet, and generates a standalone Python script based on `ntuple-maker.py`. Selecting PHYSLITE input automatically disables jet constituents because the charged and neutral PFO constituent containers are not available in PHYSLITE.

A terminal version is available with `uv run ATLAS/ntuple-wizard-tui.py` or, after checkout, directly as `ATLAS/ntuple-wizard-tui.py`. It uses Python Textual to provide a browser-like step-by-step wizard for keyboard-friendly selection of input format, sample type, output objects, variables, SLURM settings, and generation targets without needing a browser. Object and variable choices use native Textual switches, queue/QOS is selected from a dropdown, and Perlmutter account selection is populated directly from `iris` when Perlmutter is detected; outside Perlmutter the account field falls back to a text input. When it detects a Perlmutter login environment via `$NERSC_HOST`, the hostname, or NERSC `nid` hostnames, it enables the end-to-end workflow: pick scan directories from an interactive directory tree, discover matching ROOT files, choose which discovered files go into the manifest, write the input manifest atomically, generate the converter and SLURM wrapper, and submit the generated job with `sbatch` from the same interface. Outside Perlmutter, the same TUI still generates the Python converter, SLURM script, and tar bundle, but intentionally leaves submission disabled. When `--output-dir` is not provided, the TUI creates its generated files, default input manifest, and SLURM logs in a temporary directory under `$SCRATCH` when available so submitted jobs can see the files from compute nodes; otherwise it falls back to a temporary directory under the current working directory.

Dedicated SLURM wizard settings help prepare Perlmutter runs: the SLURM page and TUI configure the CPU-only wrapper. In the browser workflow, input data staging is intentionally left to the user. In the TUI workflow on Perlmutter, the wizard can create the manifest interactively before submitting. Download the tar bundle, copy it to Perlmutter when needed, create the input manifest on scratch before submitting, then submit `submit-pcdf-ntuple.slurm` from a login node. The SLURM wrapper refuses to download data on compute nodes; it only consumes the manifest created before the job starts. The wrapper defaults to one exclusive CPU node and a 30 minute wall time, prepares the `uv` environment once before launching parallel conversions, and uses GNU parallel inside the job without creating a large SLURM job array. The wrapper discovers physical cores at runtime, counts the manifest work items, partitions work across allocated nodes, and fills the available cores with one conversion per core. The wizard can be set to collision data to omit MC-only truth/flavor labels while preserving `lumiBlock` in the Event table. Each input file writes into one shared output dataset root using Hive-style partitions. Standard ATLAS filenames such as `DAOD_JETM16.37620644._000244.pool.root.1` produce `tid=.../fileNumber=...` partitions and reserve the leading 16 index bits for the genuine file number. Files without those identifiers instead split the stored 128-bit ROOT UUID losslessly into numeric `fileUUIDHigh=.../fileUUIDLow=...` partitions; their indices are file-local and are identified together with both UUID fields. No synthetic task or file numbers are introduced. Generated run helper scripts are kept under `$SCRATCH/pcdf-generated/<jobid>` and removed at job exit unless `PCDF_KEEP_RUN_DIR=1` is set.

SPIN deployment
---------------

Build from the repository root and push the image to the NERSC registry. Replace
the project and tag placeholders with values for the target deployment:

```sh
docker login registry.nersc.gov
docker build --pull -f ATLAS/Dockerfile -t registry.nersc.gov/<project>/beojan/pcdf-atlas-wizard:<tag> .
docker push registry.nersc.gov/<project>/beojan/pcdf-atlas-wizard:<tag>
```

In the [SPIN Rancher interface](https://rancher2.spin.nersc.gov/), create a
Deployment in the intended project and namespace with these settings:

- Image: `registry.nersc.gov/<project>/beojan/pcdf-atlas-wizard:<tag>`
- Container name: leave the default `container-0`
- ClusterIP service port: `8080` over TCP
- Security context: drop the `ALL` capability and add none
- Health check: HTTP `GET /healthz` on port `8080`

The image runs as the unprivileged numeric user and group `65532`, writes no
persistent state, and needs no mounted storage. Create an nginx Ingress with
path type `Prefix`, path `/`, and the workload's port-8080 ClusterIP service as
the target. NERSC documents the current Rancher steps in
[Running Your App in Spin](https://docs.nersc.gov/services/spin/running/) and
[Connecting to a Spin App](https://docs.nersc.gov/services/spin/connecting/).
