"""Build the impact and risk DEMO_MODE fixtures from Dev A's real hazard layers.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_impact_risk_fixtures.py

For every replay timestep, writes to api/data/demo/ (contracts.md §7):
- impact__results__<ts>.json   compact: non-ok rows only (app/impact/fixtures.py)
- risk__scores__<ts>.json      compact: no block polygons (app/risk/fixtures.py)
- risk__breakdown__<ts>.json
and once, risk__unscored-areas.json.

It calls the services' compute paths directly (not the DEMO_MODE branches), on the same hazard
layers and exposure infra that DEMO_MODE serves, so the fixtures round-trip exactly.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.demo import DEMO_DIR  # noqa: E402
from app.impact import fixtures  # noqa: E402
from app.impact import service as impact  # noqa: E402
from app.risk import blocks as block_data  # noqa: E402
from app.risk import fixtures as risk_fixtures  # noqa: E402
from app.risk import service as risk  # noqa: E402
from app.risk.engine import to_breakdown, to_collection  # noqa: E402
from app.schemas import REPLAY_TIMESTEPS  # noqa: E402


def write_json(path: Path, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def build(out_dir: Path) -> list[Path]:
    written = []
    ctx = risk.context()
    for ts in REPLAY_TIMESTEPS:
        results = impact.results(ts)
        path = out_dir / f"{fixtures.fixture_key(ts)}.json"
        write_json(path, fixtures.to_fixture(results))
        written.append(path)

        blocks = risk.evaluate(impact.hazard_layers(ts), results, ctx)
        for key, data in (
            (risk.fixture_key(ts), risk_fixtures.to_fixture(to_collection(blocks, ctx, ts))),
            (risk.breakdown_fixture_key(ts), to_breakdown(blocks, ctx, ts).model_dump(mode="json")),
        ):
            path = out_dir / f"{key}.json"
            write_json(path, data)
            written.append(path)

    unscored = block_data.unscored_areas(block_data.load_blocks())
    path = out_dir / f"{risk.UNSCORED_FIXTURE_KEY}.json"
    write_json(path, unscored.model_dump(mode="json"))
    written.append(path)
    return written


def main() -> None:
    written = build(DEMO_DIR)
    sizes = {p: p.stat().st_size for p in written}
    largest = max(sizes, key=sizes.get)
    print(f"{len(written)} fixtures, {sum(sizes.values()) / 1e6:.2f} MB total")
    print(f"largest: {largest.name} ({sizes[largest] / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
