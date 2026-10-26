# Smart Parking Management System

Solo-developed Software Engineering capstone project. This repository currently contains the application skeleton; parking workflows, persistence, and AI behavior are future tasks. Follow an approved Software Requirements Specification (SRS) when one is available. `DATT_AI_HANDOFF_2026-10-24.md`, if added, is preliminary context and does not establish approval.

## Layout

| Path | Purpose |
| --- | --- |
| `frontend/` | React, Vite, and TypeScript application |
| `backend/` | FastAPI application and API tests |
| `ai/` | Installable Python AI package and tests |
| `docs/` | Project documentation |
| `infrastructure/` | Deployment configuration when needed |
| `scripts/` | Local development checks |

## Prerequisites

- Node.js 20.19+ or 22.12+ and npm
- Python 3.11+
- Docker Desktop with Docker Compose for local PostgreSQL 16
- PowerShell for the commands below

The frontend and backend can start without Docker. `/health` checks the API process without opening a database connection. PyTorch and OpenCV remain optional AI dependencies.

## Local PostgreSQL setup

From the repository root, create a local configuration file:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set `POSTGRES_USER` and `POSTGRES_PASSWORD` to local values. Set `DATABASE_URL` to `postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/smart_parking`, replacing `USER` and `PASSWORD` with those same values. If the password contains reserved URL characters, URL-encode it in `DATABASE_URL`. If you change `POSTGRES_PORT`, use that port in the URL too. The `.env` file is ignored by Git.

Start Docker Desktop, then run:

```powershell
docker compose --env-file .env -f infrastructure/compose.yaml up -d db
docker compose --env-file .env -f infrastructure/compose.yaml ps
```

If `docker compose` is unavailable but `docker-compose` is installed, replace `docker compose` with `docker-compose`. PostgreSQL is bound to `127.0.0.1` only. Its named volume survives `stop` and ordinary `down`; do not use `down -v` unless you intentionally want to delete local data.

## Frontend

```powershell
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`). To check the frontend:

```powershell
npm run lint
npm run format:check
npm run build
```

## Backend

From the repository root:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open `http://localhost:8000/health`. Expected response: `{"status":"ok"}`. Run checks with:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

With PostgreSQL running, open a second PowerShell window and verify the connection and baseline migration from `backend/` while Uvicorn runs in the first window:

```powershell
.\.venv\Scripts\python.exe -m app.db
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.\.venv\Scripts\python.exe -m alembic -c alembic.ini current
Invoke-RestMethod 'http://127.0.0.1:8000/health?check_db=true'
```

`/health?check_db=true` returns `{"status":"ok","database":"ready"}` when the SQL query succeeds, or HTTP 503 with a configuration or connection message. The API itself can start before PostgreSQL. To stop only the database container, run `docker compose --env-file .env -f infrastructure/compose.yaml stop db` from the root.

## AI package

From the repository root:

```powershell
cd ai
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Install optional computer vision dependencies only when needed: `pip install -e '.[vision,dev]'`. Dataset auditing uses the smaller `audit` extra below. Neither command downloads a dataset or model weights.

### Local PKLot dataset and audit

The extracted dataset belongs in ignored `ai/data/raw/PKLot/`. If you have a local `PKLot.tar.gz` archive at the repository root, extract it from PowerShell when you are ready:

```powershell
New-Item -ItemType Directory -Force .\ai\data\raw | Out-Null
tar -xzf .\PKLot.tar.gz -C .\ai\data\raw
```

The archive already contains a top-level `PKLot/` folder, so this places full images and XML under `ai/data/raw/PKLot/PKLot/` and segmented images under `ai/data/raw/PKLot/PKLotSegmented/`. If you already have an extracted copy elsewhere, copy the **contents** of its top-level `PKLot` directory from the repository root:

```powershell
$source = Read-Host 'Absolute path to your extracted PKLot folder (containing PKLot and PKLotSegmented)'
New-Item -ItemType Directory -Force .\ai\data\raw\PKLot | Out-Null
Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination .\ai\data\raw\PKLot\ -Recurse
```

Use the path to your actual extracted copy; no source path is assumed here. Keep the original archive and extracted files unmodified. Both are ignored by Git.

The existing TASK-04 inspector reads `PKLOT_DATASET_ROOT` from the current process, defaulting to `ai/data/raw/PKLot/`. For a different location, set it in PowerShell before running a full audit:

```powershell
$env:PKLOT_DATASET_ROOT = (Resolve-Path .\ai\data\raw\PKLot).Path
cd ai
.\.venv\Scripts\python.exe -m pip install -e '.[audit,dev]'
.\.venv\Scripts\python.exe .\scripts\inspect_dataset.py --root .\data\raw\PKLot --output-dir .\data\audit\pklot
```

The audit validates image/XML pairing, decoding, camera and capture-day metadata, spot IDs, polygons, bounds, and empty/occupied labels. It writes `stats.json`, `samples.csv`, `errors.csv`, and up to three overlays labeled as **ground truth** under the ignored output directory. A full directory audit can take time. Before extraction, inspect a bounded archive sample from the repository root:

```powershell
.\ai\.venv\Scripts\python.exe .\ai\scripts\inspect_dataset.py --archive .\PKLot.tar.gz --max-samples 3 --output-dir .\ai\data\audit\pklot-archive
```

The three-pair archive sample was checked locally: 208 empty and 20 occupied polygons, with no errors in those three pairs. These are **sample ground-truth counts**, not full-dataset statistics or model metrics. The inspector does not train a model, generate crops, or use annotations as predictions. See [dataset documentation](docs/DATASET.md) for source, license, validation limits, and output details.

### Prepare PKLot manifests

After extracting and auditing the full dataset, generate leakage-safe train/validation/test manifests for one camera:

```powershell
cd ai
.\.venv\Scripts\python.exe -m pip install -e '.[audit,dev]'
cd ..
.\ai\.venv\Scripts\python.exe .\ai\scripts\prepare_dataset.py --camera UFPR04 --seed 42
```

The script reads `PKLOT_DATASET_ROOT` or defaults to `ai/data/raw/PKLot/`. It writes ignored manifests, split counts, and visual ROI samples under `ai/data/processed/pklot/`. See [dataset preparation details](docs/DATASET.md#roi-preparation-and-leakage-safe-manifests-task-05). The three-image archive sample is insufficient for this step; use an extracted dataset with at least three independent capture-day groups. No model is trained.

## Train and evaluate the PKLot classifier

After preparing full, validated PKLot manifests, run from `ai/`:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[audit,train,dev]'
.\.venv\Scripts\python.exe .\scripts\train.py --config .\configs\train.yaml --device auto
.\.venv\Scripts\python.exe .\scripts\evaluate.py --checkpoint .\runs\pklot\best.pt --device auto
```

For a dependency and pipeline check without real data or pretrained weight download, run `.\.venv\Scripts\python.exe .\scripts\train.py --smoke --device cpu`. Its output is explicitly synthetic and is not a PKLot model result. See [training and evaluation details](docs/TRAINING.md) for configuration, path overrides, Windows/Kaggle use, metrics, baseline, and saved artifacts.

## Configuration and data

In development (the default), the backend loads the root `.env` file and process environment variables override it. Set `CORS_ORIGINS` to a JSON array of exact browser origins, such as `["http://localhost:5173"]`; an empty list allows no cross-origin requests. For production, set `APP_ENV=production` and supply `DATABASE_URL` and any `CORS_ORIGINS` through process environment variables. Production ignores the local `.env` file and requires `DATABASE_URL` at startup. Never commit `.env` files, secrets, datasets, checkpoints, or other large model artifacts. Keep ground truth, model predictions, and human review data separate in future workflows.

## Development checks

From the repository root, `powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1` runs installed checks. Install frontend and Python development dependencies first. See [docs/architecture.md](docs/architecture.md) for current boundaries.

## Future architecture diagrams

The final architecture diagrams are **pending**. At release readiness, inspect the implemented repository and use the project-local [Archify skill](.agents/skills/archify/SKILL.md) to create source-backed diagrams in `docs/diagrams/`. Planned subjects are system architecture, the AI/ML pipeline, and the end-to-end parking workflow. Diagram nodes and links must reflect implemented code; planned components and unverified deployment or model performance are omitted until established.

See the [diagram generation checklist](docs/diagrams/README.md) for the exact Archify workflow, setup check, future SVG/HTML deliverables, and GitHub link checks. Add the main `architecture.svg` image and links to the other diagrams here only after those files have been generated and verified.
