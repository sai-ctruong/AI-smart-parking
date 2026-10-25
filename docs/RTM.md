# Requirements traceability matrix — MVP draft

**Status:** Draft traceability. The requirement baseline is [SRS.md](SRS.md); schemas are in [API_SPEC.md](API_SPEC.md), persistence design in [ERD.md](ERD.md), and implementation boundaries in [SDS.md](SDS.md). TASK-09 adds auth/account tests in `backend/tests/test_auth.py`; TASK-10 adds configuration tests in `backend/tests/test_configuration_api.py`; TASK-11 adds upload and inference API tests in `backend/tests/test_snapshot_inference_api.py`. Other MVP feature tests remain planned.

| MUST ID | Proposed design/contract | Planned verification ID and decisive assertion | Current status |
| --- | --- | --- | --- |
| MVP-01 | Login, user/token in API spec | T-MVP-01: correct login succeeds; wrong username/password share 401 shape; expired/disabled user denied. | Implemented for current routes; `backend/tests/test_auth.py` |
| MVP-02 | SDS permission matrix, API roles | T-MVP-02: Operator gets 403 on user/spot writes; anonymous gets 401; Admin succeeds. | Partial: user and configuration routes use backend Admin dependency; account and camera denial tests pass. Operational routes pending. |
| MVP-03 | Singleton lot/camera ERD, camera-bound upload | T-MVP-03: one configured lot/camera; foreign camera upload rejected; snapshot keeps camera ID. | Implemented for current upload API: singleton and camera selection/association tested. |
| MVP-04 | Revisioned polygons in ERD/API | T-MVP-04: reject out-of-range, repeated, zero-area, self-intersecting points; edit adds revision; old prediction keeps prior revision. | Partial: API polygon validation, reference-image provenance, 10-spot bulk persistence, revision/ID stability, and viewpoint invalidation tested in `backend/tests/test_configuration_api.py`; prediction linkage after edit pending. |
| MVP-05 | Multipart upload and private original storage | T-MVP-05: JPEG/PNG accepted byte-for-byte; corrupt/wrong format/oversize rejected; image route requires auth. | Implemented and covered by snapshot API tests; crash-time orphan reconciliation remains operational work. |
| MVP-06 | Inference adapter and fallback in SDS | T-MVP-06: one result per active spot; inactive spots excluded; missing model produces explicit unknown without XML labels. | Partial: real predictor path exercised with a synthetic checkpoint; unavailable/error fallback and one result per active spot tested. Evaluated PKLot model deployment pending. |
| MVP-07 | Prediction fields/foreign keys in ERD | T-MVP-07: each prediction has correct snapshot/spot/revision, UTC inference time, camera via snapshot, and version when model ran. | Partial: snapshot/spot/revision/camera and version persistence tested; explicit UTC inference-time assertion pending. |
| MVP-08 | Status/confidence API constraints | T-MVP-08: below-threshold result becomes unknown; confidence nullable only without model; invalid status/score rejected. | Partial: low-confidence unknown retains model provenance and no-model unknown has null confidence/version; invalid-output branch not yet tested. |
| MVP-09 | Derived authenticated overlay | T-MVP-09: polygon pixels and three-color legend match effective status; original image hash unchanged. | Not implemented |
| MVP-10 | Occupancy counts/percentage rules | T-MVP-10: totals partition correctly; unknown never available; percentage null for unknown or zero spots. | Implemented for current upload and occupancy read; edge cases tested. |
| MVP-11 | FULL predicate in SRS | T-MVP-11: all occupied and fresh yields FULL; one empty/unknown, no spots, or stale suppresses it; review recomputes. | Partial: initial FULL/empty/unknown/zero/stale cases tested; review API pending. |
| MVP-12 | STALE time rule in SRS/API | T-MVP-12: no snapshot and age strictly greater than threshold yield STALE; exact boundary and new capture clear it. | Partial: no-snapshot, old capture and exact boundary tested; newer-capture override test pending. |
| MVP-13 | Paginated history endpoint | T-MVP-13: stable newest ordering, page bounds, time filters, camera/count/model/review metadata. | Not implemented |
| MVP-14 | Append-only review, effective status | T-MVP-14: review changes effective result and counts, original prediction unchanged; later review wins with tie-breaker. | Not implemented |
| MVP-15 | CSV endpoint/columns | T-MVP-15: filtered export has exact header/order, original and reviewed status, provenance, authenticated access, safe CSV quoting. | Not implemented |
| MVP-16 | Error envelope and validation | T-MVP-16: 401/403/404/409/413/415/422/428/503 use stable codes, safe messages, request ID; rejected upload leaves no row. | Partial: configuration and upload errors, OpenAPI envelope, 413/415/422 and storage-failure rollback tested; remaining operational routes pending. |
| MVP-17 | Hashing, access control, ignored artifacts | T-MVP-17: password hash differs from input; image/export unauthorized access fails; secret/data paths ignored by Git. | Partial: Argon2, auth/RBAC, private image access and original SHA-256 verification tested; export pending. |
| MVP-18 | Ground truth/provenance separation | T-MVP-18: inference fixture cannot read PKLot XML; prediction and review rows are distinct; export labels original/effective explicitly. | Partial: runtime predictor receives only image plus stored polygons, and predictions persist separately; review/export pending. |

## Existing baseline checks

`backend/tests/test_auth.py` covers T-MVP-01 and the user-account part of T-MVP-02/T-MVP-17. `backend/tests/test_configuration_api.py` covers configuration T-MVP-02/03/04/16. `backend/tests/test_snapshot_inference_api.py` covers current T-MVP-03/05/06/08/10/11/12/16/17 upload behavior; its real predictor smoke uses a synthetic checkpoint, not PKLot evaluation. Health/config/database/schema tests cover the foundation; `ai/tests/test_dataset_audit.py` covers offline PKLot validation. Frontend has lint/format/build checks but no MVP UI tests. Remaining partial/planned rows are not accepted by these checks alone.

## Exit rule

Before claiming an MVP MUST complete, implement its code, add its planned tests (or document an equivalent), run them, link the test location/result here, and update the status. Reconcile IDs against any later approved SRS. A passing skeleton check is not MVP acceptance.
