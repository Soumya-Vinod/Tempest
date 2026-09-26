"""Build and verify deterministic Sentinel-1 validation DEMO_MODE fixture (Phase 12).

Provenance & Contracts:
    hazard__validation-sentinel.json is a generated validation benchmark artifact
    comparing the Tempest deterministic hazard models (coupled storm surge and flood
    susceptibility) against Copernicus Sentinel-1 C-band SAR observations over Sagar Island
    during Cyclone Amphan landfall (shared/contracts.md §4.8, §7).

Usage:
    .\\api\\.venv\\Scripts\\python api/scripts/build_sentinel_fixtures.py
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
from app.hazard.sentinel import DEFAULT_SENTINEL_BENCHMARK, SENTINEL_FIXTURE_KEY  # noqa: E402
from app.schemas.contracts import SentinelValidationResponse  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("build_sentinel_fixtures")


def write_sentinel_fixture(path: Path, data: dict) -> None:
    """Serialize and write a contract-compliant SentinelValidationResponse fixture with LF endings."""
    # Validate against contract schema first
    validated = SentinelValidationResponse.model_validate(data)
    text = json.dumps(validated.model_dump(mode="json"), ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")

    # Verify LF line ending constraint (contracts.md §7)
    raw = path.read_bytes()
    if b"\r\n" in raw:
        raise ValueError(f"Fixture {path.name} contains CRLF line endings; must be LF only")


def build_sentinel_fixture(out_dir: Path = DEMO_DIR) -> Path:
    """Build and write the deterministic Sentinel-1 validation fixture."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = out_dir / f"{SENTINEL_FIXTURE_KEY}.json"
    write_sentinel_fixture(fixture_path, DEFAULT_SENTINEL_BENCHMARK)
    logger.info("Successfully wrote %s", fixture_path)
    return fixture_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build deterministic DEMO_MODE fixture for Sentinel-1 validation"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEMO_DIR,
        help=f"Directory to write fixture (default: {DEMO_DIR})",
    )
    args = parser.parse_args()
    build_sentinel_fixture(args.output_dir)


if __name__ == "__main__":
    main()
