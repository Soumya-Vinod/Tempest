"""GET /api/impact/results on the hand-built scenario (tests/impact_scenario.py)."""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import demo as demo_module
from app.core.config import Settings
from app.exposure import ingest
from app.exposure import service as exposure
from app.impact import service
from app.impact.fixtures import fixture_key, to_fixture
from app.main import app
from app.schemas import LANDFALL_TIMESTEP, ImpactResultCollection
from scripts.build_exposure_fixtures import build_fixtures
from tests import impact_scenario as S

TS = LANDFALL_TIMESTEP
client = TestClient(app)
URL = "/api/impact/results"


@pytest.fixture
def files(tmp_path, monkeypatch):
    """The scenario as infra.parquet + roads.graphml, anchored at its own mainland node."""
    parquet, graphml = tmp_path / "infra.parquet", tmp_path / "roads.graphml"
    ingest.write_infra(S.records(), parquet)
    ingest.save_road_graph(S.build_graph(), graphml)
    monkeypatch.setattr(exposure, "INFRA_PATH", parquet)
    monkeypatch.setattr(service, "GRAPH_PATH", graphml)
    monkeypatch.setattr(service, "ANCHOR", S.ANCHOR)
    return tmp_path


def _mode(monkeypatch, demo_mode: bool, demo_dir=None):
    settings = Settings(_env_file=None, DEMO_MODE=demo_mode)
    for module in (service, exposure, demo_module):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    if demo_dir is not None:
        monkeypatch.setattr(demo_module, "DEMO_DIR", demo_dir)
    service.clear_cache()
    exposure.clear_cache()


@pytest.fixture
def live(files, monkeypatch):
    _mode(monkeypatch, demo_mode=False)
    yield files
    service.clear_cache()
    exposure.clear_cache()


def get(params: str):
    resp = client.get(f"{URL}?{params}")
    assert resp.status_code == 200, resp.text
    return ImpactResultCollection.model_validate(resp.json())


def test_live_without_dev_a_hazards_is_501(live):
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 501
    assert "get_hazard_layer" in resp.json()["detail"]


def test_live_synthetic_returns_full_collection(live):
    fc = get(f"timestep={TS}&synthetic=true")
    assert len(fc.features) == len(S.records()) * 3
    assert {f.properties.timestep for f in fc.features} == {TS}


def test_filters(live):
    wind = get(f"timestep={TS}&synthetic=true&hazard_type=wind")
    assert {f.properties.hazard_type for f in wind.features} == {"wind"}
    ok = get(f"timestep={TS}&synthetic=true&status=ok")
    assert ok.features and {f.properties.status for f in ok.features} == {"ok"}


@pytest.mark.parametrize("bad", ["2020-05-20T13:00:00Z", "LIVE", ""])
def test_unknown_timestep_is_422(live, bad):
    assert client.get(f"{URL}?timestep={bad}&synthetic=true").status_code == 422


def test_live_timestep_is_501(live):
    assert client.get(f"{URL}?timestep=live&synthetic=true").status_code == 501


def test_missing_graph_is_503(live, monkeypatch, tmp_path):
    monkeypatch.setattr(service, "GRAPH_PATH", tmp_path / "missing.graphml")
    service.clear_cache()
    resp = client.get(f"{URL}?timestep={TS}&synthetic=true")
    assert resp.status_code == 503 and "ingest_osm.py" in resp.json()["detail"]


def test_demo_rejects_synthetic(files, monkeypatch):
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    assert client.get(f"{URL}?timestep={TS}&synthetic=true").status_code == 422


def test_demo_without_fixture_is_501(files, monkeypatch):
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 501 and fixture_key(TS) in resp.json()["detail"]


def test_demo_fixture_response_equals_computed(files, monkeypatch):
    """A compact fixture (non-ok rows only) is served exactly as the full computed collection."""
    _mode(monkeypatch, demo_mode=False)
    computed = client.get(f"{URL}?timestep={TS}&synthetic=true").json()

    demo_dir = files / "demo"
    demo_dir.mkdir()
    build_fixtures(ingest.read_infra(files / "infra.parquet"), demo_dir)
    fixture = to_fixture(ImpactResultCollection.model_validate(computed))
    (demo_dir / f"{fixture_key(TS)}.json").write_text(json.dumps(fixture), encoding="utf-8")
    assert len(fixture["features"]) < len(computed["features"])

    _mode(monkeypatch, demo_mode=True, demo_dir=demo_dir)
    served = client.get(f"{URL}?timestep={TS}")
    assert served.status_code == 200
    assert served.json() == computed
    filtered = client.get(f"{URL}?timestep={TS}&status=ok").json()
    assert filtered["features"] == [
        f for f in computed["features"] if f["properties"]["status"] == "ok"
    ]
