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
- PowerShell for the commands below

PostgreSQL is the planned database, but it is not needed for this skeleton or its health check. PyTorch and OpenCV are optional AI dependencies and are not needed for the import smoke test.

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

Install optional computer vision dependencies only when needed: `pip install -e '.[vision,dev]'`. This does not download a dataset or model weights.

## Configuration and data

Copy `.env.example` values into local files when a later task needs them. The current skeleton does not read environment variables or connect to a database. Never commit `.env` files, secrets, datasets, checkpoints, or other large model artifacts. Keep ground truth, model predictions, and human review data separate in future workflows.

## Development checks

From the repository root, `powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1` runs installed checks. Install frontend and Python development dependencies first. See [docs/architecture.md](docs/architecture.md) for current boundaries.
