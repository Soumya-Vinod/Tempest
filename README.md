# Tempest

AI-powered predictive risk and vulnerability modeling platform utilizing Google Earth Engine (GEE)
satellite feeds, real-time meteorological data, and Gemini 3.7 Flash's multimodal reasoning.

## Repository layout

| Path      | Purpose                                            |
|-----------|----------------------------------------------------|
| `api/`    | FastAPI backend (Python 3.12)                      |
| `web/`    | React + Vite + TypeScript frontend                 |
| `shared/` | Contract docs and JSON schemas shared by both devs |
| `docs/`   | Architecture and demo notes                        |

## Setup (Windows PowerShell)

### Prerequisites

- Python 3.12 (`py -3.12 --version`)
- Node.js 20+ (`node --version`)
- Git

### 1. Clone

```powershell
git clone <repo-url> Tempest
cd Tempest
```

### 2. Backend (`api/`)

```powershell
py -3.12 -m venv api\.venv
api\.venv\Scripts\python -m pip install --upgrade pip
api\.venv\Scripts\python -m pip install -r api\requirements.txt
Copy-Item api\.env.example api\.env   # then fill in your keys
```

Put the GEE service-account key at `api\secrets\gee-key.json` (the default `GEE_KEY_PATH`;
relative paths resolve against `api\`). That folder is git-ignored.

Run the API (no venv activation needed):

```powershell
api\.venv\Scripts\python -m uvicorn app.main:app --reload --app-dir api
```

Check it at <http://localhost:8000/health>. It reports `demo_mode` and a true/false flag for each
configured key, never the values. Interactive docs are at <http://localhost:8000/docs>.

Tests and lint:

```powershell
cd api
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
cd ..
```

### 3. Frontend (`web/`)

```powershell
cd web
npm install
Copy-Item .env.example .env
npm run dev
```

### Demo mode

`DEMO_MODE` defaults to `true`, which serves the curated fixtures in `api\data\demo\` instead of
calling external services. Set `DEMO_MODE=false` in `api\.env` for live calls.
