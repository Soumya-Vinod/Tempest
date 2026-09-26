"""Insurance service for GET /api/insurance/triggers and /summary (contracts.md §4.6, §5; the
summary route, tiers and released amounts: v1.2 change, pending Dev A). ILLUSTRATIVE terms.

Live: readings per timestep from Dev A's hazard layers (the impact service's cache), each
computed once; a timestep's released amounts need every timestep up to it.
DEMO_MODE: the fixtures insurance__triggers__<ts> (compact: no block polygons, added back here,
as for risk scores) and insurance__summary, built by scripts/build_insurance_fixtures.py.
"""

from app.core.cache import SingleFlightLRU
from app.core.config import get_settings
from app.core.demo import load_fixture
from app.impact import service as impact
from app.impact.fixtures import compact_timestep
from app.insurance import engine
from app.risk import blocks as block_data
from app.schemas import (
    LIVE,
    REPLAY_TIMESTEPS,
    InsuranceSummary,
    TriggerEventCollection,
)

DemoFixtureMissing = impact.DemoFixtureMissing
ReferenceDataMissing = block_data.ReferenceDataMissing

SUMMARY_FIXTURE_KEY = "insurance__summary"

_readings_cache = SingleFlightLRU(
    lambda ts: engine.readings(impact.hazard_layers(ts), block_data.load_blocks()),
    maxsize=len(REPLAY_TIMESTEPS),
)


def fixture_key(timestep: str) -> str:
    return f"insurance__triggers__{compact_timestep(timestep)}"


def _demo(timestep: str | None = None) -> bool:
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    return get_settings().DEMO_MODE


def _demo_fixture(key: str) -> dict:
    try:
        return load_fixture(key)
    except FileNotFoundError as e:
        raise DemoFixtureMissing(f"no demo fixture yet ({key})") from e


def _geometry() -> dict[str, dict]:
    blocks = block_data.load_blocks()
    return dict(zip(blocks.codes, blocks.display, strict=True))


def series(upto: str | None = None) -> tuple[list[str], list[list[engine.ZoneReading]]]:
    """Replay timesteps from T-72 up to `upto` (all when None) and their readings."""
    end = REPLAY_TIMESTEPS.index(upto) + 1 if upto else len(REPLAY_TIMESTEPS)
    timesteps = list(REPLAY_TIMESTEPS[:end])
    return timesteps, [_readings_cache.get(ts) for ts in timesteps]


def compact_triggers(timestep: str) -> dict:
    """The trigger collection without geometry: the fixture form (and the live route's data)."""
    timesteps, readings = series(timestep)
    released = engine.released(readings)
    return {
        "type": "FeatureCollection",
        "features": engine.features(readings[-1], released[-1], timestep),
    }


def get_triggers(timestep: str) -> TriggerEventCollection:
    data = _demo_fixture(fixture_key(timestep)) if _demo(timestep) else compact_triggers(timestep)
    return engine.collection_from(data["features"], _geometry())


def get_summary() -> InsuranceSummary:
    if _demo():
        return InsuranceSummary.model_validate(_demo_fixture(SUMMARY_FIXTURE_KEY))
    return engine.summary(*series())


def clear_cache() -> None:
    _readings_cache.clear()
