"""People in the surge zone (v1.3 change, pending Dev A): population_2011 x the share of inhabited
land with surge >= 0.3 m, per block and summed for the district, on both horizons."""

import json

import pytest

from app.core.demo import DEMO_DIR
from app.impact import horizon as fh
from app.risk import service as risk
from app.risk import weights as W
from app.risk.engine import DECIMALS, surge_population
from app.schemas import REPLAY_TIMESTEPS, RiskBreakdown


def read(key: str) -> dict:
    return json.loads((DEMO_DIR / f"{key}.json").read_text("utf-8"))


def _breakdowns() -> list[tuple[str, int, dict]]:
    h24 = read(fh.index_key(risk.BREAKDOWN_H24_PREFIX))["files"]
    out = []
    for ts in REPLAY_TIMESTEPS:
        out.append((ts, 0, read(risk.breakdown_fixture_key(ts))))
        out.append((ts, 24, fh.restore(read(h24[ts]), ts)))
    return out


BREAKDOWNS = _breakdowns()


def test_the_threshold_is_the_road_cut_depth():
    assert W.SURGE_LAND_THRESHOLD_M == 0.3


def test_surge_population_is_population_times_the_surge_share():
    assert surge_population(200_000, {"surge": 0.25, "wind": 1.0, "flood": 1.0}) == 50_000
    assert surge_population(1_000, {"surge": 0.0, "wind": 0.9, "flood": 0.9}) == 0
    assert surge_population(3, {"surge": 0.5}) == 2


@pytest.mark.parametrize(("ts", "horizon", "bd"), BREAKDOWNS, ids=lambda v: str(v)[:16])
def test_committed_breakdowns(ts, horizon, bd):
    """Each block: population x surge share, within the rounding of the stored share (the
    engine uses the unrounded one). The district total is the sum."""
    model = RiskBreakdown.model_validate(bd)
    assert model.horizon_h == horizon
    tolerance = 0.5 * 10**-DECIMALS
    for b in model.blocks:
        estimate = b.population_2011 * b.hazard.surge
        assert abs(b.surge_population - estimate) <= b.population_2011 * tolerance + 0.5
        assert b.surge_population <= b.population_2011
    assert model.surge_population_total == sum(b.surge_population for b in model.blocks)


def test_the_expected_hazard_never_has_fewer_people_in_surge():
    """Horizon 24 is the worst case over the next 24 h, which includes now."""
    by = {(ts, h): bd for ts, h, bd in BREAKDOWNS}
    for ts in REPLAY_TIMESTEPS:
        now = {b["block_id"]: b["surge_population"] for b in by[(ts, 0)]["blocks"]}
        for b in by[(ts, 24)]["blocks"]:
            assert b["surge_population"] >= now[b["block_id"]], (ts, b["block_name"])


def test_somebody_is_in_the_surge_zone_by_landfall():
    by = {(ts, h): bd for ts, h, bd in BREAKDOWNS}
    assert by[(REPLAY_TIMESTEPS[-1], 0)]["surge_population_total"] > 0
