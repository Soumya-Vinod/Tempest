"""Write the unfilled land polygons of South 24 Parganas and Kolkata as a committed reference file.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_s24p_land.py

The risk engine measures hazard on land only and derives the unscored areas (Kolkata and the parts
of South 24 Parganas outside the 29 CD blocks) from this file, so risk needs no raw OSM data at
runtime. Source: the OSM district relations cached by ingest_osm.py in
api/data/raw/overpass-boundary.json (run that first). Unlike the ingest clip polygon, river
channels are NOT filled. Simplified to ~10 m and rounded to 5 decimals (~1 m).
Writes api/data/reference/s24p_land.geojson (ODbL 1.0, OpenStreetMap contributors).
"""

import json
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import API_DIR  # noqa: E402
from app.exposure import ingest  # noqa: E402

BOUNDARY_JSON = ingest.RAW_DIR / "overpass-boundary.json"
LAND_GEOJSON = API_DIR / "data" / "reference" / "s24p_land.geojson"
SIMPLIFY_M = 10.0
DECIMALS = 5


def main() -> None:
    if not BOUNDARY_JSON.exists():
        raise SystemExit(f"{BOUNDARY_JSON} missing: run api/scripts/ingest_osm.py first")
    boundary = json.loads(BOUNDARY_JSON.read_text(encoding="utf-8"))
    names = ingest.CLIP_RELATIONS  # {relation id: district name}
    land = gpd.GeoDataFrame(
        {"district": list(names.values()), "osm_relation": list(names)},
        geometry=[ingest.clip_polygon(boundary, [rid]) for rid in names],
        crs="EPSG:4326",
    )
    metric = land.to_crs(ingest.METRIC_CRS)
    metric["geometry"] = metric.simplify(SIMPLIFY_M, preserve_topology=True).make_valid()
    metric["land_area_km2"] = (metric.area / 1e6).round(1)
    out = metric.to_crs("EPSG:4326")
    out.to_file(LAND_GEOJSON, driver="GeoJSON", COORDINATE_PRECISION=DECIMALS)
    for row in out.itertuples():
        print(f"{row.district}: {row.land_area_km2:,.1f} km2")
    print(f"wrote {LAND_GEOJSON} ({LAND_GEOJSON.stat().st_size / 1e3:,.0f} KB)")


if __name__ == "__main__":
    main()
