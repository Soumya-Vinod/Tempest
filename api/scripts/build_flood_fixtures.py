"""Build deterministic flood susceptibility DEMO_MODE fixtures using the flood model.

Provenance & Contracts:
    hazard__layers-flood__<YYYYMMDDTHHMMZ>.json fixtures are generated artifacts
    produced by api/scripts/build_flood_fixtures.py using the multi-criteria flood
    susceptibility model combining SRTM/Copernicus elevation, slope, topographic depression,
    JRC surface water occurrence, IMERG rainfall climatology, and ESA WorldCover weighting
    (contracts.md §7, §4.1). In DEMO_MODE=true, the hazard service loads these fixtures
    directly to guarantee zero-latency deterministic responses without dynamic recomputation.

Run from the repo root:
    .venv\\Scripts\\python api/scripts/build_flood_fixtures.py
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
from app.hazard.replay import generate_flood_layer, iso_to_compact_ts  # noqa: E402
from app.schemas import REPLAY_TIMESTEPS, HazardLayerCollection  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("build_flood_fixtures")


def write_flood_fixture(path: Path, collection: HazardLayerCollection) -> None:
    """Serialize and write a contract-compliant HazardLayerCollection fixture with LF endings."""
    text = json.dumps(collection.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    # Verify LF line ending constraint (contracts.md §7)
    raw = path.read_bytes()
    if b"\r\n" in raw:
        raise ValueError(f"Fixture {path.name} contains CRLF line endings; must be LF only")


def build_flood_fixtures(out_dir: Path = DEMO_DIR) -> dict[str, Path]:
    """Generate and write 25 deterministic flood susceptibility fixtures for Amphan replay."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    for timestep in REPLAY_TIMESTEPS:
        compact_ts = iso_to_compact_ts(timestep)
        key = f"hazard__layers-flood__{compact_ts}"
        path = out_dir / f"{key}.json"

        collection = generate_flood_layer(timestep)
        write_flood_fixture(path, collection)
        written[key] = path

    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build deterministic DEMO_MODE fixtures for flood susceptibility"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEMO_DIR,
        help=f"Directory to write fixtures (default: {DEMO_DIR})",
    )
    args = parser.parse_args()

    written = build_flood_fixtures(out_dir=args.output_dir)
    total_size_mb = sum(p.stat().st_size for p in written.values()) / (1024 * 1024)
    print(
        f"Generated {len(written)} flood susceptibility fixtures "
        f"across all replay timesteps ({total_size_mb:.2f} MB total)"
    )


if __name__ == "__main__":
    main()
