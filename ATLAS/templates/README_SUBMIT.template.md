PCDF ntuple bundle
===================

Files
-----
- {{PYTHON_NAME}}: executable generated converter.
{{TRANSFER_FILE_LINE}}{{SLURM_FILE_LINE}}- README_SUBMIT.md: these instructions.

Local run
---------
./{{PYTHON_NAME}} DAOD_PHYSLITE.37620644._000244.pool.root -o parquet-output

The output root is shared across input files. Each table is written below
`<table>/dsid=<dsid>/fileNumber=<fileNumber>/data.parquet`, with partition
values derived from the DAOD filename.
{{SLURM_SECTION}}
