"""Write the land and inhabited-land polygons of South 24 Parganas and Kolkata (reference files).

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_s24p_land.py [--refresh]

The risk engine measures hazard on inhabited land and derives the unscored areas (Kolkata and the
parts of South 24 Parganas outside the 29 CD blocks) from land, so risk needs no raw OSM data at
runtime. Both are simplified to ~10 m and rounded to 5 decimals (~1 m); ODbL 1.0, OpenStreetMap
contributors.

- s24p_land.geojson: the unfilled OSM district polygons (river channels NOT filled), from
  api/data/raw/overpass-boundary.json cached by ingest_osm.py (run that first).
- s24p_inhabited_land.geojson: land minus every OSM protected area in the AOI (Sunderban Tiger
  Reserve with the National Park and Sajnekhali WLS inside it, West Sunderban WLS, Lothian Island
  WLS, ...): uninhabited reserve forest. From one Overpass query, cached in
  api/data/raw/overpass-protected-areas.json (--refresh re-downloads it).
"""

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import API_DIR, get_settings  # noqa: E402
from app.exposure import ingest  # noqa: E402
from scripts.ingest_osm import cached_overpass  # noqa: E402

BOUNDARY_JSON = ingest.RAW_DIR / "overpass-boundary.json"
REFERENCE = API_DIR / "data" / "reference"
LAND_GEOJSON = REFERENCE / "s24p_land.geojson"
INHABITED_GEOJSON = REFERENCE / "s24p_inhabited_land.geojson"
SIMPLIFY_M = 10.0
DECIMALS = 5


def simplified(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    metric = frame.to_crs(ingest.METRIC_CRS)
    metric["geometry"] = metric.simplify(SIMPLIFY_M, preserve_topology=True).make_valid()
    return metric


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="re-download protected areas")
    args = parser.parse_args()
    if not BOUNDARY_JSON.exists():
        raise SystemExit(f"{BOUNDARY_JSON} missing: run api/scripts/ingest_osm.py first")
    boundary = json.loads(BOUNDARY_JSON.read_text(encoding="utf-8"))
    names = ingest.CLIP_RELATIONS  # {relation id: district name}
    land = gpd.GeoDataFrame(
        {"district": list(names.values()), "osm_relation": list(names)},
        geometry=[ingest.clip_polygon(boundary, [rid]) for rid in names],
        crs="EPSG:4326",
    )

    metric = simplified(land)
    metric["land_area_km2"] = (metric.area / 1e6).round(1)
    metric.to_crs("EPSG:4326").to_file(
        LAND_GEOJSON, driver="GeoJSON", COORDINATE_PRECISION=DECIMALS
    )

    query = ingest.protected_areas_query(get_settings().aoi_bbox_tuple)
    areas = ingest.protected_polygons(cached_overpass("protected-areas", query, args.refresh))
    protected = gpd.GeoSeries([shapely.union_all([g for _, g in areas])], crs="EPSG:4326")
    protected_m = protected.to_crs(ingest.METRIC_CRS).iloc[0]
    inhabited = simplified(land)
    inhabited["geometry"] = inhabited.difference(protected_m).make_valid()
    inhabited["land_area_km2"] = metric["land_area_km2"]
    inhabited["protected_area_km2"] = (metric.intersection(protected_m).area / 1e6).round(1)
    inhabited["inhabited_area_km2"] = (inhabited.area / 1e6).round(1)
    inhabited.to_crs("EPSG:4326").to_file(
        INHABITED_GEOJSON, driver="GeoJSON", COORDINATE_PRECISION=DECIMALS
    )

    for row in inhabited.itertuples():
        print(
            f"{row.district}: land {row.land_area_km2:,.1f} km2, protected "
            f"{row.protected_area_km2:,.1f} km2, inhabited {row.inhabited_area_km2:,.1f} km2"
        )
    for path in (LAND_GEOJSON, INHABITED_GEOJSON):
        print(f"wrote {path} ({path.stat().st_size / 1e3:,.0f} KB)")


if __name__ == "__main__":
    main()
