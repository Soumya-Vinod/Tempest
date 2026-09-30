"""Critical links (v1.4 change, pending Dev A): the committed impact__critical-links fixture,
checked against the departures fixture (counts, horizons, route geometry) and a fresh build;
the ranking and merging rules on hand-made data; the block labels; and the route."""

import json

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Polygon, shape
from shapely.ops import unary_union

from app.core.config import Settings
from app.core.demo import DEMO_DIR
from app.impact import critical_links as C
from app.impact import departures
from app.impact import service as impact
from app.main import app
from app.schemas import REPLAY_TIMESTEPS, CriticalLinks

client = TestClient(app)
HORIZONS = (0, 24)


def t(hours_before_landfall: int) -> str:
    return REPLAY_TIMESTEPS[-1 - hours_before_landfall // 3]


def read(key: str) -> dict:
    return json.loads((DEMO_DIR / f"{key}.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def fixture() -> dict:
    return read(C.FIXTURE_KEY)


@pytest.fixture(scope="module")
def deps() -> dict:
    return read(departures.FIXTURE_KEY)


def ranked(fixture, deps, timestep, horizon=0) -> list[dict]:
    return C.rank(fixture, deps, timestep, horizon)["links"]


# --- Against the departures fixture ---------------------------------------------------------------


def test_every_routed_departure_has_a_route(fixture, deps):
    routed = {d["infra_id"] for d in deps["departures"] if d["deadline"] is not None}
    assert set(fixture["routes"]) == routed
    for ways in fixture["routes"].values():
        assert ways and all(str(w) in fixture["links"] for w, _ in ways)


def test_route_ways_follow_the_departure_legs(fixture, deps):
    """Each way on a route touches that departure's (simplified) legs, and the legs are
    covered by the route's ways: the way ids are the committed route's."""
    for d in deps["departures"]:
        if d["infra_id"] not in fixture["routes"]:
            continue
        legs = unary_union([shape(leg["geometry"]) for leg in d["legs"]])
        ways = [
            shape(fixture["links"][str(w)]["geometry"]) for w, _ in fixture["routes"][d["infra_id"]]
        ]
        assert all(w.distance(legs) < 0.001 for w in ways), d["name"]  # ~100 m
        assert legs.difference(unary_union(ways).buffer(0.002)).length < 0.01 * legs.length
        uses_ferry = any(
            fixture["links"][str(w)]["link_type"] == "ferry"
            for w, _ in fixture["routes"][d["infra_id"]]
        )
        assert uses_ferry == d["uses_ferry"], d["name"]


@pytest.mark.parametrize("horizon", HORIZONS)
def test_counts_match_the_departure_routes(fixture, deps, horizon):
    for ts in REPLAY_TIMESTEPS:
        now = REPLAY_TIMESTEPS.index(ts)
        routes = {
            d["infra_id"]: {w for w, _ in fixture["routes"][d["infra_id"]]}
            for d in deps["departures"]
            if d["deadline"] is not None
            and REPLAY_TIMESTEPS.index(d["deadline"]) >= now
            and (
                horizon == 0
                or (not d["route_stays_open"] and REPLAY_TIMESTEPS.index(d["deadline"]) <= now + 8)
            )
        }
        links = ranked(fixture, deps, ts, horizon)
        seen: list[int] = []
        for link in links:
            ids = {f["infra_id"] for f in link["facilities"]}
            assert link["facility_count"] == len(ids) == len(link["facilities"])
            for w in link["way_ids"]:
                assert ids == {i for i, ways in routes.items() if w in ways}, (ts, w)
            seen += link["way_ids"]
        # Every way on a counted route, exactly once.
        assert sorted(seen) == sorted(set().union(*routes.values())), ts


def test_horizon_24_is_the_deadlines_within_24_h(fixture, deps):
    for ts in REPLAY_TIMESTEPS:
        now = REPLAY_TIMESTEPS.index(ts)
        h0 = {f["infra_id"] for x in ranked(fixture, deps, ts, 0) for f in x["facilities"]}
        h24 = {f["infra_id"] for x in ranked(fixture, deps, ts, 24) for f in x["facilities"]}
        assert h24 <= h0
        for d in deps["departures"]:
            if d["infra_id"] in h0 - h24:
                assert REPLAY_TIMESTEPS.index(d["deadline"]) > now + 8


def test_no_links_once_every_deadline_has_passed(fixture, deps):
    last = max(d["deadline"] for d in deps["departures"] if d["deadline"])
    after = REPLAY_TIMESTEPS[REPLAY_TIMESTEPS.index(last) + 1]
    assert ranked(fixture, deps, last)
    assert ranked(fixture, deps, after) == []


@pytest.mark.parametrize("horizon", HORIZONS)
def test_ordering(fixture, deps, horizon):
    for ts in REPLAY_TIMESTEPS:
        links = ranked(fixture, deps, ts, horizon)
        keys = [(-x["facility_count"], x["earliest_deadline"], x["label"]) for x in links]
        assert keys == sorted(keys)
        for x in links:
            deadlines = [f["deadline"] for f in x["facilities"]]
            assert deadlines == sorted(deadlines) and x["earliest_deadline"] == deadlines[0]


def test_diamond_harbour_road_and_the_sagar_ferry(fixture, deps):
    top = ranked(fixture, deps, t(27))[0]
    assert top["label"] == "Diamond Harbour Road (Kakdwip → Kulpi)"
    assert top["facility_count"] == 9 and len(top["way_ids"]) == 5
    assert top["earliest_deadline"] == t(21)
    ferry = next(x for x in ranked(fixture, deps, t(9)) if x["label"].startswith("Unnamed ferry"))
    assert ferry["link_type"] == "ferry" and ferry["blocks"] == ["Gosaba", "Basanti"]
    sagar = [x for x in ranked(fixture, deps, t(9)) if x["blocks"] == ["Sagar", "Kakdwip"]]
    assert [x["label"] for x in sagar] == ["Unnamed ferry route (Sagar → Kakdwip)"]
    assert len(sagar[0]["way_ids"]) == 3  # one crossing, three OSM ways
    assert {f["name"] for f in sagar[0]["facilities"]} == {"Gangasagar PHC", "Mahendraganj PHC"}


def test_every_response_matches_the_contract(fixture, deps):
    for ts in REPLAY_TIMESTEPS:
        for h in HORIZONS:
            body = CriticalLinks.model_validate(C.rank(fixture, deps, ts, h))
            assert body.note == "Based on normal-condition routes to the nearest safe hospital."
            for x in body.links:
                assert x.infra_ids == [f"road-way-{w}" for w in x.way_ids]
                base = x.name or f"Unnamed {'ferry route' if x.link_type == 'ferry' else 'road'}"
                assert x.label == f"{base} ({' → '.join(x.blocks)})" and x.blocks


@pytest.mark.skipif(not impact.GRAPH_PATH.is_file(), reason="needs data/processed/roads.graphml")
def test_fixture_matches_a_fresh_build(fixture):
    """Rebuild it (scripts/build_critical_links_fixture.py) after rebuilding the departures."""
    assert C.build() == fixture


# --- Rules on hand-made data ----------------------------------------------------------------------


def line(*xy) -> dict:
    return {"type": "LineString", "coordinates": [list(p) for p in xy]}


def dep(infra_id: str, deadline: str, stays_open: bool = False) -> dict:
    return {
        "infra_id": infra_id,
        "name": infra_id.upper(),
        "deadline": deadline,
        "route_stays_open": stays_open,
    }


def hand_data() -> tuple[dict, dict]:
    """a, b and c share ways 1 and 2 (road "Main"), then a and b way 3 (also "Main"), then a
    alone way 4 (unnamed ferry, crossed against its coordinate order). c's deadline is last."""
    links = {
        "1": {
            "name": "Main",
            "link_type": "road",
            "blocks": ["X"],
            "geometry": line((0, 0), (1, 0)),
        },
        "2": {
            "name": "Main",
            "link_type": "road",
            "blocks": ["X", "Y"],
            "geometry": line((1, 0), (2, 0)),
        },
        "3": {
            "name": "Main",
            "link_type": "road",
            "blocks": ["Y"],
            "geometry": line((2, 0), (3, 0)),
        },
        "4": {
            "name": None,
            "link_type": "ferry",
            "blocks": ["Y", "Z"],
            "geometry": line((4, 0), (3, 0)),
        },
    }
    routes = {
        "a": [[1, True], [2, True], [3, True], [4, False]],
        "b": [[1, True], [2, True], [3, True]],
        "c": [[1, True], [2, True]],
    }
    deps = {"departures": [dep("a", t(12)), dep("b", t(9)), dep("c", t(0), stays_open=True)]}
    return {"note": C.NOTE, "routes": routes, "links": links}, deps


def test_merging_and_ranking_rules():
    data, deps = hand_data()
    links = C.rank(data, deps, t(24), 0)["links"]
    assert [(x["way_ids"], x["facility_count"], x["earliest_deadline"]) for x in links] == [
        ([1, 2], 3, t(12)),  # same name, same facilities: one link
        ([3], 2, t(12)),  # same name, fewer facilities: its own link
        ([4], 1, t(12)),
    ]
    assert [x["label"] for x in links] == [
        "Main (X → Y)",
        "Main (Y)",
        "Unnamed ferry route (Z → Y)",  # travelled against the way's coordinate order
    ]
    assert links[0]["geometry"]["type"] == "MultiLineString"
    assert links[2]["geometry"] == data["links"]["4"]["geometry"]
    assert [f["infra_id"] for f in links[0]["facilities"]] == ["a", "b", "c"]


def test_horizon_and_deadline_rules():
    data, deps = hand_data()
    # At T-9, a's deadline (T-12) has passed.
    assert {
        f["infra_id"] for x in C.rank(data, deps, t(9), 0)["links"] for f in x["facilities"]
    } == {"b", "c"}
    # Horizon 24 at T-36: only deadlines up to T-12; c's route stays open (no real deadline).
    h24 = C.rank(data, deps, t(36), 24)["links"]
    assert {f["infra_id"] for x in h24 for f in x["facilities"]} == {"a"}
    assert C.rank(data, deps, t(33), 24)["links"][0]["facility_count"] == 2  # T-9 is 24 h ahead


def test_blocks_along_orders_blocks_and_ignores_slivers():
    names = ["West", "East", "Sliver"]
    polygons = [
        Polygon([(0, -1), (1, -1), (1, 1), (0, 1)]),
        Polygon([(1, -1), (2, -1), (2, 1), (1, 1)]),
        Polygon([(1.99, -1), (2.5, -1), (2.5, 1), (1.99, 1)]),  # the line's last ~1%
    ]
    assert C.blocks_along(LineString([(0.5, 0), (2.0, 0)]), names, polygons) == ["West", "East"]
    assert C.blocks_along(LineString([(1.5, 0), (0.5, 0)]), names, polygons) == ["East", "West"]
    assert C.blocks_along(LineString([(5, 5), (6, 5)]), names, polygons) == ["Sliver"]  # nearest


# --- Route --------------------------------------------------------------------------------------


@pytest.fixture
def demo(monkeypatch):
    s = Settings(_env_file=None, DEMO_MODE=True)
    monkeypatch.setattr(C, "get_settings", lambda: s)
    monkeypatch.setattr(departures, "get_settings", lambda: s)
    C.clear_cache()
    departures.clear_cache()
    yield
    C.clear_cache()
    departures.clear_cache()


@pytest.mark.parametrize("horizon", HORIZONS)
def test_route(demo, fixture, deps, horizon):
    r = client.get("/api/impact/critical-links", params={"timestep": t(9), "horizon": horizon})
    assert r.status_code == 200, r.text
    expected = CriticalLinks.model_validate(C.rank(fixture, deps, t(9), horizon))
    assert CriticalLinks.model_validate(r.json()) == expected


def test_route_rejects_bad_parameters(demo):
    r = client.get("/api/impact/critical-links", params={"timestep": t(9), "horizon": 12})
    assert r.status_code == 422
    assert client.get("/api/impact/critical-links", params={"timestep": "live"}).status_code == 501
    assert client.get("/api/impact/critical-links").status_code == 422
