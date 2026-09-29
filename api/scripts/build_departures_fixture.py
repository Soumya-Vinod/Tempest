"""Build the last safe departure DEMO_MODE fixture (v1.3 change, pending Dev A).

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_departures_fixture.py

Needs the road graph (api/data/processed/roads.graphml, scripts/ingest_osm.py) and reads the
hazard layers plus the committed impact and exposure fixtures. Writes
api/data/demo/impact__departures.json (app/impact/departures.py). Run it after
build_impact_risk_fixtures.py; tests/test_departures.py fails if it is out of date.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.demo import DEMO_DIR  # noqa: E402
from app.impact import departures  # noqa: E402


def main() -> None:
    start = time.perf_counter()
    data = departures.build()
    path = DEMO_DIR / f"{departures.FIXTURE_KEY}.json"
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    for d in data["departures"]:
        minutes = round(d["travel_time_s"] / 60) if d["travel_time_s"] is not None else None
        destination = (d["destination_name"] or "-")[:36]
        print(
            f"{d['name'][:34]:34} {d['deadline'] or '-':21} {destination:36}"
            f" {minutes if minutes is not None else '-':>4} min ferry={d['uses_ferry']}"
            f" usual={d['usual_destination_name']} note={d['note']}"
        )
    print(f"wrote {path.name} in {time.perf_counter() - start:.0f} s")


if __name__ == "__main__":
    main()
