"""Build the impact and risk DEMO_MODE fixtures from Dev A's real hazard layers.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_impact_risk_fixtures.py

For every replay timestep, writes to api/data/demo/ (contracts.md §7):
- impact__results__<ts>.json   compact: non-ok rows only (app/impact/fixtures.py)
- risk__scores__<ts>.json      compact: no block polygons (app/risk/fixtures.py)
- risk__breakdown__<ts>.json
and once, risk__unscored-areas.json.

At horizon 24 (v1.3 change, pending Dev A; on the expected hazard, app/impact/horizon.py), each
distinct result is stored once, deduplicated by content hash with the timestep factored out:
impact__results-h24-<hash>.json, risk__scores-h24-<hash>.json, risk__breakdown-h24-<hash>.json,
plus an index per resource (<resource>-h24-index.json: timestep -> file). Hash files no index
refers to any more are deleted.

It calls the services' compute paths directly (not the DEMO_MODE branches), on the same hazard
layers and exposure infra that DEMO_MODE serves, so the fixtures round-trip exactly.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.demo import DEMO_DIR  # noqa: E402
from app.impact import fixtures  # noqa: E402
from app.impact import horizon as fh  # noqa: E402
from app.impact import service as impact  # noqa: E402
from app.risk import blocks as block_data  # noqa: E402
from app.risk import fixtures as risk_fixtures  # noqa: E402
from app.risk import service as risk  # noqa: E402
from app.risk.engine import to_breakdown, to_collection  # noqa: E402
from app.schemas import REPLAY_TIMESTEPS  # noqa: E402


def write_json(path: Path, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def build_h24(out_dir: Path, ctx) -> list[Path]:
    """The deduplicated horizon-24 fixtures and their indexes."""
    h = fh.FORECAST_HORIZON_H
    prefixes = {
        "impact": impact.H24_PREFIX,
        "scores": risk.SCORES_H24_PREFIX,
        "breakdown": risk.BREAKDOWN_H24_PREFIX,
    }
    indexes: dict[str, dict[str, str]] = {name: {} for name in prefixes}
    stored: dict[str, dict] = {}
    for ts in REPLAY_TIMESTEPS:
        results = impact.results(ts, h)
        blocks = risk.evaluate(impact.hazard_layers(ts, h), results, ctx)
        data = {
            "impact": fixtures.to_fixture(results),
            "scores": risk_fixtures.to_fixture(to_collection(blocks, ctx, ts, h)),
            "breakdown": to_breakdown(blocks, ctx, ts, h).model_dump(mode="json"),
        }
        for name, prefix in prefixes.items():
            key, neutral = fh.dedup_key(prefix, data[name], ts)
            stored[key] = neutral
            indexes[name][ts] = key
    written = []
    for key, neutral in stored.items():
        path = out_dir / f"{key}.json"
        write_json(path, neutral)
        written.append(path)
    for name, prefix in prefixes.items():
        path = out_dir / f"{fh.index_key(prefix)}.json"
        write_json(path, {"horizon_h": h, "files": indexes[name]})
        written.append(path)
        # Hash files from earlier runs that no index refers to any more.
        for old in out_dir.glob(f"{prefix}-*.json"):
            if old.stem not in stored and old.stem != fh.index_key(prefix):
                old.unlink()
    return written


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

    written += build_h24(out_dir, ctx)

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
