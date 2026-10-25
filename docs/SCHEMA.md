# Database schema setup (TASK-08)

The SQLAlchemy 2.x models live in `backend/app/models.py`. Alembic migration `0002_smart_parking_schema` adds the nine persistence tables documented in [ERD.md](ERD.md), including `polygon_revisions` so a prediction retains the exact geometry used at inference time. `0001_initial` remains the empty baseline. This schema creates no users, lots, cameras, images, or predictions by itself.

For local PostgreSQL 16, configure the ignored root `.env` with `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `DATABASE_URL` as described in the root README. From the repository root in PowerShell:

```powershell
docker compose -f .\infrastructure\compose.yaml up -d db
cd backend
.\.venv\Scripts\python.exe -m app.db
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

Run `alembic upgrade head` against a fresh or backed-up database. Alembic does not delete the PostgreSQL volume. This migration's downgrade drops the new tables and their data, so use it only on a disposable database.

The automated schema tests create and migrate a fresh SQLite file under pytest's temporary directory for each test; foreign-key enforcement is enabled. They exercise relationships, review provenance, polygon validation, SQL constraints, and restricted deletion:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_models.py tests/test_migrations.py -q
```

SQLite proves the portable model/migration behavior, while production uses PostgreSQL. For a PostgreSQL migration check, create a **separate disposable database**, set `DATABASE_URL` to that database for the current shell, run `alembic upgrade head`, and inspect `alembic current`; do not target the development database by accident. PostgreSQL stores `DateTime(timezone=True)` as `TIMESTAMP WITH TIME ZONE`. Images remain in private storage: `snapshots.original_key` stores an opaque reference, never image bytes.

The SQLAlchemy polygon type rejects malformed/out-of-range/self-intersecting normalized points on ORM and SQLAlchemy Core writes. Raw SQL can bypass Python validation, so any direct database writer must validate the same `[0,1]` geometry contract. `audit_logs.target_type` and `target_id` identify a generic target and do not form a polymorphic foreign key; `actor_id` references `users`. No application endpoints, authorization policy, or event-writing service are implemented in this task.
