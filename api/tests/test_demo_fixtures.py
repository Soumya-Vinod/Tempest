"""Every demo fixture must match its contract schema (shared/contracts.md §7)."""

import json
import re
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from app.core import demo as demo_module
from app.core.config import Settings
from app.core.demo import DEMO_DIR
from app.exposure import service as exposure
from app.hazard.models import CycloneTrack
from app.impact import critical_links
from app.impact import service as impact
from app.insurance import engine as insurance_engine
from app.main import app
from app.risk import fixtures as risk_fixtures
from app.risk import service as risk
from app.risk.blocks import load_blocks
from app.schemas import (
    REPLAY_TIMESTEPS,
    ActionCountdown,
    CriticalLinks,
    Departures,
    HazardLayerCollection,
    HazardType,
    ImpactResultCollection,
    InfraFeatureCollection,
    InfraType,
    InsuranceSummary,
    ReplayTimeline,
    RiskBreakdown,
    RiskScoreCollection,
    TriggerEventCollection,
    UnscoredAreaCollection,
)

KEY_RE = re.compile(r"^(?P<module>[a-z]+)__(?P<resource>[a-z0-9-]+)(?:__(?P<ts>\d{8}T\d{4}Z))?$")
MODULES = {"hazard", "exposure", "impact", "risk", "advisory", "dispatch", "insurance"}
RAW_PREFIXES = ("gee-", "openmeteo-", "gdacs-", "gemini-", "overpass-")


def _alternatives(literal) -> str:
    """Enum values as a regex alternation, `_` written as `-` (e.g. power_line -> power-line)."""
    return "|".join(v.replace("_", "-") for v in get_args(literal))


# module -> [(resource regex, schema, time-dependent, id in the key -> id in the body)]
ROUTE_SCHEMAS = {
    "hazard": [
        (r"timesteps", ReplayTimeline, False, None),
        (r"track", CycloneTrack, False, None),
        (rf"layers-({_alternatives(HazardType)})", HazardLayerCollection, True, None),
    ],
    # Per type only: the unfiltered route is composed from these (contracts.md §7).
    "exposure": [(rf"infra-({_alternatives(InfraType)})", InfraFeatureCollection, False, None)],
    # v1.3 change, pending Dev A: deduplicated horizon-24 results (a content hash per distinct
    # result) and their timestep indexes. schema None: validated through the index, per timestep,
    # in test_horizon.py.
    "impact": [
        (r"results-h24-(index|[0-9a-f]{12})", None, False, None),
        # v1.3 change, pending Dev A: every timestep's ActionCountdown in one file (§7).
        (r"countdown", ActionCountdown, False, None),
        (r"departures", Departures, False, None),  # v1.3 change, pending Dev A
        # v1.4 change, pending Dev A: routes and ways; ranked per timestep × horizon on request.
        (r"critical-links", CriticalLinks, False, None),
        (r"results(-[a-z0-9-]+)?", ImpactResultCollection, True, None),
    ],
    "risk": [
        (r"(scores|breakdown)-h24-(index|[0-9a-f]{12})", None, False, None),
        (r"scores", RiskScoreCollection, True, None),
        (r"breakdown", RiskBreakdown, True, None),
        (r"unscored-areas", UnscoredAreaCollection, False, None),
    ],
    # Advisory state lives in SQLite; its only fixtures are raw gemini-* responses.
    "advisory": [],
    # Dispatch receipts live in SQLite (added in v1.2: receipt fixture dropped).
    "dispatch": [],
    "insurance": [
        (r"triggers", TriggerEventCollection, True, None),
        (r"summary", InsuranceSummary, False, None),  # added in v1.2
    ],
}
FIXTURES = sorted(DEMO_DIR.glob("*.json"))


def _iso(ts: str) -> str:  # 20200520T1200Z -> 2020-05-20T12:00:00Z
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[9:11]}:{ts[11:13]}:00Z"


def _route_schema(module: str, resource: str):
    """(regex match, schema, time-dependent, body id getter) for a route resource, or None."""
    for pattern, schema, timed, body_id in ROUTE_SCHEMAS.get(module, []):
        if match := re.fullmatch(pattern, resource):
            return match, schema, timed, body_id
    return None


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_matches_contract(path):
    m = KEY_RE.match(path.stem)
    assert m, f"{path.name}: key must be <module>__<resource>[__<YYYYMMDDTHHMMZ>]"
    module, resource, ts = m["module"], m["resource"], m["ts"]
    assert module in MODULES, f"unknown module {module!r}"
    if ts:
        assert _iso(ts) in REPLAY_TIMESTEPS, f"{ts} is not a replay timestep"
    raw = path.read_bytes()
    assert b"\r\n" not in raw, "fixtures must be LF"
    if resource.startswith(RAW_PREFIXES):
        json.loads(raw)  # raw upstream body: no contract schema, just valid JSON
        return
    entry = _route_schema(module, resource)
    if entry is None:
        pytest.fail(f"no contract schema mapped for {module}__{resource}")
    match, schema, timed, body_id = entry
    assert bool(ts) == timed, "timestep suffix required iff the resource is time-dependent"
    if schema is None:  # a horizon-24 dedup file or index (test_horizon.py resolves them)
        json.loads(raw)
        return
    if (module, resource) == ("impact", "countdown"):  # one file for the replay (§7, v1.3)
        data = json.loads(raw)
        assert set(data["timesteps"]) == set(REPLAY_TIMESTEPS)
        for t, entry in data["timesteps"].items():
            ActionCountdown.model_validate(
                {"timestep": t, **entry, "key_moments": data["key_moments"]}
            )
        return
    if (module, resource) == ("impact", "critical-links"):  # every timestep × horizon (v1.4)
        data = json.loads(raw)
        deps = json.loads((DEMO_DIR / "impact__departures.json").read_text("utf-8"))
        for t in REPLAY_TIMESTEPS:
            for h in (0, 24):
                CriticalLinks.model_validate(critical_links.rank(data, deps, t, h))
        return
    if (module, resource) == ("risk", "scores"):  # compact: polygons added on load (§7)
        data = json.loads(raw)
        assert all("geometry" not in f for f in data["features"]), "scores store no geometry"
        model = risk_fixtures.from_fixture(data, load_blocks())
    elif (module, resource) == ("insurance", "triggers"):  # compact, as risk scores (v1.2)
        data = json.loads(raw)
        assert all("geometry" not in f for f in data["features"]), "triggers store no geometry"
        blocks = load_blocks()
        geometry = dict(zip(blocks.codes, blocks.display, strict=True))
        model = insurance_engine.collection_from(data["features"], geometry)
    else:
        model = schema.model_validate_json(raw)
    if body_id:
        assert body_id(model) == match["id"], "id in the file name must match the body"
    if ts:
        if isinstance(model, RiskBreakdown):
            assert model.timestep == _iso(ts), "timestep differs from file name"
        for f in getattr(model, "features", []):
            assert f.properties.timestep == _iso(ts), f"{f.id}: timestep differs from file name"


def test_demo_dir_contains_only_fixtures():
    extras = {p.name for p in DEMO_DIR.iterdir()} - {p.name for p in FIXTURES}
    # validation/: Dev A's committed Sentinel-1 validation data (app/hazard/validation).
    assert extras <= {".gitkeep", "README.md", "validation"}, extras


VALIDATION_JSON = sorted(
    p
    for p in (DEMO_DIR / "validation").rglob("*")
    if p.suffix in {".json", ".geojson"} and p.is_file()
)


def test_validation_dir_has_json():
    assert (DEMO_DIR / "validation" / "benchmark_suite.json") in VALIDATION_JSON


@pytest.mark.parametrize("path", VALIDATION_JSON, ids=lambda p: p.relative_to(DEMO_DIR).as_posix())
def test_validation_json_parses(path):
    with path.open(encoding="utf-8") as f:
        json.load(f)


@pytest.fixture
def demo_mode(monkeypatch):
    """DEMO_MODE on against the committed fixtures, whatever api/.env says."""
    settings = Settings(_env_file=None, DEMO_MODE=True)
    for module in (impact, risk, exposure, demo_module):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    for module in (impact, risk, exposure):
        module.clear_cache()
    yield
    for module in (impact, risk, exposure):
        module.clear_cache()


def test_demo_mode_serves_impact_and_risk_at_every_timestep(demo_mode):
    client = TestClient(app)
    for ts in REPLAY_TIMESTEPS:
        for route in ("/api/impact/results", "/api/risk/scores", "/api/risk/breakdown"):
            r = client.get(route, params={"timestep": ts})
            assert r.status_code == 200, f"{route} {ts}: {r.status_code} {r.text[:200]}"
    assert client.get("/api/risk/unscored-areas").status_code == 200


def test_real_hazards_t72_scores_about_zero():
    # 72 h before landfall the cyclone is far out at sea: no block is reached yet.
    data = json.loads((DEMO_DIR / f"{risk.fixture_key(REPLAY_TIMESTEPS[0])}.json").read_bytes())
    assert max(f["properties"]["score"] for f in data["features"]) < 0.02
