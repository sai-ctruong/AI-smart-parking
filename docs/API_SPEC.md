# API contract — proposed MVP v1

**Status:** Draft MVP contract. Authentication and user-account routes are implemented in `backend/app/auth.py`; lot, camera, and spot configuration routes are implemented in `backend/app/configuration.py`; snapshot predict/detail/private-image and current occupancy routes are implemented in `backend/app/snapshots.py`; history, review and CSV routes are implemented in `backend/app/operations.py`. A derived overlay image route remains proposed. `GET /health` keeps its existing response shape. This document is not proof of approved SRS scope. See [AUTH.md](AUTH.md), [CONFIGURATION.md](CONFIGURATION.md), [SNAPSHOT_INFERENCE.md](SNAPSHOT_INFERENCE.md) and [OPERATIONS.md](OPERATIONS.md) for implemented setup and examples.

## Common rules

- Base path `/api/v1`; JSON unless the endpoint says multipart, image, or CSV. Use `Authorization: Bearer <access_token>` on every `/api/v1` route except login. Access tokens expire; the backend loads the user and current role for each request and rejects disabled accounts.
- IDs are UUID strings. Timestamps are UTC ISO 8601 with `Z`. Geometry points are ordered arrays of `{ "x": number, "y": number }` with finite values in `[0,1]`. `empty`, `occupied`, and `unknown` are the only status strings.
- All status responses expose both immutable `prediction_status` and `effective_status`. A latest review changes only the latter. `confidence` is a model score in `[0,1]` or `null` when no model ran; it is never a human-review confidence.
- `captured_at` defaults to server upload time if omitted and cannot be in the future. “Latest snapshot” means greatest `(captured_at, uploaded_at, id)` among accepted snapshots. History uses that same descending order. Snapshot capture revisions are frozen at upload acceptance.
- `from` is inclusive and `to` exclusive, both UTC timestamps, for history and CSV. `page` starts at 1, `page_size` defaults to 25 and is capped at 100. Invalid ranges return 422.

## Endpoints and permissions

| Method and path | Actor | Request | Success |
| --- | --- | --- | --- |
| `POST /api/v1/auth/login` | Public | JSON `username`, `password` | 200 token response; 401 on invalid credentials. |
| `GET /api/v1/auth/me` | Admin/Operator | None | 200 user summary. |
| `POST /api/v1/users` | Admin | JSON `username`, `password`, `role` | 201 user summary; 409 duplicate username. |
| `GET /api/v1/users` | Admin | None | 200 `{ "items": [<user summaries>] }`. |
| `PATCH /api/v1/users/{user_id}` | Admin | JSON `role` and/or `is_active` | 200 user summary; cannot disable/demote last active Admin. |
| `POST /api/v1/users/{user_id}/password` | Admin | JSON `password` | 200 user summary; old tokens are invalidated. |
| `POST /api/v1/lots` | Admin | JSON `name` | 201 lot; 409 if MVP singleton exists. |
| `GET /api/v1/lots/current`, `GET /api/v1/lots/{lot_id}` | Admin/Operator | None | 200 lot; 404 if absent. |
| `PATCH /api/v1/lots/{lot_id}` | Admin | JSON `name` | 200 updated lot. |
| `DELETE /api/v1/lots/{lot_id}` | Admin | None | 204 if no camera; otherwise 409. |
| `POST /api/v1/lots/{lot_id}/cameras` | Admin | JSON `name`, `reference_image` | 201 fixed camera; 409 if lot already has one. |
| `GET /api/v1/cameras/current`, `GET /api/v1/cameras/{camera_id}` | Admin/Operator | None | 200 camera; 404 if absent. |
| `PATCH /api/v1/cameras/{camera_id}` | Admin | JSON `name`, `is_active`, and/or `reference_image`; `invalidate_spots` required when changing reference with existing spots | 200 camera; 409 if geometry would be silently reused. |
| `DELETE /api/v1/cameras/{camera_id}` | Admin | None | 204 if no spots or snapshots; otherwise 409. |
| `GET /api/v1/spots`, `GET /api/v1/cameras/{camera_id}/spots` | Admin/Operator | None | 200 `{ "items": [<spot>] }`. |
| `POST /api/v1/cameras/{camera_id}/spots` | Admin | JSON `code`, `points` | 201 spot with polygon revision 1. |
| `PUT /api/v1/cameras/{camera_id}/spots/bulk` | Admin | JSON `items` of up to 100 objects with optional `id`, `code`, `points` | 200 atomic upsert with `items` and overlap `warnings`; existing `id` is retained. |
| `GET /api/v1/spots/{spot_id}`, `GET /api/v1/spots/{spot_id}/revisions` | Admin/Operator | None | 200 spot or ordered immutable polygon revisions. |
| `PUT /api/v1/spots/{spot_id}/polygon` | Admin | JSON `points`, header `If-Match: "<revision_no>"` | 200 spot with replacement revision; 409 on stale revision. |
| `PATCH /api/v1/spots/{spot_id}` | Admin | JSON `code` and/or `is_active` | 200 updated spot; stale geometry cannot be reactivated. |
| `DELETE /api/v1/spots/{spot_id}` | Admin | None | 204 soft deactivation; spot ID and history remain. |
| `POST /api/v1/snapshots/predict` | Admin/Operator | Multipart `file` JPEG/PNG, `camera_id`, optional timezone-aware `captured_at` | 201 snapshot with predictions and coordinates; unavailable model yields explicit unknown rows. |
| `GET /api/v1/snapshots` | Admin/Operator | `page`, `page_size`, optional `camera_id`, `from`/`to` | 200 paginated history. |
| `GET /api/v1/snapshots/{snapshot_id}` | Admin/Operator | None | 200 stored original predictions, captured polygons and current effective counts. |
| `GET /api/v1/snapshots/{snapshot_id}/image` | Admin/Operator | None | 200 original image bytes with its validated media type and SHA-256 integrity check. |
| `GET /api/v1/snapshots/{snapshot_id}/overlay` | Admin/Operator | None | 200 derived PNG; polygons colored by effective status (empty green, occupied red, unknown amber) and legend. |
| `GET /api/v1/lots/current/occupancy` | Admin/Operator | None | 200 latest effective counts, threshold and `alert_state`. |
| `POST /api/v1/predictions/{prediction_id}/reviews` | Admin/Operator | JSON `reviewed_status`, optional `note` | 201 append-only review; re-read counts to see current effective state. |
| `GET /api/v1/predictions/{prediction_id}/reviews` | Admin/Operator | None | 200 chronological review history. |
| `GET /api/v1/snapshots/export.csv` | Admin/Operator | Optional `camera_id`, `from`/`to` | 200 UTF-8 CSV with one row per prediction; no history mutation. |

The export route must be registered before the dynamic `/{snapshot_id}` route when implemented. The initial Admin is created locally with `python -m app.bootstrap_admin --username <name>` after migration; the password is entered at a hidden prompt. No public registration exists. All configuration writes use the backend Admin dependency.

## Request and response shapes

Login request: `{"username":"operator1","password":"<entered secret>"}`. Successful response:

```json
{"access_token":"<opaque-to-client bearer token>","token_type":"bearer","expires_in":900}
```

User summary: `{"id":"<uuid>","username":"operator1","role":"operator","is_active":true}`. Passwords and hashes never appear in a response. Lot response contains `id`, `name`, `created_at`. Camera response contains `id`, `parking_lot_id`, `name`, `is_active`, `viewpoint_version`, `reference_image`, `created_at`. Names are examples, not seeded values.

Spot create body:

```json
{"code":"A01","points":[{"x":0.1,"y":0.2},{"x":0.2,"y":0.2},{"x":0.2,"y":0.3}]}
```

The spot response contains `id`, `camera_id`, `code`, `is_active`, `geometry_status`, nested `polygon`, and `created_at`. The nested polygon contains `id`, `revision_no`, `points`, `reference_image`, `camera_viewpoint_version`, `created_by`, and `created_at`. `geometry_status` is `current`, `needs_recalibration`, or `legacy_missing` for rows created before the reference-image migration. `PUT /spots/{id}/polygon` appends a revision when geometry or the camera reference changes; `If-Match` must equal the current quoted decimal revision. Missing precondition returns 428, stale precondition returns 409. Soft deactivation excludes a spot from later snapshots but preserves prior prediction rows. Bulk upsert is atomic, normalizes codes to uppercase, rejects duplicate codes and identical active polygons, and reports intersecting polygons in `warnings` without discarding them. Single-spot create and polygon replace reject overlap with another current active spot using `422 OVERLAPPING_POLYGON`; shared edges alone do not count. All coordinates are relative to the declared reference image; a polygon under four pixels in that image is rejected.

Successful upload returns the snapshot prediction schema below (selected fields shown). The server reads `camera_id` from multipart form data, stores `uploaded_by`, and returns one prediction per active current spot. The original file is private. A missing model still yields 201 with `unknown` results, null confidence/version, and `reason_code: "MODEL_UNAVAILABLE"` for each spot; no PKLot annotation is substituted. The model runtime error fallback uses `INFERENCE_ERROR` instead. The response also includes a numeric `processing_time_ms` measured before database persistence.

```json
{
  "snapshot_id": "<snapshot-uuid>",
  "camera_id": "<camera-uuid>",
  "timestamp": "2026-10-25T08:00:00Z",
  "total_spots": 1,
  "empty_count": 0,
  "occupied_count": 0,
  "unknown_count": 1,
  "occupancy_percent": null,
  "model_version": null,
  "alert_state": "NONE",
  "image_url": "/api/v1/snapshots/<snapshot-uuid>/image",
  "predictions": [{
    "prediction_id": "<prediction-uuid>", "spot_id": "<spot-uuid>",
    "polygon_revision_id": "<revision-uuid>",
    "predicted_status": "unknown",
    "effective_status": "unknown",
    "review_version": 0,
    "latest_review_id": null,
    "latest_reviewed_by": null,
    "latest_reviewed_at": null,
    "confidence": null, "model_version": null,
    "reason_code": "MODEL_UNAVAILABLE",
    "polygon": [{"x": 0.1, "y": 0.2}, {"x": 0.2, "y": 0.2}, {"x": 0.2, "y": 0.3}]
  }]
}
```

`POST /predictions/{id}/reviews` requires `If-Match: "0"` for an unreviewed prediction, or the current quoted `review_version`. It accepts, for example, `{"reviewed_status":"occupied","note":"Vehicle visible"}` and returns `id`, `prediction_id`, `revision_no`, `reviewed_status`, `note`, `reviewed_by`, and `reviewed_at`. The original prediction stays unchanged. Missing precondition returns 428; a stale version returns 409 `REVIEW_CONFLICT` with no new review/audit row. A conditional database update serializes competing reviews so only one writer can advance a given version. `GET .../reviews` returns `{"items":[<review objects>]}` in ascending `revision_no` order. Reviews are append-only; the latest revision determines effective status.

The implemented paginated history endpoint returns `{"items":[<snapshot summaries>],"page":1,"page_size":25,"total_items":<integer>}`. Each summary includes snapshot/camera IDs, capture/upload time, total and effective empty/occupied/unknown counts, occupancy percentage, model version, number of reviewed spots and read-time alert state. Ordering is `(captured_at, uploaded_at, id)` descending. `GET /snapshots/{id}` returns stored original predictions and captured polygons; each prediction also exposes `effective_status`, `review_version`, and latest review identity/time, with effective counts recalculated from reviews.

Occupancy response contains `snapshot_id` (nullable), `camera_id`, `captured_at` (nullable), `as_of` (server UTC), `stale_after_seconds`, `counts` (nullable object with `total`, `empty`, `occupied`, `unknown`, `available_confirmed`, `occupancy_percent`), and singular `alert_state` (`NONE`, `FULL`, or `STALE`). If no snapshot exists, counts are null and state is `STALE`. With any unknown result, counts include it and `FULL` is absent. `FULL` requires at least one captured spot. `STALE` takes precedence when the latest acquired image is strictly older than the configured threshold.

CSV columns, in order: `snapshot_id,camera_id,captured_at,uploaded_at,spot_id,polygon_revision_id,prediction_status,effective_status,confidence,model_version,reason_code,inferred_at,latest_review_id,latest_reviewed_by,latest_reviewed_at`. Null values are empty fields. A snapshot with zero active spots yields no prediction row. CSV uses standard quoting and guards spreadsheet-formula injection in exported cells; this export contains no review note or username. `Content-Disposition` uses a fixed safe filename.

## Error conventions

All new `/api/v1` errors use `{"error":{"code":"<STABLE_CODE>","message":"Human-readable summary","details":{},"request_id":"<id>"}}`; `details` may contain field paths but no secret, token, internal path, or stack trace. The existing `/health` keeps FastAPI's current `detail` response. Proposed codes and statuses:

| HTTP | Code | Use |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | Semantically invalid request not covered by field validation. |
| 401 | `UNAUTHENTICATED` | Missing, expired, or invalid token; invalid login credentials. |
| 403 | `FORBIDDEN` | Authenticated role lacks permission. |
| 404 | `NOT_FOUND` | Unknown or inaccessible camera, spot, snapshot, or prediction. |
| 409 | `CONFLICT` / `REVISION_CONFLICT` / `REVIEW_CONFLICT` / `VIEWPOINT_CONFLICT` / `REFERENCE_REQUIRED` | Duplicate unique value, stale review/polygon revision, or camera reference change requiring geometry invalidation/recalibration. |
| 413 | `PAYLOAD_TOO_LARGE` | Upload exceeds configured byte limit. |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Upload is not a decoded JPEG or PNG. |
| 422 | `VALIDATION_ERROR` / `INVALID_POLYGON` / `OVERLAPPING_POLYGON` / `INVALID_IMAGE` | Invalid fields, polygon, overlapping single-spot change, date range, dimensions, or corrupt image. |
| 428 | `PRECONDITION_REQUIRED` | Polygon update lacks `If-Match`. |
| 503 | `SERVICE_UNAVAILABLE` | Database or private image storage unavailable; no accepted snapshot is reported. |

On any upload validation or persistence error, no accepted snapshot is created. An inference failure is accepted with explicit unknown predictions instead. Implemented `/api/v1` routes include `X-Request-ID` on responses. `MAX_UPLOAD_BYTES` and `MAX_IMAGE_PIXELS` are configurable; see [SNAPSHOT_INFERENCE.md](SNAPSHOT_INFERENCE.md).
