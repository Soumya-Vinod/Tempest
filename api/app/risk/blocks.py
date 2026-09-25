"""The 29 South 24 Parganas CD blocks, their population and land, from committed reference files.

- api/data/reference/s24p_blocks.geojson: block polygons (land + river water), land_area_km2,
  inhabited_area_km2 (land outside protected areas: the Sundarbans reserve forest).
- api/data/reference/s24p_blocks.csv: census2011_code -> population_2011 (sources in its header).
- api/data/reference/s24p_land.geojson: unfilled OSM land of South 24 Parganas and Kolkata.
- api/data/reference/s24p_inhabited_land.geojson: that land minus OSM protected areas.

Hazard and population density use each block's inhabited land (block ∩ inhabited land), so the
uninhabited reserve forest doesn't dilute or inflate them. The unscored areas are the land no
block covers: Kolkata, and municipal areas outside the CD blocks.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from app.core.config import API_DIR
from app.exposure.ingest import METRIC_CRS
from app.schemas import UnscoredAreaCollection

REFERENCE_DIR = API_DIR / "data" / "reference"
BLOCKS_GEOJSON = REFERENCE_DIR / "s24p_blocks.geojson"
LOOKUP_CSV = REFERENCE_DIR / "s24p_blocks.csv"
LAND_GEOJSON = REFERENCE_DIR / "s24p_land.geojson"
INHABITED_GEOJSON = REFERENCE_DIR / "s24p_inhabited_land.geojson"
BLOCK_SOURCE = "census2011_cd"
UNSCORED_LABEL = "Municipal area, not scored"
MIN_UNSCORED_KM2 = 0.5  # drop slivers left where block and district edges don't quite meet
DISPLAY_SIMPLIFY_M = 10.0
DISPLAY_DECIMALS = 5


class ReferenceDataMissing(RuntimeError):
    """A block reference file or the population column is missing."""


@dataclass(frozen=True)
class Blocks:
    codes: list[str]  # census2011_code, used as block_id
    names: list[str]
    population: np.ndarray  # Census 2011
    land_area_km2: np.ndarray  # from the block file (full-precision land)
    inhabited_area_km2: np.ndarray  # from the block file: land outside protected areas
    geometry: gpd.GeoSeries  # EPSG:4326, full precision
    metric: gpd.GeoSeries  # METRIC_CRS
    inhabited_metric: gpd.GeoSeries  # block ∩ inhabited land, METRIC_CRS (hazard weighting)
    land_union_metric: BaseGeometry  # all land in the file (S24P + Kolkata), METRIC_CRS
    display: list[dict]  # simplified, rounded GeoJSON geometry for responses


def _polygonal(geom: BaseGeometry) -> BaseGeometry:
    geom = shapely.make_valid(geom)
    parts = [
        g for g in getattr(geom, "geoms", [geom]) if g.geom_type in ("Polygon", "MultiPolygon")
    ]
    return shapely.union_all(parts)


def display_geometry(metric_geoms: gpd.GeoSeries) -> list[dict]:
    """Simplify (~10 m) and round (5 decimals) polygons for API responses."""
    simplified = metric_geoms.simplify(DISPLAY_SIMPLIFY_M, preserve_topology=True)
    wgs = simplified.to_crs("EPSG:4326")
    rounded = [
        _polygonal(shapely.transform(g, lambda c: np.round(c, DISPLAY_DECIMALS))) for g in wgs
    ]
    return [mapping(g) for g in rounded]


def make_blocks(
    frame: gpd.GeoDataFrame, land: BaseGeometry, inhabited: BaseGeometry | None = None
) -> Blocks:
    """Blocks from a frame with census2011_code, block_name, population_2011, land_area_km2 and
    inhabited_area_km2. `inhabited` defaults to `land` (no protected areas)."""
    metric = frame.geometry.to_crs(METRIC_CRS)
    land_metric = gpd.GeoSeries([land], crs="EPSG:4326").to_crs(METRIC_CRS).iloc[0]
    inhabited_metric = (
        land_metric
        if inhabited is None
        else gpd.GeoSeries([inhabited], crs="EPSG:4326").to_crs(METRIC_CRS).iloc[0]
    )
    shapely.prepare(land_metric)
    return Blocks(
        codes=list(frame["census2011_code"]),
        names=list(frame["block_name"]),
        population=frame["population_2011"].astype(float).to_numpy(),
        land_area_km2=frame["land_area_km2"].astype(float).to_numpy(),
        inhabited_area_km2=frame["inhabited_area_km2"].astype(float).to_numpy(),
        geometry=frame.geometry,
        metric=metric,
        inhabited_metric=metric.intersection(land_metric).intersection(inhabited_metric),
        land_union_metric=land_metric,
        display=display_geometry(metric),
    )


@lru_cache(maxsize=2)
def load_blocks(
    blocks_path: Path = BLOCKS_GEOJSON,
    lookup_path: Path = LOOKUP_CSV,
    land_path: Path = LAND_GEOJSON,
    inhabited_path: Path = INHABITED_GEOJSON,
) -> Blocks:
    for path in (blocks_path, lookup_path, land_path, inhabited_path):
        if not path.is_file():
            raise ReferenceDataMissing(f"{path.name} not found in api/data/reference/")
    lookup = pd.read_csv(lookup_path, comment="#", dtype=str)
    if "population_2011" not in lookup.columns:
        raise ReferenceDataMissing("s24p_blocks.csv has no population_2011 column")
    frame = gpd.read_file(blocks_path).merge(
        lookup[["census2011_code", "population_2011"]], on="census2011_code", how="left"
    )
    if frame["population_2011"].isna().any():
        raise ReferenceDataMissing("population_2011 missing for some blocks")
    # Keep the CSV's block order, so responses are stable.
    order = {code: i for i, code in enumerate(lookup["census2011_code"])}
    frame = frame.sort_values("census2011_code", key=lambda s: s.map(order)).reset_index(drop=True)
    if "inhabited_area_km2" not in frame.columns:
        raise ReferenceDataMissing("s24p_blocks.geojson has no inhabited_area_km2")
    land = shapely.union_all(gpd.read_file(land_path).geometry.to_numpy())
    inhabited = shapely.union_all(gpd.read_file(inhabited_path).geometry.to_numpy())
    return make_blocks(frame, land, inhabited)


_cached_load = load_blocks  # the lru_cache wrapper, even if tests replace load_blocks


def clear_cache() -> None:
    _cached_load.cache_clear()


def unscored_areas(blocks: Blocks) -> UnscoredAreaCollection:
    """Land that no block covers, one feature per piece of at least MIN_UNSCORED_KM2."""
    rest = blocks.land_union_metric.difference(shapely.union_all(blocks.metric.to_numpy()))
    pieces = gpd.GeoSeries(list(getattr(rest, "geoms", [rest])), crs=METRIC_CRS)
    pieces = pieces[pieces.area / 1e6 >= MIN_UNSCORED_KM2]
    pieces = pieces.iloc[np.argsort(-pieces.area.to_numpy(), kind="stable")]  # Kolkata first
    geoms = display_geometry(pieces.reset_index(drop=True))
    features = [
        {
            "type": "Feature",
            "id": f"unscored-{i + 1}",
            "geometry": g,
            "properties": {
                "id": f"unscored-{i + 1}",
                "label": UNSCORED_LABEL,
                "area_km2": round(float(a) / 1e6, 1),
            },
        }
        for i, (g, a) in enumerate(zip(geoms, pieces.area, strict=True))
    ]
    return UnscoredAreaCollection.model_validate(
        {"type": "FeatureCollection", "features": features}
    )
