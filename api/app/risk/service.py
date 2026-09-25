"""Risk service for GET /api/risk/scores and /api/risk/unscored-areas (contracts.md §4.4, §5).

Scores reuse the impact service's caches: the same hazard layers and impact results per
(timestep, synthetic), so a timestep's hazards and impacts are computed once for both routes.
DEMO_MODE and ?synthetic=true follow the impact rules (synthetic is dev-only, DEMO_MODE off).
"""

from app.core.cache import SingleFlightLRU
from app.core.config import get_settings
from app.core.demo import load_fixture
from app.exposure import service as exposure
from app.impact import service as impact
from app.impact.fixtures import compact_timestep
from app.risk import blocks as block_data
from app.risk.engine import (
    BlockRisk,
    RiskContext,
    build_context,
    evaluate,
    to_breakdown,
    to_collection,
)
from app.schemas import LIVE, RiskBreakdown, RiskScoreCollection, UnscoredAreaCollection

# Re-exported so the router maps the same errors for both routes.
SyntheticNotAllowed = impact.SyntheticNotAllowed
DemoFixtureMissing = impact.DemoFixtureMissing
ReferenceDataMissing = block_data.ReferenceDataMissing

CACHE_SIZE = 8


def _build_context() -> RiskContext:
    return build_context(
        block_data.load_blocks(),
        exposure.get_infra(),
        impact._graph(impact.GRAPH_PATH),
        impact.ANCHOR,
    )


_context_cache = SingleFlightLRU(lambda _: _build_context(), maxsize=1)
# Evaluated blocks per (timestep, synthetic): scores and breakdown both come from one evaluation.
_risk_cache = SingleFlightLRU(lambda ts, synthetic: _compute(ts, synthetic), CACHE_SIZE)


def context() -> RiskContext:
    """Static risk inputs (vulnerability, block membership, road lengths), built once."""
    return _context_cache.get("context")


def _compute(timestep: str, synthetic: bool) -> list[BlockRisk]:
    # Hazards first: Dev A's NotImplementedError stops here before anything heavy loads.
    hazards = impact.hazard_layers(timestep, synthetic)
    impacts = impact.results(timestep, synthetic)
    return evaluate(hazards, impacts, context())


def _demo_fixture(key: str) -> dict:
    try:
        return load_fixture(key)
    except FileNotFoundError as e:
        raise DemoFixtureMissing(f"no demo fixture for this timestep yet ({key})") from e


def _live_or_demo(timestep: str, synthetic: bool) -> bool:
    """True in DEMO_MODE (after its checks); raises for live timesteps and demo+synthetic."""
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    if get_settings().DEMO_MODE:
        if synthetic:
            raise SyntheticNotAllowed("synthetic=true is only available with DEMO_MODE off")
        return True
    return False


def fixture_key(timestep: str) -> str:
    return f"risk__scores__{compact_timestep(timestep)}"


def breakdown_fixture_key(timestep: str) -> str:
    return f"risk__breakdown__{compact_timestep(timestep)}"


def get_scores(timestep: str, synthetic: bool = False) -> RiskScoreCollection:
    if _live_or_demo(timestep, synthetic):
        return RiskScoreCollection.model_validate(_demo_fixture(fixture_key(timestep)))
    return to_collection(_risk_cache.get((timestep, synthetic)), context(), timestep)


def get_breakdown(timestep: str, synthetic: bool = False) -> RiskBreakdown:
    """Every part per block (v1.1 change, pending Dev A); same cache as get_scores."""
    if _live_or_demo(timestep, synthetic):
        return RiskBreakdown.model_validate(_demo_fixture(breakdown_fixture_key(timestep)))
    return to_breakdown(_risk_cache.get((timestep, synthetic)), context(), timestep)


def get_unscored_areas() -> UnscoredAreaCollection:
    """Static, from the committed reference files: the same in DEMO_MODE and live."""
    return _unscored_cache.get("unscored")


_unscored_cache = SingleFlightLRU(
    lambda _: block_data.unscored_areas(block_data.load_blocks()), maxsize=1
)


def clear_cache() -> None:
    _context_cache.clear()
    _risk_cache.clear()
    _unscored_cache.clear()
    block_data.clear_cache()
