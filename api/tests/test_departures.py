"""Last safe departure (v1.3 change, pending Dev A): the committed impact__departures fixture,
checked against the impact fixtures and a fresh computation; the rule on a hand-built graph; the
route; and the advisory facts built from it."""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.demo import DEMO_DIR
from app.impact import countdown, departures
from app.impact import service as impact
from app.impact.fixtures import fixture_key
from app.impact.network import build_network
from app.main import app
from app.risk import weights as W
from app.schemas import REPLAY_TIMESTEPS, Departures, InfraFeature
from tests import impact_scenario as S

client = TestClient(app)


def t(hours_before_landfall: int) -> str:
    return REPLAY_TIMESTEPS[-1 - hours_before_landfall // 3]


def read(key: str) -> dict:
    return json.loads((DEMO_DIR / f"{key}.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def fixture() -> dict:
    return read(departures.FIXTURE_KEY)


def entry(fixture: dict, name: str) -> dict:
    (e,) = [d for d in fixture["departures"] if d["name"] == name]
    return e


# --- Named facilities -----------------------------------------------------------------------------


def test_gosaba_rural_hospital(fixture):
    e = entry(fixture, "Gosaba Rural Hospital")
    assert e["first_cut_off"] == t(3)
    assert e["deadline"] == t(6)
    assert e["destination_name"] == "Basanti Rural Hospital"
    assert e["uses_ferry"] is True
    assert any(leg["ferry"] for leg in e["legs"])
    assert e["travel_time_s"] == pytest.approx(37 * 60, abs=60)


def test_gangasagar_phc_surge_driven(fixture):
    """Sagar Island: cut off by surge on its roads; the way out is by ferry to the mainland."""
    e = entry(fixture, "Gangasagar PHC")
    cd = read(countdown.FIXTURE_KEY)["timesteps"][t(6)]["expected"]
    (row,) = [r for r in cd if r["name"] == "Gangasagar PHC"]
    assert row["cause"] == "road cut by surge"
    assert e["first_cut_off"] == t(3)
    assert e["deadline"] == t(6)
    assert e["destination_name"] == "Kulpi Rural Hospital"
    assert e["uses_ferry"] is True


# --- Every facility -------------------------------------------------------------------------------


def _isolated(key: str) -> set[str]:
    return {
        r["properties"]["infra_id"]
        for r in read(key)["features"]
        if r["properties"]["status"] == "isolated"
    }


def test_facilities_are_the_cut_off_hospitals_and_health_centres(fixture):
    """Hospitals and health centres only (shelter stand-ins show only when they are cut off),
    minus the advisory-excluded names."""
    hospitals = {
        f["id"]: f["properties"]["name"] for f in read("exposure__infra-hospital")["features"]
    }
    shelters = {f["id"] for f in read("exposure__infra-shelter")["features"]}
    ever = set().union(*(_isolated(fixture_key(ts)) for ts in REPLAY_TIMESTEPS))
    counted = {i for i in ever if i in hospitals and W.counts_for_advisory(hospitals[i])}
    ids = {d["infra_id"] for d in fixture["departures"]}
    assert ids == counted
    assert len(ids) == 14
    assert {d["infra_type"] for d in fixture["departures"]} == {"hospital"}
    assert ever & shelters and not ids & shelters  # cut-off shelters exist, with no departure
    names = {d["name"] for d in fixture["departures"]}
    assert "Suraksha Diagnostic Centre" not in names
    assert "Sundarban Adarsha Vidyamandir" not in names


def test_deadline_is_before_the_first_cut_off(fixture):
    for d in fixture["departures"]:
        first = next(ts for ts in REPLAY_TIMESTEPS if d["infra_id"] in _isolated(fixture_key(ts)))
        assert d["first_cut_off"] == first
        assert d["deadline"] is not None and d["deadline"] < first, d["name"]
        assert not d["route_stays_open"]
        assert d["destination_name"] and d["travel_time_s"] > 0 and d["legs"]


def test_destinations_are_never_cut_off(fixture):
    ever = set().union(*(_isolated(fixture_key(ts)) for ts in REPLAY_TIMESTEPS))
    for d in fixture["departures"]:
        assert d["destination_id"] not in ever
        assert d["usual_destination_id"] not in ever


def test_route_legs_run_from_the_facility(fixture):
    infra = {f.id: f for f in countdown._infra_from_fixtures().values()}
    for d in fixture["departures"]:
        start = d["legs"][0]["geometry"]["coordinates"][0]
        end = d["legs"][-1]["geometry"]["coordinates"][-1]
        f, dest = infra[d["infra_id"]], infra[d["destination_id"]]
        assert np.hypot(*np.subtract(start, f.geometry.coordinates)) < 0.03, d["name"]
        assert np.hypot(*np.subtract(end, dest.geometry.coordinates)) < 0.03, d["name"]


@pytest.mark.skipif(not impact.GRAPH_PATH.is_file(), reason="needs data/processed/roads.graphml")
def test_fixture_matches_a_fresh_computation(fixture):
    """Rebuild it (scripts/build_departures_fixture.py) after regenerating impact fixtures."""
    assert departures.build() == fixture


# --- The rule on a hand-built graph ---------------------------------------------------------------


def point(i: int, name: str, xy: tuple[float, float], infra_type: str = "hospital"):
    return InfraFeature.model_validate(
        {
            "type": "Feature",
            "id": f"{infra_type}-node-{i}",
            "geometry": {"type": "Point", "coordinates": list(xy)},
            "properties": {
                "id": f"{infra_type}-node-{i}",
                "infra_type": infra_type,
                "name": name,
                "osm_id": f"node/{i}",
                "attributes": {},
            },
        }
    )


def test_rule_on_the_scenario_graph():
    """Island shelter (F) reaches the mainland hospital (A) only by the ferry: open at step 0,
    ferry suspended from step 1. The G-H hospital has no road to any safe destination."""
    net = build_network(S.build_graph(), S.ANCHOR)
    ts = REPLAY_TIMESTEPS[:3]
    none = np.zeros(len(net.link_u), dtype=bool)
    ferry_cut = net.link_ferry.copy()
    steps = [
        departures.Step(ts[0], none, ferry_cut),  # the ferry is at risk at the deadline
        departures.Step(ts[1], ferry_cut, none),
        departures.Step(ts[2], ferry_cut, none),
    ]
    island = point(1, "Island Shelter", S.XY[S.F], "shelter")
    stranded = point(2, "Stranded Hospital", S.XY[S.H])
    mainland = point(3, "Mainland Hospital", S.XY[S.A])
    out = departures.compute(net, steps, [(island, ts[1]), (stranded, ts[1])], [mainland])
    by_name = {d["name"]: d for d in out["departures"]}

    e = by_name["Island Shelter"]
    assert e["deadline"] == ts[0] and not e["route_stays_open"]
    assert e["destination_name"] == "Mainland Hospital" == e["usual_destination_name"]
    assert e["uses_ferry"] is True and e["at_risk"] is True
    assert [leg["ferry"] for leg in e["legs"]] == [False, True, False]

    s = by_name["Stranded Hospital"]
    assert s["deadline"] is None and s["destination_id"] is None and s["legs"] == []
    assert s["note"] == "No safe destination reachable by road at any step"
    assert [d["name"] for d in out["departures"]] == ["Island Shelter", "Stranded Hospital"]

    # No cut at all: the route stays open to the last step.
    open_steps = [departures.Step(x, none, none) for x in ts]
    (kept,) = departures.compute(net, open_steps, [(island, ts[1])], [mainland])["departures"]
    assert kept["deadline"] == ts[-1] and kept["route_stays_open"]


def test_nearest_reachable_destination_can_differ_from_the_usual_one():
    """C's usual nearest hospital is at D (dead end, 1 link); with Clinic Road cut it must go
    to A instead."""
    net = build_network(S.build_graph(), S.ANCHOR)
    ts = REPLAY_TIMESTEPS[:2]
    clinic_road = np.array([osm == 3 for osm in net.link_osmid])
    none = np.zeros(len(net.link_u), dtype=bool)
    facility = point(1, "Junction Shelter", S.XY[S.C], "shelter")
    near, far = point(2, "Clinic", S.XY[S.D]), point(3, "Mainland Hospital", S.XY[S.A])
    steps = [
        departures.Step(ts[0], clinic_road, none),
        departures.Step(ts[1], np.ones_like(none), none),
    ]
    (e,) = departures.compute(net, steps, [(facility, ts[1])], [near, far])["departures"]
    assert e["usual_destination_name"] == "Clinic"
    assert e["destination_name"] == "Mainland Hospital"


# --- Route and facts ------------------------------------------------------------------------------


@pytest.fixture
def demo(monkeypatch):
    s = Settings(_env_file=None, DEMO_MODE=True)
    monkeypatch.setattr(departures, "get_settings", lambda: s)
    departures.clear_cache()
    yield
    departures.clear_cache()


def test_route(demo, fixture):
    r = client.get("/api/impact/departures")
    assert r.status_code == 200
    assert (
        Departures.model_validate(r.json()).model_dump()
        == Departures.model_validate(fixture).model_dump()
    )


def test_facts_give_where_and_by_when(monkeypatch):
    """Gosaba at T-12: Gosaba Rural Hospital is expected to be cut off; leave by T-6 (6 h) for
    Basanti Rural Hospital, by ferry."""
    from app.advisory import facts as facts_module
    from app.core import demo as demo_module
    from app.exposure import service as exposure
    from app.insurance import service as insurance
    from app.risk import service as risk
    from app.risk.blocks import load_blocks

    s = Settings(_env_file=None, DEMO_MODE=True)
    for module in (impact, risk, exposure, insurance, demo_module, departures):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    for module in (impact, risk, exposure, insurance, departures):
        module.clear_cache()
    blocks = load_blocks()
    facts = facts_module.build_facts(blocks.codes[blocks.names.index("Gosaba")], t(12))
    c = {x.key: x.value for x in facts.citations}
    (n,) = [
        k.split("_")[1]
        for k, v in c.items()
        if v == "Gosaba Rural Hospital" and k.startswith("expected_")
    ]
    assert c[f"expected_{n}_leave_by_hours"] == 6
    assert c[f"expected_{n}_destination"] == "Basanti Rural Hospital"
    assert c[f"expected_{n}_route_mode"] == "ferry"

    # Kakdwip at T-6: its shelter stand-ins are expected to be cut off too, with no departure
    # facts; Kakdwip Sub Divisional Hospital gets them.
    facts = facts_module.build_facts(blocks.codes[blocks.names.index("Kakdwip")], t(6))
    c = {x.key: x.value for x in facts.citations}
    expected = {
        k.split("_")[1]: v
        for k, v in c.items()
        if k.endswith("_name") and k.startswith("expected_")
    }
    shelters = {"Sundarban Adarsha Vidyamandir", "Sundarban Maha Vidyalaya"}
    assert shelters <= set(expected.values())
    for n, name in expected.items():
        has = f"expected_{n}_leave_by_hours" in c
        assert has is (name not in shelters), name
        assert (f"expected_{n}_destination" in c) is has and (
            f"expected_{n}_route_mode" in c
        ) is has
    (hospital,) = [n for n, v in expected.items() if v == "Kakdwip Sub Divisional Hospital"]
    assert c[f"expected_{hospital}_destination"] == "Kulpi Rural Hospital"
    for module in (impact, risk, exposure, insurance, departures):
        module.clear_cache()
