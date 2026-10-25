# Operational history and human review (TASK-12)

Admin and Operator may read history, export CSV and review predictions. All routes require a bearer token. The original AI `predicted_status`, confidence and model version remain immutable. A human review appends a separate row with actor, UTC time, status, note and monotonic revision number. The latest review becomes `effective_status`; counts and alerts use that value. `unknown` never contributes to confirmed availability. An audit log row is committed with each review.

## PowerShell examples

After following [AUTH.md](AUTH.md) and [SNAPSHOT_INFERENCE.md](SNAPSHOT_INFERENCE.md), obtain a token and set `$base`:

```powershell
$base = 'http://127.0.0.1:8000/api/v1'
$login = Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType 'application/json' -Body (@{ username = 'operator'; password = (Read-Host 'Password') } | ConvertTo-Json)
$token = $login.access_token
$headers = @{ Authorization = "Bearer $token" }
$history = Invoke-RestMethod -Uri "$base/snapshots?page=1&page_size=25" -Headers $headers
$snapshot = Invoke-RestMethod -Uri "$base/snapshots/$($history.items[0].snapshot_id)" -Headers $headers
$prediction = $snapshot.predictions[0]
$reviewHeaders = @{ Authorization = "Bearer $token"; 'If-Match' = '"0"' }
$review = Invoke-RestMethod -Method Post -Uri "$base/predictions/$($prediction.prediction_id)/reviews" -Headers $reviewHeaders -ContentType 'application/json' -Body '{"reviewed_status":"empty","note":"Operator checked image"}'
Invoke-RestMethod -Uri "$base/predictions/$($prediction.prediction_id)/reviews" -Headers $headers
curl.exe -H "Authorization: Bearer $token" -o history.csv "$base/snapshots/export.csv"
```

Use the returned `review_version` in the quoted `If-Match` header when a prediction already has reviews. If another operator reviews first, the request returns 409 `REVIEW_CONFLICT`. Reload the snapshot/prediction before deciding whether to submit a new review. Missing `If-Match` returns 428. Only `empty`, `occupied` and `unknown` are valid review statuses.

History supports `camera_id`, inclusive `from`, exclusive `to` (timezone-aware ISO 8601 capture timestamps), `page` (1-based) and `page_size` (1–100; default 25). CSV uses the same camera/time filters without pagination. Its exact column order is in [API_SPEC.md](API_SPEC.md). The CSV contains one row per stored prediction; it shows both AI and effective labels plus latest reviewer ID and time. A snapshot with no spots remains visible in history but creates no CSV data row. Review notes are excluded from CSV. The response is private and should be opened only by authorized users.

`FULL` requires fresh evidence and all captured spots effectively occupied; one `unknown` prevents it. `STALE` uses the snapshot's capture time and `STALE_AFTER_SECONDS`, taking precedence over `FULL`. Historical summary alerts are calculated at request time and can change as the clock advances or reviews arrive. The summary's `reviewed_spots` is the number of spots with at least one review, rather than the total number of review events.

Apply migration `0006_review_versions` before running the new routes:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.\.venv\Scripts\python.exe -m pytest -q
```

Concurrent review control uses a conditional SQL update on `predictions.review_version`. The review row and audit row commit in the same transaction. Migration `0006` numbers any pre-existing review rows in chronological `(reviewed_at, id)` order. PostgreSQL deployment and multi-process concurrency should also be verified in the target environment; automated API tests use disposable SQLite databases.
