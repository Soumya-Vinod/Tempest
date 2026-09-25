"""Impact service for GET /api/impact/results (contracts.md §5).

- DEMO_MODE: the compact fixture impact__results__<ts> (non-ok rows), expanded with ok rows.
- Live: Dev A's get_hazard_layer for each hazard type, then compute_impacts on the road graph.
- ?synthetic=true (TEMPORARY, dev only, DEMO_MODE off): synthetic hazards instead of Dev A's.
  Remove once get_hazard_layer is implemented.
"""

from functools import lru_cache
from pathlib import Path

import networkx as nx

from app.core.config import get_settings
from app.core.demo import load_fixture
from app.exposure import service as exposure
from app.exposure.ingest import ROADS_GRAPHML, load_road_graph
from app.hazard.service import get_hazard_layer
from app.impact.engine import HAZARD_TYPES, compute_impacts
from app.impact.fixtures import fixture_key, from_fixture
from app.impact.synthetic import synthetic_hazards
from app.impact.thresholds import ANCHOR_LONLAT
from app.schemas import LIVE, ImpactResultCollection

GRAPH_PATH: Path = ROADS_GRAPHML  # tests point this at a small graph
ANCHOR: tuple[float, float] = ANCHOR_LONLAT  # and this at its mainland node


class SyntheticNotAllowed(ValueError):
    """?synthetic=true is only for development with DEMO_MODE off."""


class DemoFixtureMissing(RuntimeError):
    """No impact demo fixture for this timestep yet."""


class GraphMissing(RuntimeError):
    """roads.graphml has not been generated (run scripts/ingest_osm.py)."""


@lru_cache(maxsize=2)
def _graph(path: Path) -> nx.MultiDiGraph:
    if not path.is_file():
        raise GraphMissing(f"{path.name} not found; run api/scripts/ingest_osm.py")
    return load_road_graph(path)


@lru_cache(maxsize=4)
def _computed(timestep: str, synthetic: bool) -> ImpactResultCollection:
    # Hazards first: without them (Dev A's NotImplementedError) nothing else needs loading.
    if synthetic:
        hazards = synthetic_hazards(timestep)
    else:
        hazards = {h: get_hazard_layer(h, timestep) for h in HAZARD_TYPES}
    graph = _graph(GRAPH_PATH)
    return compute_impacts(hazards, exposure.get_infra(), graph, timestep, anchor=ANCHOR)


def get_results(
    timestep: str,
    hazard_type: str | None = None,
    status: str | None = None,
    synthetic: bool = False,
) -> ImpactResultCollection:
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    if get_settings().DEMO_MODE:
        if synthetic:
            raise SyntheticNotAllowed("synthetic=true is only available with DEMO_MODE off")
        key = fixture_key(timestep)
        try:
            fixture = load_fixture(key)
        except FileNotFoundError as e:
            raise DemoFixtureMissing(f"no demo fixture for this timestep yet ({key})") from e
        results = from_fixture(fixture, exposure.get_infra(), timestep)
    else:
        results = _computed(timestep, synthetic)
    features = [
        f
        for f in results.features
        if (hazard_type is None or f.properties.hazard_type == hazard_type)
        and (status is None or f.properties.status == status)
    ]
    return ImpactResultCollection(features=features)


def clear_cache() -> None:
    _graph.cache_clear()
    _computed.cache_clear()
