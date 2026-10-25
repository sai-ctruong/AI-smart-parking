# Software Requirements Specification — MVP proposal

**Status:** Draft for review, 2026-10-25. No approved SRS, WBS, or `DATT_AI_HANDOFF_2026-10-24.md` was found in this repository. This document is a proposed contract, not evidence of formal approval or implementation. If an approved SRS becomes available, reconcile it before building the features below.

## Scope and actors

The MVP supports one parking lot and one fixed camera. A person uploads a JPEG/PNG snapshot from that camera; the system classifies configured parking-spot regions, shows an overlay and occupancy, and supports review and export. Automatic camera capture, multiple lots/cameras, payments, reservations, and model training are outside this MVP.

**Admin** manages users and spot geometry and can perform operator actions. **Operator** uploads and reviews snapshots, views results and history, and exports CSV. There is no public account registration. The backend enforces every permission; hiding a frontend control is insufficient.

## Normative requirements

Each row is a **MUST** requirement. Test IDs are specified in [RTM.md](RTM.md). None of these MVP requirements is implemented yet unless the repository evidence table below says otherwise.

| ID | Requirement | Acceptance condition |
| --- | --- | --- |
| MVP-01 | Authenticate Admin and Operator accounts. | Valid credentials return a short-lived bearer token; invalid credentials do not reveal which field was wrong; no protected MVP endpoint succeeds anonymously. |
| MVP-02 | Enforce role-based access in the backend. | Admin-only user/geometry writes return 403 for Operator; missing/invalid authentication returns 401. |
| MVP-03 | Limit operational data to one configured lot and one fixed camera. | Snapshot uploads bind to that camera; a different camera ID is rejected; responses retain lot/camera association. |
| MVP-04 | Allow Admin to create and edit active parking spots with normalized polygon coordinates. | Each polygon has at least three distinct, non-collinear vertices with both coordinates in `[0,1]`; edits create an immutable revision, and prior snapshots keep their original revision. |
| MVP-05 | Accept JPEG/PNG snapshot uploads for the fixed camera. | Decode and validate image type, dimensions, and size; store original bytes privately without changing them; reject invalid uploads. |
| MVP-06 | Classify each active spot ROI for an accepted snapshot. | Produce one original prediction per active spot using its captured polygon revision; model failures become explicit `unknown` results with a reason, never ground-truth labels. |
| MVP-07 | Preserve inference provenance. | Each prediction records snapshot, spot, polygon revision, camera association through snapshot, inference timestamp, status, confidence, and model version when a model actually ran. |
| MVP-08 | Use `empty`, `occupied`, or `unknown` consistently. | Low-confidence or unavailable predictions are `unknown`; unknown is neither empty nor occupied; confidence is a number in `[0,1]` for model output or `null` when no model ran. |
| MVP-09 | Show a snapshot overlay. | Draw the spot polygons on a derived view of the uploaded image, with a legend for all three effective statuses; the source image remains unchanged. |
| MVP-10 | Show occupancy statistics from the latest accepted snapshot. | Active-spot totals satisfy `total = empty + occupied + unknown`; available confirmed spaces equal `empty`; occupancy percentage is `null` when total is zero or any spot is unknown. |
| MVP-11 | Raise a `FULL` alert only when every active spot is occupied. | `FULL` requires at least one active spot, a non-stale latest snapshot, and zero empty/unknown spots; review changes recompute it. |
| MVP-12 | Raise a `STALE` alert when evidence is missing or too old. | No accepted snapshot, or age beyond configured `STALE_AFTER_SECONDS`, yields `STALE`; response exposes threshold and last capture time. |
| MVP-13 | Keep paginated snapshot history. | Authorized users can list snapshots in newest-first order with capture time, camera, counts, model version, and review indicators. |
| MVP-14 | Support Operator review without overwriting inference. | A review appends actor, time, selected status, and optional note; original prediction remains immutable; latest review determines effective status. |
| MVP-15 | Export history as CSV. | Authorized users export filtered history with snapshot/spot IDs, original and effective statuses, confidence, model version, camera, capture time, and review provenance. |
| MVP-16 | Apply shared validation and error conventions. | Bad input returns structured 4xx errors; unsupported image type, oversize data, missing records, and conflicts have stable codes; internal details and secrets are not exposed. |
| MVP-17 | Protect credentials, images, and derived data. | Passwords are one-way hashed; no default credentials or secrets enter Git; image access and export require authorization; raw PKLot data stays out of operational inference output. |
| MVP-18 | Keep ground truth, predictions, and human review separate. | PKLot XML is used only in offline dataset work; operational prediction and review records have separate provenance and cannot masquerade as ground truth. |

## Shared semantics

- Geometry is stored as ordered `{x, y}` vertices normalized to image width/height, inclusive of 0 and 1. A polygon revision is immutable after use; the client sends the full replacement polygon with a revision precondition. The backend validates geometry and owns revision numbering.
- Capture time is UTC `captured_at`; upload time is UTC `uploaded_at`. The server uses upload time when the uploader omits capture time. A future capture time is rejected. All timestamps use ISO 8601 with `Z` in API responses.
- Original `prediction_status` is immutable. The effective status is the latest human review status if present, otherwise the prediction status. Reviews may also choose `unknown`. The overlay, counts, and alerts use effective status while exposing original status alongside it.
- `unknown` is never counted as available. `occupancy_percent = 100 × occupied / total` only when `total > 0` and `unknown = 0`; otherwise it is `null`. `FULL` never appears alongside `STALE` for the same current snapshot.
- Inference is requested synchronously by the upload API for this proposed MVP. An accepted image creates a snapshot and one result per active spot. If inference cannot run, each spot receives `unknown`, `confidence: null`, and a reason such as `MODEL_UNAVAILABLE`; the API must not fabricate an occupied/empty label. See [DECISIONS.md](DECISIONS.md) for unresolved processing limits.

## Evidence and approval boundary

Implemented today: React/Vite shell, FastAPI `/health` (including optional database readiness), environment/CORS settings, SQLAlchemy connection/session utilities, an empty Alembic baseline, PostgreSQL Compose, and a PKLot ground-truth audit. See [SDS.md](SDS.md) for source paths. There are no auth, parking tables, upload, inference, statistics, review, or CSV endpoints yet. [DECISIONS.md](DECISIONS.md) records proposed and unresolved choices. This draft requires project-owner/SRS approval before being treated as the authoritative scope.
