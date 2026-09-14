PCDF ntuple bundle
===================

Files
-----
- {{PYTHON_NAME}}: executable generated converter.
{{SLURM_FILE_LINE}}- README_SUBMIT.md: these instructions.

Local run
---------
./{{PYTHON_NAME}} DAOD_{{INPUT_FORMAT}}.37620644._000244.pool.root -o parquet-output

The output root is shared across input files. Each table is written below
`<table>/tid=<tid>/fileNumber=<fileNumber>/data.parquet`, with partition
values derived from the DAOD filename. Leading zeros are stripped from `fileNumber`, and the generated indices reserve their leading 16 bits for the file number so they are global within each `tid`. Event rows include `lumiBlock`; MC-only truth/flavor labels are omitted when the wizard is set to collision data.
If an input filename does not contain an ATLAS task ID and file number, the
converter uses the file's actual ROOT UUID instead, writing
`<table>/fileUUIDHigh=<int64>/fileUUIDLow=<int64>/data.parquet`. These two
numeric values are the lossless high and low halves of the 128-bit UUID.
Indices in these partitions are local to the file and are joined together with
both UUID fields; no task or file numbers are invented. Renaming or copying the
same physical ROOT file does not change its output partition.
{{SLURM_SECTION}}
