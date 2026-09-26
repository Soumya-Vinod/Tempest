"""Parametric insurance (illustrative): tiers, max-not-sum, the 90th-percentile reading, released
amounts that only go up, first triggers, the routes and the committed fixtures."""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core import demo as demo_module
from app.core.config import Settings
from app.core.demo import DEMO_DIR
from app.impact import service as impact
from app.insurance import engine
from app.insurance import service as insurance
from app.insurance.constants import SURGE_TIERS_M, WIND_TIERS_MS
from app.main import app
from app.risk.blocks import load_blocks
from app.schemas import (
    LANDFALL_TIMESTEP,
    REPLAY_TIMESTEPS,
    HazardLayerCollection,
    InsuranceSummary,
)

client = TestClient(app)
T3, T0 = REPLAY_TIMESTEPS[-2], REPLAY_TIMESTEPS[-1]
NAMKHANA = "02439"


@pytest.fixture
def demo(monkeypatch):
    s = Settings(_env_file=None, DEMO_MODE=True)
    for module in (insurance, impact, demo_module):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    insurance.clear_cache()
    yield
    insurance.clear_cache()


def hazard_fixture(kind: str, timestep: str) -> HazardLayerCollection:
    key = f"hazard__layers-{kind}__{timestep.replace('-', '').replace(':', '')[:13]}Z"
    return HazardLayerCollection.model_validate_json((DEMO_DIR / f"{key}.json").read_text("utf-8"))


# --- Tiers ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "tier", "fraction"),
    [(32.99, 0, 0.0), (33.0, 1, 0.25), (45.99, 1, 0.25), (46.0, 2, 0.5), (61.99, 2, 0.5),
     (62.0, 3, 1.0), (80.0, 3, 1.0)],
)  # fmt: skip
def test_wind_tier_boundaries(value, tier, fraction):
    t = engine.tier_of(value, WIND_TIERS_MS)
    assert (t.index, t.fraction) == (tier, fraction)


@pytest.mark.parametrize(
    ("value", "tier", "threshold"),
    [(0.99, 0, 1.0), (1.0, 1, 1.0), (1.99, 1, 1.0), (2.0, 2, 2.0), (2.99, 2, 2.0), (3.0, 3, 3.0)],
)
def test_surge_tier_boundaries_and_threshold(value, tier, threshold):
    t = engine.tier_of(value, SURGE_TIERS_M)
    assert (t.index, t.threshold) == (tier, threshold)  # no trigger: the first tier's threshold


def test_payout_is_the_higher_tier_never_the_sum():
    metric, observed, tier = engine.governing(wind=35.0, surge=1.2)  # tier 1 and tier 1
    assert tier.fraction == 0.25  # not 0.5
    metric, observed, tier = engine.governing(wind=35.0, surge=2.4)  # tier 1 and tier 2
    assert (metric, observed, tier.index, tier.fraction) == ("surge_depth", 2.4, 2, 0.5)
    metric, _, tier = engine.governing(wind=63.0, surge=2.4)
    assert (metric, tier.fraction) == ("wind_speed", 1.0)


def test_untriggered_block_reports_the_metric_closest_to_its_first_tier():
    metric, observed, tier = engine.governing(wind=30.0, surge=0.2)  # 91 % vs 20 %
    assert (metric, observed, tier.index, tier.threshold) == ("wind_speed", 30.0, 0, 33.0)


# --- The 90th-percentile reading ------------------------------------------------------------------


def test_one_extreme_cell_cannot_set_the_reading():
    assert engine.reading(np.array([0.1, 0.2, 0.3, 0.4, 9.0])) == 0.4
    assert engine.reading(np.array([0.1, 0.2, 0.3, 9.0, 9.0])) == 9.0  # two cells do
    assert engine.reading(np.array([])) == 0.0


def test_a_single_extreme_cell_in_a_real_block_does_not_trigger_it():
    blocks = load_blocks()
    surge = hazard_fixture("surge", T0)
    before = engine.block_cell_values(surge, blocks)
    i = blocks.codes.index("02433")  # Kultali
    cells = before[i]
    assert len(cells) >= 5
    # Push the block's highest cell to 5 m (tier 3 on its own).
    target = float(cells.max())
    hot = surge.model_copy(deep=True)
    for f in hot.features:
        if f.properties.value == target:
            f.properties.value = 5.0
    after = engine.block_cell_values(hot, blocks)[i]
    assert after.max() == 5.0
    assert engine.reading(after) == engine.reading(cells) < 3.0


def test_cells_must_overlap_inhabited_land_by_1_km2():
    blocks = load_blocks()
    counts = [len(v) for v in engine.block_cell_values(hazard_fixture("wind", T0), blocks)]
    assert min(counts) >= 5  # every block has enough cells for the percentile rule


# --- Readings, payouts, releases ------------------------------------------------------------------


def test_no_trigger_means_zero_payout(demo):
    fc = insurance.get_triggers(REPLAY_TIMESTEPS[0])
    assert len(fc.features) == 29
    for f in fc.features:
        p = f.properties
        assert not p.triggered and p.tier == 0
        assert p.payout_estimate_inr == 0 and p.released_payout_inr == 0


def test_sum_insured_is_1000_inr_per_resident(demo):
    blocks = load_blocks()
    fc = insurance.get_triggers(T3)
    by_zone = {f.properties.zone_id: f.properties for f in fc.features}
    i = blocks.codes.index(NAMKHANA)
    assert by_zone[NAMKHANA].sum_insured_inr == float(blocks.population[i]) * 1000


def test_released_payout_never_falls_namkhana(demo):
    at = {ts: {f.properties.zone_id: f.properties for f in insurance.get_triggers(ts).features}
          for ts in (T3, T0)}  # fmt: skip
    t3, t0 = at[T3][NAMKHANA], at[T0][NAMKHANA]
    assert t3.tier == 3 and t3.metric == "surge_depth"
    assert t0.observed < t3.observed and t0.tier < t3.tier  # the reading fell...
    assert t0.released_tier == 3  # ...but released money is not taken back
    assert t0.released_payout_inr == t3.payout_estimate_inr
    assert t0.payout_estimate_inr < t0.released_payout_inr


def test_released_uses_the_highest_tier_so_far():
    def zone(tier):
        t = engine.Tier(tier, 1.0, [0, 0.25, 0.5, 1.0][tier])
        return engine.ZoneReading("z", "Zone", "surge_depth", 1.0, t, 1000.0, 0.0, 1.0)

    rel = engine.released([[zone(0)], [zone(1)], [zone(3)], [zone(2)], [zone(0)]])
    assert [r[0].tier for r in rel] == [0, 1, 3, 3, 3]
    assert [r[0].payout_inr for r in rel] == [0, 250, 1000, 1000, 1000]


def test_first_trigger_is_the_first_timestep_with_a_tier():
    def step(tier):
        t = engine.Tier(tier, 1.0, [0, 0.25, 0.5, 1.0][tier])
        return [engine.ZoneReading("z", "Zone", "surge_depth", 1.0, t, 1000.0, 0.0, 1.0)]

    ts = list(REPLAY_TIMESTEPS[-4:])
    s = engine.summary(ts, [step(0), step(1), step(3), step(2)])
    [z] = s.zones
    assert z.first_trigger_timestep == ts[1] and z.hours_before_landfall == 6
    assert (z.first_trigger_tier, z.first_trigger_payout_inr) == (1, 250)
    assert (z.final_released_tier, z.final_released_payout_inr) == (3, 1000)
    assert [d.released_payout_inr for d in s.district] == [0, 250, 1000, 1000]


def test_never_triggered_zone_has_no_first_trigger():
    t = engine.Tier(0, 1.0, 0.0)
    s = engine.summary(
        [LANDFALL_TIMESTEP],
        [[engine.ZoneReading("z", "Zone", "surge_depth", 0.1, t, 1000.0, 0.0, 0.1)]],
    )
    assert s.zones[0].first_trigger_timestep is None and s.zones[0].first_trigger_tier == 0


# --- The committed fixtures and the routes --------------------------------------------------------


def test_district_total_never_decreases_across_the_25_timesteps():
    summary = InsuranceSummary.model_validate_json(
        (DEMO_DIR / "insurance__summary.json").read_text("utf-8")
    )
    totals = [d.released_payout_inr for d in summary.district]
    assert len(totals) == 25
    assert all(b >= a for a, b in zip(totals, totals[1:], strict=False))
    assert totals[0] == 0 and totals[-1] > 0


def test_summary_matches_the_trigger_fixtures(demo):
    summary = insurance.get_summary()
    for d in summary.district:
        fc = insurance.get_triggers(d.timestep)
        assert d.released_payout_inr == sum(f.properties.released_payout_inr for f in fc.features)


def test_fixtures_round_trip_the_live_computation(demo, monkeypatch):
    live = Settings(_env_file=None, DEMO_MODE=False)
    monkeypatch.setattr(insurance, "get_settings", lambda: live)
    computed = insurance.compact_triggers(T3)  # hazards still come from Dev A's fixtures
    fixture = json.loads((DEMO_DIR / f"{insurance.fixture_key(T3)}.json").read_text("utf-8"))
    assert computed == fixture


def test_routes(demo):
    r = client.get("/api/insurance/triggers", params={"timestep": T3})
    assert r.status_code == 200
    features = r.json()["features"]
    assert len(features) == 29 and all(f["geometry"] for f in features)
    assert client.get("/api/insurance/summary").status_code == 200
    assert client.get("/api/insurance/triggers", params={"timestep": "live"}).status_code == 501
    assert client.get("/api/insurance/triggers", params={"timestep": "x"}).status_code == 422
