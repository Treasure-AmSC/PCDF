ATLAS PCDF Maker
================

This directory contains the definition of a TREASURE definition, consiting of PHYSLITE + additional components (from FTAG1LITE), along with the Python script required to turn this derivation format into a set of Parquet files.

Other formats such as HDF5 can later be produced from the Parquet dataset.

Interactive ntuple wizard
-------------------------

Serve the repository over HTTP and open `ATLAS/ntuple-wizard.html`, for example with `python -m http.server 8000` from the repository root and then `http://127.0.0.1:8000/ATLAS/ntuple-wizard.html`. Deploy `ntuple-wizard.html`, `ntuple-wizard.css`, `ntuple-wizard.js`, and `opendata-2024r-pp-fallback.json` together as static files. The wizard embeds its script-generation templates in the HTML page, configures which ATLAS TREASURE/PHYSLITE objects and variables should be written to Parquet, and generates a standalone Python script based on `ntuple-maker.py`. Selecting PHYSLITE input automatically disables jet constituents because the charged and neutral PFO constituent containers are not available in PHYSLITE.

Dedicated Open Data and SLURM wizard pages help prepare Perlmutter runs: the Open Data page searches datasets with AJAX and estimates transfer size/time, while the SLURM page configures the CPU-only Perlmutter wrapper plus an executable `download-atlas-opendata.sh` helper. The wizard searches ATLAS Open Data research PHYSLITE datasets from the `2024r-pp` release via the atlasopenmagic REST API (`https://atlasopenmagic-api.app.cern.ch`). If browser CORS or local network policy blocks the live preview, the UI falls back to the bundled `opendata-2024r-pp-fallback.json` starter index so the search interface remains usable; the generated DTN transfer script still performs the authoritative live API lookup before downloading. Download the tar bundle, copy it to Perlmutter, run the Open Data download helper on a Perlmutter data transfer node to populate `$SCRATCH` and write the input manifest, then submit `submit-pcdf-ntuple.slurm` from a login node. The SLURM wrapper refuses to build manifests or download data on compute nodes; it only consumes the manifest created before the job starts. The wrapper defaults to one CPU node, prepares the `uv` environment once before launching parallel conversions, and uses GNU parallel inside the job without creating a large SLURM job array. Conversions per node controls parallelism; CPUs per conversion are derived from Perlmutter CPU nodes (128 CPU cores per node), rather than entered independently.

