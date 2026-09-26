"""Build deterministic DEMO_MODE fixtures for all hazard layers (wind, surge, flood).

Generates 75 fixtures (3 hazard types × 25 timesteps):
    api/data/demo/hazard__layers-<hazard_type>__<compact_ts>.json

Provenance & Contracts:
    These fixtures are generated artifacts produced by api/scripts/build_hazard_fixtures.py
    using the canonical Holland wind model, coastal storm surge model with SRTM terrain
    elevation, and static flood susceptibility index (contracts.md §7, §4.1). In DEMO_MODE=true,
    the hazard service loads these fixtures directly to guarantee zero-latency deterministic
    responses without dynamic recomputation.

Run from repo root:
    .venv\\Scripts\\python api/scripts/build_hazard_fixtures.py
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
from app.hazard.models import HazardType  # noqa: E402
from app.hazard.replay import (  # noqa: E402
    generate_hazard_layer,
    generate_surge_layer,
    generate_wind_layer,
    iso_to_compact_ts,
)
from app.schemas import REPLAY_TIMESTEPS, HazardLayerCollection  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("build_hazard_fixtures")

HAZARD_TYPES: tuple[HazardType, ...] = ("wind", "surge", "flood")


def write_fixture(path: Path, collection: HazardLayerCollection) -> None:
    """Serialize and write a contract-compliant HazardLayerCollection fixture with LF endings."""
    text = json.dumps(collection.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    # Verify LF line ending constraint (contracts.md §7)
    raw = path.read_bytes()
    if b"\r\n" in raw:
        raise ValueError(f"Fixture {path.name} contains CRLF line endings; must be LF only")


def build_hazard_fixtures(
    out_dir: Path = DEMO_DIR,
    hazard_types: tuple[HazardType, ...] = HAZARD_TYPES,
) -> dict[str, Path]:
    """Generate and write 75 deterministic hazard layer fixtures (3 types × 25 timesteps)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    for h_type in hazard_types:
        for timestep in REPLAY_TIMESTEPS:
            compact_ts = iso_to_compact_ts(timestep)
            key = f"hazard__layers-{h_type}__{compact_ts}"
            path = out_dir / f"{key}.json"

            if h_type == "wind":
                collection = generate_wind_layer(timestep)
            elif h_type == "surge":
                collection = generate_surge_layer(timestep)
            else:
                collection = generate_hazard_layer(h_type, timestep)

            write_fixture(path, collection)
            written[key] = path

    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic DEMO_MODE fixtures for all hazard layers (wind, surge, flood)"
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEMO_DIR,
        help=f"Directory to write fixtures (default: {DEMO_DIR})",
    )
    parser.add_argument(
        "--types",
        nargs="+",
        choices=["wind", "surge", "flood"],
        default=["wind", "surge", "flood"],
        help="Hazard types to generate (default: all)",
    )
    args = parser.parse_args()

    hazard_types = tuple(args.types)
    written = build_hazard_fixtures(out_dir=args.output_dir, hazard_types=hazard_types)

    total_size_mb = sum(p.stat().st_size for p in written.values()) / (1024 * 1024)
    print(
        f"Generated {len(written)} fixtures across {len(hazard_types)} "
        f"hazard types ({total_size_mb:.2f} MB total)"
    )


if __name__ == "__main__":
    main()
