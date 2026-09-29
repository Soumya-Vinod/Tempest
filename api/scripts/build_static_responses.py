"""Pre-render every GET the web app makes in DEMO_MODE into data/static/ (gzip + manifest.json).

Each body is fetched through the app itself (TestClient, the static middleware off), so it is
exactly what the route returns; app/core/static_responses.py then serves the file as it is.
Only 200 responses are stored; anything else is left to the live code. Run in the API image
build (api/Dockerfile) and, when wanted, locally:

    api\\.venv\\Scripts\\python api\\scripts\\build_static_responses.py [--out DIR]

The web app's requests (web/src/features/*): hazard layers (wind and surge per timestep, flood
at the first), the track and timeline; infra per type; impact results per timestep × horizon ×
non-ok status; risk scores and breakdown per timestep × horizon; countdown, triggers, departures,
insurance summary, unscored areas; and the Sentinel-1 validation reports.
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
os.environ["DEMO_MODE"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.core import static_responses  # noqa: E402
from app.core.static_responses import MANIFEST, request_key  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import REPLAY_TIMESTEPS  # noqa: E402

HORIZONS = (0, 24)
NON_OK = ("isolated", "cut", "at_risk")  # web/src/features/impact/style.ts
INFRA_TYPES = ("substation", "power_line", "road", "hospital", "shelter")


def web_requests() -> list[tuple[str, dict[str, str]]]:
    """(path, query) for every GET the web app makes, except the validation block reports."""
    reqs: list[tuple[str, dict[str, str]]] = [
        ("/api/hazard/timesteps", {}),
        ("/api/hazard/track", {}),
        ("/api/hazard/layers", {"hazard_type": "flood", "timestep": REPLAY_TIMESTEPS[0]}),
        ("/api/exposure/infra", {}),
        *(("/api/exposure/infra", {"infra_type": t}) for t in INFRA_TYPES),
        ("/api/impact/departures", {}),
        ("/api/risk/unscored-areas", {}),
        ("/api/insurance/summary", {}),
        ("/api/hazard/validation", {}),
    ]
    for ts in REPLAY_TIMESTEPS:
        for hazard_type in ("wind", "surge"):
            reqs.append(("/api/hazard/layers", {"hazard_type": hazard_type, "timestep": ts}))
        reqs.append(("/api/impact/countdown", {"timestep": ts}))
        reqs.append(("/api/insurance/triggers", {"timestep": ts}))
        for h in HORIZONS:
            for status in NON_OK:
                q = {"timestep": ts, "status": status, "horizon": str(h)}
                reqs.append(("/api/impact/results", q))
            for route in ("/api/risk/scores", "/api/risk/breakdown"):
                reqs.append((route, {"timestep": ts, "horizon": str(h)}))
    return reqs


def file_name(key: str) -> str:
    """Readable and unique: a slug of the key plus a short hash of it."""
    slug = re.sub(r"[^A-Za-z0-9=-]+", "_", key.removeprefix("/api/")).strip("_")[:120]
    return f"{slug}-{hashlib.sha1(key.encode()).hexdigest()[:10]}.json.gz"


def build(out: Path, reqs: list[tuple[str, dict[str, str]]] | None = None) -> dict:
    """Fetch `reqs` (default: web_requests() plus the validation block reports) into `out`.

    Writes to a sibling temp directory first and swaps it in, so a failed build leaves the
    previous one in place. Returns the manifest.
    """
    static_responses.STATIC_DIR = None  # always the live code
    client = TestClient(app)
    with_blocks = reqs is None
    reqs = web_requests() if reqs is None else list(reqs)

    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    manifest: dict[str, dict[str, str]] = {}
    skipped: list[str] = []
    i = 0
    while i < len(reqs):
        path, query = reqs[i]
        i += 1
        # identity: the raw body, which is then compressed once here.
        res = client.get(path, params=query, headers={"Accept-Encoding": "identity"})
        key = request_key(path, res.request.url.query.decode("latin-1"))
        if res.status_code != 200:
            skipped.append(f"{key} ({res.status_code})")
            continue
        if with_blocks and path == "/api/hazard/validation":
            for block in res.json().get("blocks", []):
                ident = block["identifier"]
                reqs.append((f"/api/hazard/validation/{ident}", {}))
                reqs.append((f"/api/hazard/validation/{ident}/metrics", {}))
        name = file_name(key)
        (tmp / name).write_bytes(gzip.compress(res.content, compresslevel=9, mtime=0))
        manifest[key] = {"file": name, "content_type": res.headers["content-type"]}

    (tmp / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    for s in skipped:
        print(f"  skipped (live code serves it): {s}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=API_DIR / "data" / "static")
    args = parser.parse_args()
    start = time.perf_counter()
    manifest = build(args.out)
    size = sum(f.stat().st_size for f in args.out.iterdir())
    print(
        f"{len(manifest)} responses, {size / 1e6:.1f} MB in {args.out} "
        f"({time.perf_counter() - start:.0f} s)"
    )


if __name__ == "__main__":
    main()
