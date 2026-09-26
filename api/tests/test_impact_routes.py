"""GET /api/impact/results on the hand-built scenario (tests/impact_scenario.py)."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.core import demo as demo_module
from app.core.config import Settings
from app.exposure import ingest
from app.exposure import service as exposure
from app.impact import service
from app.impact.fixtures import fixture_key, to_fixture
from app.impact.synthetic import synthetic_hazards
from app.main import app
from app.schemas import LANDFALL_TIMESTEP, REPLAY_TIMESTEPS, ImpactResultCollection
from scripts.build_exposure_fixtures import build_fixtures
from tests import impact_scenario as S

TS = LANDFALL_TIMESTEP
NON_OK = ("at_risk", "cut", "isolated")
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


@pytest.fixture
def synth(live, monkeypatch):
    """Live mode on the synthetic test hazards (tests only), so results don't depend on Dev A's
    model. Dev A's real layers are covered by test_live_with_dev_a_hazards_succeeds."""
    monkeypatch.setattr(service, "get_hazard_layer", lambda h, ts: synthetic_hazards(ts)[h])
    service.clear_cache()
    return live


def get(params: str):
    resp = client.get(f"{URL}?{params}")
    assert resp.status_code == 200, resp.text
    return ImpactResultCollection.model_validate(resp.json())


def test_live_without_dev_a_hazards_is_501(live, monkeypatch):
    def _stub(hazard_type, timestep):
        raise NotImplementedError("get_hazard_layer: not implemented")

    monkeypatch.setattr(service, "get_hazard_layer", _stub)
    service.clear_cache()
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 501
    assert "get_hazard_layer" in resp.json()["detail"]


def test_live_with_dev_a_hazards_succeeds(live):
    service.clear_cache()
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 200
    fc = ImpactResultCollection.model_validate(resp.json())
    assert len(fc.features) > 0


def test_live_returns_full_collection(synth):
    fc = get(f"timestep={TS}")
    assert len(fc.features) == len(S.records()) * 3
    assert {f.properties.timestep for f in fc.features} == {TS}


def test_filters(synth):
    wind = get(f"timestep={TS}&hazard_type=wind")
    assert {f.properties.hazard_type for f in wind.features} == {"wind"}
    ok = get(f"timestep={TS}&status=ok")
    assert ok.features and {f.properties.status for f in ok.features} == {"ok"}


@pytest.mark.parametrize("bad", ["2020-05-20T13:00:00Z", "LIVE", ""])
def test_unknown_timestep_is_422(live, bad):
    assert client.get(f"{URL}?timestep={bad}").status_code == 422


def test_live_timestep_is_501(live):
    assert client.get(f"{URL}?timestep=live").status_code == 501


def test_missing_graph_is_503(synth, monkeypatch, tmp_path):
    monkeypatch.setattr(service, "GRAPH_PATH", tmp_path / "missing.graphml")
    service.clear_cache()
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 503 and "ingest_osm.py" in resp.json()["detail"]


def test_demo_without_fixture_is_501(files, monkeypatch):
    _mode(monkeypatch, demo_mode=True, demo_dir=files)
    resp = client.get(f"{URL}?timestep={TS}")
    assert resp.status_code == 501 and fixture_key(TS) in resp.json()["detail"]


def test_demo_fixture_response_equals_computed(files, monkeypatch):
    """A compact fixture (non-ok rows only) is served exactly as the full computed collection."""
    _mode(monkeypatch, demo_mode=False)
    monkeypatch.setattr(service, "get_hazard_layer", lambda h, ts: synthetic_hazards(ts)[h])
    computed = client.get(f"{URL}?timestep={TS}").json()

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


# --- Server-side cache --------------------------------------------------------------------------


@pytest.fixture
def counted(synth, monkeypatch):
    """Counts real computations behind the route (sequential or concurrent)."""
    calls: list[str] = []
    compute = service._compute

    def counting(timestep, horizon_h=0):
        calls.append(timestep)
        time.sleep(0.2)  # long enough for concurrent requests to overlap
        return compute(timestep, horizon_h)

    monkeypatch.setattr(service, "_compute", counting)
    return calls


def test_three_status_filters_compute_once(counted):
    for status in ("at_risk", "cut", "isolated"):
        get(f"timestep={TS}&status={status}")
    assert counted == [TS]


def test_concurrent_status_requests_compute_once(counted):
    """The web client sends the three non-ok status requests in parallel."""
    url = f"{URL}?timestep={TS}&status="
    with ThreadPoolExecutor(max_workers=3) as pool:
        codes = list(pool.map(lambda s: client.get(url + s).status_code, NON_OK))
    assert codes == [200, 200, 200]
    assert counted == [TS]


def test_cache_is_lru_with_eight_entries(counted):
    steps = REPLAY_TIMESTEPS[: service.CACHE_SIZE + 1]  # one more than fits
    for ts in steps:
        get(f"timestep={ts}&status=isolated")
    get(f"timestep={steps[-1]}&status=cut")  # still cached
    assert len(counted) == len(steps)
    get(f"timestep={steps[0]}&status=cut")  # evicted: computed again
    assert counted[-1] == steps[0] and len(counted) == len(steps) + 1


def test_failures_are_not_cached(live, monkeypatch):
    calls = []

    def failing(timestep, horizon_h=0):
        calls.append(timestep)
        raise NotImplementedError("get_hazard_layer: not implemented")

    monkeypatch.setattr(service, "_compute", failing)
    for _ in range(2):
        assert client.get(f"{URL}?timestep={TS}").status_code == 501
    assert len(calls) == 2
