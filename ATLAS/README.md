ATLAS PCDF Maker
================

This directory holds the tools that convert ATLAS DAOD files (JETMOD1 or PHYSLITE) into Parquet files, with one Parquet table for each selected object. JETMOD1 is the name of the format that earlier versions of these tools called JETM16. A browser wizard and a terminal wizard generate the converter and the scripts that run it. Other formats such as HDF5 can later be produced from the Parquet dataset. The historical TREASURE derivation definition remains under `ATLAS/Derivation/` for reference.

Paths that start with `ATLAS/` are relative to the repository root. Paths such as `code/make-manifest.py` are inside a generated bundle.

These programs run through [uv](https://docs.astral.sh/uv/), a Python script runner: the local server for the browser wizard, the terminal wizard, `ATLAS/build_site.py`, and every script in a generated bundle. Install `uv` on each machine that runs one of them, including HTCondor execute nodes.

What the wizards produce
------------------------

Both wizards produce the same tar bundle. You choose the input format, the sample type (simulation or collision data), the output objects and their variables, and the batch system. The bundle then contains:

- `code/ntuple-maker-<format>.py`, a standalone Python converter filled in from `ATLAS/templates/ntuple-maker.template.py`
- `code/make-manifest.py`, which creates the list of input files
- `run-pcdf.sh`, which creates that list, submits the job, and follows it to completion
- a SLURM or HTCondor submit file, chosen in the wizard
- `README_SUBMIT.md`, which describes the bundle

`run-pcdf.sh` and the submit file are included only when batch file generation is on.

Two input rules shape the output. PHYSLITE input turns off jet constituents, because the charged and neutral PFO constituent containers are not available in PHYSLITE. Collision data omits the simulation-only truth and flavor labels and keeps `lumiBlock` in the Event table.

The hand-written `ATLAS/ntuple-maker.py` is legacy and kept for reference only.

Browser wizard
--------------

Start the wizard locally with `uv run ATLAS/serve-ntuple-wizard.py`. It listens only on `127.0.0.1` and opens `http://127.0.0.1:8000/`.

To host the wizard elsewhere, run `uv run ATLAS/build_site.py <directory>` and upload that directory to any static web host. The page source, `ATLAS/ntuple-wizard.html.j2`, is a Jinja template, so the file in the repository cannot be uploaded as is. `build_site.py` combines the template, the wording in `ATLAS/wizard-text.txt`, the object definitions in `ATLAS/ntuple-wizard.objects.json`, and the generator templates in `ATLAS/templates/` into one page. After that page loads, the browser makes no further requests.

All the text that the wizards, the generated scripts, and the bundle README show is kept once in `ATLAS/wizard-text.txt`.

Terminal wizard
---------------

Run the terminal wizard with `uv run ATLAS/ntuple-wizard-tui.py`, or directly as `ATLAS/ntuple-wizard-tui.py` after checkout. It uses the Python library Textual to offer the same step-by-step choices without a browser. Objects and variables are native Textual switches, and the queue (QOS) is a dropdown. On Perlmutter, the account list comes from `iris`, the NERSC account command. Elsewhere the account is a text field.

The wizard writes the input manifest atomically, generates the converter and the batch file, and can submit the job from the same interface. SLURM jobs are submitted with `sbatch`, which is available only on Perlmutter. HTCondor jobs are submitted with `condor_submit` wherever that command is on the PATH. When submission is not available, the wizard still generates the converter, the batch file, and the tar bundle.

By default the wizard writes `pcdf-ntuple/` and its archive in the current directory. Use `--output-dir` to choose another parent directory. On Perlmutter, choose one that the compute nodes can see, such as a directory under `$SCRATCH`, because the job reads the bundle from there.

Create the input manifest
-------------------------

`code/make-manifest.py` writes the input manifest, a text file with one input file path on each line. It can scan a directory populated by `rucio download`, or it can look up a `scope:name` dataset at `NERSC_LOCALGROUPDISK`, a Rucio storage element, through the Rucio client. For each replica, it removes the scheme, host, and port from the replica PFN and keeps the local path.

The helper uses the first Rucio configuration file that exists. It checks, in order, the file named by `$RUCIO_CONFIG`, `$RUCIO_HOME/etc/rucio.cfg`, `~/.rucio/etc/rucio.cfg`, `/opt/rucio/etc/rucio.cfg`, and the copy in an ATLASLocalRootBase installation, the ATLAS software setup on CVMFS.

For a SLURM bundle, the helper can also download a Rucio dataset into `$SCRATCH` before submission. To do that, it creates a private ATLAS VOMS proxy file under `~/.cache/pcdf/credentials` that both the login node and a NERSC data transfer node can read, then downloads the dataset on that node. The batch job itself never downloads data and does not need Rucio.

Run a generated bundle
----------------------

Copy the bundle to the cluster, extract it, and run `./run-pcdf.sh` from the bundle directory. The script creates the input manifest interactively, asks before submitting, and follows the job to completion. Each bundle holds either a SLURM or an HTCondor submit file, and `run-pcdf.sh` uses whichever it finds. An HTCondor bundle can also run its conversions on a single machine with `./run-pcdf.sh --local`. That mode needs `uv` on the machine and does not need HTCondor.

To run the steps yourself, run `code/make-manifest.py`, then run `sbatch code/submit-pcdf-ntuple.slurm` from a login node.

The SLURM job script reads the manifest that you created before the job started and refuses to download data on compute nodes. By default it uses one exclusive CPU node for 30 minutes. It prepares the `uv` environment once, then uses GNU parallel inside the job, so it does not create a large SLURM job array. At run time it finds the physical cores, counts the manifest entries, divides the work across the allocated nodes, and fills the cores with one conversion per core. It keeps its generated helper scripts in `$SCRATCH/pcdf-generated/<jobid>` and removes them when the job ends, unless `PCDF_KEEP_RUN_DIR=1` is set.

Output layout
-------------

Each input file writes into one shared output dataset directory, using Hive-style partitions. The default directory is `./output`, inside the extracted bundle directory. If you enter another relative path in the "Output dataset directory" field on the batch job step, the bundle ships an empty directory with that name instead of `./output`.

Tables are linked by index columns. Each table has an `eventIndex` column. Every table except `MET`, which has one row per event, also has an index column of its own, such as `jetIndex`, and constituent and track rows also carry the `jetIndex` of their jet. Each index is a 64-bit unsigned integer. Its top 16 bits hold the file number, and its low 48 bits give the position of the row within its table in that file.

A standard ATLAS filename such as `DAOD_JETMOD1.37620644._000244.pool.root.1` produces `tid=.../fileNumber=...` partitions, and the file number in the index is the actual one. Indices are therefore unique within each `tid`.

A file without those identifiers is partitioned by its stored 128-bit ROOT UUID. The converter splits the UUID into two numeric halves without losing any bits and writes `fileUUIDHigh=.../fileUUIDLow=...` partitions. The file number in the index is 0, so indices in those partitions are unique only within the file, and you identify a file by both UUID fields. No synthetic task or file numbers are created.

SPIN deployment
---------------

Build from the repository root and push the image to the NERSC registry. The build renders the page in a first stage, so the running image needs only the Python standard library. Replace the project and tag placeholders with values for the target deployment:

```sh
docker login registry.nersc.gov
docker build --pull -f ATLAS/Dockerfile -t registry.nersc.gov/<project>/beojan/pcdf-atlas-wizard:<tag> .
docker push registry.nersc.gov/<project>/beojan/pcdf-atlas-wizard:<tag>
```

In the [SPIN Rancher interface](https://rancher2.spin.nersc.gov/), create a Deployment in the intended project and namespace with these settings:

- Image: `registry.nersc.gov/<project>/beojan/pcdf-atlas-wizard:<tag>`
- Container name: leave the default `container-0`
- ClusterIP service port: `8080` over TCP
- Security context: drop the `ALL` capability and add none
- Health check: HTTP `GET /healthz` on port `8080`

The image runs as the unprivileged numeric user and group `65532`, writes no persistent state, and needs no mounted storage. Create an nginx Ingress with path type `Prefix`, path `/`, and the workload's port-8080 ClusterIP service as the target. NERSC documents the current Rancher steps in [Running Your App in Spin](https://docs.nersc.gov/services/spin/running/) and [Connecting to a Spin App](https://docs.nersc.gov/services/spin/connecting/).

GitHub Pages deployment
-----------------------

The browser wizard can also be published as a static GitHub Pages site. The workflow in `.github/workflows/deploy-pages.yml` runs `build_site.py`, which renders the page and puts it, the stylesheet, the script, and the textures into the Pages artifact. It does not publish the Python server, and it does not run Rucio, SLURM, or data conversion. Those actions happen when a user runs a generated bundle on a cluster.

In the repository's GitHub Pages settings, select **GitHub Actions** as the publishing source. Pushes to `main` that change `ATLAS/` then deploy the site. SPIN remains available for the container-based deployment with `/healthz`.
