# Parking configuration API (TASK-10)

The implemented configuration routes use the migrated database and bearer authentication. Admin can change lot, camera and spot configuration; Admin and Operator can read it. The MVP database enforces one lot and one camera per lot. The IDs and foreign keys allow camera-scoped spots without changing spot identity during polygon edits.

## Start locally (PowerShell)

From the repository root, start PostgreSQL as described in the [root README](../README.md), configure `DATABASE_URL` and `AUTH_SECRET_KEY` in the ignored `.env`, then run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.\.venv\Scripts\python.exe -m app.bootstrap_admin --username admin
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The bootstrap command prompts for a password and refuses to create a second initial Admin. Open `http://127.0.0.1:8000/docs` for generated OpenAPI documentation. Configuration endpoints are under `/api/v1`. No default lot, camera or spot is seeded.

## Declared reference image

Each camera stores a SHA-256 fingerprint and pixel dimensions for the image on which an Admin draws polygons. A polygon revision copies this metadata and the camera's `viewpoint_version`. Coordinates are finite normalized `{x,y}` values in `[0,1]`, relative to that image's width and height. The API checks that each polygon has at least three distinct points, no self-intersection, positive area, and at least four pixels of area at the declared dimensions.

After declaring the metadata, Admin uploads the matching JPEG/PNG through the **Cấu hình bãi đỗ** page or `PUT /api/v1/cameras/{camera_id}/reference-image` as multipart field `file`. The backend enforces `MAX_UPLOAD_BYTES` and `MAX_IMAGE_PIXELS`, checks content MIME, decoded dimensions and SHA-256, rejects EXIF rotation, and stores the original privately under `IMAGE_STORAGE_ROOT/references/<camera-id>/`. Authenticated `GET` serves only the file matching the camera's *current* declared fingerprint. An Operator may view it but only Admin may upload. The upload is never a ground-truth dataset import.

A real camera viewpoint change requires a new fingerprint, even if dimensions remain the same. If spots exist, the change returns `409 VIEWPOINT_CONFLICT` unless Admin sends `invalidate_spots: true`; this increments `viewpoint_version` and deactivates every old spot. The old revisions remain for history. Upload the new matching image, then add new polygon revisions to recalibrate spots. The old reference file is retained privately for possible historical use; it is not served as the current image.

For a local JPEG or PNG on Windows PowerShell, substitute your actual path:

```powershell
$referencePath = 'C:\path\to\your\reference.jpg'
$referenceDigest = (Get-FileHash -LiteralPath $referencePath -Algorithm SHA256).Hash.ToLowerInvariant()
Add-Type -AssemblyName System.Drawing
$referenceBitmap = [System.Drawing.Image]::FromFile($referencePath)
try {
    $referenceWidth = $referenceBitmap.Width
    $referenceHeight = $referenceBitmap.Height
} finally {
    $referenceBitmap.Dispose()
}
```

## Example requests

The following illustrates request shapes; replace the credentials, reference image and polygon coordinates with your own values. Run the commands in another PowerShell window:

```powershell
$base = 'http://127.0.0.1:8000/api/v1'
$loginBody = @{ username = 'admin'; password = (Read-Host 'Admin password') } | ConvertTo-Json
$login = Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType 'application/json' -Body $loginBody
$headers = @{ Authorization = "Bearer $($login.access_token)" }

$lotBody = @{ name = 'Main lot' } | ConvertTo-Json
$lot = Invoke-RestMethod -Method Post -Uri "$base/lots" -Headers $headers -ContentType 'application/json' -Body $lotBody

$cameraBody = @{
    name = 'Fixed camera'
    reference_image = @{ sha256 = $referenceDigest; width = $referenceWidth; height = $referenceHeight }
} | ConvertTo-Json -Depth 5
$camera = Invoke-RestMethod -Method Post -Uri "$base/lots/$($lot.id)/cameras" -Headers $headers -ContentType 'application/json' -Body $cameraBody

$spotBody = @{
    code = 'A01'
    points = @(
        @{ x = 0.10; y = 0.20 }, @{ x = 0.20; y = 0.20 },
        @{ x = 0.20; y = 0.30 }, @{ x = 0.10; y = 0.30 }
    )
} | ConvertTo-Json -Depth 5
$spot = Invoke-RestMethod -Method Post -Uri "$base/cameras/$($camera.id)/spots" -Headers $headers -ContentType 'application/json' -Body $spotBody

$bulkBody = @{ items = @(
    @{ id = $spot.id; code = 'A01'; points = @(
        @{ x = 0.11; y = 0.20 }, @{ x = 0.21; y = 0.20 },
        @{ x = 0.21; y = 0.30 }, @{ x = 0.11; y = 0.30 }
    ) }
) } | ConvertTo-Json -Depth 7
$updated = Invoke-RestMethod -Method Put -Uri "$base/cameras/$($camera.id)/spots/bulk" -Headers $headers -ContentType 'application/json' -Body $bulkBody
$updated.items | Select-Object id, code, geometry_status
$updated.warnings
```

For the visual editor, log in as Admin, open **Cấu hình bãi đỗ**, upload the same reference file, draw polygons by clicking vertices, adjust vertices by dragging, and save. The browser sends normalized coordinates via `PUT /cameras/{camera_id}/spots/bulk`, preserving server-assigned IDs for existing spots. Reload the page to confirm overlay alignment. Zoom, pan, and viewport resizing do not change stored coordinates. The editor blocks local invalid shapes and duplicate codes; the backend remains authoritative for geometry and authorization.

`PUT /spots/{spot_id}/polygon` requires `If-Match: "<revision_no>"`; a missing header returns 428 and a stale revision returns 409. Bulk upsert accepts 1–100 entries. Include `id` to update an existing spot; omit it to create one. The whole request rolls back on a validation error. A `POLYGON_OVERLAP` warning names overlapping active spot IDs. Exact duplicate active geometry is rejected. Single-spot create/update rejects actual overlap with another active spot using `422 OVERLAPPING_POLYGON`; touching edges are allowed. `DELETE /spots/{id}` deactivates a spot while retaining its ID and immutable polygon history. Camera deletion is blocked while it has spots or snapshots; lot deletion is blocked while it has a camera.

## Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m alembic -c alembic.ini current
```

The automated API tests use a disposable SQLite database migrated through Alembic. Repeat `alembic upgrade head`, then create and reload a camera and spots against local PostgreSQL to check your configured service.
