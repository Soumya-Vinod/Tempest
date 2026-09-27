"""Engine facts for one block and timestep, as contract Citations (contracts.md §4.5).

Every figure an advisory may state comes from here: the risk engine (score, components, driver,
reach, hospital access), the impact engine (isolated facilities and their cause, cut roads and
substations), Dev A's hazard layers (peak surge and wind on the block's inhabited land, the same
basis as the risk engine's hazard parts) and the exposure layer (stand-in shelters, next-hospital
times). Gemini only ever refers to them as {{key}} placeholders; render.py fills them in.
"""

from dataclasses import dataclass
from datetime import datetime

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import shape

from app.advisory.render import UNNAMED
from app.exposure import service as exposure
from app.exposure.ingest import METRIC_CRS
from app.impact import service as impact
from app.impact.engine import FIRST_CUT_LABEL
from app.impact.horizon import FORECAST_HORIZON_H, window
from app.risk import blocks as block_data
from app.risk import service as risk
from app.schemas import (
    LANDFALL_TIMESTEP,
    Citation,
    HazardLayerCollection,
    ImpactResultCollection,
    InfraFeature,
)

MAX_STAND_INS = 10  # named stand-in shelters cited; the count covers all of them
TIMESTEP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Enumerated text values. English here; render.py has the bn and hi versions.
DRIVER_TEXT = {
    "surge": "storm surge",
    "wind": "wind",
    "flood": "flood susceptibility",
    "isolated_facilities": "isolated facilities",
    "cut_roads": "cut roads",
    "cut_substations": "cut substations",
    "population_density": "population density",
    "hospital_access": "hospital access",
    "low_literacy": "low literacy",
    "mapped_shelters": "few mapped shelters",
}
REACH_TEXT = {"direct": "direct hazard", "cut_off": "cut off by the storm"}
# (first cut is a ferry, hazard) -> cause
CAUSE_TEXT = {
    (True, "wind"): "ferry suspended by wind",
    (True, "surge"): "ferry route closed by storm surge",
    (False, "surge"): "road flooded by storm surge",
    (False, "wind"): "road blocked by wind",
    (False, "flood"): "road flooded",
    (True, "flood"): "ferry route closed by flooding",
}


# Every list the facts expose has a count, so a draft never needs to count in words (prompt.py).
# Cut roads are measured in km (cut_road_km): a count would be of OSM road segments.
COUNT_SUFFIX = "_count"


def count_citations(citations: list[Citation]) -> list[Citation]:
    return [c for c in citations if c.key.endswith(COUNT_SUFFIX)]


# Model scores: cited (the citations table, CAP severity) but never offered to the model as
# placeholders; the advisory text states physical facts only.
MODEL_SCORE_KEYS = frozenset(
    {"risk_score", "risk_score_24h", "risk_hazard", "risk_exposure", "risk_vulnerability"}
)


def offered_citations(citations: list[Citation]) -> list[Citation]:
    """The citations the model may use as {{placeholders}}."""
    return [c for c in citations if c.key not in MODEL_SCORE_KEYS]


def offered_keys(citations: list[Citation]) -> set[str]:
    return {c.key for c in offered_citations(citations)}


class UnknownBlock(LookupError):
    """No CD block with this census code."""


@dataclass(frozen=True)
class Facts:
    block_id: str
    block_name: str
    timestep: str
    citations: list[Citation]


def _cite(key: str, label: str, value, unit: str | None, source: str) -> Citation:
    return Citation(key=key, label=label, value=value, unit=unit, source=source)


def hours_to_landfall(timestep: str) -> int:
    ts = datetime.strptime(timestep, TIMESTEP_FORMAT)
    landfall = datetime.strptime(LANDFALL_TIMESTEP, TIMESTEP_FORMAT)
    return round((landfall - ts).total_seconds() / 3600)


def peak_on_land(layer: HazardLayerCollection, land_metric) -> float:
    """Highest value among the hazard cells that intersect the inhabited land (positive area)."""
    if not layer.features or land_metric is None or land_metric.is_empty:
        return 0.0
    polys = gpd.GeoSeries(
        [shape(f.geometry.model_dump()) for f in layer.features], crs="EPSG:4326"
    ).to_crs(METRIC_CRS)
    values = np.array([f.properties.value for f in layer.features], dtype=float)
    geoms = polys.to_numpy()
    idx = shapely.STRtree(geoms).query(land_metric, predicate="intersects")
    idx = idx[shapely.area(shapely.intersection(geoms[idx], land_metric)) > 0]
    return float(values[idx].max()) if len(idx) else 0.0


def cause_of(pathway, roads: dict[str, InfraFeature], hazard_type: str) -> tuple[str, str | None]:
    """(cause text, name of the first cut route or None) from an isolated facility's pathway."""
    first_cut = next(
        (s for s in pathway if s.type == "infra" and s.label.startswith(FIRST_CUT_LABEL)), None
    )
    ferry = False
    name = None
    if first_cut is not None and (road := roads.get(first_cut.id)) is not None:
        ferry = road.properties.attributes.get("ferry") is True
        name = road.properties.name
    return CAUSE_TEXT[(ferry, hazard_type)], name


def _in_block(features: list[InfraFeature], block_geom) -> list[InfraFeature]:
    if not features:
        return []
    xy = np.array([f.geometry.coordinates[:2] for f in features], dtype=float)
    inside = shapely.contains_xy(block_geom, xy[:, 0], xy[:, 1])
    return [f for f, ok in zip(features, inside, strict=True) if ok]


def build_facts(block_id: str, timestep: str) -> Facts:
    blocks = block_data.load_blocks()
    if block_id not in blocks.codes:
        raise UnknownBlock(f"unknown block_id {block_id!r}")
    b = blocks.codes.index(block_id)
    name = blocks.names[b]

    score = next(
        f.properties
        for f in risk.get_scores(timestep).features
        if f.properties.block_id == block_id
    )
    breakdown = next(x for x in risk.get_breakdown(timestep).blocks if x.block_id == block_id)
    score_24h = next(
        f.properties
        for f in risk.get_scores(timestep, FORECAST_HORIZON_H).features
        if f.properties.block_id == block_id
    )
    impacts: ImpactResultCollection = impact.get_results(timestep)
    hazards = impact.hazard_layers(timestep)
    infra = exposure.get_infra()
    by_id = {f.id: f for f in infra.features}
    roads = {f.id: f for f in infra.features if f.properties.infra_type == "road"}

    c: list[Citation] = []
    c.append(_cite("block_name", "CD block", name, None, "reference"))
    c.append(
        _cite(
            "timestep_utc",
            "Figures as of (UTC)",
            datetime.strptime(timestep, TIMESTEP_FORMAT).strftime("%d %b %Y, %H:%M"),
            None,
            "replay",
        )
    )
    c.append(
        _cite("hours_to_landfall", "Hours to landfall", hours_to_landfall(timestep), "h", "replay")
    )

    comp = score.components
    c += [
        _cite("risk_score", "Block risk score now (0-1)", score.score, None, "risk"),
        _cite(
            "risk_score_24h",
            "Block risk score, expected within 24 h (0-1)",
            score_24h.score,
            None,
            "risk",
        ),
        _cite("risk_hazard", "Hazard component (0-1)", comp.hazard, None, "risk"),
        _cite("risk_exposure", "Exposure component (0-1)", comp.exposure, None, "risk"),
        _cite(
            "risk_vulnerability", "Vulnerability component (0-1)", comp.vulnerability, None, "risk"
        ),
        _cite(
            "reach", "How the cyclone reaches the block", REACH_TEXT[breakdown.reach], None, "risk"
        ),
    ]
    if score.top_driver:
        c.append(_cite("top_driver", "Main driver", DRIVER_TEXT[score.top_driver], None, "risk"))
    if breakdown.hospital_travel_min is not None:
        c.append(
            _cite(
                "hospital_median_min",
                "Median travel time to a hospital (residents)",
                round(breakdown.hospital_travel_min),
                "min",
                "risk",
            )
        )

    land = blocks.inhabited_metric.iloc[b]
    c.append(
        _cite(
            "peak_surge_m",
            "Peak storm surge on inhabited land",
            round(peak_on_land(hazards["surge"], land), 2),
            "m",
            "hazard",
        )
    )
    c.append(
        _cite(
            "peak_wind_ms",
            "Peak wind on inhabited land",
            round(peak_on_land(hazards["wind"], land)),
            "m/s",
            "hazard",
        )
    )

    # Isolated facilities: one entry per facility (first hazard in the engine's order).
    block_geom = blocks.geometry.iloc[b]
    points = [f for f in infra.features if f.geometry.type == "Point"]
    in_block = {f.id for f in _in_block(points, block_geom)}
    isolated: dict[str, object] = {}
    cut_subs: set[str] = set()
    cut_roads: set[str] = set()
    for r in impacts.features:
        p = r.properties
        if p.status == "isolated" and p.infra_id in in_block and p.infra_id not in isolated:
            isolated[p.infra_id] = p
        elif p.status == "cut" and p.infra_id in in_block and p.infra_id.startswith("substation-"):
            cut_subs.add(p.infra_id)
        elif p.status == "cut" and p.infra_id in roads:
            cut_roads.add(p.infra_id)
    kinds = [by_id[fid].properties.infra_type for fid in isolated]
    c.append(_cite("isolated_count", "Isolated facilities", len(isolated), None, "impact"))
    c.append(
        _cite(
            "isolated_hospital_count",
            "Isolated hospitals and health centres",
            kinds.count("hospital"),
            None,
            "impact",
        )
    )
    c.append(
        _cite("isolated_shelter_count", "Isolated shelters", kinds.count("shelter"), None, "impact")
    )
    for i, (fid, p) in enumerate(sorted(isolated.items(), key=lambda kv: _name(by_id[kv[0]])), 1):
        f = by_id[fid]
        cause, route = cause_of(p.pathway, roads, p.hazard_type)
        c.append(
            _cite(
                f"isolated_{i}_name",
                "Isolated facility (already cut off now)",
                _name(f),
                None,
                "impact",
            )
        )
        c.append(_cite(f"isolated_{i}_cause", "Cause", cause, None, "impact"))
        if route:
            c.append(
                _cite(f"isolated_{i}_route", "First cut on its usual route", route, None, "impact")
            )
        t = f.properties.attributes.get("hospital_travel_time_s")
        if t is not None:
            label = (
                "Next hospital by road"
                if f.properties.infra_type == "hospital"
                else "Nearest hospital by road"
            )
            c.append(
                _cite(f"isolated_{i}_next_hospital_min", label, round(t / 60), "min", "exposure")
            )

    # Expected within the forecast horizon (v1.3 change, pending Dev A): isolated on the expected
    # hazard (the next 24 h, a perfect-forecast replay) but not now. The hours are the time until
    # it is first isolated on the observed hazard at a later step (the horizon when the expected
    # isolation only comes from combining peaks that never coincide).
    expected: dict[str, object] = {}
    for r in impact.get_results(timestep, horizon_h=FORECAST_HORIZON_H).features:
        p = r.properties
        if (
            p.status == "isolated"
            and p.infra_id in in_block
            and p.infra_id not in isolated
            and p.infra_id not in expected
        ):
            expected[p.infra_id] = p
    hours = hours_until_isolated(set(expected), timestep)
    c.append(
        _cite(
            "expected_isolated_count",
            "Facilities expected to be cut off within 24 h (not yet)",
            len(expected),
            None,
            "impact",
        )
    )
    ordered = sorted(expected.items(), key=lambda kv: _name(by_id[kv[0]]))
    for j, (fid, p) in enumerate(ordered, 1):
        cause, route = cause_of(p.pathway, roads, p.hazard_type)
        c.append(
            _cite(
                f"expected_{j}_name",
                "Expected to be cut off (not yet)",
                _name(by_id[fid]),
                None,
                "impact",
            )
        )
        c.append(_cite(f"expected_{j}_cause", "Expected cause", cause, None, "impact"))
        if route:
            c.append(
                _cite(f"expected_{j}_route", "First cut on its usual route", route, None, "impact")
            )
        c.append(
            _cite(f"expected_{j}_hours", "Expected to be cut off within", hours[fid], "h", "impact")
        )

    # Cut road length inside the block.
    cut_m = 0.0
    if cut_roads:
        lines = gpd.GeoSeries(
            [shape(roads[r].geometry.model_dump()) for r in sorted(cut_roads)], crs="EPSG:4326"
        ).to_crs(METRIC_CRS)
        cut_m = float(
            shapely.length(shapely.intersection(lines.to_numpy(), blocks.metric.iloc[b])).sum()
        )
    c.append(_cite("cut_road_km", "Cut road length", round(cut_m / 1000, 1), "km", "impact"))
    c.append(_cite("cut_substation_count", "Cut substations", len(cut_subs), None, "impact"))

    # Stand-in shelters (buildings that could shelter people, not designated shelters).
    stand_ins = [
        f
        for f in _in_block([f for f in points if f.properties.infra_type == "shelter"], block_geom)
        if str(f.properties.attributes.get("shelter_kind", "")).endswith("_proxy")
    ]
    c.append(
        _cite(
            "standin_count", "Stand-in shelters (not designated)", len(stand_ins), None, "exposure"
        )
    )
    named = sorted({f.properties.name for f in stand_ins if f.properties.name})[:MAX_STAND_INS]
    c.append(
        _cite(
            "standin_named_count",
            "Stand-in shelters named below",
            len(named),
            None,
            "exposure",
        )
    )
    for i, n in enumerate(named, 1):
        c.append(_cite(f"standin_{i}_name", "Stand-in shelter", n, None, "exposure"))

    return Facts(block_id, name, timestep, c)


def hours_until_isolated(infra_ids: set[str], timestep: str) -> dict[str, int]:
    """Per facility: hours from `timestep` to the first later step (within the horizon) where it
    is isolated on the observed hazard; the horizon itself if that never happens."""
    out = {fid: FORECAST_HORIZON_H for fid in infra_ids}
    pending = set(infra_ids)
    for ts in window(timestep, FORECAST_HORIZON_H)[1:]:
        if not pending:
            break
        hit = pending & impact.isolated_ids(ts)
        for fid in hit:
            out[fid] = hours_to_landfall(timestep) - hours_to_landfall(ts)
        pending -= hit
    return out


def _name(f: InfraFeature) -> str:
    """The facility's name; if it has none, render.UNNAMED's label for its facility_level or
    shelter_kind (render.py writes that in the text's language)."""
    if f.properties.name:
        return f.properties.name
    attrs = f.properties.attributes
    kind = str(attrs.get("facility_level") or attrs.get("shelter_kind") or f.properties.infra_type)
    return UNNAMED[kind][0] if kind in UNNAMED else f"Unnamed {kind.replace('_', ' ')}"
