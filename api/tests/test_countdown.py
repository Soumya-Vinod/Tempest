"""Action countdown (v1.3 change, pending Dev A): the committed impact__countdown fixture, checked
against the committed impact and risk fixtures, its ordering, the key moments and the route."""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.demo import DEMO_DIR
from app.impact import countdown
from app.impact import horizon as fh
from app.impact.countdown import Isolation
from app.impact.fixtures import fixture_key
from app.main import app
from app.schemas import LANDFALL_TIMESTEP, REPLAY_TIMESTEPS, ActionCountdown

client = TestClient(app)
GOSABA = "Gosaba Rural Hospital"


def t(hours_before_landfall: int) -> str:
    """ "T-27" -> its replay timestep."""
    return REPLAY_TIMESTEPS[-1 - hours_before_landfall // 3]


def read(key: str) -> dict:
    return json.loads((DEMO_DIR / f"{key}.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def fixture() -> dict:
    return read(countdown.FIXTURE_KEY)


@pytest.fixture
def demo(monkeypatch):
    s = Settings(_env_file=None, DEMO_MODE=True)
    monkeypatch.setattr(countdown, "get_settings", lambda: s)
    countdown.clear_cache()
    yield
    countdown.clear_cache()


# --- The fixture matches the impact fixtures ------------------------------------------------------


def test_fixture_is_up_to_date_with_the_committed_fixtures(fixture):
    """Rebuild it (scripts/build_countdown_fixture.py) after regenerating impact or risk."""
    assert fixture == countdown.from_fixtures()


def _isolated(fx: dict) -> set[str]:
    return {
        r["properties"]["infra_id"]
        for r in fx["features"]
        if r["properties"]["status"] == "isolated"
    }


def test_every_timestep_matches_the_impact_fixtures(fixture):
    """Independently of countdown.py: expected = isolated on horizon 24 but not on horizon 0;
    cut off = isolated on horizon 0; hours = until the next horizon-0 isolation."""
    h24_files = read(fh.index_key(countdown.IMPACT_H24_PREFIX))["files"]
    h0 = {ts: _isolated(read(fixture_key(ts))) for ts in REPLAY_TIMESTEPS}
    h24 = {ts: _isolated(read(h24_files[ts])) for ts in REPLAY_TIMESTEPS}
    for n, ts in enumerate(REPLAY_TIMESTEPS):
        entry = fixture["timesteps"][ts]
        assert {e["infra_id"] for e in entry["expected"]} == h24[ts] - h0[ts], ts
        assert {e["infra_id"] for e in entry["cut_off"]} == h0[ts], ts
        for e in entry["expected"]:
            later = [
                m
                for m in range(n + 1, len(REPLAY_TIMESTEPS))
                if e["infra_id"] in h0[REPLAY_TIMESTEPS[m]]
            ]
            assert e["hours_remaining"] == (3 * (later[0] - n) if later else None)
        for e in entry["cut_off"]:
            k = REPLAY_TIMESTEPS.index(e["since"])
            assert all(e["infra_id"] in h0[REPLAY_TIMESTEPS[m]] for m in range(k, n + 1))
            assert k == 0 or e["infra_id"] not in h0[REPLAY_TIMESTEPS[k - 1]]


def test_perfect_forecast_flags_within_the_window(fixture):
    """The replay's expected hazard is the observed next 24 h: every flagged facility is cut off
    within it (this is by construction, which is why the panel says so)."""
    for ts in REPLAY_TIMESTEPS:
        for e in fixture["timesteps"][ts]["expected"]:
            assert e["hours_remaining"] is not None and 0 < e["hours_remaining"] <= 24


# --- Ordering -------------------------------------------------------------------------------------


def test_expected_is_ordered_by_hours_remaining(fixture):
    for ts in REPLAY_TIMESTEPS:
        entries = fixture["timesteps"][ts]["expected"]
        keys = [
            (e["hours_remaining"] is None, e["hours_remaining"] or 0, e["name"]) for e in entries
        ]
        assert keys == sorted(keys), ts
        cut = [(e["since"], e["name"]) for e in fixture["timesteps"][ts]["cut_off"]]
        assert cut == sorted(cut), ts


def test_compute_orders_and_finds_the_start_of_each_isolation():
    ts = REPLAY_TIMESTEPS[:5]
    wind, surge = Isolation("wind", None), Isolation("surge", None)
    none: dict[str, Isolation] = {}
    h0 = {
        ts[0]: none,
        ts[1]: {"a": surge},
        ts[2]: none,
        ts[3]: {"a": surge},
        ts[4]: {"a": surge, "b": wind},
    }
    h24 = {
        ts[0]: {"a": surge, "b": wind},
        ts[1]: {"a": surge, "b": wind},
        ts[2]: {"a": surge, "b": wind},
        ts[3]: {"b": wind},
        ts[4]: none,
    }
    out = countdown.compute(h0, h24, {t_: [] for t_ in ts}, {}, 0.25, timesteps=ts)
    first = out["timesteps"][ts[0]]["expected"]
    assert [(e["infra_id"], e["hours_remaining"]) for e in first] == [("a", 3), ("b", 12)]
    # "a" is cut off at ts[1], reconnected at ts[2], cut off again from ts[3].
    assert out["timesteps"][ts[2]]["expected"][0]["hours_remaining"] == 3
    assert [(e["infra_id"], e["since"]) for e in out["timesteps"][ts[4]]["cut_off"]] == [
        ("a", ts[3]),
        ("b", ts[4]),
    ]
    assert out["key_moments"][0] == {
        "kind": "first_alert",
        "timestep": None,
        "label": "No alert in the replay",
    }


# --- Gosaba and the key moments -------------------------------------------------------------------


def _find(entries: list[dict], name: str) -> dict:
    (e,) = [e for e in entries if e["name"] == name]
    return e


@pytest.mark.parametrize(("before", "hours"), [(27, 24), (12, 9)])
def test_gosaba_is_flagged_with_the_time_left(fixture, before, hours):
    e = _find(fixture["timesteps"][t(before)]["expected"], GOSABA)
    assert e["hours_remaining"] == hours
    assert e["cause"] == "ferry suspended by wind"


def test_gosaba_first_appears_at_t27_and_is_cut_off_from_t3(fixture):
    names = lambda ts, part: {e["name"] for e in fixture["timesteps"][ts][part]}  # noqa: E731
    assert GOSABA not in names(t(30), "expected")
    assert GOSABA in names(t(27), "expected")
    assert _find(fixture["timesteps"][t(3)]["cut_off"], GOSABA)["since"] == t(3)


def test_key_moments(fixture):
    moments = {m["kind"]: m for m in fixture["key_moments"]}
    assert list(moments) == [
        "first_alert",
        "first_expected_isolation",
        "first_actual_isolation",
        "landfall",
    ]
    assert moments["first_alert"]["timestep"] == t(33)
    assert moments["first_alert"]["label"] == "First alert: Namkhana"
    assert moments["landfall"]["timestep"] == LANDFALL_TIMESTEP
    first_expected = min(ts for ts in REPLAY_TIMESTEPS if fixture["timesteps"][ts]["expected"])
    assert moments["first_expected_isolation"]["timestep"] == first_expected
    assert (
        moments["first_expected_isolation"]["timestep"]
        < moments["first_actual_isolation"]["timestep"]
    )


# --- Route ----------------------------------------------------------------------------------------


def test_route_serves_the_fixture_in_demo_mode(demo, fixture):
    r = client.get("/api/impact/countdown", params={"timestep": t(12)})
    assert r.status_code == 200
    body = ActionCountdown.model_validate(r.json())
    assert body.horizon_h == 24
    assert [e.infra_id for e in body.expected] == [
        e["infra_id"] for e in fixture["timesteps"][t(12)]["expected"]
    ]
    assert [m.model_dump() for m in body.key_moments] == fixture["key_moments"]


@pytest.mark.parametrize(("timestep", "status"), [("live", 501), ("2020-05-17T13:00:00Z", 422)])
def test_route_rejects(demo, timestep, status):
    assert client.get("/api/impact/countdown", params={"timestep": timestep}).status_code == status


def test_missing_fixture_is_501(demo, monkeypatch):
    def missing(key):
        raise FileNotFoundError(key)

    monkeypatch.setattr(countdown, "_read", missing)
    countdown.clear_cache()
    assert client.get("/api/impact/countdown", params={"timestep": t(12)}).status_code == 501
