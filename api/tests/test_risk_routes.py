"""GET /api/risk/scores, /breakdown and /unscored-areas on the hand-built scenario."""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import demo as demo_module
from app.core.config import Settings
from app.exposure import ingest
from app.exposure import service as exposure
from app.impact import service as impact
from app.impact.synthetic import synthetic_hazards
from app.main import app
from app.risk import blocks as block_data
from app.risk import fixtures as risk_fixtures
from app.risk import service, weights
from app.schemas import (
    LANDFALL_TIMESTEP,
    RiskBreakdown,
    RiskScoreCollection,
    UnscoredAreaCollection,
)
from tests import impact_scenario as S
from tests import risk_scenario as R

TS = LANDFALL_TIMESTEP
client = TestClient(app)
URL = "/api/risk/scores"


def _clear():
    for module in (impact, exposure, service):
        module.clear_cache()


def _mode(monkeypatch, demo_mode: bool, demo_dir=None):
    settings = Settings(_env_file=None, DEMO_MODE=demo_mode)
    for module in (impact, exposure, service, demo_module):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    if demo_dir is not None:
        monkeypatch.setattr(demo_module, "DEMO_DIR", demo_dir)
    _clear()


@pytest.fixture
def files(tmp_path, monkeypatch):
    parquet, graphml = tmp_path / "infra.parquet", tmp_path / "roads.graphml"
    ingest.write_infra(S.records(), parquet)
    ingest.save_road_graph(S.build_graph(), graphml)
    monkeypatch.setattr(exposure, "INFRA_PATH", parquet)
    monkeypatch.setattr(impact, "GRAPH_PATH", graphml)
    monkeypatch.setattr(impact, "ANCHOR", S.ANCHOR)
    monkeypatch.setattr(block_data, "load_blocks", lambda: R.blocks())
    yield tmp_path
    _clear()


@pytest.fixture
def live(files, monkeypatch):
    """Live mode on Dev A's real hazard layers."""
    _mode(monkeypatch, demo_mode=False)
    return files


@pytest.fixture
def synth(live, monkeypatch):
    """Live mode on the synthetic test hazards (tests only), independent of Dev A's model."""
    monkeypatch.setattr(impact, "get_hazard_layer", lambda h, ts: synthetic_hazards(ts)[h])
    _clear()
    return live


def test_scores(synth):
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 200, resp.text
    fc = RiskScoreCollection.model_validate(resp.json())
    assert [f.properties.block_id for f in fc.features] == list(R.BLOCK_BOXES)
    assert all(f.properties.timestep == TS for f in fc.features)


def test_live_without_dev_a_hazards_is_501(live, monkeypatch):
    def _stub(hazard_type, timestep):
        raise NotImplementedError("get_hazard_layer: not implemented")

    monkeypatch.setattr(impact, "get_hazard_layer", _stub)
    _clear()
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 501 and "get_hazard_layer" in resp.json()["detail"]


def test_live_with_dev_a_hazards_succeeds(live):
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 200, resp.text
    fc = RiskScoreCollection.model_validate(resp.json())
    assert [f.properties.block_id for f in fc.features] == list(R.BLOCK_BOXES)


def test_synthetic_is_not_a_route_parameter(synth):
    """?synthetic=true was removed: it's ignored like any unknown query parameter."""
    plain = client.get(f"{URL}?timestep={TS}").json()
    assert client.get(f"{URL}?timestep={TS}&synthetic=true").json() == plain


def test_live_timestep_is_501_and_bad_timestep_422(live):
    assert client.get(f"{URL}?timestep=live").status_code == 501
    assert client.get(f"{URL}?timestep=2020-05-20T13:00:00Z").status_code == 422


def test_risk_reuses_the_impact_cache(synth, monkeypatch):
    calls = []
    compute = impact._compute

    def counting(timestep):
        calls.append(timestep)
        return compute(timestep)

    monkeypatch.setattr(impact, "_compute", counting)
    assert client.get(f"/api/impact/results?timestep={TS}").status_code == 200
    assert client.get(f"{URL}?timestep={TS}").status_code == 200
    assert client.get(f"{URL}?timestep={TS}").status_code == 200
    assert calls == [TS]


def test_demo_without_fixture_is_501(files, monkeypatch):
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 501 and service.fixture_key(TS) in resp.json()["detail"]


def test_demo_serves_compact_fixture(files, monkeypatch):
    # Scores are stored without block polygons; the route adds them back from the blocks, and
    # the rebuilt response equals the computed one.
    _mode(monkeypatch, demo_mode=False)
    monkeypatch.setattr(impact, "get_hazard_layer", lambda h, ts: synthetic_hazards(ts)[h])
    computed = client.get(f"{URL}?timestep={TS}").json()
    fixture = risk_fixtures.to_fixture(RiskScoreCollection.model_validate(computed))
    assert all("geometry" not in f for f in fixture["features"])
    (files / f"{service.fixture_key(TS)}.json").write_text(json.dumps(fixture), encoding="utf-8")
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    assert client.get(f"{URL}?timestep={TS}").json() == computed


def test_demo_fixture_for_unknown_block_fails():
    fixture = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "x", "properties": {"block_id": "99999"}}
    ]}  # fmt: skip
    with pytest.raises(ValueError, match="99999"):
        risk_fixtures.from_fixture(fixture, R.blocks())


def test_missing_reference_data_is_503(synth, monkeypatch):
    def missing():
        raise block_data.ReferenceDataMissing("s24p_blocks.csv has no population_2011 column")

    monkeypatch.setattr(block_data, "load_blocks", missing)
    service.clear_cache()
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 503 and "population_2011" in resp.json()["detail"]


def test_unscored_areas_live(live):
    resp = client.get("/api/risk/unscored-areas")
    assert resp.status_code == 200
    fc = UnscoredAreaCollection.model_validate(resp.json())
    assert [f.properties.label for f in fc.features] == ["Municipal area, not scored"]


def test_unscored_areas_demo_uses_fixture(files, monkeypatch):
    _mode(monkeypatch, demo_mode=False)
    computed = client.get("/api/risk/unscored-areas").json()
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    missing = client.get("/api/risk/unscored-areas")
    assert missing.status_code == 501 and service.UNSCORED_FIXTURE_KEY in missing.json()["detail"]
    path = files / f"{service.UNSCORED_FIXTURE_KEY}.json"
    path.write_text(json.dumps(computed), encoding="utf-8")
    assert client.get("/api/risk/unscored-areas").json() == computed


def test_breakdown_matches_scores(synth):
    scores = client.get(f"{URL}?timestep={TS}").json()
    resp = client.get(f"/api/risk/breakdown?timestep={TS}")
    assert resp.status_code == 200, resp.text
    bd = RiskBreakdown.model_validate(resp.json())
    assert bd.timestep == TS
    assert [b.block_id for b in bd.blocks] == [
        f["properties"]["block_id"] for f in scores["features"]
    ]
    by_id = {f["properties"]["block_id"]: f["properties"] for f in scores["features"]}
    for b in bd.blocks:
        hazard = min(1, max(b.hazard.surge, b.hazard.wind) + weights.FLOOD_WEIGHT * b.hazard.flood)
        assert hazard == pytest.approx(by_id[b.block_id]["components"]["hazard"], abs=1e-3)
        assert b.population_2011 == R.POPULATION
    fragment = next(b for b in bd.blocks if b.block_id == "90003")
    assert fragment.hospital_travel_min is not None  # the cut-off hospital is in this block
    mainland = next(b for b in bd.blocks if b.block_id == "90001")
    assert mainland.hospital_travel_min is None  # no hospital reachable


def test_breakdown_shares_the_risk_cache(synth, monkeypatch):
    calls = []
    compute = service._compute
    monkeypatch.setattr(service, "_compute", lambda ts: calls.append(ts) or compute(ts))
    client.get(f"{URL}?timestep={TS}")
    client.get(f"/api/risk/breakdown?timestep={TS}")
    assert calls == [TS]


def test_breakdown_demo_without_fixture_is_501(files, monkeypatch):
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    resp = client.get(f"/api/risk/breakdown?timestep={TS}")
    assert resp.status_code == 501 and service.breakdown_fixture_key(TS) in resp.json()["detail"]
