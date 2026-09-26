"""Risk service for GET /api/risk/scores, /breakdown and /unscored-areas (contracts.md §4.4, §5).

Live: scores and breakdown reuse the impact service's caches (the same hazard layers and impact
results per timestep), so a timestep's hazards and impacts are computed once for all routes.
DEMO_MODE: the fixtures risk__scores__<ts>, risk__breakdown__<ts> and risk__unscored-areas,
built from Dev A's real hazards by scripts/build_impact_risk_fixtures.py. Score fixtures carry no
block polygons; they are added back from s24p_blocks.geojson (app/risk/fixtures.py).
"""

from app.core.cache import SingleFlightLRU
from app.core.config import get_settings
from app.core.demo import load_fixture
from app.exposure import service as exposure
from app.impact import service as impact
from app.impact.fixtures import compact_timestep
from app.risk import blocks as block_data
from app.risk import fixtures as risk_fixtures
from app.risk.engine import (
    BlockRisk,
    RiskContext,
    build_context,
    evaluate,
    to_breakdown,
    to_collection,
)
from app.schemas import LIVE, RiskBreakdown, RiskScoreCollection, UnscoredAreaCollection

# Re-exported so the router maps the same errors for all routes.
DemoFixtureMissing = impact.DemoFixtureMissing
ReferenceDataMissing = block_data.ReferenceDataMissing

CACHE_SIZE = 8
UNSCORED_FIXTURE_KEY = "risk__unscored-areas"


def _build_context() -> RiskContext:
    return build_context(
        block_data.load_blocks(),
        exposure.get_infra(),
        impact._graph(impact.GRAPH_PATH),
        impact.ANCHOR,
    )


_context_cache = SingleFlightLRU(lambda _: _build_context(), maxsize=1)
# Evaluated blocks per timestep: scores and breakdown both come from one evaluation.
_risk_cache = SingleFlightLRU(lambda ts: _compute(ts), CACHE_SIZE)
_unscored_cache = SingleFlightLRU(
    lambda _: block_data.unscored_areas(block_data.load_blocks()), maxsize=1
)


def context() -> RiskContext:
    """Static risk inputs (vulnerability, block membership, road lengths), built once."""
    return _context_cache.get("context")


def _compute(timestep: str) -> list[BlockRisk]:
    # Hazards first: Dev A's NotImplementedError stops here before anything heavy loads.
    hazards = impact.hazard_layers(timestep)
    impacts = impact.results(timestep)
    return evaluate(hazards, impacts, context())


def _demo_fixture(key: str) -> dict:
    try:
        return load_fixture(key)
    except FileNotFoundError as e:
        raise DemoFixtureMissing(f"no demo fixture yet ({key})") from e


def _demo(timestep: str | None = None) -> bool:
    """True in DEMO_MODE; raises for the reserved "live" timestep (501 in v1.1)."""
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    return get_settings().DEMO_MODE


def fixture_key(timestep: str) -> str:
    return f"risk__scores__{compact_timestep(timestep)}"


def breakdown_fixture_key(timestep: str) -> str:
    return f"risk__breakdown__{compact_timestep(timestep)}"


def get_scores(timestep: str) -> RiskScoreCollection:
    if _demo(timestep):
        fixture = _demo_fixture(fixture_key(timestep))
        return risk_fixtures.from_fixture(fixture, block_data.load_blocks())
    return to_collection(_risk_cache.get(timestep), context(), timestep)


def get_breakdown(timestep: str) -> RiskBreakdown:
    """Every part per block (added in v1.1); same cache as get_scores."""
    if _demo(timestep):
        return RiskBreakdown.model_validate(_demo_fixture(breakdown_fixture_key(timestep)))
    return to_breakdown(_risk_cache.get(timestep), context(), timestep)


def get_unscored_areas() -> UnscoredAreaCollection:
    """Static: live from the committed reference files, DEMO_MODE from its fixture."""
    if _demo():
        return UnscoredAreaCollection.model_validate(_demo_fixture(UNSCORED_FIXTURE_KEY))
    return _unscored_cache.get("unscored")


def clear_cache() -> None:
    _context_cache.clear()
    _risk_cache.clear()
    _unscored_cache.clear()
    block_data.clear_cache()
