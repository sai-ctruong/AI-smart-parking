# API contract — proposed MVP v1

**Status:** Draft MVP contract. The auth and user-account routes below are implemented in `backend/app/auth.py`; other `/api/v1` feature routes remain proposed. `GET /health` keeps its existing response shape. This document is not proof of approved SRS scope. See [AUTH.md](AUTH.md) for setup and current security boundaries.

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
| `GET /api/v1/lots/current` | Admin/Operator | None | 200 single lot summary. |
| `GET /api/v1/cameras/current` | Admin/Operator | None | 200 fixed camera summary. |
| `GET /api/v1/spots` | Admin/Operator | None | 200 list of spots and current revisions. |
| `POST /api/v1/spots` | Admin | JSON `code`, `points` | 201 spot with revision 1; 409 duplicate code. |
| `PUT /api/v1/spots/{spot_id}/polygon` | Admin | JSON `points`, header `If-Match: "<revision_no>"` | 200 spot with next revision; 409 on stale revision. |
| `PATCH /api/v1/spots/{spot_id}` | Admin | JSON `is_active` | 200 updated spot; historical snapshots remain unchanged. |
| `POST /api/v1/cameras/{camera_id}/snapshots` | Admin/Operator | Multipart `file` JPEG/PNG, optional `captured_at` UTC | 201 snapshot detail with predictions; 404 for a camera other than the configured one. |
| `GET /api/v1/snapshots` | Admin/Operator | `page`, `page_size`, optional `from`/`to` | 200 paginated history. |
| `GET /api/v1/snapshots/{snapshot_id}` | Admin/Operator | None | 200 snapshot detail, predictions, latest reviews, counts. |
| `GET /api/v1/snapshots/{snapshot_id}/image` | Admin/Operator | None | 200 original image bytes with its validated media type. |
| `GET /api/v1/snapshots/{snapshot_id}/overlay` | Admin/Operator | None | 200 derived PNG; polygons colored by effective status (empty green, occupied red, unknown amber) and legend. |
| `GET /api/v1/lots/current/occupancy` | Admin/Operator | None | 200 latest counts and active alerts. |
| `POST /api/v1/predictions/{prediction_id}/reviews` | Admin/Operator | JSON `reviewed_status`, optional `note` | 201 append-only review; re-read counts to see current effective state. |
| `GET /api/v1/predictions/{prediction_id}/reviews` | Admin/Operator | None | 200 chronological review history. |
| `GET /api/v1/snapshots/export.csv` | Admin/Operator | Optional `from`/`to` | 200 UTF-8 CSV with one row per prediction; no history mutation. |

The export route must be registered before the dynamic `/{snapshot_id}` route. The initial Admin is created locally with `python -m app.bootstrap_admin --username <name>` after migration; the password is entered at a hidden prompt. No public registration exists. Camera/spot write routes remain unimplemented and must use the backend Admin dependency when added.

## Request and response shapes

Login request: `{"username":"operator1","password":"<entered secret>"}`. Successful response:

```json
{"access_token":"<opaque-to-client bearer token>","token_type":"bearer","expires_in":900}
```

User summary: `{"id":"<uuid>","username":"operator1","role":"operator","is_active":true}`. Passwords and hashes never appear in a response. Lot summary: `{"id":"<uuid>","name":"Main lot","camera_id":"<uuid>"}`. Camera summary: `{"id":"<uuid>","lot_id":"<uuid>","name":"Fixed camera","is_active":true}`. Names are examples, not seeded values.

Spot create body and returned geometry (returned object also contains `id`, `camera_id`, `is_active`, `revision_no`, `created_at`):

```json
{"code":"A01","points":[{"x":0.1,"y":0.2},{"x":0.2,"y":0.2},{"x":0.2,"y":0.3}]}
```

`GET /spots` returns `{"items":[<spot objects>]}`. `PUT /spots/{id}/polygon` replaces all points and increments `revision_no`; `If-Match` must equal the current quoted decimal revision. Missing precondition returns 428, stale precondition returns 409. `PATCH` accepts only `is_active`; disabling excludes the spot from later snapshots but not prior prediction rows.

Successful upload returns the snapshot detail schema below. The server captures `camera_id` from the path, stores `uploaded_by`, and returns one prediction per active spot. The original file is private. A missing model still yields 201 with `unknown` results, null confidence/version, and `reason_code: "MODEL_UNAVAILABLE"` for each spot; no PKLot annotation is substituted.

```json
{
  "id": "<snapshot-uuid>",
  "camera_id": "<camera-uuid>",
  "captured_at": "2026-10-25T08:00:00Z",
  "uploaded_at": "2026-10-25T08:00:02Z",
  "image_url": "/api/v1/snapshots/<snapshot-uuid>/image",
  "overlay_url": "/api/v1/snapshots/<snapshot-uuid>/overlay",
  "counts": {"total": 1, "empty": 0, "occupied": 0, "unknown": 1, "available_confirmed": 0, "occupancy_percent": null},
  "predictions": [{
    "id": "<prediction-uuid>", "spot_id": "<spot-uuid>",
    "polygon_revision_id": "<revision-uuid>",
    "prediction_status": "unknown", "effective_status": "unknown",
    "confidence": null, "model_version": null,
    "reason_code": "MODEL_UNAVAILABLE", "inferred_at": "2026-10-25T08:00:03Z",
    "latest_review": null
  }]
}
```

`POST /predictions/{id}/reviews` accepts, for example, `{"reviewed_status":"occupied","note":"Vehicle visible"}` and returns `{"id":"<uuid>","prediction_id":"<uuid>","reviewed_status":"occupied","note":"Vehicle visible","reviewed_by":"<user-uuid>","reviewed_at":"2026-10-25T08:05:00Z"}`. The prediction's original fields stay unchanged. `GET .../reviews` returns `{"items":[<review objects>]}` in ascending `(reviewed_at,id)` order.

History returns `{"items":[<snapshot summaries>],"page":1,"page_size":25,"total_items":<integer>}`. Each summary contains `id`, `camera_id`, `captured_at`, `uploaded_at`, `counts`, distinct non-null `model_versions`, and `review_count`. Detail includes the same snapshot metadata plus every prediction and its latest review. Empty history has `items: []`, `total_items: 0`.

Occupancy response contains `snapshot_id` (nullable), `camera_id`, `captured_at` (nullable), `as_of` (server UTC), `stale_after_seconds`, `counts` (same schema as detail), and `active_alerts` (array containing `"STALE"` and/or `"FULL"`). If no snapshot exists, counts are null, occupancy percentage is null, and alerts contain `STALE`. With any unknown result, counts include it and `FULL` is absent. `STALE` takes precedence over `FULL` when a captured image ages beyond the threshold.

CSV columns, in order: `snapshot_id,camera_id,captured_at,uploaded_at,spot_id,polygon_revision_id,prediction_status,effective_status,confidence,model_version,reason_code,inferred_at,latest_review_id,latest_reviewed_by,latest_reviewed_at`. Null values are empty fields. A snapshot with zero active spots yields no prediction row. CSV uses standard quoting and guards spreadsheet-formula injection in free-text fields; this export currently contains no review note or username. `Content-Disposition` uses a fixed safe filename.

## Error conventions

All new `/api/v1` errors use `{"error":{"code":"<STABLE_CODE>","message":"Human-readable summary","details":{},"request_id":"<id>"}}`; `details` may contain field paths but no secret, token, internal path, or stack trace. The existing `/health` keeps FastAPI's current `detail` response. Proposed codes and statuses:

| HTTP | Code | Use |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | Semantically invalid request not covered by field validation. |
| 401 | `UNAUTHENTICATED` | Missing, expired, or invalid token; invalid login credentials. |
| 403 | `FORBIDDEN` | Authenticated role lacks permission. |
| 404 | `NOT_FOUND` | Unknown or inaccessible camera, spot, snapshot, or prediction. |
| 409 | `CONFLICT` / `REVISION_CONFLICT` | Duplicate unique value or stale polygon revision. |
| 413 | `PAYLOAD_TOO_LARGE` | Upload exceeds configured byte limit. |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Upload is not a decoded JPEG or PNG. |
| 422 | `VALIDATION_ERROR` / `INVALID_IMAGE` | Invalid fields, polygon, date range, dimensions, or corrupt image. |
| 428 | `PRECONDITION_REQUIRED` | Polygon update lacks `If-Match`. |
| 503 | `SERVICE_UNAVAILABLE` | Database or private image storage unavailable; no accepted snapshot is reported. |

On any error, a rejected upload creates no accepted snapshot. Internal request IDs support log correlation. Define the exact request-id middleware and size limit before implementing the API.
