# Tempest

AI-powered predictive risk and vulnerability modeling platform utilizing Google Earth Engine (GEE)
satellite feeds, real-time meteorological data, and Gemini 3.7 Flash's multimodal reasoning.

## Repository layout

| Path      | Purpose                                            |
|-----------|----------------------------------------------------|
| `api/`    | FastAPI backend (Python 3.12)                      |
| `web/`    | React + Vite + TypeScript frontend                 |
| `shared/` | `contracts.md`, the API contract for both devs     |
| `docs/`   | Architecture and demo notes                        |

## Setup (Windows PowerShell)

### Prerequisites

- Python 3.12 (`py -3.12 --version`)
- Node.js 20.19+ or 22.13+ (`node --version`; matches `engines` in `web/package.json`)
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
api\.venv\Scripts\python -m uvicorn app.main:app --reload --reload-dir api/app --app-dir api
```

`--reload-dir api/app` limits the file watcher to backend code, so it doesn't also watch
`web/node_modules` and the rest of the repo.

Check it at <http://localhost:8000/health>. It reports `demo_mode` and a true/false flag for each
configured key, never the values. Interactive docs are at <http://localhost:8000/docs>.

Tests and lint:

```powershell
cd api
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
cd ..
```

OSM infrastructure and road graph (exposure module). Outputs in `api\data\processed\` are
git-ignored; regenerate them with:

```powershell
api\.venv\Scripts\python api\scripts\ingest_osm.py            # reuses cached downloads
api\.venv\Scripts\python api\scripts\ingest_osm.py --refresh  # re-downloads from Overpass
```

This writes `infra.parquet` (InfraFeatures, clipped to South 24 Parganas + Kolkata) and
`roads.graphml` (road graph with ferries and travel times). Raw Overpass responses are cached in
`api\data\raw\` and the osmnx cache in `api\data\cache\osmnx\`, both git-ignored.

### 3. Frontend (`web/`)

React + Vite + TypeScript, Tailwind v4, MapLibre with the keyless OpenFreeMap Positron basemap, and
deck.gl overlays.

```powershell
cd web
npm install
npm run dev
```

Open <http://localhost:5173>. Start the API first (step 2). In dev, Vite proxies `/api` and
`/health` to `http://127.0.0.1:8000`, so no `.env` is needed. The side panel shows backend health
and demo mode.

Type-check, lint and build:

```powershell
npx tsc --noEmit -p tsconfig.app.json
npm run lint
npm run build
cd ..
```

For a production build against a deployed API, copy `.env.example` to `.env` and set
`VITE_API_BASE_URL` before `npm run build`.

### Demo mode

`DEMO_MODE` defaults to `true`, which serves the curated fixtures in `api\data\demo\` instead of
calling external services. Set `DEMO_MODE=false` in `api\.env` for live calls.
