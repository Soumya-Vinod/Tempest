"""Exposure service: InfraFeatures for GET /api/exposure/infra (contracts.md §4.2, §5).

Live: api/data/processed/infra.parquet from scripts/ingest_osm.py, passed through display_gdf
(the same rounding and simplification as the fixtures). DEMO_MODE: the per-type
fixtures api/data/demo/exposure__infra-<type>.json, built by scripts/build_exposure_fixtures.py;
the unfiltered response has no fixture of its own and is composed from them (contracts.md §7).
Both are loaded once per process and cached.
"""

import json
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import mapping

from app.core.config import get_settings
from app.core.demo import load_fixture
from app.exposure.ingest import INFRA_PARQUET, INFRA_TYPES, METRIC_CRS, read_infra
from app.schemas import InfraFeature, InfraFeatureCollection, InfraType

INFRA_PATH: Path = INFRA_PARQUET  # tests point this at a small parquet


DISPLAY_DECIMALS = 5  # ~1 m
DISPLAY_TOLERANCE_M = 10.0  # line simplification


def _round(geom, decimals: int):
    return shapely.transform(geom, lambda c: np.round(c, decimals))


def _drop_repeats(geom):
    """Remove consecutive duplicate vertices left by rounding, unless a line would collapse."""
    tidy = shapely.remove_repeated_points(geom)
    parts = getattr(tidy, "geoms", [tidy])
    return geom if any(len(p.coords) < 2 for p in parts) else tidy


def display_gdf(
    gdf: gpd.GeoDataFrame,
    tolerance_m: float = DISPLAY_TOLERANCE_M,
    decimals: int = DISPLAY_DECIMALS,
) -> gpd.GeoDataFrame:
    """Response / fixture geometry: lines simplified to ~tolerance_m metres, all coordinates
    rounded to `decimals` places. Shared by the live route and the fixture builder."""
    out = gdf.copy()
    lines = out.geom_type.isin(["LineString", "MultiLineString"])
    if lines.any():
        metric = out.loc[lines].geometry.to_crs(METRIC_CRS)
        simplified = metric.simplify(tolerance_m, preserve_topology=True).to_crs("EPSG:4326")
        out.loc[lines, "geometry"] = simplified.to_numpy()
    out["geometry"] = [_drop_repeats(_round(g, decimals)) for g in out.geometry]
    return out


class InfraDataMissing(RuntimeError):
    """infra.parquet has not been generated (run scripts/ingest_osm.py)."""


def fixture_key(infra_type: InfraType) -> str:
    """Contract §7 resource `infra-<infra_type>`, with `_` written as `-`."""
    return f"exposure__infra-{infra_type.replace('_', '-')}"


def features_from_gdf(gdf: gpd.GeoDataFrame) -> list[InfraFeature]:
    """infra.parquet rows -> validated contract InfraFeatures (attributes are JSON strings)."""
    return [
        InfraFeature.model_validate(
            {
                "type": "Feature",
                "id": row.id,
                "geometry": mapping(row.geometry),
                "properties": {
                    "id": row.id,
                    "infra_type": row.infra_type,
                    "name": row.name if isinstance(row.name, str) else None,
                    "osm_id": row.osm_id,
                    "attributes": json.loads(row.attributes),
                },
            }
        )
        for row in gdf.itertuples(index=False)
    ]


@lru_cache(maxsize=4)
def _parquet_features(path: Path) -> tuple[InfraFeature, ...]:
    if not path.is_file():
        raise InfraDataMissing(f"{path.name} not found; run api/scripts/ingest_osm.py")
    return tuple(features_from_gdf(display_gdf(read_infra(path))))


@lru_cache(maxsize=8)
def _demo_collection(infra_type: InfraType | None) -> InfraFeatureCollection:
    if infra_type is not None:
        return InfraFeatureCollection.model_validate(load_fixture(fixture_key(infra_type)))
    # Unfiltered: composed from the per-type fixtures, in INFRA_TYPES order.
    parts = [_demo_collection(t) for t in INFRA_TYPES]
    return InfraFeatureCollection(features=[f for part in parts for f in part.features])


def get_infra(infra_type: InfraType | None = None) -> InfraFeatureCollection:
    """All InfraFeatures in the AOI, or only `infra_type` (contract §5)."""
    if get_settings().DEMO_MODE:
        return _demo_collection(infra_type)
    features = _parquet_features(INFRA_PATH)
    if infra_type is not None:
        features = tuple(f for f in features if f.properties.infra_type == infra_type)
    return InfraFeatureCollection(features=list(features))


def clear_cache() -> None:
    _parquet_features.cache_clear()
    _demo_collection.cache_clear()
