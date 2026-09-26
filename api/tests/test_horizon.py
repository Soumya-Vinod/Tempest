"""Forecast horizon (v1.3 change, pending Dev A): the expected hazard, horizon-24 impact, risk
and breakdown, their deduplicated fixtures, and what advisories, suggestions and insurance make
of it."""

import json

import pytest
from fastapi.testclient import TestClient

from app.advisory import facts as facts_module
from app.advisory import prompt
from app.core import demo as demo_module
from app.core.config import Settings
from app.core.demo import DEMO_DIR
from app.exposure import service as exposure
from app.impact import fixtures as impact_fixtures
from app.impact import horizon as fh
from app.impact import service as impact
from app.insurance import service as insurance
from app.main import app
from app.risk import fixtures as risk_fixtures
from app.risk import service as risk
from app.risk.blocks import load_blocks
from app.risk.engine import to_breakdown, to_collection
from app.schemas import REPLAY_TIMESTEPS, RiskBreakdown

client = TestClient(app)
T6, T3, T0 = REPLAY_TIMESTEPS[-3], REPLAY_TIMESTEPS[-2], REPLAY_TIMESTEPS[-1]
T27, T33 = REPLAY_TIMESTEPS[-10], REPLAY_TIMESTEPS[-12]


def set_demo(monkeypatch, on: bool) -> None:
    s = Settings(_env_file=None, DEMO_MODE=on)
    for module in (impact, risk, exposure, insurance, demo_module):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    for module in (impact, risk, exposure, insurance):
        module.clear_cache()


@pytest.fixture
def demo(monkeypatch):
    set_demo(monkeypatch, True)
    yield
    for module in (impact, risk, exposure, insurance):
        module.clear_cache()


# --- The expected hazard --------------------------------------------------------------------------


def test_window_is_the_next_24_h_capped_at_landfall():
    assert fh.window(REPLAY_TIMESTEPS[0]) == list(REPLAY_TIMESTEPS[:9])  # t .. t+24 h: 9 steps
    assert fh.window(T6) == [T6, T3, T0]  # capped at landfall
    assert fh.window(T0) == [T0]
    assert fh.window(T3, 0) == [T3]


def test_expected_hazard_is_the_cell_wise_max_over_the_window(demo):
    layers = [impact.hazard_layers(ts) for ts in fh.window(T6)]
    expected = fh.expected_hazard(layers)
    for h in fh.HAZARD_TYPES:
        by_cell = {}
        for step in layers:
            for f in step[h].features:
                cell = f.properties.id.split("__")[1]
                by_cell[cell] = max(by_cell.get(cell, 0), f.properties.value)
        got = {f.properties.id.split("__")[1]: f.properties.value for f in expected[h].features}
        assert got == by_cell
        # Labelled with the timestep itself: its ids and timestep.
        assert [f.id for f in expected[h].features] == [f.id for f in layers[0][h].features]
    # Namkhana's T-3 surge peak is already expected at T-6.
    surge_t6 = max(f.properties.value for f in layers[0]["surge"].features)
    assert max(f.properties.value for f in expected["surge"].features) > surge_t6


def test_at_landfall_both_horizons_agree(demo):
    now = impact.get_results(T0)
    later = impact.get_results(T0, horizon_h=24)
    strip = lambda fc: [(f.properties.infra_id, f.properties.hazard_type, f.properties.status)  # noqa: E731
                        for f in fc.features]  # fmt: skip
    assert strip(now) == strip(later)
    assert {f.properties.horizon_h for f in later.features} == {24}


# --- Routes ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/impact/results", "/api/risk/scores", "/api/risk/breakdown"])
def test_horizon_param(demo, path):
    for horizon, status in (("0", 200), ("24", 200), ("12", 422), ("-24", 422), ("x", 422)):
        r = client.get(path, params={"timestep": T3, "horizon": horizon})
        assert r.status_code == status, (horizon, r.text[:120])
    body = client.get(path, params={"timestep": T3, "horizon": "24"}).json()
    if path.endswith("breakdown"):
        assert body["horizon_h"] == 24
    else:
        assert {f["properties"]["horizon_h"] for f in body["features"][:50]} == {24}
    default = client.get(path, params={"timestep": T3}).json()
    assert (default if path.endswith("breakdown") else default["features"][0]["properties"])[
        "horizon_h"
    ] == 0


def test_isolation_is_expected_earlier_than_it_happens(demo):
    names = {f.id: f.properties.name for f in exposure.get_infra().features}
    watch = {"Gosaba Rural Hospital", "Gangasagar PHC", "Mahendraganj PHC"}

    def first(h):
        for ts in REPLAY_TIMESTEPS:
            iso = {names.get(i) for i in impact.isolated_ids(ts, h)}
            if watch <= iso:
                return ts
        return None

    assert first(0) == T3 and first(24) == T27  # a full day of warning


# --- Deduplicated fixtures ------------------------------------------------------------------------


PREFIXES = [impact.H24_PREFIX, risk.SCORES_H24_PREFIX, risk.BREAKDOWN_H24_PREFIX]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_every_timestep_resolves_and_every_file_is_used(prefix):
    index = json.loads((DEMO_DIR / f"{fh.index_key(prefix)}.json").read_text("utf-8"))
    assert index["horizon_h"] == 24
    assert list(index["files"]) == list(REPLAY_TIMESTEPS)
    on_disk = {p.stem for p in DEMO_DIR.glob(f"{prefix}-*.json")} - {fh.index_key(prefix)}
    assert on_disk == set(index["files"].values())  # nothing missing, nothing orphaned
    assert len(on_disk) < len(REPLAY_TIMESTEPS)  # deduplication actually happened


def test_h24_fixtures_match_a_fresh_computation(monkeypatch):
    """Every timestep: the DEMO_MODE response (dedup file + index) equals the live computation."""
    blocks = load_blocks()
    set_demo(monkeypatch, False)
    ctx = risk.context()
    fresh = {}
    for ts in REPLAY_TIMESTEPS:
        results = impact.results(ts, 24)
        evaluated = risk.evaluate(impact.hazard_layers(ts, 24), results, ctx)
        fresh[ts] = (
            impact_fixtures.to_fixture(results),
            to_collection(evaluated, ctx, ts, 24),
            to_breakdown(evaluated, ctx, ts, 24),
        )
    set_demo(monkeypatch, True)
    infra = exposure.get_infra()
    for ts in REPLAY_TIMESTEPS:
        compact, scores, breakdown = fresh[ts]
        assert impact.demo_compact(ts, 24) == compact, ts
        served = impact_fixtures.from_fixture(impact.demo_compact(ts, 24), infra, ts, 24)
        assert all(f.properties.timestep == ts for f in served.features)
        assert risk.get_scores(ts, 24) == risk_fixtures.from_fixture(
            risk_fixtures.to_fixture(scores), blocks
        ), ts
        assert risk.get_breakdown(ts, 24) == RiskBreakdown.model_validate(
            breakdown.model_dump(mode="json")
        ), ts


# --- Advisories, suggestions, insurance -----------------------------------------------------------


def test_facts_describe_expected_isolations_with_hours(demo):
    f = facts_module.build_facts("02438", T6)  # Sagar, 6 h before landfall
    by_key = {c.key: c.value for c in f.citations}
    assert by_key["isolated_count"] == 0  # nothing is cut off yet at T-6
    expected = {
        by_key[k]: by_key[k.replace("_name", "_hours")]
        for k in by_key
        if k.startswith("expected_") and k.endswith("_name")
    }
    assert expected == {"Gangasagar PHC": 3, "Mahendraganj PHC": 3}  # isolated at T-3
    assert by_key["expected_isolated_count"] == 2
    assert by_key["expected_1_cause"] == "road flooded by storm surge"
    assert by_key["risk_score_24h"] >= by_key["risk_score"]
    assert "risk_score_24h" not in facts_module.offered_keys(f.citations)


def test_prompt_rule_for_expected_isolation():
    assert "expected to be cut off" in prompt.SYSTEM_PROMPT
    assert "{{expected_<n>_hours}}" in prompt.SYSTEM_PROMPT
    assert "preparatory actions" in prompt.SYSTEM_PROMPT


def test_suggestions_start_from_the_expected_risk(demo):
    first = next(
        ts
        for ts in REPLAY_TIMESTEPS
        if client.get("/api/advisory/suggestions", params={"timestep": ts}).json()["blocks"]
    )
    assert first == T33
    blocks = client.get("/api/advisory/suggestions", params={"timestep": T33}).json()["blocks"]
    assert [b["block_name"] for b in blocks] == ["Namkhana"]


def test_insurance_pays_on_the_observed_hazard_but_shows_the_expected_tier(demo):
    fc = insurance.get_triggers(T27)
    namkhana = next(f.properties for f in fc.features if f.properties.zone_name == "Namkhana")
    assert namkhana.tier == 0 and namkhana.payout_estimate_inr == 0  # nothing observed yet
    assert namkhana.released_payout_inr == 0
    assert namkhana.expected_tier_24h == 3
