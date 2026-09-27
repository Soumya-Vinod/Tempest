"""Impact service for GET /api/impact/results (contracts.md §5).

- DEMO_MODE: the compact fixture impact__results__<ts> (non-ok rows), expanded with ok rows.
  At horizon 24 (v1.3 change, pending Dev A): the deduplicated impact__results-h24-<hash>
  fixtures, found through impact__results-h24-index (app/impact/horizon.py).
- Live: Dev A's get_hazard_layer for each hazard type, then compute_impacts on the road graph;
  at horizon 24, on the expected hazard (the cell-wise max over the next 24 h).
"""

from functools import lru_cache
from pathlib import Path

import networkx as nx

from app.core.cache import SingleFlightLRU
from app.core.config import get_settings
from app.core.demo import load_fixture
from app.exposure import service as exposure
from app.exposure.ingest import ROADS_GRAPHML, load_road_graph
from app.hazard.service import get_hazard_layer
from app.impact import horizon as fh
from app.impact.engine import HAZARD_TYPES, compute_impacts
from app.impact.fixtures import fixture_key, from_fixture
from app.impact.thresholds import ANCHOR_LONLAT
from app.schemas import LIVE, HazardLayerCollection, ImpactResultCollection

GRAPH_PATH: Path = ROADS_GRAPHML  # tests point this at a small graph
ANCHOR: tuple[float, float] = ANCHOR_LONLAT  # and this at its mainland node


class DemoFixtureMissing(RuntimeError):
    """No impact demo fixture for this timestep yet."""


class GraphMissing(RuntimeError):
    """roads.graphml has not been generated (run scripts/ingest_osm.py)."""


@lru_cache(maxsize=2)
def _graph(path: Path) -> nx.MultiDiGraph:
    if not path.is_file():
        raise GraphMissing(f"{path.name} not found; run api/scripts/ingest_osm.py")
    return load_road_graph(path)


# Hazard layers and computed collections per timestep, each computed once even when the web
# client's parallel requests arrive together (app/core/cache.py). Risk reuses both.
CACHE_SIZE = 8
# Keyed by (timestep, horizon_h). The window of a horizon-24 composite spans up to 9 timesteps.
_hazard_cache = SingleFlightLRU(lambda ts, h: _load_hazards(ts, h), 3 * CACHE_SIZE)
_results_cache = SingleFlightLRU(lambda ts, h: _compute(ts, h), CACHE_SIZE)


def _load_hazards(timestep: str, horizon_h: int) -> dict[str, HazardLayerCollection]:
    if horizon_h == 0:
        return {h: get_hazard_layer(h, timestep) for h in HAZARD_TYPES}
    return fh.expected_hazard([hazard_layers(ts) for ts in fh.window(timestep, horizon_h)])


def hazard_layers(timestep: str, horizon_h: int = 0) -> dict[str, HazardLayerCollection]:
    """Dev A's hazard layers for a replay timestep (horizon 0), or the expected hazard over the
    next `horizon_h` hours (the cell-wise max), cached."""
    return _hazard_cache.get((timestep, horizon_h))


def results(timestep: str, horizon_h: int = 0) -> ImpactResultCollection:
    """The full computed collection (live mode), cached per timestep and horizon."""
    return _results_cache.get((timestep, horizon_h))


def _compute(timestep: str, horizon_h: int) -> ImpactResultCollection:
    # Hazards first: without them (Dev A's NotImplementedError) nothing else needs loading.
    hazards = hazard_layers(timestep, horizon_h)
    graph = _graph(GRAPH_PATH)
    return compute_impacts(
        hazards, exposure.get_infra(), graph, timestep, anchor=ANCHOR, horizon_h=horizon_h
    )


H24_PREFIX = "impact__results-h24"


def _demo_fixture(key: str) -> dict:
    try:
        return load_fixture(key)
    except FileNotFoundError as e:
        raise DemoFixtureMissing(f"no demo fixture for this timestep yet ({key})") from e


def demo_compact(timestep: str, horizon_h: int = 0) -> dict:
    """The compact (non-ok rows) DEMO_MODE fixture for a timestep and horizon."""
    if horizon_h == 0:
        return _demo_fixture(fixture_key(timestep))
    index = _demo_fixture(fh.index_key(H24_PREFIX))
    if timestep not in index["files"]:
        raise DemoFixtureMissing(f"no horizon-24 impact fixture for {timestep}")
    return fh.restore(_demo_fixture(index["files"][timestep]), timestep)


def isolated_ids(timestep: str, horizon_h: int = 0) -> set[str]:
    """Infra ids isolated at a timestep and horizon (any hazard). In DEMO_MODE from the compact
    fixture's non-ok rows only, without expanding the full collection."""
    if get_settings().DEMO_MODE:
        rows = demo_compact(timestep, horizon_h)["features"]
        return {
            r["properties"]["infra_id"] for r in rows if r["properties"]["status"] == "isolated"
        }
    return {
        f.properties.infra_id
        for f in results(timestep, horizon_h).features
        if f.properties.status == "isolated"
    }


def get_results(
    timestep: str,
    hazard_type: str | None = None,
    status: str | None = None,
    horizon_h: int = 0,
) -> ImpactResultCollection:
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    if get_settings().DEMO_MODE:
        fixture = demo_compact(timestep, horizon_h)
        collection = from_fixture(fixture, exposure.get_infra(), timestep, horizon_h)
    else:
        collection = results(timestep, horizon_h)
    features = [
        f
        for f in collection.features
        if (hazard_type is None or f.properties.hazard_type == hazard_type)
        and (status is None or f.properties.status == status)
    ]
    return ImpactResultCollection(features=features)


def clear_cache() -> None:
    _graph.cache_clear()
    _hazard_cache.clear()
    _results_cache.clear()
