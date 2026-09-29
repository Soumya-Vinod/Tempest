"""Single-command runner for the Generalized Sentinel-1 Validation Pipeline.

Usage:
    python scripts/run_sentinel_validation.py
    python scripts/run_sentinel_validation.py --blocks sagar namkhana
    python scripts/run_sentinel_validation.py --artifacts-dir data/artifacts/validation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add api to sys.path so app can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.hazard.gee import init_ee, is_ee_available
from app.hazard.validation.benchmark import run_validation
from app.hazard.validation.config import ValidationPipelineConfig


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run generalized Sentinel-1 SAR observational validation pipeline."
    )
    parser.add_argument(
        "--blocks",
        nargs="*",
        default=None,
        help=(
            "Optional list of administrative blocks to benchmark "
            "(e.g. sagar namkhana gosaba patharpratima)."
        ),
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help="Destination directory for exported GeoTIFFs, GeoJSONs, and report.",
    )
    args = parser.parse_args()

    print("================================================================================")
    print(" TEMPEST SENTINEL-1 SAR OBSERVATIONAL VALIDATION PIPELINE (PHASE A)")
    print("================================================================================")

    init_ee()
    ee_status = "Authenticated (Live Copernicus Earth Engine)" if is_ee_available() else "Offline"
    print(f"Earth Engine Status: {ee_status}")

    cfg = ValidationPipelineConfig()
    if args.artifacts_dir:
        cfg = ValidationPipelineConfig(artifacts_dir=args.artifacts_dir)

    print("\nExecuting validation benchmark across coastal administrative blocks...")
    benchmark_suite = run_validation(
        block_names_or_codes=args.blocks,
        config=cfg,
    )

    print("\n" + benchmark_suite.report_markdown)
    print("\nBenchmark completed successfully.")
    print(f"Artifacts exported to: {cfg.artifacts_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
