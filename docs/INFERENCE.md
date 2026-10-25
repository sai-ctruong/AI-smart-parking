# Parking occupancy inference (TASK-07)

The reusable inference module loads a TASK-06 MobileNetV3-Small checkpoint once per predictor instance. It uses the checkpoint's input size and normalization metadata, then applies the same masked polygon crop and deterministic test transform used by training. The model has two supervised classes: `empty` and `occupied`. `unknown` is a decision made after inference or input validation, not a third class.

Install dependencies from `ai/` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[train,dev]'
```

Set `PARKING_MODEL_CHECKPOINT` to a real evaluated checkpoint for actual use. The ignored `ai/runs/task06-smoke/best.pt`, if present, is trained on synthetic data and is suitable **only** for a pipeline smoke check. It does not establish parking-classifier performance.

```powershell
$env:PARKING_MODEL_CHECKPOINT = (Resolve-Path .\runs\pklot\best.pt).Path
$env:PARKING_CONFIDENCE_THRESHOLD = '0.7'
$env:PARKING_INFERENCE_DEVICE = 'auto' # or cpu / cuda
$env:PARKING_INFERENCE_BATCH_SIZE = '32'
```

From `ai/`, use the module-level function with the configured checkpoint:

```python
from PIL import Image
from inference.predictor import predict_spots

with Image.open("snapshot.jpg") as image:
    results = predict_spots(
        image,
        [
            {"spot_id": "A1", "polygon": [[0.10, 0.20], [0.30, 0.20], [0.30, 0.50], [0.10, 0.50]]},
            {"spot_id": "A2", "polygon": [[0.35, 0.20], [0.55, 0.20], [0.55, 0.50], [0.35, 0.50]]},
        ],
    )
    for result in results:
        print(result.to_dict())
```

For repeated calls with explicit configuration, keep one instance alive:

```python
from inference.predictor import ParkingOccupancyPredictor

predictor = ParkingOccupancyPredictor(
    "runs/pklot/best.pt", confidence_threshold=0.7, batch_size=32, device="auto"
)
results = predictor.predict_spots(image, polygons)
```

The input polygon coordinates are normalized to `[0,1]` and ordered around each ROI. `spot_id` is a nonempty, unique string within a call. Outputs retain input order. Invalid polygons return `unknown`, with null confidence/probabilities and `uncertainty_reason="invalid_polygon"`; malformed images, duplicate IDs, missing/incompatible checkpoints, and unsupported devices raise clear exceptions. No XML, annotations, manifests, or ground-truth labels are read during inference.

`confidence` is the larger **uncalibrated softmax** probability. `class_probabilities` always has only `empty` and `occupied` for valid model outputs. When `confidence` is below the configured threshold, status becomes `unknown` with `uncertainty_reason="low_confidence"`, while the original binary probabilities remain available. `calibrated_confidence` is always null until a separate calibration procedure is implemented and evaluated. `model_version` is the full SHA-256 digest of the checkpoint file, prefixed with `sha256:`; it identifies bytes, not training quality. The metadata and device are available as predictor properties. Changing the checkpoint file at the same path requires a new predictor instance or process restart for the module-level cache.

Run the isolated tests from `ai/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_inference.py -q
```
