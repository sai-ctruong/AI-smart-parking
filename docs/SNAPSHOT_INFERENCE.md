# Snapshot upload and AI inference (TASK-11)

The implemented `POST /api/v1/snapshots/predict` accepts one JPEG/PNG snapshot for a configured camera. Admin and Operator can call it. The backend loads the camera's active, current polygon revisions, runs the standalone AI predictor when configured, persists the unchanged original bytes and one immutable prediction per active spot, and returns normalized polygon coordinates for a future overlay UI. No PKLot XML, ground-truth label, or human review is passed into the predictor.

## Install and start on Windows PowerShell

After setting up PostgreSQL, `DATABASE_URL` and `AUTH_SECRET_KEY` as described in the [root README](../README.md):

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pip install -e '../ai[train]'
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The second install makes the AI predictor, PyTorch and torchvision available **in the backend's Python environment**. Without a model checkpoint, the backend does not import PyTorch and produces explicit `unknown` results. If a configured checkpoint or AI runtime is unavailable, it also records `unknown` with `MODEL_UNAVAILABLE`. If inference raises an error, it records `unknown` with `INFERENCE_ERROR` for all captured spots. Neither case invents `empty` or `occupied` predictions.

Development stores original files under ignored `backend/data/snapshots` unless `IMAGE_STORAGE_ROOT` is set. Production requires an absolute private `IMAGE_STORAGE_ROOT` path. Keep it outside any public web root, back it up separately from PostgreSQL and never commit it. The database stores an opaque filename, SHA-256, MIME, byte size, dimensions, capture time, uploader, camera ID and measured decode/inference time. The original file is readable only through authenticated `GET /api/v1/snapshots/{snapshot_id}/image`, which verifies its stored hash. The temporary file is removed on a handled persistence failure. Once the file has been renamed to its final key, a database commit error can be ambiguous, so the file is retained to avoid a committed snapshot pointing at a deleted original. Orphan-file reconciliation and retention policy remain deployment work.

Set or adjust these values in the ignored root `.env` (production uses process environment only):

```dotenv
MAX_UPLOAD_BYTES=10485760
MAX_IMAGE_PIXELS=20000000
STALE_AFTER_SECONDS=300
PARKING_MODEL_CHECKPOINT=
PARKING_CONFIDENCE_THRESHOLD=0.7
PARKING_INFERENCE_BATCH_SIZE=32
PARKING_INFERENCE_DEVICE=auto
```

Set `PARKING_MODEL_CHECKPOINT` to the **absolute path of a trained and evaluated** TASK-06 checkpoint. The model is loaded once per process/configuration and reused. After replacing checkpoint bytes at the same path, restart the backend so its cache and model-version SHA-256 reflect the new artifact. A synthetic smoke checkpoint can check integration only; it is not evidence of PKLot classifier quality.

The API rejects files over `MAX_UPLOAD_BYTES` with 413, unsupported or mismatched MIME/content with 415, and corrupt or out-of-range image dimensions with 422. Both JPEG and PNG are decoded safely before storage; the original bytes are saved unchanged. The multipart request includes `camera_id`, `file`, and optional timezone-aware `captured_at` (UTC recommended). An omitted timestamp becomes server acquisition time; a future or timezone-naive value is rejected. The chosen camera must exist and be active, and its active spot polygons must match its current reference-image/viewpoint version. This API does not verify that a newly uploaded scene has the same physical viewpoint as the Admin-declared reference image; that remains an operational camera setup responsibility.

## Request example

Replace the paths and credentials with real local values. The camera must already be configured using [CONFIGURATION.md](CONFIGURATION.md).

```powershell
$base = 'http://127.0.0.1:8000/api/v1'
$login = Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType 'application/json' -Body (@{ username = 'operator'; password = (Read-Host 'Password') } | ConvertTo-Json)
$cameraId = '<configured-camera-uuid>'
$snapshotPath = 'C:\path\to\snapshot.jpg'
curl.exe -X POST "$base/snapshots/predict" -H "Authorization: Bearer $($login.access_token)" -F "camera_id=$cameraId" -F "file=@$snapshotPath;type=image/jpeg"
```

The response includes `snapshot_id`, `camera_id`, acquisition `timestamp`, `total_spots`, `empty_count`, `occupied_count`, `unknown_count`, `occupancy_percent`, `predictions`, `model_version`, `processing_time_ms`, `alert_state`, and an authenticated `image_url`. Each prediction includes stable spot/revision IDs, original AI status, confidence, model version, reason code and normalized polygon. `processing_time_ms` measures upload reading, validation, decoding and inference before database persistence; it is a runtime measurement, not a model benchmark.

`unknown` never counts as empty or confirmed available. Counts always satisfy `total_spots = empty_count + occupied_count + unknown_count`. Occupancy percentage is `100 × occupied / total` only when total is positive and unknown is zero; otherwise it is null. `FULL` requires at least one captured spot, zero empty/unknown spots, and fresh evidence. `STALE` applies when no snapshot exists or the newest acquired snapshot is **strictly older** than `STALE_AFTER_SECONDS`; it takes precedence over FULL. `GET /api/v1/lots/current/occupancy` recalculates this against the latest `(captured_at, uploaded_at, id)` snapshot and current UTC time. `GET /api/v1/snapshots/{snapshot_id}` returns stored original predictions and polygon revisions. Reviews, when implemented, remain separate records; occupancy reads their latest effective statuses without altering AI predictions.

## Checks

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

The regular backend test environment exercises API behavior with a disposable migrated SQLite database and an injected model boundary. The optional real-predictor smoke test runs when `torch` and the AI package are installed in the same interpreter. It uses a synthetic image and checkpoint and does **not** report real PKLot model metrics. For a local PostgreSQL/manual check, run `alembic upgrade head`, configure a camera and spots, upload one real JPEG/PNG, then verify `GET /api/v1/snapshots/{id}`, the authenticated image URL, and `/api/v1/lots/current/occupancy`.
