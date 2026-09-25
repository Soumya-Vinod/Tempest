"""Impact engine, network, synthetic hazards and compact fixtures, on the hand-built scenario."""

import re

import pytest

from app.impact import engine, synthetic
from app.impact.fixtures import compact_timestep, fixture_key, from_fixture, to_fixture
from app.impact.network import baseline_access
from app.schemas import LANDFALL_TIMESTEP, REPLAY_TIMESTEPS, ImpactResultCollection
from tests import impact_scenario as S

TS = LANDFALL_TIMESTEP


@pytest.fixture(scope="module")
def graph():
    return S.build_graph()


def run(graph, infra=None, **boxes) -> ImpactResultCollection:
    return engine.compute_impacts(
        S.hazards(TS, **boxes), infra or S.infra(), graph, TS, anchor=S.ANCHOR
    )


def row(fc: ImpactResultCollection, infra_id: str, hazard: str):
    return next(
        f.properties
        for f in fc.features
        if f.properties.infra_id == infra_id and f.properties.hazard_type == hazard
    )


def steps(props) -> list[tuple[str, str, str]]:
    return [(s.type, s.id, s.label) for s in props.pathway]


CLINIC_ROAD_SURGE = S.box(88.29, 22.46, 88.31, 22.49, 0.5)  # over way 3 only
FERRY_GALE = S.box(88.19, 22.35, 88.21, 22.45, 20.0)  # over the ferry only


# --- Isolation and pathways ---------------------------------------------------------------------


def test_road_cut_isolates_clinic(graph):
    fc = run(graph, surge=[CLINIC_ROAD_SURGE])
    road = row(fc, "road-way-3", "surge")
    assert road.status == "cut"
    assert steps(road) == [
        ("hazard", "hazard:surge", "Surge 0.50 m"),
        ("infra", "road-way-3", "Clinic Road"),
    ]
    clinic = row(fc, S.CLINIC, "surge")
    assert clinic.status == "isolated"
    assert steps(clinic) == [
        ("hazard", "hazard:surge", "Surge 0.50 m"),
        ("infra", "road-way-3", "First cut on usual route: Clinic Road"),
        ("infra", S.CLINIC, "Clinic"),
    ]
    assert row(fc, S.CLINIC, "wind").status == "ok"
    assert row(fc, S.SHELTER, "surge").status == "ok"  # island still reached by ferry


def test_ferry_cut_isolates_island(graph):
    fc = run(graph, wind=[FERRY_GALE])
    assert row(fc, "road-way-5", "wind").status == "cut"
    shelter = row(fc, S.SHELTER, "wind")
    assert shelter.status == "isolated"
    assert steps(shelter) == [
        ("hazard", "hazard:wind", "Wind 20 m/s"),
        ("infra", "road-way-5", "First cut on usual route: Island Ferry"),
        ("infra", S.SHELTER, "Unnamed shelter"),
    ]
    assert row(fc, S.CLINIC, "wind").status == "ok"


def test_combined_cuts_attributed_to_first_cut_on_path(graph):
    # Surge cuts the island road and wind the ferry: the shelter's usual route (F-E-B) meets
    # the island road first, so the isolation is attributed to surge.
    island_road_surge = S.box(88.21, 22.29, 88.24, 22.31, 1.0)
    fc = run(graph, surge=[island_road_surge], wind=[FERRY_GALE])
    assert row(fc, S.SHELTER, "surge").status == "isolated"
    assert row(fc, S.SHELTER, "wind").status == "ok"  # one isolated row, not two
    assert steps(row(fc, S.SHELTER, "surge"))[1][1] == "road-way-4"


def test_baseline_disconnected_and_far_facilities_never_isolated(graph):
    fc = run(graph, surge=[S.box(*S.EVERYWHERE, 5.0)], wind=[S.box(*S.EVERYWHERE, 60.0)])
    assert row(fc, S.CLINIC, "surge").status == "isolated"
    for fid in (S.CUT_OFF, S.FAR):
        statuses = {row(fc, fid, h).status for h in engine.HAZARD_TYPES}
        assert "isolated" not in statuses
        assert row(fc, fid, "surge").status == "at_risk"  # hazard at the location


def test_missing_road_feature_gives_placeholder_step(graph):
    fc = run(graph, infra=S.infra(skip_ways=(3,)), surge=[CLINIC_ROAD_SURGE])
    clinic = row(fc, S.CLINIC, "surge")
    assert clinic.status == "isolated"
    assert steps(clinic)[1] == (
        "infra",
        "road-way-3",
        "First cut on usual route: unmapped road segment (OSM way 3)",
    )


# --- Thresholds (inclusive) ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("infra_id", "hazard", "value", "expected"),
    [
        ("road-way-1", "surge", 0.14, "ok"),
        ("road-way-1", "surge", 0.15, "at_risk"),
        ("road-way-1", "surge", 0.29, "at_risk"),
        ("road-way-1", "surge", 0.30, "cut"),
        ("road-way-1", "flood", 0.69, "ok"),
        ("road-way-1", "flood", 0.70, "at_risk"),
        ("road-way-1", "flood", 1.00, "at_risk"),  # flood never cuts (static susceptibility)
        ("road-way-1", "wind", 60.0, "ok"),  # wind never cuts a road
        ("road-way-5", "wind", 11.9, "ok"),
        ("road-way-5", "wind", 12.0, "at_risk"),
        ("road-way-5", "wind", 16.9, "at_risk"),
        ("road-way-5", "wind", 17.0, "cut"),
        ("road-way-5", "surge", 3.0, "ok"),  # surge never cuts a ferry
        (S.SUBSTATION, "surge", 0.49, "ok"),
        (S.SUBSTATION, "surge", 0.50, "cut"),
        (S.SUBSTATION, "flood", 0.69, "ok"),
        (S.SUBSTATION, "flood", 0.70, "at_risk"),
        (S.SUBSTATION, "flood", 1.00, "at_risk"),
        (S.SUBSTATION, "wind", 32.9, "ok"),
        (S.SUBSTATION, "wind", 33.0, "at_risk"),
        (S.POWER_LINE, "wind", 32.9, "ok"),
        (S.POWER_LINE, "wind", 33.0, "at_risk"),
        (S.POWER_LINE, "surge", 3.0, "ok"),
        (S.CUT_OFF, "surge", 0.14, "ok"),
        (S.CUT_OFF, "surge", 0.15, "at_risk"),
        (S.CUT_OFF, "flood", 0.69, "ok"),
        (S.CUT_OFF, "flood", 0.70, "at_risk"),
        (S.CUT_OFF, "wind", 32.9, "ok"),
        (S.CUT_OFF, "wind", 33.0, "at_risk"),
    ],
)
def test_thresholds(graph, infra_id, hazard, value, expected):
    fc = run(graph, **{hazard: [S.box(*S.EVERYWHERE, value)]})
    got = row(fc, infra_id, hazard)
    assert got.status == expected
    if expected == "ok":
        assert got.pathway == []
    else:
        assert got.pathway[0].id == f"hazard:{hazard}" and got.pathway[-1].id == infra_id


def test_flood_never_cuts_or_isolates(graph):
    fc = run(graph, flood=[S.box(*S.EVERYWHERE, 1.0)])
    statuses = {f.properties.status for f in fc.features}
    assert statuses == {"ok", "at_risk"}
    assert row(fc, "road-way-3", "flood").status == "at_risk"
    assert row(fc, S.CLINIC, "flood").status == "at_risk"  # at its location, not isolated


def test_flood_cuts_roads_flag_restores_old_rule(graph, monkeypatch):
    """Only for a future time-varying flood layer: cut at 0.7, at_risk from 0.35, isolates."""
    monkeypatch.setattr("app.impact.thresholds.FLOOD_CUTS_ROADS", True)
    assert row(run(graph, flood=[S.box(*S.EVERYWHERE, 0.35)]), "road-way-1", "flood").status == (
        "at_risk"
    )
    fc = run(graph, flood=[S.box(88.29, 22.46, 88.31, 22.49, 0.7)])
    assert row(fc, "road-way-3", "flood").status == "cut"
    clinic = row(fc, S.CLINIC, "flood")
    assert clinic.status == "isolated"
    assert steps(clinic)[0] == ("hazard", "hazard:flood", "Flood severity 0.70")


def test_results_are_complete_valid_and_deterministic(graph):
    kwargs = {"surge": [CLINIC_ROAD_SURGE], "wind": [FERRY_GALE]}
    fc = run(graph, **kwargs)
    infra = S.infra()
    assert len(fc.features) == len(infra.features) * len(engine.HAZARD_TYPES)
    for f in fc.features:
        p = f.properties
        assert p.id == f"{p.infra_id}__{p.hazard_type}__{TS}" == f.id
        assert (p.status == "ok") == (p.pathway == [])
    ImpactResultCollection.model_validate(fc.model_dump(mode="json"))
    assert run(graph, **kwargs).model_dump() == fc.model_dump()


def test_no_hazards_means_all_ok(graph):
    fc = engine.compute_impacts({}, S.infra(), graph, TS, anchor=S.ANCHOR)
    assert {f.properties.status for f in fc.features} == {"ok"}


# --- Network ------------------------------------------------------------------------------------


def test_snaps_are_cached_and_flag_far_facilities(graph):
    net = engine.network_for(graph, S.ANCHOR)
    assert net.anchor == S.A and S.G not in net.main
    first = net.snap("x", 88.3005, 22.4495)
    assert first is net.snap("x", 88.3005, 22.4495)
    assert first.node == S.D and first.distance_m < 100 and not first.too_far
    assert net.snap("far", 88.9, 22.6).too_far


def test_baseline_access_attributes(graph):
    access = baseline_access(
        graph,
        {"clinic": (88.3005, 22.4495), "cut-off": (88.52, 22.1005), "far": (88.9, 22.6)},
        S.ANCHOR,
    )
    assert access["clinic"]["baseline_travel_time_s"] > 0
    assert access["clinic"]["snap_too_far"] is False
    assert access["cut-off"]["baseline_travel_time_s"] is None  # not in the anchor's component
    assert access["far"] == {
        "snap_distance_m": access["far"]["snap_distance_m"],
        "snap_too_far": True,
        "baseline_travel_time_s": None,
    }


# --- Compact fixtures ---------------------------------------------------------------------------


def test_fixture_stores_non_ok_and_reconstructs_exactly(graph):
    fc = run(graph, surge=[S.box(*S.EVERYWHERE, 5.0)], wind=[FERRY_GALE])
    fixture = to_fixture(fc)
    assert fixture["features"] and all(
        r["properties"]["status"] != "ok" for r in fixture["features"]
    )
    assert len(fixture["features"]) < len(fc.features)
    rebuilt = from_fixture(fixture, S.infra(), TS)
    assert rebuilt.model_dump(mode="json") == fc.model_dump(mode="json")


def test_fixture_rows_for_unknown_features_are_an_error(graph):
    fixture = to_fixture(run(graph, surge=[CLINIC_ROAD_SURGE]))
    with pytest.raises(ValueError, match="unknown infra features"):
        from_fixture(fixture, S.infra(skip_ways=(3,)), TS)


def test_fixture_key():
    assert compact_timestep("2020-05-20T12:00:00Z") == "20200520T1200Z"
    assert fixture_key(TS) == "impact__results__20200520T1200Z"


# --- Synthetic hazards --------------------------------------------------------------------------


def test_synthetic_hazards_are_valid_marked_and_deterministic():
    first, last = REPLAY_TIMESTEPS[0], REPLAY_TIMESTEPS[-1]
    for ts in REPLAY_TIMESTEPS:
        layers = synthetic.synthetic_hazards(ts)  # validated as HazardLayerCollection
        assert set(layers) == {"wind", "surge", "flood"}
        for h, fc in layers.items():
            assert all(re.fullmatch(rf"synthetic-{h}-\d+-\d+", f.id) for f in fc.features)
            assert all(f.properties.timestep == ts for f in fc.features)
    a, b = synthetic.synthetic_hazards(last), synthetic.synthetic_hazards(last)
    assert {h: fc.model_dump() for h, fc in a.items()} == {
        h: fc.model_dump() for h, fc in b.items()
    }

    def peak(ts, h):
        return max(
            (f.properties.value for f in synthetic.synthetic_hazards(ts)[h].features), default=0
        )

    assert peak(first, "surge") < peak(last, "surge")
    assert peak(first, "wind") < peak(last, "wind")
    flood_ids = {ts: {f.id for f in synthetic.synthetic_hazards(ts)["flood"].features}
                 for ts in (first, last)}  # fmt: skip
    assert flood_ids[first] == flood_ids[last]  # flood is static


def test_synthetic_rejects_unknown_timestep():
    with pytest.raises(ValueError):
        synthetic.synthetic_hazards("2020-05-20T13:00:00Z")


def test_unnamed_labels():
    infra = {f.id: f for f in S.infra().features}
    ferry = infra["road-way-5"].model_copy(deep=True)
    ferry.properties.name = None
    road = infra["road-way-2"]  # unnamed road
    assert engine.feature_label(ferry) == "Unnamed ferry route"
    assert engine.feature_label(road) == "Unnamed road"
    assert engine.feature_label(infra[S.SHELTER]) == "Unnamed shelter"
    assert engine.feature_label(infra[S.POWER_LINE]) == "Unnamed power line"
