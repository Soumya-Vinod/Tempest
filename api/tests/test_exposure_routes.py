"""GET /api/exposure/infra with DEMO_MODE off (parquet) and on (fixtures). Uses the tiny
tests/data/infra-sample.parquet (regenerate: python -m tests.data.make_infra_sample)."""

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
import shapely
from fastapi.testclient import TestClient
from shapely.geometry import shape

from app.core import demo as demo_module
from app.core.config import Settings
from app.exposure import ingest, service
from app.main import app
from app.schemas import InfraFeatureCollection
from scripts.build_exposure_fixtures import build_fixtures

SAMPLE = Path(__file__).parent / "data" / "infra-sample.parquet"
client = TestClient(app)


def _use_settings(monkeypatch, demo_mode: bool) -> None:
    settings = Settings(_env_file=None, DEMO_MODE=demo_mode)
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    monkeypatch.setattr(demo_module, "get_settings", lambda: settings)


@pytest.fixture
def live(monkeypatch):
    _use_settings(monkeypatch, demo_mode=False)
    monkeypatch.setattr(service, "INFRA_PATH", SAMPLE)
    service.clear_cache()
    yield ingest.read_infra(SAMPLE)
    service.clear_cache()


@pytest.fixture
def demo(monkeypatch, tmp_path):
    _use_settings(monkeypatch, demo_mode=True)
    monkeypatch.setattr(demo_module, "DEMO_DIR", tmp_path)
    monkeypatch.setattr(service, "INFRA_PATH", tmp_path / "absent.parquet")  # never read
    build_fixtures(ingest.read_infra(SAMPLE), tmp_path)
    service.clear_cache()
    yield tmp_path
    service.clear_cache()


def get(path: str):
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    return InfraFeatureCollection.model_validate(resp.json())


# --- DEMO_MODE off ------------------------------------------------------------------------------


def test_live_unfiltered_returns_every_feature(live):
    fc = get("/api/exposure/infra")
    assert len(fc.features) == len(live)
    assert Counter(f.properties.infra_type for f in fc.features) == Counter(live["infra_type"])


@pytest.mark.parametrize("infra_type", ingest.INFRA_TYPES)
def test_live_filter_by_infra_type(live, infra_type):
    fc = get(f"/api/exposure/infra?infra_type={infra_type}")
    assert {f.properties.infra_type for f in fc.features} <= {infra_type}
    assert len(fc.features) == (live["infra_type"] == infra_type).sum() > 0


def test_live_keeps_attributes_and_null_names(live):
    features = {f.id: f for f in get("/api/exposure/infra?infra_type=road").features}
    assert features["road-way-102"].properties.attributes == {"ferry": True}
    hospitals = {f.id: f for f in get("/api/exposure/infra?infra_type=hospital").features}
    assert hospitals["hospital-node-7"].properties.name is None  # UI shows "Unnamed …"


def test_live_missing_parquet_returns_503(live, monkeypatch, tmp_path):
    monkeypatch.setattr(service, "INFRA_PATH", tmp_path / "missing.parquet")
    service.clear_cache()
    resp = client.get("/api/exposure/infra")
    assert resp.status_code == 503
    assert "ingest_osm.py" in resp.json()["detail"]


@pytest.mark.parametrize("bad", ["power-line", "bridge", "ROAD"])
def test_unknown_infra_type_returns_422(live, bad):
    assert client.get(f"/api/exposure/infra?infra_type={bad}").status_code == 422


# --- DEMO_MODE on -------------------------------------------------------------------------------


def _fixture(demo_dir: Path, infra_type: str) -> dict:
    path = demo_dir / f"{service.fixture_key(infra_type)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_demo_unfiltered_is_composed_from_type_fixtures(demo):
    fc = get("/api/exposure/infra")
    composed = [f for t in ingest.INFRA_TYPES for f in _fixture(demo, t)["features"]]
    assert fc.model_dump(mode="json")["features"] == composed
    assert not (demo / "exposure__infra.json").exists()  # no fixture of its own


@pytest.mark.parametrize("infra_type", ingest.INFRA_TYPES)
def test_demo_filter_uses_type_fixture(demo, infra_type):
    fc = get(f"/api/exposure/infra?infra_type={infra_type}")
    assert fc.model_dump(mode="json") == _fixture(demo, infra_type)
    assert {f.properties.infra_type for f in fc.features} <= {infra_type}


def test_demo_fixture_names_and_rounding(demo):
    names = sorted(p.name for p in demo.glob("*.json"))
    assert names == sorted(
        [
            "exposure__infra-substation.json",
            "exposure__infra-power-line.json",
            "exposure__infra-road.json",
            "exposure__infra-hospital.json",
            "exposure__infra-shelter.json",
        ]
    )
    text = (demo / "exposure__infra-road.json").read_text(encoding="utf-8")
    xy = shapely.get_coordinates([shape(f["geometry"]) for f in json.loads(text)["features"]])
    assert len(xy) and (np.round(xy, 5) == xy).all()
    assert "\r\n" not in text


def test_fixtures_keep_road_baseline_attributes(tmp_path):
    infra = ingest.read_infra(SAMPLE)
    roads = infra["infra_type"] == "road"
    infra.loc[roads, "attributes"] = [
        json.dumps(
            {**json.loads(a), "baseline_component": i, "baseline_reachable_from_main": i == 0}
        )
        for i, a in enumerate(infra.loc[roads, "attributes"])
    ]
    build_fixtures(infra, tmp_path)
    for i, f in enumerate(_fixture(tmp_path, "road")["features"]):
        assert f["properties"]["attributes"]["baseline_component"] == i
        assert f["properties"]["attributes"]["baseline_reachable_from_main"] is (i == 0)


# --- Compression --------------------------------------------------------------------------------


def test_gzip_when_accepted(live):
    resp = client.get("/api/exposure/infra", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers["content-encoding"] == "gzip"
    assert resp.num_bytes_downloaded < len(resp.content)  # compressed on the wire
    InfraFeatureCollection.model_validate(resp.json())


def test_no_gzip_when_not_accepted(live):
    resp = client.get("/api/exposure/infra", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in resp.headers


def test_small_responses_are_not_gzipped():
    resp = client.get("/health", headers={"Accept-Encoding": "gzip"})  # < minimum_size
    assert "content-encoding" not in resp.headers


def test_live_geometry_matches_fixtures(live, tmp_path):
    """Live and demo share service.display_gdf: same parquet in, identical collections out."""
    live_fc = get("/api/exposure/infra").model_dump(mode="json")
    build_fixtures(ingest.read_infra(SAMPLE), tmp_path)
    composed = [f for t in ingest.INFRA_TYPES for f in _fixture(tmp_path, t)["features"]]
    assert live_fc["features"] == composed
    xy = shapely.get_coordinates([shape(f["geometry"]) for f in live_fc["features"]])
    assert (np.round(xy, 5) == xy).all()


def test_live_leaves_parquet_unchanged(live):
    get("/api/exposure/infra")
    assert ingest.read_infra(SAMPLE).geometry.equals(live.geometry)


def test_live_order_matches_demo_order(live, tmp_path):
    """Live output is in INFRA_TYPES order whatever the parquet row order."""
    shuffled = ingest.read_infra(SAMPLE).sample(frac=1, random_state=1)
    path = tmp_path / "shuffled.parquet"
    shuffled.to_parquet(path, index=False)
    service.INFRA_PATH = path
    service.clear_cache()
    try:
        types = [f.properties.infra_type for f in get("/api/exposure/infra").features]
    finally:
        service.INFRA_PATH = SAMPLE
        service.clear_cache()
    assert types == sorted(types, key=ingest.INFRA_TYPES.index)
