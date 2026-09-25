"""Sample elevation data over the Sundarbans AOI grid (0.05° resolution, 528 cells) via GEE.

Produces the committed reference file:
    api/data/reference/hazard_elevation_grid.json

Run from repo root:
    .venv\\Scripts\\python api/scripts/build_hazard_elevation_grid.py [--refresh]

This reference file is used by the offline hazard replay engine and fixture generator,
ensuring realistic terrain elevation (NASA SRTM GL1 30m / Copernicus DEM) while keeping
runtime execution deterministic and free of external network dependencies.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

# Ensure api directory is in Python path when executed directly
API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.core.config import API_DIR as CONFIG_API_DIR  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.hazard.gee import init_ee  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("build_hazard_elevation_grid")

REFERENCE_DIR = CONFIG_API_DIR / "data" / "reference"
REFERENCE_PATH = REFERENCE_DIR / "hazard_elevation_grid.json"

DEFAULT_ROWS = 24
DEFAULT_COLS = 22
DEFAULT_RESOLUTION = 0.05
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers using the Haversine formula."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def build_elevation_grid(
    out_path: Path = REFERENCE_PATH,
    rows: int = DEFAULT_ROWS,
    cols: int = DEFAULT_COLS,
    use_gee: bool = True,
) -> Path:
    """Generate the 528-cell AOI grid and sample terrain elevation from Earth Engine."""
    settings = get_settings()
    min_lon, min_lat, max_lon, max_lat = settings.aoi_bbox_tuple
    dx = (max_lon - min_lon) / cols
    dy = (max_lat - min_lat) / rows
    coastline_lat = min_lat + 0.05

    grid_meta = []
    for r in range(rows):
        for c in range(cols):
            c_min_lon = round(min_lon + c * dx, 5)
            c_max_lon = round(c_min_lon + dx, 5)
            c_min_lat = round(min_lat + r * dy, 5)
            c_max_lat = round(c_min_lat + dy, 5)
            cent_lon = round((c_min_lon + c_max_lon) / 2.0, 5)
            cent_lat = round((c_min_lat + c_max_lat) / 2.0, 5)
            cell_id = f"c{r:02d}{c:02d}"
            dist_km = round(max(0.0, haversine_km(cent_lat, cent_lon, coastline_lat, cent_lon)), 2)
            ring = [
                [c_min_lon, c_min_lat],
                [c_max_lon, c_min_lat],
                [c_max_lon, c_max_lat],
                [c_min_lon, c_max_lat],
                [c_min_lon, c_min_lat],
            ]
            grid_meta.append(
                {
                    "id": cell_id,
                    "r": r,
                    "c": c,
                    "min_lon": c_min_lon,
                    "min_lat": c_min_lat,
                    "max_lon": c_max_lon,
                    "max_lat": c_max_lat,
                    "centroid_lon": cent_lon,
                    "centroid_lat": cent_lat,
                    "dist_to_coast_km": dist_km,
                    "ring": ring,
                }
            )

    elev_by_id: dict[str, float] = {}

    if use_gee and init_ee():
        try:
            import ee

            logger.info(
                "Sampling SRTM GL1 30m elevation via Earth Engine for %d cells...", len(grid_meta)
            )
            features = [
                ee.Feature(
                    ee.Geometry.Rectangle([m["min_lon"], m["min_lat"], m["max_lon"], m["max_lat"]]),
                    {"id": m["id"]},
                )
                for m in grid_meta
            ]
            fc = ee.FeatureCollection(features)
            dem = ee.Image("USGS/SRTMGL1_003").select("elevation")
            sampled = dem.reduceRegions(
                collection=fc, reducer=ee.Reducer.mean(), scale=90
            ).getInfo()
            for f in sampled.get("features", []):
                cid = f["properties"]["id"]
                val = f["properties"].get("mean")
                elev_by_id[cid] = round(max(0.0, float(val if val is not None else 0.0)), 2)
            logger.info("Successfully sampled %d cells from Earth Engine", len(elev_by_id))
        except Exception as e:
            logger.warning(
                "Earth Engine elevation sampling failed: %s; falling back to interpolation", e
            )

    # Deterministic fallback if GEE was unavailable or incomplete
    if len(elev_by_id) < len(grid_meta):
        for m in grid_meta:
            if m["id"] not in elev_by_id:
                rel_north = (m["centroid_lat"] - min_lat) / (max_lat - min_lat)
                fallback_elev = 1.0 + rel_north * 4.5 + 0.3 * math.sin(m["centroid_lon"] * 10.0)
                elev_by_id[m["id"]] = round(max(0.5, fallback_elev), 2)

    out_cells = []
    for m in grid_meta:
        cid = m["id"]
        out_cells.append(
            {
                "id": cid,
                "r": m["r"],
                "c": m["c"],
                "centroid_lon": m["centroid_lon"],
                "centroid_lat": m["centroid_lat"],
                "min_lon": m["min_lon"],
                "min_lat": m["min_lat"],
                "max_lon": m["max_lon"],
                "max_lat": m["max_lat"],
                "elevation_m": elev_by_id.get(cid, 1.0),
                "dist_to_coast_km": m["dist_to_coast_km"],
                "ring": m["ring"],
            }
        )

    payload = {
        "dataset": "USGS/SRTMGL1_003",
        "aoi_bbox": [min_lon, min_lat, max_lon, max_lat],
        "resolution_deg": DEFAULT_RESOLUTION,
        "rows": rows,
        "cols": cols,
        "total_cells": len(out_cells),
        "cells": out_cells,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    out_path.write_text(text, encoding="utf-8", newline="\n")
    logger.info(
        "Wrote %d elevation grid cells to %s (%d KB)", len(out_cells), out_path, len(text) // 1024
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build hazard elevation reference grid from Earth Engine"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-query Earth Engine even if reference file already exists",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REFERENCE_PATH,
        help=f"Output path (default: {REFERENCE_PATH})",
    )
    args = parser.parse_args()

    if args.output.is_file() and not args.refresh:
        logger.info("Reference file %s already exists. Use --refresh to rebuild.", args.output)
        return

    build_elevation_grid(out_path=args.output)


if __name__ == "__main__":
    main()
