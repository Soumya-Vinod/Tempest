"""Regenerate tests/data/infra-sample.parquet from the hand-written Overpass samples here.

Run from api/:  .venv\\Scripts\\python -m tests.data.make_infra_sample
"""

import json
from pathlib import Path

from app.exposure import ingest

DATA = Path(__file__).parent


def load(name: str) -> dict:
    return json.loads((DATA / f"overpass-{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    clip = ingest.clip_polygon(load("boundary"), [1])
    records = []
    for infra_type, sample in [
        ("substation", "power"),
        ("power_line", "power"),
        ("road", "road"),
        ("hospital", "hospital"),
        ("shelter", "shelter"),
    ]:
        found = ingest.normalise(infra_type, load(sample))
        if infra_type == "hospital":
            found = ingest.dedupe_health(found)
        records += ingest.clip_records(found, clip)
    ingest.write_infra(records, DATA / "infra-sample.parquet")
    print(f"{len(records)} features")


if __name__ == "__main__":
    main()
