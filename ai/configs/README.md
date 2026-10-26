# AI configuration

Store small, reviewed configuration files here. Keep dataset paths and credentials in local environment variables or ignored files.

`PKLOT_DATASET_ROOT` is the local path read by `ai/scripts/inspect_dataset.py` and the preparation pipeline. Its default is `ai/data/raw/PKLot/`. Set it in the current PowerShell process with `$env:PKLOT_DATASET_ROOT = '<your actual extracted PKLot directory>'` if the dataset is elsewhere. The inspector does not load the root `.env` file. Do not put a machine-specific dataset path in tracked configuration.
