# PKLot dataset exploration

This is an **offline ground-truth audit**, not model training or operational inference. It reads local images and annotations without editing or copying them. Reports and overlays belong under ignored `ai/data/audit/`; raw data and outputs must never be committed.

## Source and license

PKLot is published by the [UFPR Vision, Robotics and Imaging laboratory](https://web.inf.ufpr.br/vri/databases/parking-lot-database/). The official page identifies the license as [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/) and asks researchers to acknowledge the source by citing Almeida, Oliveira, Silva Jr., Britto Jr., and Koerich, “PKLot – A robust dataset for parking lot classification,” *Expert Systems with Applications* 42(11), 4937–4949 (2015). Check the official page and the terms accompanying your downloaded copy before redistributing images or derivatives. This repository does not redistribute the dataset.

The local archive `PKLot.tar.gz` is available in this workspace. The configured extracted location is `ai/data/raw/PKLot/`, set through `PKLOT_DATASET_ROOT` or `--root`. The inspector does not download or extract the archive. The archive's full-frame images and XML follow paths like `PKLot/PKLot/UFPR04/Rainy/2012-12-21/<timestamp>.jpg` and `.xml`; it also contains a separate `PKLotSegmented` crop collection. The scanner discovers XML recursively and does not depend on that exact nesting. It excludes a directory named `PKLotSegmented` from the extracted full-frame scan so crops are not mistaken for missing annotations.

## Supported format and validation

The parser supports the original PKLot full-frame XML: `<parking id="camera">` with `<space id="..." occupied="0|1">` children and each space's `<contour><point x="integer" y="integer"/>...</contour>`. `0` means **empty** and `1` means **occupied**. An optional `<rotatedRect>` is accepted but its geometry is not used; contour points supply polygons. Camera ID comes from XML and is checked against a recognized camera component (`UFPR04`, `UFPR05`, `PUCPR`) when one appears in the path. Capture day is a valid `YYYY-MM-DD` found anywhere in the relative path or filename. Missing/conflicting day information is an error.

The audit pairs image and XML by case-insensitive stem in the same directory, decodes JPEG/PNG bytes, records dimensions, and rejects missing counterparts, corrupt images, invalid labels, duplicate spot IDs, malformed XML, zero-area/duplicate/crossing polygons, and coordinates outside the image. Invalid samples appear in `errors.csv` and `stats.json`; they are **excluded** from class/camera/day/dimension counts. No invalid annotation is silently counted as valid. XML formats such as COCO, Pascal VOC, and YOLO text are unsupported; an unsupported XML root is reported as an error. The archive mode audits a bounded sample and does not claim to detect all missing files in the archive.

## PowerShell setup and commands

From the repository root, install the lightweight audit dependency into the existing AI virtual environment:

```powershell
cd ai
.\.venv\Scripts\python.exe -m pip install -e '.[audit,dev]'
```

Audit all extracted full-frame annotations (including orphan images outside XML-bearing folders). The default root is `ai/data/raw/PKLot/`:

```powershell
.\.venv\Scripts\python.exe .\scripts\inspect_dataset.py --root .\data\raw\PKLot --output-dir .\data\audit\pklot
```

For a different local layout, pass its actual root through `--root` or set `$env:PKLOT_DATASET_ROOT` in the same PowerShell session. A directory audit defaults to **all** XML files; `--max-samples 100` makes an explicitly partial audit. If only the local archive is available, return to the repository root and sample it without extraction:

```powershell
cd ..
.\ai\.venv\Scripts\python.exe .\ai\scripts\inspect_dataset.py --archive .\PKLot.tar.gz --max-samples 3 --output-dir .\ai\data\audit\pklot-archive
```

Archive mode always requires a positive sample limit; its default is 3. Both modes draw up to three annotated PNGs by default; change with `--overlays N`. Exit code 0 means no detected validation errors in the scanned scope, 1 means the saved report contains errors, and 2 means the audit could not run (for example, missing source or no XML). Original images/XML are read only.

## Outputs and interpretation

| File | Contents |
| --- | --- |
| `stats.json` | Source, `complete`/`sample` scope, scanned XML/image counts, valid pair count, empty/occupied polygon counts, per-camera/day/dimension frame counts, overlay paths, and every validation error. |
| `samples.csv` | One row per valid image/XML pair with camera, capture day, dimensions, and empty/occupied counts. |
| `errors.csv` | One row per detected issue with stable code, relative source, and message; header-only when none were found. |
| `overlays/001.png`, etc. | Original image rendered to a new PNG with **ground-truth** contours: red occupied, green empty. These are audit artifacts, never inference predictions. |

On 2026-10-25, a **three-pair sample** read directly from the local archive had 208 empty and 20 occupied polygons, cameras `UFPR04` and `PUCPR`, three capture days, `1280x720` images, and zero errors *within those three pairs*. See the locally generated `ai/data/audit/task04/stats.json` and overlays. These numbers are not full-dataset statistics or model metrics. The full extracted dataset has not been audited here.

Keep future train/validation/test partitions separate by capture day and camera as required by an approved experiment protocol; do not let near-duplicate frames or crops from one frame cross splits. No split or training is performed by this tool.
