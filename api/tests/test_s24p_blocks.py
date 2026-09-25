"""The committed South 24 Parganas block reference files (api/scripts/build_s24p_blocks.py)."""

import json
import re
from itertools import combinations

import geopandas as gpd
import pandas as pd
import pytest

from app.core.config import API_DIR
from app.exposure import ingest

REFERENCE_DIR = API_DIR / "data" / "reference"
LOOKUP_CSV = REFERENCE_DIR / "s24p_blocks.csv"
BLOCKS_GEOJSON = REFERENCE_DIR / "s24p_blocks.geojson"
BOUNDARY_JSON = ingest.RAW_DIR / "overpass-boundary.json"
KOLKATA_RELATION = 10371838
CODE_RE = re.compile(r"^[0-9]{5}$")
N_BLOCKS = 29
# Shared edges are snapped to a 1e-6 degree grid, which can leave slivers of a few m2.
SLIVER_KM2 = 0.001
AREA_TOLERANCE_KM2 = 0.5


@pytest.fixture(scope="module")
def lookup() -> pd.DataFrame:
    return pd.read_csv(LOOKUP_CSV, comment="#", dtype=str)


@pytest.fixture(scope="module")
def blocks() -> gpd.GeoDataFrame:
    return gpd.read_file(BLOCKS_GEOJSON)


@pytest.fixture(scope="module")
def blocks_m(blocks) -> gpd.GeoSeries:
    return blocks.geometry.to_crs(ingest.METRIC_CRS)


def test_lookup_has_29_unique_census_codes(lookup):
    assert len(lookup) == N_BLOCKS
    codes = lookup["census2011_code"]
    assert codes.map(lambda c: isinstance(c, str) and bool(CODE_RE.match(c))).all()
    assert codes.is_unique


def test_geojson_codes_match_lookup(lookup):
    # Read raw JSON so a code written as a number (leading zero lost) fails here.
    features = json.loads(BLOCKS_GEOJSON.read_text(encoding="utf-8"))["features"]
    assert len(features) == N_BLOCKS
    codes = [f["properties"]["census2011_code"] for f in features]
    assert all(isinstance(c, str) for c in codes)
    assert sorted(codes) == sorted(lookup["census2011_code"])


def test_blocks_do_not_overlap(blocks, blocks_m):
    overlaps = {
        (blocks.at[i, "block_name"], blocks.at[j, "block_name"]): round(a, 4)
        for i, j in combinations(range(len(blocks_m)), 2)
        if (a := blocks_m.iloc[i].intersection(blocks_m.iloc[j]).area / 1e6) > SLIVER_KM2
    }
    assert not overlaps


@pytest.mark.skipif(not BOUNDARY_JSON.exists(), reason="needs api/data/raw (ingest_osm.py)")
def test_no_block_area_inside_kolkata(blocks_m):
    boundary = json.loads(BOUNDARY_JSON.read_text(encoding="utf-8"))
    kolkata = gpd.GeoSeries(
        [ingest.clip_polygon(boundary, [KOLKATA_RELATION])], crs="EPSG:4326"
    ).to_crs(ingest.METRIC_CRS)
    assert blocks_m.intersection(kolkata.iloc[0]).area.sum() / 1e6 < SLIVER_KM2


def test_land_plus_water_equals_total(blocks):
    diff = (blocks["land_area_km2"] + blocks["water_area_km2"] - blocks["area_km2"]).abs()
    assert (diff <= AREA_TOLERANCE_KM2).all(), blocks.loc[diff > AREA_TOLERANCE_KM2, "block_name"]
