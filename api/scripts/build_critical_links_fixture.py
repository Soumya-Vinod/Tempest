"""Build the critical links DEMO_MODE fixture (v1.4 change, pending Dev A).

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_critical_links_fixture.py

Needs the road graph (api/data/processed/roads.graphml): it re-runs the last safe departure
routing to get each route's OSM way ids, and stops if that no longer reproduces the committed
api/data/demo/impact__departures.json (run build_departures_fixture.py first). Labels, types and
geometry come from the committed exposure road features, blocks from
api/data/reference/s24p_blocks.geojson. Writes api/data/demo/impact__critical-links.json
(app/impact/critical_links.py); tests/test_critical_links.py fails if it is out of date.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.demo import DEMO_DIR  # noqa: E402
from app.impact import countdown, critical_links, departures  # noqa: E402
from app.schemas import LANDFALL_TIMESTEP, REPLAY_TIMESTEPS  # noqa: E402

TOP = 5
REPORT_HOURS = (27, 9)  # before landfall: the top links printed after the build


def main() -> None:
    sys.stdout.reconfigure(errors="replace")  # labels hold "→"; a cp1252 console can't print it
    start = time.perf_counter()
    data = critical_links.build()
    path = DEMO_DIR / f"{critical_links.FIXTURE_KEY}.json"
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    dep = countdown._read(departures.FIXTURE_KEY)
    landfall = REPLAY_TIMESTEPS.index(LANDFALL_TIMESTEP)
    for hours in REPORT_HOURS:
        ts = REPLAY_TIMESTEPS[landfall - hours // 3]
        for h in (0, 24):
            body = critical_links.rank(data, dep, ts, h)
            print(f"T-{hours} (horizon {h}): {len(body['links'])} links")
            for x in body["links"][:TOP]:
                before = landfall - REPLAY_TIMESTEPS.index(x["earliest_deadline"])
                print(f"  {x['label']} · {x['facility_count']} · before T-{before * 3}")
    print(f"{len(data['routes'])} routes, {len(data['links'])} ways")
    size = path.stat().st_size // 1024
    print(f"wrote {path.name} ({size} KB) in {time.perf_counter() - start:.0f} s")


if __name__ == "__main__":
    main()
