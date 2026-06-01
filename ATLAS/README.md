ATLAS PCDF Maker
================

This directory contains the definition of a TREASURE definition, consiting of PHYSLITE + additional components (from FTAG1LITE), along with the Python script required to turn this derivation format into a set of Parquet files.

Other formats such as HDF5 can later be produced from the Parquet dataset.

Interactive ntuple wizard
-------------------------

Open `ntuple-wizard.html` in a browser, or deploy it as a static web page, to configure which ATLAS TREASURE/PHYSLITE objects and variables should be written to Parquet. The wizard generates a standalone Python script based on `ntuple-maker.py`; selecting PHYSLITE input automatically disables jet constituents because the charged and neutral PFO constituent containers are not available in PHYSLITE.

The final wizard step can also generate a CPU-only SLURM wrapper targeted at NERSC Perlmutter. Download both the Python script and `submit-pcdf-ntuple.slurm`, copy them to Perlmutter, create a manifest with one input DAOD path per line or provide the Rucio dataset DID plus local RSE from your Rucio rule, edit the NERSC project account plus manifest/Rucio/output settings, and submit with `sbatch submit-pcdf-ntuple.slurm` from a Perlmutter login node. The tar bundle marks the generated Python and SLURM scripts executable. The wrapper defaults to one CPU node, prepares the `uv` environment once before launching parallel conversions, and uses GNU parallel inside the job without creating a large SLURM job array. Conversions per node controls parallelism; CPUs per conversion are derived from Perlmutter CPU nodes (128 CPU cores per node), rather than entered independently.

