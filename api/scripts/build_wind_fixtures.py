"""Build deterministic wind DEMO_MODE fixtures using the Holland wind model.

Provenance & Contracts:
    hazard__layers-wind__<YYYYMMDDTHHMMZ>.json fixtures are generated artifacts
    produced by api/scripts/build_wind_fixtures.py using the canonical Holland parametric
    wind model (contracts.md §7, §4.1). In DEMO_MODE=true, the hazard service loads
    these fixtures directly to guarantee zero-latency deterministic responses without
    dynamic recomputation.

Run from the repo root:
    .venv\\Scripts\\python api/scripts/build_wind_fixtures.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure api directory is in Python path when executed directly
API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.core.demo import DEMO_DIR  # noqa: E402
from app.hazard.replay import generate_wind_layer, iso_to_compact_ts  # noqa: E402
from app.schemas import REPLAY_TIMESTEPS, HazardLayerCollection  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("build_wind_fixtures")


def write_wind_fixture(path: Path, collection: HazardLayerCollection) -> None:
    """Serialize and write a contract-compliant HazardLayerCollection fixture with LF endings."""
    text = json.dumps(collection.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    # Verify LF line ending constraint (contracts.md §7)
    raw = path.read_bytes()
    if b"\r\n" in raw:
        raise ValueError(f"Fixture {path.name} contains CRLF line endings; must be LF only")


def build_wind_fixtures(out_dir: Path = DEMO_DIR) -> dict[str, Path]:
    """Generate and write 25 deterministic wind hazard layer fixtures for Amphan replay timeline."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    for timestep in REPLAY_TIMESTEPS:
        compact_ts = iso_to_compact_ts(timestep)
        key = f"hazard__layers-wind__{compact_ts}"
        path = out_dir / f"{key}.json"

        collection = generate_wind_layer(timestep)
        write_wind_fixture(path, collection)
        written[key] = path

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate DEMO_MODE wind hazard fixtures.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEMO_DIR,
        help="Target directory for generated fixtures (default: api/data/demo)",
    )
    args = parser.parse_args()

    logger.info("Generating 25 deterministic wind layer fixtures in %s...", args.out_dir)
    fixtures = build_wind_fixtures(args.out_dir)

    print("\nGenerated Wind Hazard Fixtures:")
    print(f"{'Filename':<46} {'Features':>8} {'Size (KB)':>10} {'Min (m/s)':>10} {'Max (m/s)':>10}")
    print("-" * 90)

    for _key, path in fixtures.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        features = data["features"]
        speeds = [f["properties"]["value"] for f in features]
        min_v = min(speeds)
        max_v = max(speeds)
        size_kb = path.stat().st_size / 1024.0
        print(f"{path.name:<46} {len(features):>8} {size_kb:>10.1f} {min_v:>10.1f} {max_v:>10.1f}")

    print(f"\nSuccessfully generated {len(fixtures)} fixtures in {args.out_dir}.\n")


if __name__ == "__main__":
    main()
