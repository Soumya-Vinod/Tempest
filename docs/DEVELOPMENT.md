# Development

Setup, checks and the scripts that build Tempest's data. For deployment (Render for the API,
Vercel for the web app), see [deploy.md](../deploy.md). The API contract between the two developers is
[shared/contracts.md](../shared/contracts.md).

## Repository layout

| Path      | Purpose                                                                  |
|-----------|--------------------------------------------------------------------------|
| `api/`    | FastAPI backend (Python 3.12)                                            |
| `web/`    | React + Vite + TypeScript frontend                                       |
| `shared/` | `contracts.md`, the API contract for both devs                           |
| `docs/`   | Hazard model notes (Dev A) and this guide                                |

## Prerequisites (Windows PowerShell)

- Python 3.12 (`py -3.12 --version`)
- Node.js 20.19+ or 22.13+ (`node --version`; matches `engines` in `web/package.json`)
- Git

```powershell
git clone <repo-url> Tempest
cd Tempest
```

## Backend (`api/`)

```powershell
py -3.12 -m venv api\.venv
api\.venv\Scripts\python -m pip install --upgrade pip
api\.venv\Scripts\python -m pip install -r api\requirements-dev.txt   # runtime + pytest, ruff
Copy-Item api\.env.example api\.env   # then fill in your keys
```

`requirements.txt` holds the runtime dependencies only (the API image installs just these);
`requirements-dev.txt` adds pytest and ruff.

Put the GEE service-account key at `api\secrets\gee-key.json` (the default `GEE_KEY_PATH`;
relative paths resolve against `api\`). That folder is git-ignored. It is only needed to rebuild
hazard reference data, not to run the demo.

Run the API (no venv activation needed):

```powershell
api\.venv\Scripts\python -m uvicorn app.main:app --reload --reload-dir api/app --app-dir api
```

`--reload-dir api/app` limits the file watcher to backend code, so it doesn't also watch
`web/node_modules` and the rest of the repo.

Check it at <http://localhost:8000/health>. It reports `demo_mode` and a true/false flag for each
configured key, never the values. Interactive docs are at <http://localhost:8000/docs>.

### Demo mode

`DEMO_MODE` defaults to `true`: every route is served from the committed fixtures in
`api\data\demo\` and the reference files in `api\data\reference\`, with no external calls.
Set `DEMO_MODE=false` in `api\.env` to compute live. Advisory generation uses a cached model
response when one exists for the block and timestep; otherwise it needs `GEMINI_API_KEY` (and
optionally `GROQ_API_KEY` for the fallback), or it returns 503. Dispatch sends for real in both
modes and needs a `DISPATCH_PIN` (see `api\.env.example`).

### Tests and lint

```powershell
cd api
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check . --exclude app/hazard --exclude tests/test_hazard.py
cd ..
```

`app/hazard/` and `tests/test_hazard.py` belong to Dev A: don't run `ruff format` on them.
`tests/test_smoke_demo.py` runs every route for all 25 timesteps the way the API image does
(DEMO_MODE, no keys, no `data/raw` or `data/processed`).

## Data pipeline (scripts in `api\scripts\`)

Raw downloads are cached in `api\data\raw\` and generated data in `api\data\processed\` (both
git-ignored). Everything the demo serves is committed in `api\data\demo\` and
`api\data\reference\`.

OSM infrastructure and road graph (exposure):

```powershell
api\.venv\Scripts\python api\scripts\ingest_osm.py            # reuses cached downloads
api\.venv\Scripts\python api\scripts\ingest_osm.py --refresh  # re-downloads from Overpass
api\.venv\Scripts\python api\scripts\build_exposure_fixtures.py
```

`ingest_osm.py` writes `infra.parquet` (InfraFeatures, clipped to South 24 Parganas + Kolkata,
with river channels up to 4 km wide filled in) and `roads.graphml` (road graph with ferries and
travel times). The Overpass cache is keyed by file name only: after changing a query in
`api\app\exposure\ingest.py`, delete its `overpass-*.json` file or pass `--refresh`.

Block reference data for risk (sources and verification status are in each file's header):

```powershell
api\.venv\Scripts\python api\scripts\build_s24p_blocks.py       # block polygons and areas
api\.venv\Scripts\python api\scripts\build_s24p_population.py   # population_2011
api\.venv\Scripts\python api\scripts\build_s24p_block_names.py  # Bengali and Hindi names
api\.venv\Scripts\python api\scripts\build_s24p_land.py         # land polygon (after ingest_osm.py)
```

Demo fixtures built from Dev A's hazard layers:

```powershell
api\.venv\Scripts\python api\scripts\build_impact_risk_fixtures.py  # impact, risk, breakdown (0 and 24 h)
api\.venv\Scripts\python api\scripts\build_insurance_fixtures.py    # insurance triggers and summary
api\.venv\Scripts\python api\scripts\build_countdown_fixture.py     # action countdown, key moments
api\.venv\Scripts\python api\scripts\build_departures_fixture.py    # last safe departure (needs the road graph)
```

`build_countdown_fixture.py` reads only the committed impact and risk fixtures, so run it after
`build_impact_risk_fixtures.py`; `tests/test_countdown.py` fails if it is out of date. The same
goes for `build_departures_fixture.py` and `tests/test_departures.py`.

Advisory drafts (live model calls; paced, capped by `--max-calls`):

```powershell
api\.venv\Scripts\python api\scripts\build_advisory_fixtures.py --pairs "Namkhana:T-33,Gosaba:T-27" --allow-groq-fallback
```

Telegram chat id for dispatch: `api\.venv\Scripts\python api\scripts\telegram_chat_ids.py`.

## Frontend (`web/`)

React + Vite + TypeScript, Tailwind v4, MapLibre with the keyless OpenFreeMap Positron basemap,
and deck.gl overlays.

```powershell
cd web
npm install
npm run dev
```

Open <http://localhost:5173>. Start the API first. In dev, Vite proxies `/api` and `/health` to
`http://127.0.0.1:8000`, so no `.env` is needed.

Type-check, lint and build:

```powershell
npx tsc -b --noEmit
npm run lint
npm run build
cd ..
```

For a production build against an API on another origin, copy `.env.example` to `.env` and set
`VITE_API_BASE_URL` before `npm run build`. The Vercel setup in `web/vercel.json` forwards `/api`
and `/health` to the API, so it serves the API on the same origin and leaves that unset.

## Updating "About the data"

The data sources, models and limits shown in the app and summarised in the README live in one
file: `web/src/features/about/sources.ts`. Update it (and the README summary) when an input
changes.
