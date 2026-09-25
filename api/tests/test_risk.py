"""Risk engine on the hand-built scenario (tests/risk_scenario.py)."""

import math

import pytest

from app.impact import engine as impact_engine
from app.risk import engine, weights
from app.risk.blocks import UNSCORED_LABEL, unscored_areas
from app.schemas import LANDFALL_TIMESTEP, ImpactResultCollection, RiskScoreCollection
from tests import impact_scenario as S
from tests import risk_scenario as R

TS = LANDFALL_TIMESTEP
MAINLAND, ISLAND, FRAGMENT = 0, 1, 2
NO_IMPACTS = ImpactResultCollection(features=[])


@pytest.fixture(scope="module")
def graph():
    return S.build_graph()


@pytest.fixture(scope="module")
def ctx(graph):
    return engine.build_context(R.blocks(), R.infra(), graph, S.ANCHOR)


def run(ctx, graph, **boxes):
    hazards = S.hazards(TS, **boxes)
    impacts = impact_engine.compute_impacts(hazards, R.infra(), graph, TS, anchor=S.ANCHOR)
    return engine.evaluate(hazards, impacts, ctx), hazards, impacts


# --- Weights and fixed scales -------------------------------------------------------------------


def test_weights_sum_to_one():
    assert weights.W_EXPOSURE + weights.W_VULNERABILITY == pytest.approx(1)
    assert sum(weights.EXPOSURE_PARTS.values()) == pytest.approx(1)
    assert sum(weights.VULNERABILITY_PARTS.values()) == pytest.approx(1)
    assert weights.VULNERABILITY_PARTS["low_literacy"] == 0  # off: no primary source yet
    assert weights.SURGE_LAND_THRESHOLD_M == 0.3  # the road-cut threshold


@pytest.mark.parametrize(
    ("fn", "args", "expected"),
    [
        (engine.wind_part, (17.0,), 0.0),
        (engine.wind_part, (38.5,), 0.5),
        (engine.wind_part, (60.0,), 1.0),
        (engine.wind_part, (80.0,), 1.0),
        (engine.density_part, (1000.0, 1.0), 0.5),
        (engine.density_part, (5000.0, 1.0), 1.0),
        (engine.hospital_access_part, (3600.0,), 0.5),
        (engine.hospital_access_part, (math.inf,), 1.0),
        (engine.mapped_shelters_part, (1, 10_000.0), 0.5),  # 1 per 10k; target 2
        (engine.mapped_shelters_part, (0, 10_000.0), 1.0),
        (engine.mapped_shelters_part, (5, 10_000.0), 0.0),
    ],
)
def test_fixed_scales(fn, args, expected):
    assert fn(*args) == pytest.approx(expected)


# --- Hazard (land only) -------------------------------------------------------------------------


def test_no_hazard_scores_zero(ctx):
    risks = engine.evaluate({}, NO_IMPACTS, ctx)
    assert [r.score for r in risks] == [0, 0, 0]
    assert all(r.hazard == 0 and r.top_driver is None for r in risks)
    assert all(r.reach == "direct" for r in risks)  # a tie at 0 counts as direct
    assert all(r.vulnerability > 0 for r in risks)  # static, still there


def test_surge_part_is_land_share_above_threshold(ctx, graph):
    west_half = S.box(88.15, 22.25, 88.25, 22.35, 1.0)  # half of the island block
    shallow = S.box(88.25, 22.25, 88.35, 22.35, 0.29)  # below 0.3 m: doesn't count
    risks, *_ = run(ctx, graph, surge=[west_half, shallow])
    assert risks[ISLAND].hazard_parts["surge"] == pytest.approx(0.5, abs=0.01)
    assert risks[MAINLAND].hazard_parts["surge"] == 0


def test_wind_part_is_land_weighted(ctx, graph):
    risks, *_ = run(ctx, graph, wind=[S.box(*S.EVERYWHERE, 38.5)])
    assert all(r.hazard_parts["wind"] == pytest.approx(0.5) for r in risks)
    assert all(r.hazard == pytest.approx(0.5) for r in risks)


def test_flood_adds_a_small_weight(ctx, graph):
    risks, *_ = run(ctx, graph, flood=[S.box(*S.EVERYWHERE, 1.0)])
    assert all(r.hazard == pytest.approx(weights.FLOOD_WEIGHT) for r in risks)
    both, *_ = run(ctx, graph, wind=[S.box(*S.EVERYWHERE, 60.0)],
                   flood=[S.box(*S.EVERYWHERE, 1.0)])  # fmt: skip
    assert all(r.hazard == 1.0 for r in both)  # capped


# --- Exposure -----------------------------------------------------------------------------------

BACKGROUND_WIND = S.box(*S.EVERYWHERE, 38.5)  # hazard 0.5 everywhere, cuts nothing on land
CLINIC_ROAD_SURGE = S.box(88.29, 22.46, 88.31, 22.49, 0.5)


def test_isolated_facility_raises_exposure(ctx, graph):
    calm, *_ = run(ctx, graph, wind=[BACKGROUND_WIND])
    cut_off, _, impacts = run(ctx, graph, wind=[BACKGROUND_WIND], surge=[CLINIC_ROAD_SURGE])
    assert any(
        f.properties.infra_id == S.CLINIC and f.properties.status == "isolated"
        for f in impacts.features
    )
    before, after = calm[MAINLAND], cut_off[MAINLAND]
    # The clinic is the mainland's only eligible facility: 1 of 1 isolated.
    assert ctx.eligible_facilities[MAINLAND] == 1
    assert after.exposure_parts["isolated_facilities"] == pytest.approx(1.0)
    assert before.exposure_parts["isolated_facilities"] == 0
    assert after.exposure > before.exposure
    assert after.score > before.score


def test_cut_off_block_scores_without_its_own_hazard(ctx, graph):
    # Surge only on the clinic's road: almost no hazard on the mainland's land, but the storm
    # has cut its only facility off. Reached indirectly, so exposure scales the score.
    risks, _, impacts = run(ctx, graph, surge=[CLINIC_ROAD_SURGE])
    assert any(
        f.properties.infra_id == S.CLINIC and f.properties.status == "isolated"
        for f in impacts.features
    )
    r = risks[MAINLAND]
    assert r.hazard < 0.1
    assert r.exposure > r.hazard and r.reach == "cut_off"
    assert r.score > 0.2
    assert r.score == pytest.approx(
        r.exposure * (weights.W_EXPOSURE * r.exposure + weights.W_VULNERABILITY * r.vulnerability)
    )


def test_reach_is_the_larger_of_hazard_and_exposure(ctx, graph):
    # Wind everywhere (hazard 0.5) also stops the island's ferry: its shelter is cut off.
    risks, *_ = run(ctx, graph, wind=[BACKGROUND_WIND])
    assert [r.reach for r in risks] == ["direct", "cut_off", "direct"]
    for r in risks:
        assert r.reach == ("direct" if r.hazard >= r.exposure else "cut_off")
    breakdown = engine.to_breakdown(risks, ctx, TS)
    assert [b.reach for b in breakdown.blocks] == [r.reach for r in risks]


def test_cut_road_share_uses_length(ctx, graph):
    risks, *_ = run(ctx, graph, surge=[S.box(88.12, 22.49, 88.18, 22.51, 1.0)])  # way 1 only
    assert {r for r in ctx.road_lengths if r.startswith("road-way-")} >= {"road-way-1"}
    share = ctx.road_lengths["road-way-1"][MAINLAND] / ctx.total_road_m[MAINLAND]
    assert 0 < share < 1
    assert risks[MAINLAND].exposure_parts["cut_roads"] == pytest.approx(share)  # no cap


def test_cut_substation_counts(ctx, graph):
    risks, *_ = run(ctx, graph, surge=[S.box(88.09, 22.49, 88.11, 22.51, 1.0)])  # at the sub
    assert risks[MAINLAND].exposure_parts["cut_substations"] == pytest.approx(0.5)  # 1 of cap 2


# --- Vulnerability ------------------------------------------------------------------------------


def test_hospital_access_is_multi_source(graph):
    only_fragment = engine.build_context(R.blocks(), R.infra(), graph, S.ANCHOR)
    assert only_fragment.static[FRAGMENT].hospital_minutes < 5
    assert math.isinf(only_fragment.static[MAINLAND].hospital_minutes)  # no hospital reachable
    assert only_fragment.static[MAINLAND].vulnerability_parts["hospital_access"] == 1.0

    with_mainland = engine.build_context(R.blocks(), R.infra(True), graph, S.ANCHOR)
    minutes = with_mainland.static[MAINLAND].hospital_minutes
    assert 0 < minutes < 60
    island = with_mainland.static[ISLAND].hospital_minutes
    assert minutes < island < math.inf  # reached over the ferry


def test_mapped_shelters_and_density(ctx):
    island = ctx.static[ISLAND]
    assert island.shelters == 1
    assert island.vulnerability_parts["mapped_shelters"] == pytest.approx(
        engine.mapped_shelters_part(1, R.POPULATION)
    )
    area = ctx.blocks.land_area_km2[ISLAND]
    assert island.vulnerability_parts["population_density"] == pytest.approx(
        min(1, R.POPULATION / area / weights.DENSITY_SCALE_PER_KM2)
    )


# --- Output -------------------------------------------------------------------------------------


def test_scores_are_contract_valid_and_deterministic(ctx, graph):
    _, hazards, impacts = run(ctx, graph, wind=[BACKGROUND_WIND], surge=[CLINIC_ROAD_SURGE])
    fc = engine.compute_scores(hazards, impacts, ctx, TS)
    assert fc.model_dump() == engine.compute_scores(hazards, impacts, ctx, TS).model_dump()
    RiskScoreCollection.model_validate(fc.model_dump(mode="json"))
    assert [f.properties.block_id for f in fc.features] == list(R.BLOCK_BOXES)
    for f in fc.features:
        p = f.properties
        assert f.id == p.id == f"{p.block_id}__{TS}"
        assert p.block_source == "census2011_cd"
        assert 0 <= p.score <= 1
        assert p.score == pytest.approx(
            max(p.components.hazard, p.components.exposure)
            * (weights.W_EXPOSURE * p.components.exposure
               + weights.W_VULNERABILITY * p.components.vulnerability),
            abs=1e-3,
        )  # fmt: skip
        assert p.top_driver is not None


def test_top_driver_is_largest_part(ctx, graph):
    # Nothing isolated and no hospital reachable from the mainland: access (0.4 x 0.5 x 1 = 0.2)
    # is the largest part.
    calm, *_ = run(ctx, graph, wind=[BACKGROUND_WIND])
    assert calm[MAINLAND].top_driver == "hospital_access"
    # The clinic cut off: 1 of 1 eligible facilities, 0.6 x 0.5 x 1 = 0.3 beats access.
    risks, *_ = run(ctx, graph, wind=[BACKGROUND_WIND], surge=[CLINIC_ROAD_SURGE])
    assert risks[MAINLAND].top_driver == "isolated_facilities"
    # In general: the part with the largest weighted contribution to the score.
    near = engine.build_context(R.blocks(), R.infra(True), graph, S.ANCHOR)
    risks, *_ = run(near, graph, wind=[BACKGROUND_WIND], surge=[CLINIC_ROAD_SURGE])
    for r in risks:
        contributions = {
            **{k: weights.W_EXPOSURE * weights.EXPOSURE_PARTS[k] * v
               for k, v in r.exposure_parts.items()},
            **{k: weights.W_VULNERABILITY * weights.VULNERABILITY_PARTS[k] * v
               for k, v in r.vulnerability_parts.items()},
        }  # fmt: skip
        assert r.top_driver == max(contributions, key=lambda k: contributions[k])
    assert risks[MAINLAND].top_driver == "isolated_facilities"


def test_eligible_facilities_exclude_unreachable_and_far(ctx, graph):
    # Mainland: the clinic. Island: the shelter (reached by ferry). Fragment: the cut-off
    # hospital is not in the main component at baseline, so it can never be isolated.
    assert list(ctx.eligible_facilities) == [1, 1, 0]
    everything, *_ = run(ctx, graph, surge=[S.box(*S.EVERYWHERE, 5.0)])
    assert everything[FRAGMENT].exposure_parts["isolated_facilities"] == 0
    assert everything[MAINLAND].exposure_parts["isolated_facilities"] == 1.0


def test_top_driver_falls_back_to_hazard():
    zero = dict.fromkeys(weights.EXPOSURE_PARTS, 0.0)
    vuln = dict.fromkeys(weights.VULNERABILITY_PARTS, 0.0)
    hz = {"surge": 0.2, "wind": 0.6, "flood": 1.0}
    assert engine._top_driver(hz, zero, vuln, 0.5) == "wind"
    assert engine._top_driver(hz, zero, vuln, 0.0) is None


def test_unscored_areas_are_land_outside_blocks():
    fc = unscored_areas(R.blocks())
    assert len(fc.features) == 1
    area = fc.features[0].properties
    assert area.label == UNSCORED_LABEL
    assert area.area_km2 == pytest.approx(10.3 * 11.1, rel=0.05)  # 0.1 deg x 0.1 deg at 22.45 N


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("Gosaba Rural Hospital", True),
        ("Kakdwip Sub-Divisional Hospital", True),
        ("Diamond Harbour Govt Medical College", True),
        ("Rural Hospital & Maternity Ward", True),  # keep pattern wins over "maternity"
        ("Peerless Hospital", True),
        (None, True),  # unnamed: can't judge, kept
        ("ABC Nursing Home", False),
        ("City Polyclinic", False),
        ("Suraksha Diagnostic Centre", False),
        ("Care Clinic", False),
        ("Disha Eye Hospital", False),
        ("Smile Dental Clinic", False),
        ("Matri Maternity Home", False),
    ],
)
def test_hospital_access_sources(name, source):
    assert weights.is_access_hospital(name) is source


# --- Inhabited land (reserve forest excluded) ---------------------------------------------------

ISLAND_WEST = (88.15, 22.25, 88.25, 22.35)  # the island block's west half, made "protected"


@pytest.fixture(scope="module")
def reserve_ctx(graph):
    from shapely.geometry import box

    blocks = R.blocks(protected=box(*ISLAND_WEST))
    return engine.build_context(blocks, R.infra(), graph, S.ANCHOR)


def test_surge_on_protected_land_does_not_count(reserve_ctx, graph):
    on_reserve, *_ = run(reserve_ctx, graph, surge=[S.box(*ISLAND_WEST, 2.0)])
    assert on_reserve[ISLAND].hazard_parts["surge"] == 0
    east = S.box(88.25, 22.25, 88.35, 22.35, 2.0)
    on_villages, *_ = run(reserve_ctx, graph, surge=[east])
    assert on_villages[ISLAND].hazard_parts["surge"] == pytest.approx(1.0, abs=0.01)


def test_wind_and_flood_weighted_by_inhabited_land(reserve_ctx, graph):
    risks, *_ = run(
        reserve_ctx, graph,
        wind=[S.box(*ISLAND_WEST, 60.0), S.box(88.25, 22.25, 88.35, 22.35, 17.0)],
    )  # fmt: skip
    assert risks[ISLAND].hazard_parts["wind"] == pytest.approx(0.0, abs=0.01)  # gale floor only


def test_density_uses_inhabited_area(reserve_ctx, ctx):
    full = ctx.static[ISLAND].vulnerability_parts["population_density"]
    half = reserve_ctx.static[ISLAND].vulnerability_parts["population_density"]
    assert reserve_ctx.blocks.inhabited_area_km2[ISLAND] == pytest.approx(
        ctx.blocks.land_area_km2[ISLAND] / 2, rel=0.02
    )
    assert half == pytest.approx(2 * full, rel=0.02)
