PCDF ntuple bundle
===================

Generated files
---------------
- {{PYTHON_NAME}} is the executable converter.
{{SLURM_FILE_LINE}}- README_SUBMIT.md contains these instructions.

Local run
---------
./{{PYTHON_NAME}} DAOD_{{INPUT_FORMAT}}.37620644._000244.pool.root -o parquet-output

Output layout
-------------
All input files share one output directory. For a standard ATLAS filename,
each table is written to:

`<table>/tid=<tid>/fileNumber=<fileNumber>/data.parquet`

Here, `tid` is the ATLAS production task ID. The converter removes leading
zeros from `fileNumber`, so Parquet tools read it as an integer. Generated
indices include the file number. This keeps them unique within each `tid`.

Event rows include `lumiBlock`. When the wizard is set to collision data, the
converter omits simulation-only truth and flavor labels.

If the filename has no ATLAS task ID and file number, the converter uses the
ROOT UUID stored in the file. A UUID is a 128-bit file ID. The output path is:

`<table>/fileUUIDHigh=<int64>/fileUUIDLow=<int64>/data.parquet`

The two numbers are the high and low halves of the UUID. Together, they keep
all 128 bits, so the output does not need a text UUID column. Each half is a
signed 64-bit integer because more Parquet tools support signed integers. A
negative value still keeps the original bits. It is the two's-complement form
of the same 64-bit value.

Indices in UUID folders are local to the file. Use both UUID fields when you
join tables. Renaming or copying the same ROOT file does not change its output
folder.
{{SLURM_SECTION}}
