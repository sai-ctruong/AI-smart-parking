# MVP decisions, approval gaps, and risks

**Status:** Draft architectural record, 2026-10-25. “Proposed” means documented for consistency across [SRS](SRS.md), [SDS](SDS.md), [ERD](ERD.md), [API spec](API_SPEC.md), and [RTM](RTM.md); it does **not** mean an approved SRS or implemented feature. No SRS, WBS, or handoff file was found in this repository at drafting time. The known handoff filename is explicitly preliminary context if it later appears.

## Proposed decisions for MVP review

| ID | Choice | Reason and consequence | Status |
| --- | --- | --- | --- |
| ADR-01 | One lot and one fixed camera; manual snapshot upload. | Bounds the capstone scope and keeps camera capture integration outside MVP. Enforce singleton in data setup and API. | Proposed |
| ADR-02 | Normalize spot geometry to `[0,1]` and keep immutable revisions. | Same geometry works for different image sizes; historical prediction evidence remains stable. | Proposed |
| ADR-03 | Keep original prediction and append-only human reviews; compute effective status from latest review. | Avoids changing model evidence and supports audit/export. | Proposed |
| ADR-04 | Use three statuses; unknown never counts as empty. | Prevents low-confidence or failed inference from overstating availability. Occupancy percentage is null when any spot is unknown. | Proposed |
| ADR-05 | Derive FULL and STALE at read time instead of persisting alert rows. | Avoids state drift from review and clock changes. FULL requires fresh all-occupied evidence; STALE wins when old. | Proposed |
| ADR-06 | Version `/api/v1`, use short-lived bearer tokens, and recheck current user/role in backend. | Simple SPA integration while preserving immediate disabled-user denial. Token storage in browser memory and login renewal need UX work. | Proposed |
| ADR-07 | Keep original images private and expose authenticated image/overlay routes. | Hides storage keys and protects historical snapshots. File/DB consistency and retention are still open. | Proposed |
| ADR-08 | Accept upload synchronously and return snapshot plus predictions. | Small MVP contract without a job queue. Inference timeout/throughput limits must be measured before implementation. | Proposed |
| ADR-09 | If no model runs, write per-spot unknown results with null confidence/version and a reason. | Snapshot remains reviewable without fabricating a model verdict or using PKLot XML as output. | Proposed |
| ADR-10 | Use the latest `(captured_at, uploaded_at, id)` snapshot and evaluate STALE against `captured_at`. | Gives deterministic ordering and ties alert freshness to when the scene was captured. | Proposed |

## Open decisions before feature implementation

| ID | Question and needed resolution | Owner/gate |
| --- | --- | --- |
| OPEN-01 | Is there an approved SRS/WBS elsewhere, and does it change this MVP scope, terminology, or acceptance criteria? | Project owner; reconcile all six documents before declaring a baseline. |
| OPEN-02 | What exact one-time Admin bootstrap command and secret supply mechanism will be used? No default password or public registration is allowed. | Auth implementation design. |
| OPEN-03 | Where will private images live in production, what are backup/retention/deletion rules, and how are staged file writes reconciled with DB transactions? | Deployment/storage design. |
| OPEN-04 | What validated model artifact and version will be deployed, what confidence threshold is justified, and what evaluation protocol prevents PKLot train/validation/test leakage? No metrics may be invented. | AI task before claiming classification quality. |
| OPEN-05 | What maximum upload bytes, image dimensions, inference timeout, and concurrency are feasible on target hardware? | Measure during implementation; configure positive limits. |
| OPEN-06 | What exact `STALE_AFTER_SECONDS` is operationally useful, and should manually supplied capture times have a maximum age? | Product acceptance; tests use an injected clock at the chosen boundary. |
| OPEN-07 | Are duplicate uploads allowed? If not, define idempotency key/hash policy and behavior under concurrent geometry edits or reviews. | API/database implementation. |
| OPEN-08 | Are polygon self-intersections always rejected, and what pixel rounding/masking convention will match overlay and ROI extraction? | Geometry implementation, with fixtures. |
| OPEN-09 | Is bearer-token-in-memory adequate for deployment, or is a secure-cookie/CSRF design required? Define login throttling and token signing/rotation policy. | Security review before production use. |

## Risks and controls

| Risk | Impact | Planned control / evidence needed |
| --- | --- | --- |
| Dataset leakage or annotation-as-output | Inflated evaluation and false operational predictions | Separate offline PKLot loader from inference package path; split by appropriate grouping before training; test provenance and report real metrics only. |
| Misaligned polygons | Wrong per-spot verdict and misleading overlay | Revisioned normalized geometry, same conversion for ROI and overlay, image/polygon visual fixtures. |
| Unknown treated as vacant or FULL despite uncertainty | Incorrect availability or alert | Shared status/count predicate tests T-MVP-08/10/11; explicit null percentage. |
| File stored without matching database row, or vice versa | Orphaned/missing image | Staged write and cleanup/reconciliation strategy before implementing uploads. |
| Long inference blocks API worker | Slow/failing uploads | Measure runtime and set timeout; revisit ADR-08 for a queue if needed. |
| Exposed images, weak credential setup, or stale token roles | Unauthorized access | Backend authorization on every route, private storage, safe bootstrap, short token life, role lookup. |
| Missing authoritative requirements | Rework or invalid acceptance claim | Obtain approved SRS/WBS; mark this set draft until reconciled. |

No final architecture diagrams are generated here. The repository rule reserves source-backed Archify deliverables for release readiness; the local `docs/diagrams/README.md` holds that checklist when present.
