"""Extract the 29 South 24 Parganas CD blocks from geoBoundaries and clip them to the AOI.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_s24p_blocks.py [--refresh]

Downloads the all-India geoBoundaries IND ADM3 GeoJSON (~106 MB, ODbL 1.0) to api/data/raw/
(ignored) unless it is already there. The clip polygon is the one ingest_osm.py uses, built from
its cached api/data/raw/overpass-boundary.json; run that script first if the file is missing.
Blocks are picked by shapeID from api/data/reference/s24p_blocks.csv, which also supplies the
Census 2011 codes. Kolkata is subtracted from every block (it is not risk-scored). Each feature
gets area_km2 = land_area_km2 + water_area_km2 (UTM 45N, 0.1 km2), where land is the unfilled
OSM S24P district and water the river channels the clip fills. Writes
api/data/reference/s24p_blocks.geojson.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import httpx
import pandas as pd
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import API_DIR  # noqa: E402
from app.exposure import ingest  # noqa: E402

# Pinned to a release commit so the shapeIDs in the lookup stay valid.
GB_URL = (
    "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/IND/ADM3/"
    "geoBoundaries-IND-ADM3.geojson"
)
GB_PATH = ingest.RAW_DIR / "geoBoundaries-IND-ADM3.geojson"
REFERENCE_DIR = API_DIR / "data" / "reference"
LOOKUP_CSV = REFERENCE_DIR / "s24p_blocks.csv"
BLOCKS_GEOJSON = REFERENCE_DIR / "s24p_blocks.geojson"
BOUNDARY_JSON = ingest.RAW_DIR / "overpass-boundary.json"
EXPECTED_BLOCKS = 29
S24P_RELATION, KOLKATA_RELATION = 9513027, 10371838  # keys of ingest.CLIP_RELATIONS
# Read only this window of the all-India file (min_lon, min_lat, max_lon, max_lat).
READ_BBOX = (87.9, 21.4, 89.2, 22.8)
COORD_DECIMALS = 6  # ~0.1 m


def download(url: str, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(path)


@dataclass
class Aoi:
    polygon: shapely.Geometry  # ingest clip: S24P + Kolkata, narrow river channels filled
    kolkata: shapely.Geometry  # subtracted from every block (excluded from risk scoring)
    land: shapely.Geometry  # unfilled OSM S24P district: the land part of each block


def load_aoi() -> Aoi:
    if not BOUNDARY_JSON.exists():
        sys.exit(f"missing {BOUNDARY_JSON}; run api/scripts/ingest_osm.py first")
    boundary = json.loads(BOUNDARY_JSON.read_text(encoding="utf-8"))
    land = ingest.clip_polygon(boundary)
    neighbours = ingest.clip_polygon(boundary, ingest.NEIGHBOUR_RELATIONS)
    return Aoi(
        polygon=ingest.fill_water_gaps(land, neighbours),
        kolkata=ingest.clip_polygon(boundary, [KOLKATA_RELATION]),
        land=ingest.clip_polygon(boundary, [S24P_RELATION]),
    )


def add_areas(blocks: gpd.GeoDataFrame, land: shapely.Geometry) -> gpd.GeoDataFrame:
    """area_km2 = land_area_km2 + water_area_km2 (filled river channels), in UTM 45N."""
    metric = blocks.geometry.to_crs(ingest.METRIC_CRS)
    land_m = gpd.GeoSeries([land], crs="EPSG:4326").to_crs(ingest.METRIC_CRS).iloc[0]
    blocks = blocks.copy()
    blocks["area_km2"] = (metric.area / 1e6).round(1)
    blocks["land_area_km2"] = (metric.intersection(land_m).area / 1e6).round(1)
    blocks["water_area_km2"] = (metric.difference(land_m).area / 1e6).round(1)
    return blocks


def build_blocks(gb_path: Path, lookup: pd.DataFrame, aoi: Aoi) -> gpd.GeoDataFrame:
    gb = gpd.read_file(gb_path, bbox=READ_BBOX)
    blocks = lookup.merge(
        gb[["shapeID", "shapeName", "geometry"]],
        left_on="geoboundaries_shape_id",
        right_on="shapeID",
        how="left",
    )
    missing = blocks[blocks["geometry"].isna()]["block_name"].tolist()
    if missing:
        raise ValueError(f"shapeIDs not found in {gb_path.name}: {missing}")
    blocks = gpd.GeoDataFrame(blocks.drop(columns="shapeID"), geometry="geometry", crs=gb.crs)
    clipped = blocks.geometry.make_valid().intersection(aoi.polygon).difference(aoi.kolkata)
    blocks["geometry"] = shapely.set_precision(clipped.values, 10**-COORD_DECIMALS)
    empty = blocks[blocks.geometry.is_empty]["block_name"].tolist()
    if empty:
        raise ValueError(f"blocks empty after clipping: {empty}")
    blocks = add_areas(blocks, aoi.land)
    return blocks[
        [
            "census2011_code",
            "block_name",
            "geoboundaries_shape_id",
            "area_km2",
            "land_area_km2",
            "water_area_km2",
            "geometry",
        ]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="re-download geoBoundaries")
    args = parser.parse_args()

    if args.refresh or not GB_PATH.exists():
        print(f"downloading {GB_URL}")
        download(GB_URL, GB_PATH)
    lookup = pd.read_csv(LOOKUP_CSV, comment="#", dtype=str)
    if len(lookup) != EXPECTED_BLOCKS:
        raise ValueError(f"{LOOKUP_CSV.name} has {len(lookup)} rows, expected {EXPECTED_BLOCKS}")

    blocks = build_blocks(GB_PATH, lookup, load_aoi())
    blocks.to_file(BLOCKS_GEOJSON, driver="GeoJSON", COORDINATE_PRECISION=COORD_DECIMALS)

    total, land, water = (blocks[c].sum() for c in ("area_km2", "land_area_km2", "water_area_km2"))
    print(f"wrote {BLOCKS_GEOJSON} ({len(blocks)} blocks)")
    print(f"  area {total:.1f} km2 = land {land:.1f} + water {water:.1f}")
    area = blocks["area_km2"]
    print(f"  smallest: {blocks.loc[area.idxmin(), 'block_name']} {area.min():.1f} km2")
    print(f"  largest:  {blocks.loc[area.idxmax(), 'block_name']} {area.max():.1f} km2")


if __name__ == "__main__":
    main()
