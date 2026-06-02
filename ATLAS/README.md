ATLAS PCDF Maker
================

This directory contains the definition of a TREASURE definition, consiting of PHYSLITE + additional components (from FTAG1LITE), along with the Python script required to turn this derivation format into a set of Parquet files.

Other formats such as HDF5 can later be produced from the Parquet dataset.

Interactive ntuple wizard
-------------------------

Open `ntuple-wizard.html` directly in a browser, including from `file://`, or deploy `ntuple-wizard.html`, `ntuple-wizard.css`, and `ntuple-wizard.js` together as static files. The wizard embeds its script-generation templates in the HTML page, configures which ATLAS TREASURE/PHYSLITE objects and variables should be written to Parquet, and generates a standalone Python script based on `ntuple-maker.py`. Selecting PHYSLITE input automatically disables jet constituents because the charged and neutral PFO constituent containers are not available in PHYSLITE.

The final wizard step can also generate a CPU-only SLURM wrapper targeted at NERSC Perlmutter plus an executable `download-atlas-opendata.sh` helper. The wizard can search ATLAS Open Data research PHYSLITE datasets from the `2024r-pp` release via the REST API (`https://atlasopenmagic-rest-api-atlas-open-data.app.cern.ch`), retry browser-only preview requests through a built-in CORS proxy fallback if the API blocks direct static-page fetches, preview the selected dataset/skim, sample file sizes, and estimate the scratch download size and time from the configured DTN throughput. Download the tar bundle, copy it to Perlmutter, run the Open Data download helper on a Perlmutter data transfer node to populate `$SCRATCH` and write the input manifest, then submit `submit-pcdf-ntuple.slurm` from a login node. The SLURM wrapper refuses to build manifests or download data on compute nodes; it only consumes the manifest created before the job starts. The wrapper defaults to one CPU node, prepares the `uv` environment once before launching parallel conversions, and uses GNU parallel inside the job without creating a large SLURM job array. Conversions per node controls parallelism; CPUs per conversion are derived from Perlmutter CPU nodes (128 CPU cores per node), rather than entered independently.

