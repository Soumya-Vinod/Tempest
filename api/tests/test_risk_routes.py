"""GET /api/risk/scores and /api/risk/unscored-areas on the hand-built scenario."""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import demo as demo_module
from app.core.config import Settings
from app.exposure import ingest
from app.exposure import service as exposure
from app.impact import service as impact
from app.main import app
from app.risk import blocks as block_data
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
    _mode(monkeypatch, demo_mode=False)
    return files


def test_synthetic_scores(live):
    resp = client.get(f"{URL}?timestep={TS}&synthetic=true")
    assert resp.status_code == 200, resp.text
    fc = RiskScoreCollection.model_validate(resp.json())
    assert [f.properties.block_id for f in fc.features] == list(R.BLOCK_BOXES)
    assert all(f.properties.timestep == TS for f in fc.features)


def test_live_without_dev_a_hazards_is_501(live):
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 501 and "get_hazard_layer" in resp.json()["detail"]


def test_live_timestep_is_501_and_bad_timestep_422(live):
    assert client.get(f"{URL}?timestep=live&synthetic=true").status_code == 501
    assert client.get(f"{URL}?timestep=2020-05-20T13:00:00Z").status_code == 422


def test_risk_reuses_the_impact_cache(live, monkeypatch):
    calls = []
    compute = impact._compute

    def counting(timestep, synthetic):
        calls.append((timestep, synthetic))
        return compute(timestep, synthetic)

    monkeypatch.setattr(impact, "_compute", counting)
    assert client.get(f"/api/impact/results?timestep={TS}&synthetic=true").status_code == 200
    assert client.get(f"{URL}?timestep={TS}&synthetic=true").status_code == 200
    assert client.get(f"{URL}?timestep={TS}&synthetic=true").status_code == 200
    assert calls == [(TS, True)]


def test_demo_rejects_synthetic(files, monkeypatch):
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    assert client.get(f"{URL}?timestep={TS}&synthetic=true").status_code == 422


def test_demo_without_fixture_is_501(files, monkeypatch):
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 501 and service.fixture_key(TS) in resp.json()["detail"]


def test_demo_serves_fixture(files, monkeypatch):
    _mode(monkeypatch, demo_mode=False)
    computed = client.get(f"{URL}?timestep={TS}&synthetic=true").json()
    (files / f"{service.fixture_key(TS)}.json").write_text(json.dumps(computed), encoding="utf-8")
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    assert client.get(f"{URL}?timestep={TS}").json() == computed


def test_missing_reference_data_is_503(live, monkeypatch):
    def missing():
        raise block_data.ReferenceDataMissing("s24p_blocks.csv has no population_2011 column")

    monkeypatch.setattr(block_data, "load_blocks", missing)
    service.clear_cache()
    resp = client.get(f"{URL}?timestep={TS}&synthetic=true")
    assert resp.status_code == 503 and "population_2011" in resp.json()["detail"]


@pytest.mark.parametrize("demo_mode", [False, True])
def test_unscored_areas(files, monkeypatch, demo_mode):
    _mode(monkeypatch, demo_mode=demo_mode, demo_dir=files)
    resp = client.get("/api/risk/unscored-areas")
    assert resp.status_code == 200
    fc = UnscoredAreaCollection.model_validate(resp.json())
    assert [f.properties.label for f in fc.features] == ["Municipal area, not scored"]


def test_breakdown_matches_scores(live):
    scores = client.get(f"{URL}?timestep={TS}&synthetic=true").json()
    resp = client.get(f"/api/risk/breakdown?timestep={TS}&synthetic=true")
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


def test_breakdown_shares_the_risk_cache(live, monkeypatch):
    calls = []
    compute = service._compute
    monkeypatch.setattr(service, "_compute", lambda ts, syn: calls.append(ts) or compute(ts, syn))
    client.get(f"{URL}?timestep={TS}&synthetic=true")
    client.get(f"/api/risk/breakdown?timestep={TS}&synthetic=true")
    assert calls == [TS]


def test_breakdown_demo_rules(files, monkeypatch):
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    assert client.get(f"/api/risk/breakdown?timestep={TS}&synthetic=true").status_code == 422
    resp = client.get(f"/api/risk/breakdown?timestep={TS}")
    assert resp.status_code == 501 and service.breakdown_fixture_key(TS) in resp.json()["detail"]
