"""Impact engine: hazards + infrastructure + road graph -> ImpactResults (contracts.md §4.3).

compute_impacts is pure: hazards are passed in (the route gets them from Dev A's
get_hazard_layer; tests pass synthetic ones from synthetic.py). Rules live in thresholds.py.

- Roads: surge on each road edge (cut / at_risk); a road takes its worst edge.
- Flood is static susceptibility: at_risk only, never cut or isolated (FLOOD_CUTS_ROADS).
- Ferries: wind along the ferry (cut / at_risk).
- Substations: surge cut, flood / wind at_risk, at the location. Power lines: wind at_risk.
- Hospitals and shelters: at_risk by hazard at the location; isolated when the combined cut
  edges of all hazards disconnect them from the anchor's component although they were in it at
  baseline. The isolated row is attributed to the hazard that cut the first cut edge on the
  facility's baseline shortest path; features unreachable at baseline are never isolated.
"""

from typing import Any, get_args
from weakref import WeakKeyDictionary

import networkx as nx
import numpy as np
import shapely
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.impact import thresholds as T
from app.impact.network import ImpactNetwork, build_network
from app.schemas import (
    HazardLayerCollection,
    HazardType,
    ImpactResult,
    ImpactResultCollection,
    ImpactResultProperties,
    InfraFeature,
    InfraFeatureCollection,
    PathwayStep,
)

HAZARD_TYPES: tuple[str, ...] = get_args(HazardType)
OK, AT_RISK, CUT, ISOLATED = 0, 1, 2, 3
STATUS = {OK: "ok", AT_RISK: "at_risk", CUT: "cut", ISOLATED: "isolated"}
FACILITY_TYPES = ("hospital", "shelter")
FIRST_CUT_LABEL = "First cut on usual route"

_networks: WeakKeyDictionary[nx.MultiDiGraph, dict[tuple[float, float], ImpactNetwork]]
_networks = WeakKeyDictionary()


def network_for(graph: nx.MultiDiGraph, anchor: tuple[float, float]) -> ImpactNetwork:
    """The graph's ImpactNetwork, built on first use and cached for the graph's lifetime."""
    per_graph = _networks.setdefault(graph, {})
    if anchor not in per_graph:
        per_graph[anchor] = build_network(graph, anchor)
    return per_graph[anchor]


# --- Hazard sampling ----------------------------------------------------------------------------


def hazard_metric(hazard_type: str) -> str:
    """Surge and wind thresholds use the physical value (m, m/s); flood uses severity."""
    return "severity" if hazard_type == "flood" else "value"


def _index(fc: HazardLayerCollection | None, hazard_type: str):
    if fc is None or not fc.features:
        return None
    geoms = [shape(f.geometry.model_dump()) for f in fc.features]
    metric = hazard_metric(hazard_type)
    values = np.array([getattr(f.properties, metric) for f in fc.features], dtype=float)
    return shapely.STRtree(geoms), values


def _sample(index, targets: list[BaseGeometry]) -> np.ndarray:
    """Maximum hazard metric over the polygons each target touches (0 where none)."""
    out = np.zeros(len(targets))
    if index is None or not targets:
        return out
    tree, values = index
    target_idx, poly_idx = tree.query(targets, predicate="intersects")
    np.maximum.at(out, target_idx, values[poly_idx])
    return out


# --- Rules --------------------------------------------------------------------------------------


def _grade(v: np.ndarray, at_risk: float | None, cut: float | None) -> np.ndarray:
    status = np.zeros(len(v), dtype=np.int8)
    if at_risk is not None:
        status[v >= at_risk] = AT_RISK
    if cut is not None:
        status[v >= cut] = CUT
    return status


Rule = tuple[float | None, float | None]  # (at_risk, cut) thresholds; None = never


def road_rules() -> dict[str, Rule]:
    """Read at call time, so FLOOD_CUTS_ROADS can be switched (tests, a future flood layer)."""
    flood = (
        (T.ROAD_AT_RISK_FLOOD_SEVERITY, T.ROAD_CUT_FLOOD_SEVERITY)
        if T.FLOOD_CUTS_ROADS
        else (T.FLOOD_AT_RISK_SEVERITY, None)
    )
    return {"surge": (T.ROAD_AT_RISK_SURGE_M, T.ROAD_CUT_SURGE_M), "flood": flood}


FERRY_RULES: dict[str, Rule] = {"wind": (T.FERRY_AT_RISK_WIND_MS, T.FERRY_CUT_WIND_MS)}
_FACILITY: dict[str, Rule] = {
    "surge": (T.FACILITY_AT_RISK_SURGE_M, None),
    "flood": (T.FACILITY_AT_RISK_FLOOD_SEVERITY, None),
    "wind": (T.FACILITY_AT_RISK_WIND_MS, None),
}
POINT_RULES: dict[str, dict[str, Rule]] = {
    "substation": {
        "surge": (None, T.SUBSTATION_CUT_SURGE_M),
        "flood": (T.FLOOD_AT_RISK_SEVERITY, None),
        "wind": (T.SUBSTATION_AT_RISK_WIND_MS, None),
    },
    "power_line": {"wind": (T.POWER_LINE_AT_RISK_WIND_MS, None)},
    "hospital": _FACILITY,
    "shelter": _FACILITY,
}


def _link_status(net: ImpactNetwork, hazard_type: str, v: np.ndarray) -> np.ndarray:
    status = np.zeros(len(v), dtype=np.int8)
    roads = ~net.link_ferry & ~net.link_connector
    rules = road_rules()
    if hazard_type in rules:
        graded = _grade(v, *rules[hazard_type])
        status[roads] = graded[roads]
    if hazard_type in FERRY_RULES:
        graded = _grade(v, *FERRY_RULES[hazard_type])
        status[net.link_ferry] = graded[net.link_ferry]
    return status


def _road_rule_on_geometry(hazard_type: str, is_ferry: bool, v: float) -> int:
    """Fallback for a road feature with no edge in the graph: its own geometry."""
    rules = FERRY_RULES if is_ferry else road_rules()
    if hazard_type not in rules:
        return OK
    return int(_grade(np.array([v]), *rules[hazard_type])[0])


# --- Labels -------------------------------------------------------------------------------------


def hazard_label(hazard_type: str, v: float) -> str:
    if hazard_type == "wind":
        return f"Wind {v:.0f} m/s"
    if hazard_type == "surge":
        return f"Surge {v:.2f} m"
    return f"Flood severity {v:.2f}"


def feature_label(f: InfraFeature) -> str:
    """The feature's name, or "Unnamed <kind>" (ferries are "ferry route", as on the map)."""
    if f.properties.name:
        return f.properties.name
    if f.properties.attributes.get("ferry") is True:
        return "Unnamed ferry route"
    return f"Unnamed {f.properties.infra_type.replace('_', ' ')}"


def _hazard_step(hazard_type: str, v: float) -> PathwayStep:
    return PathwayStep(
        id=f"hazard:{hazard_type}", label=hazard_label(hazard_type, v), type="hazard"
    )


def _infra_step(f: InfraFeature) -> PathwayStep:
    return PathwayStep(id=f.id, label=feature_label(f), type="infra")


def _first_cut_step(way_id: int, roads_by_way: dict[int, InfraFeature]) -> PathwayStep:
    road = roads_by_way.get(way_id)
    if road is None:  # an edge kept across the clip boundary whose road feature is empty
        return PathwayStep(
            id=f"road-way-{way_id}",
            label=f"{FIRST_CUT_LABEL}: unmapped road segment (OSM way {way_id})",
            type="infra",
        )
    return PathwayStep(id=road.id, label=f"{FIRST_CUT_LABEL}: {feature_label(road)}", type="infra")


# --- Engine -------------------------------------------------------------------------------------


def _way_id(f: InfraFeature) -> int | None:
    osm_id = f.properties.osm_id or ""
    return int(osm_id.split("/")[1]) if osm_id.startswith("way/") else None


def _reachable(net: ImpactNetwork, cut: np.ndarray) -> set[Any]:
    seen = {net.anchor}
    stack = [net.anchor]
    while stack:
        n = stack.pop()
        for m, link in net.adjacency[n]:
            if m not in seen and not cut[link]:
                seen.add(m)
                stack.append(m)
    return seen


def _first_cut(net: ImpactNetwork, node: Any, cut: np.ndarray) -> int | None:
    """The first hop on the node's baseline path to the anchor whose links are all cut."""
    for a, b in net.path_to_anchor(node):
        links = net.pair_links[(a, b) if a <= b else (b, a)]
        if all(cut[i] for i in links):
            return min(links, key=lambda i: net.link_tt[i])
    return None


def compute_impacts(
    hazards: dict[str, HazardLayerCollection],
    infra: InfraFeatureCollection,
    graph: nx.MultiDiGraph,
    timestep: str,
    *,
    anchor: tuple[float, float] = T.ANCHOR_LONLAT,
    horizon_h: int = 0,
) -> ImpactResultCollection:
    """One ImpactResult per (infra feature, hazard type) at `timestep`, in infra order.
    `horizon_h` only labels the results: the caller passes the expected hazard for 24."""
    net = network_for(graph, anchor)
    features = infra.features
    geoms = [shape(f.geometry.model_dump()) for f in features]
    indexes = {h: _index(hazards.get(h), h) for h in HAZARD_TYPES}

    link_v = {h: _sample(indexes[h], net.link_geom) for h in HAZARD_TYPES}
    link_status = {h: _link_status(net, h, link_v[h]) for h in HAZARD_TYPES}
    feat_v = {h: _sample(indexes[h], geoms) for h in HAZARD_TYPES}

    # Isolation from the combined cuts of all hazards.
    cut = np.zeros(len(net.link_u), dtype=bool)
    isolating = T.isolation_hazards()  # flood excluded: static susceptibility
    for h in isolating:
        cut |= link_status[h] == CUT
    reach = _reachable(net, cut) if cut.any() else None
    roads_by_way = {
        w: f for f in features if f.properties.infra_type == "road" if (w := _way_id(f))
    }

    results = []
    for i, f in enumerate(features):
        infra_type = f.properties.infra_type
        isolated_by: tuple[str, int] | None = None  # (hazard, cut link)
        if infra_type in FACILITY_TYPES and reach is not None:
            p = f.geometry.coordinates
            snap = net.snap(f.id, p[0], p[1])
            if not snap.too_far and snap.node in net.main and snap.node not in reach:
                link = _first_cut(net, snap.node, cut)
                if link is not None:
                    h = next(h for h in isolating if link_status[h][link] == CUT)
                    isolated_by = (h, link)

        for h in HAZARD_TYPES:
            status, pathway = OK, []
            if isolated_by and isolated_by[0] == h:
                link = isolated_by[1]
                status = ISOLATED
                pathway = [
                    _hazard_step(h, link_v[h][link]),
                    _first_cut_step(int(net.link_osmid[link]), roads_by_way),
                    _infra_step(f),
                ]
            else:
                v = feat_v[h][i]
                if infra_type == "road":
                    links = net.way_links.get(_way_id(f) or -1)
                    if links is not None and len(links):
                        status = int(link_status[h][links].max())
                        v = float(link_v[h][links].max())
                    else:
                        status = _road_rule_on_geometry(
                            h, f.properties.attributes.get("ferry") is True, v
                        )
                elif h in POINT_RULES.get(infra_type, {}):
                    status = int(_grade(np.array([v]), *POINT_RULES[infra_type][h])[0])
                if status != OK:
                    pathway = [_hazard_step(h, v), _infra_step(f)]
            results.append(
                ImpactResult(
                    id=f"{f.id}__{h}__{timestep}",
                    geometry=f.geometry,
                    properties=ImpactResultProperties(
                        id=f"{f.id}__{h}__{timestep}",
                        infra_id=f.id,
                        hazard_type=h,
                        status=STATUS[status],
                        timestep=timestep,
                        pathway=pathway,
                        horizon_h=horizon_h,
                    ),
                )
            )
    return ImpactResultCollection(features=results)
