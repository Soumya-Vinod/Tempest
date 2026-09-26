import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import LANDFALL_TIMESTEP

client = TestClient(app)
TS = LANDFALL_TIMESTEP

# Every contract route is implemented; see the test_<module>*.py files.

TIMESTEP_ROUTES = [
    "/api/hazard/layers?hazard_type=wind&timestep={}",
    "/api/impact/results?timestep={}",
    "/api/risk/scores?timestep={}",
    "/api/insurance/triggers?timestep={}",
]


@pytest.mark.parametrize("path", TIMESTEP_ROUTES)
def test_live_timestep_returns_501(path):
    assert client.get(path.format("live")).status_code == 501


@pytest.mark.parametrize("path", TIMESTEP_ROUTES)
@pytest.mark.parametrize("bad", ["2020-05-20T13:00:00Z", "2020-05-20T12:00Z", "LIVE", ""])
def test_unknown_timestep_returns_422(path, bad):
    assert client.get(path.format(bad)).status_code == 422


def test_bad_block_id_in_body_returns_422():
    body = {"block_id": "Block_1", "timestep": TS}
    assert client.post("/api/advisory/", json=body).status_code == 422


def test_openapi_uses_contract_models():
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("HazardLayerCollection", "RiskScoreCollection", "Advisory", "DispatchReceipt"):
        assert name in schemas
