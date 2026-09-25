"""Exposure service: InfraFeatures for GET /api/exposure/infra (contracts.md §4.2, §5).

Live: api/data/processed/infra.parquet from scripts/ingest_osm.py. DEMO_MODE: the per-type
fixtures api/data/demo/exposure__infra-<type>.json, built by scripts/build_exposure_fixtures.py;
the unfiltered response has no fixture of its own and is composed from them (contracts.md §7).
Both are loaded once per process and cached.
"""

import json
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
from shapely.geometry import mapping

from app.core.config import get_settings
from app.core.demo import load_fixture
from app.exposure.ingest import INFRA_PARQUET, INFRA_TYPES, read_infra
from app.schemas import InfraFeature, InfraFeatureCollection, InfraType

INFRA_PATH: Path = INFRA_PARQUET  # tests point this at a small parquet


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
    return tuple(features_from_gdf(read_infra(path)))


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
