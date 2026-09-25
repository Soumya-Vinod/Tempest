"""Every demo fixture must match its contract schema (shared/contracts.md §7)."""

import json
import re
from typing import get_args

import pytest

from app.core.demo import DEMO_DIR
from app.hazard.models import CycloneTrack
from app.schemas import (
    REPLAY_TIMESTEPS,
    Advisory,
    AdvisoryCollection,
    DispatchReceipt,
    HazardLayerCollection,
    HazardType,
    ImpactResultCollection,
    InfraFeatureCollection,
    InfraType,
    ReplayTimeline,
    RiskScoreCollection,
    TriggerEventCollection,
)

KEY_RE = re.compile(r"^(?P<module>[a-z]+)__(?P<resource>[a-z0-9-]+)(?:__(?P<ts>\d{8}T\d{4}Z))?$")
MODULES = {"hazard", "exposure", "impact", "risk", "advisory", "dispatch", "insurance"}
RAW_PREFIXES = ("gee-", "openmeteo-", "gdacs-", "gemini-", "overpass-")


def _alternatives(literal) -> str:
    """Enum values as a regex alternation, `_` written as `-` (e.g. power_line -> power-line)."""
    return "|".join(v.replace("_", "-") for v in get_args(literal))


ADVISORY_ID = r"(?P<id>[a-z0-9-]+)"
# module -> [(resource regex, schema, time-dependent, id in the key -> id in the body)]
ROUTE_SCHEMAS = {
    "hazard": [
        (r"timesteps", ReplayTimeline, False, None),
        (r"track", CycloneTrack, False, None),
        (rf"layers-({_alternatives(HazardType)})", HazardLayerCollection, True, None),
    ],
    # Per type only: the unfiltered route is composed from these (contracts.md §7).
    "exposure": [(rf"infra-({_alternatives(InfraType)})", InfraFeatureCollection, False, None)],
    "impact": [(r"results(-[a-z0-9-]+)?", ImpactResultCollection, True, None)],
    "risk": [(r"scores", RiskScoreCollection, True, None)],
    "advisory": [
        (r"list", AdvisoryCollection, False, None),
        (rf"item-{ADVISORY_ID}", Advisory, False, lambda m: m.properties.id),
    ],
    "dispatch": [(rf"receipt-{ADVISORY_ID}", DispatchReceipt, False, lambda m: m.advisory_id)],
    "insurance": [(r"triggers", TriggerEventCollection, True, None)],
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
    model = schema.model_validate_json(raw)
    if body_id:
        assert body_id(model) == match["id"], "id in the file name must match the body"
    if ts:
        for f in getattr(model, "features", []):
            assert f.properties.timestep == _iso(ts), f"{f.id}: timestep differs from file name"


def test_demo_dir_contains_only_fixtures():
    extras = {p.name for p in DEMO_DIR.iterdir()} - {p.name for p in FIXTURES}
    assert extras <= {".gitkeep", "README.md"}, extras
