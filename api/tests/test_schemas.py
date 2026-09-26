import uuid

import pytest
from pydantic import ValidationError

from app.core import demo
from app.core.config import Settings
from app.hazard.service import get_hazard_layer
from app.schemas import (
    LANDFALL_TIMESTEP,
    REPLAY_TIMESTEPS,
    AdvisoryProperties,
    Citation,
    DispatchReceipt,
    HazardLayer,
    HazardLayerCollection,
    ImpactResultProperties,
    RiskScoreProperties,
    TriggerEventProperties,
)

TS = LANDFALL_TIMESTEP
SQUARE = [[[88.0, 21.5], [88.1, 21.5], [88.1, 21.6], [88.0, 21.5]]]


def test_replay_timeline():
    assert len(REPLAY_TIMESTEPS) == 25
    assert REPLAY_TIMESTEPS[0] == "2020-05-17T12:00:00Z"
    assert REPLAY_TIMESTEPS[-1] == TS == "2020-05-20T12:00:00Z"


def test_hazard_layer_valid_and_unit_checked():
    feature = {
        "type": "Feature",
        "id": "c1",
        "geometry": {"type": "Polygon", "coordinates": SQUARE},
        "properties": {
            "id": "c1",
            "hazard_type": "surge",
            "timestep": TS,
            "value": 2.4,
            "unit": "m",
            "severity": 0.7,
        },
    }
    HazardLayer.model_validate(feature)
    feature["properties"]["unit"] = "m/s"
    with pytest.raises(ValidationError):
        HazardLayer.model_validate(feature)


def test_feature_id_must_match_properties_id():
    feature = {
        "id": "other",
        "geometry": {"type": "Polygon", "coordinates": SQUARE},
        "properties": {
            "id": "c1",
            "hazard_type": "wind",
            "timestep": TS,
            "value": 40,
            "unit": "m/s",
            "severity": 0.5,
        },
    }
    with pytest.raises(ValidationError):
        HazardLayer.model_validate(feature)


def test_live_is_not_a_response_timestep():
    with pytest.raises(ValidationError):
        ImpactResultProperties(
            id="x", infra_id="i", hazard_type="wind", status="ok", timestep="live", pathway=[]
        )


def test_ok_impact_has_empty_pathway():
    with pytest.raises(ValidationError):
        ImpactResultProperties(
            id="x",
            infra_id="i",
            hazard_type="surge",
            status="ok",
            timestep=TS,
            pathway=[{"id": "hazard:surge", "label": "Surge", "type": "hazard"}],
        )


@pytest.mark.parametrize("block_id", ["1234", "872a1070fffffff", "b-12"])
def test_block_id_accepts_fixture_safe(block_id):
    RiskScoreProperties(
        id=f"{block_id}__{TS}",
        block_id=block_id,
        block_source="h3_r7",
        block_name="x",
        timestep=TS,
        score=0.5,
        components={"hazard": 0.5, "exposure": 0.5, "vulnerability": 0.5},
    )


@pytest.mark.parametrize("block_id", ["Block1", "b_1", "a.b", "a/b", ""])
def test_block_id_rejects_unsafe(block_id):
    with pytest.raises(ValidationError):
        RiskScoreProperties(
            id="x",
            block_id=block_id,
            block_source="census2011_cd",
            block_name="x",
            timestep=TS,
            score=0.5,
            components={"hazard": 0.5, "exposure": 0.5, "vulnerability": 0.5},
        )


TEXT = {"headline": "h", "body": "b", "actions": ["a", "b", "c"]}
TEXTS = {"en": TEXT, "bn": TEXT, "hi": TEXT}


def _advisory(**changes):
    fields = {
        "id": "a",
        "block_id": "b-1",
        "block_name": "B",
        "timestep": TS,
        "texts": TEXTS,
        "templates": TEXTS,
        "citations": [],
        "status": "draft",
        "created_at": "2020-05-20T12:00:00Z",
    }
    return AdvisoryProperties(**(fields | changes))


def test_approved_advisory_needs_approver():
    _advisory()
    with pytest.raises(ValidationError):
        _advisory(status="approved")
    _advisory(status="approved", approved_by="A (BDO)", approved_at="2020-05-20T12:00:00Z")


def test_rejected_advisory_needs_reason():
    with pytest.raises(ValidationError):
        _advisory(status="rejected", rejected_at="2020-05-20T12:00:00Z")
    _advisory(status="rejected", rejection_reason="r", rejected_at="2020-05-20T12:00:00Z")


def test_advisory_needs_three_to_five_actions():
    for n in (2, 6):
        with pytest.raises(ValidationError):
            _advisory(texts={**TEXTS, "bn": {**TEXT, "actions": ["x"] * n}})


def test_citation_value_can_be_text():
    Citation(key="isolated_1_name", label="l", value="Gosaba Rural Hospital", unit=None, source="s")


@pytest.mark.parametrize("advisory_id", ["3F2504E0-4F89-41D3-9A0C-0305E82C3301", "a_1", "a.b", ""])
def test_advisory_id_rejects_unsafe(advisory_id):
    with pytest.raises(ValidationError):
        AdvisoryProperties(
            id=advisory_id,
            block_id="b-1",
            timestep=TS,
            language="en",
            body="text",
            citations=[],
            status="draft",
            created_at="2020-05-20T12:00:00Z",
        )
    with pytest.raises(ValidationError):
        DispatchReceipt(advisory_id=advisory_id, dispatched_at="2020-05-20T12:00:00Z", channels=[])


def test_advisory_id_accepts_lowercase_uuid4():
    advisory_id = str(uuid.uuid4())
    DispatchReceipt(advisory_id=advisory_id, dispatched_at="2020-05-20T12:00:00Z", channels=[])


def test_trigger_consistency():
    base = {
        "id": "z__t",
        "zone_id": "z",
        "zone_name": "Zone",
        "timestep": TS,
        "metric": "wind_speed",
        "unit": "m/s",
        "threshold": 40.0,
        "observed": 45.0,
    }
    tier1 = {"tier": 1, "payout_fraction": 0.25, "sum_insured_inr": 4e6}
    released = {"released_tier": 1, "released_payout_inr": 1e6}
    TriggerEventProperties(**base, triggered=True, payout_estimate_inr=1e6, **tier1, **released)
    with pytest.raises(ValidationError):
        TriggerEventProperties(**base, triggered=False, payout_estimate_inr=0)
    # v1.2: tier > 0 exactly when triggered; payout = fraction x sum insured; released >= current.
    with pytest.raises(ValidationError):
        TriggerEventProperties(**base, triggered=True, payout_estimate_inr=1e6)  # tier 0
    with pytest.raises(ValidationError):
        TriggerEventProperties(**base, triggered=True, payout_estimate_inr=2e6, **tier1, **released)
    with pytest.raises(ValidationError):
        TriggerEventProperties(**base, triggered=True, payout_estimate_inr=1e6, **tier1)


def test_get_hazard_layer_live_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        get_hazard_layer("surge", "live")


def test_get_hazard_layer_returns_collection():
    res = get_hazard_layer("surge", TS)
    assert isinstance(res, HazardLayerCollection)


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(demo, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=True))


@pytest.mark.parametrize("key", ["../secrets", "a.b", "a/b", "a\\b", "", "x y"])
def test_fixture_key_rejects_unsafe(demo_on, key):
    with pytest.raises(ValueError):
        demo.load_fixture(key)


def test_fixture_key_accepts_contract_names(demo_on):
    # Valid key for existing fixture returns loaded data (added in v1.1)
    data = demo.load_fixture("hazard__layers-surge__20200520T1200Z")
    assert isinstance(data, dict)

    # Valid key for non-existent fixture passes format validation but raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        demo.load_fixture("hazard__layers-surge__19990101T0000Z")
