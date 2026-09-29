"""Pre-rendered DEMO_MODE responses (scripts/build_static_responses.py and
app/core/static_responses.py): a sample is built into a temp directory, and each static body
decompresses to exactly what the live code returns for the same request."""

import gzip
import importlib.util

import pytest
from fastapi.testclient import TestClient

from app.core import config, static_responses
from app.core.static_responses import request_key
from app.main import app
from app.schemas import REPLAY_TIMESTEPS

_spec = importlib.util.spec_from_file_location(
    "build_static_responses", config.API_DIR / "scripts" / "build_static_responses.py"
)
build_static = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_static)

T0 = REPLAY_TIMESTEPS[-1]
SAMPLE = [
    ("/api/impact/results", {"timestep": T0, "status": "cut", "horizon": "24"}),
    ("/api/impact/results", {"timestep": REPLAY_TIMESTEPS[8], "status": "at_risk", "horizon": "0"}),
    ("/api/risk/scores", {"timestep": T0, "horizon": "24"}),
    ("/api/risk/breakdown", {"timestep": REPLAY_TIMESTEPS[3], "horizon": "0"}),
    ("/api/hazard/layers", {"hazard_type": "surge", "timestep": T0}),
    ("/api/exposure/infra", {"infra_type": "hospital"}),
    ("/api/impact/countdown", {"timestep": T0}),
    ("/api/impact/departures", {}),
    ("/api/insurance/triggers", {"timestep": T0}),
    ("/api/risk/unscored-areas", {}),
    ("/api/hazard/track", {}),
    ("/api/hazard/validation", {}),
]
GZ = {"Accept-Encoding": "gzip"}


@pytest.fixture(scope="module")
def static_dir(tmp_path_factory):
    config.get_settings.cache_clear()
    out = tmp_path_factory.mktemp("static") / "static"
    manifest = build_static.build(out, SAMPLE)
    assert len(manifest) == len(SAMPLE)
    return out


@pytest.fixture
def client(static_dir, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    config.get_settings.cache_clear()
    monkeypatch.setattr(static_responses, "STATIC_DIR", static_dir)
    yield TestClient(app)
    config.get_settings.cache_clear()


def _key(client, path, query):
    """The key the build stored: the query exactly as the client encodes it."""
    url = client.build_request("GET", path, params=query).url
    return request_key(path, url.query.decode())


@pytest.mark.parametrize(("path", "query"), SAMPLE)
def test_static_body_matches_live(client, static_dir, monkeypatch, path, query):
    entry = static_responses.load_manifest(static_dir)[_key(client, path, query)]
    raw = (static_dir / entry["file"]).read_bytes()

    # Served as the file itself, gzip-encoded.
    with client.stream("GET", path, params=query, headers=GZ) as res:
        assert res.status_code == 200
        assert res.headers["content-encoding"] == "gzip"
        assert res.headers["content-type"] == entry["content_type"]
        assert b"".join(res.iter_raw()) == raw

    monkeypatch.setattr(static_responses, "STATIC_DIR", None)
    live = client.get(path, params=query, headers={"Accept-Encoding": "identity"})
    assert live.status_code == 200
    assert live.headers["content-type"] == entry["content_type"]
    assert gzip.decompress(raw) == live.content


def test_query_order_does_not_matter(client, static_dir):
    path, query = SAMPLE[0]
    entry = static_responses.load_manifest(static_dir)[_key(client, path, query)]
    url = f"{path}?horizon=24&status=cut&timestep={T0}"  # another order, ':' not escaped
    with client.stream("GET", url, headers=GZ) as res:
        assert b"".join(res.iter_raw()) == (static_dir / entry["file"]).read_bytes()


def test_client_without_gzip_gets_plain_body(client, monkeypatch):
    path, query = SAMPLE[0]
    res = client.get(path, params=query, headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in res.headers
    monkeypatch.setattr(static_responses, "STATIC_DIR", None)
    assert res.content == client.get(path, params=query).content


def test_missing_request_falls_back_to_the_route(client):
    # Not in the sample build: the route answers (and GZipMiddleware compresses it).
    res = client.get("/api/risk/scores", params={"timestep": REPLAY_TIMESTEPS[0], "horizon": "0"})
    assert res.status_code == 200
    assert res.json()["type"] == "FeatureCollection"
    # Invalid parameters still get the route's validation error.
    assert client.get("/api/impact/results", params={"timestep": "nope"}).status_code == 422


def test_off_outside_demo_mode(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    config.get_settings.cache_clear()

    def never(_):
        raise AssertionError("static manifest used outside DEMO_MODE")

    monkeypatch.setattr(static_responses, "load_manifest", never)
    client.get("/api/hazard/timesteps")  # whatever the live route answers; not the static file
