"""Risk engine: one RiskScore per block per timestep (contracts.md §4.4).

    score = hazard x (W_EXPOSURE * exposure + W_VULNERABILITY * vulnerability)

compute_scores is pure: hazards and impact results are passed in (the route takes both from the
impact service's cache). The static part (vulnerability, block membership, road lengths) is built
once by build_context. Weights and fixed scales live in weights.py.
"""

import heapq
from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely
from shapely.geometry import shape

from app.exposure.ingest import METRIC_CRS
from app.impact.engine import network_for
from app.impact.network import ImpactNetwork
from app.risk import weights as W
from app.risk.blocks import BLOCK_SOURCE, Blocks
from app.schemas import (
    HazardLayerCollection,
    ImpactResultCollection,
    InfraFeatureCollection,
    RiskScore,
    RiskScoreCollection,
)

DECIMALS = 4


# --- Part normalisation (fixed scales) ----------------------------------------------------------


def clip01(v: float) -> float:
    return float(min(1.0, max(0.0, v)))


def wind_part(speed_ms: float) -> float:
    return clip01((speed_ms - W.WIND_FLOOR_MS) / (W.WIND_CEILING_MS - W.WIND_FLOOR_MS))


def density_part(population: float, land_km2: float) -> float:
    return clip01(population / land_km2 / W.DENSITY_SCALE_PER_KM2) if land_km2 > 0 else 1.0


def hospital_access_part(median_s: float) -> float:
    return clip01(median_s / W.HOSPITAL_ACCESS_SCALE_S)  # inf (unreachable) -> 1


def mapped_shelters_part(shelters: int, population: float) -> float:
    per_10k = shelters / population * 10_000 if population > 0 else 0.0
    return 1.0 - clip01(per_10k / W.MAPPED_SHELTERS_PER_10K_TARGET)


# --- Static context -----------------------------------------------------------------------------


@dataclass
class BlockStatic:
    vulnerability_parts: dict[str, float]
    vulnerability: float
    hospital_minutes: float | None  # median over the block's nodes; inf if none reaches one
    shelters: int
    graph_nodes: int


@dataclass
class RiskContext:
    blocks: Blocks
    point_block: dict[str, int]  # infra id -> block index (points inside a block)
    road_lengths: dict[str, dict[int, float]]  # road id -> {block index: metres inside}
    total_road_m: np.ndarray
    static: list[BlockStatic]
    land_area_m2: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.land_area_m2 = self.blocks.land_metric.area.to_numpy()


def _hospital_times(net: ImpactNetwork, sources: list[Any]) -> dict[Any, float]:
    """Multi-source Dijkstra (seconds) from every hospital node over the undirected links."""
    dist: dict[Any, float] = {}
    heap = [(0.0, i, n) for i, n in enumerate(dict.fromkeys(sources))]
    heapq.heapify(heap)
    tie = len(heap)
    while heap:
        d, _, n = heapq.heappop(heap)
        if n in dist:
            continue
        dist[n] = d
        for m, link in net.adjacency[n]:
            if m not in dist:
                tie += 1
                heapq.heappush(heap, (d + float(net.link_tt[link]), tie, m))
    return dist


def build_context(
    blocks: Blocks,
    infra: InfraFeatureCollection,
    graph: nx.MultiDiGraph,
    anchor: tuple[float, float],
) -> RiskContext:
    """Everything that doesn't change with the timestep. Build once and reuse."""
    net = network_for(graph, anchor)
    tree = shapely.STRtree(blocks.metric.to_numpy())

    # Points (substations, hospitals, shelters) -> block.
    points = [f for f in infra.features if f.geometry.type == "Point"]
    pts = gpd.GeoSeries([shape(f.geometry.model_dump()) for f in points], crs="EPSG:4326")
    pts_m = pts.to_crs(METRIC_CRS).to_numpy()
    point_block: dict[str, int] = {}
    if len(pts_m):
        p_idx, b_idx = tree.query(pts_m, predicate="within")
        for p, b in zip(p_idx, b_idx, strict=True):
            point_block.setdefault(points[p].id, int(b))

    # Road length inside each block (metres).
    roads = [f for f in infra.features if f.properties.infra_type == "road"]
    road_lengths: dict[str, dict[int, float]] = {}
    total = np.zeros(len(blocks.codes))
    if roads:
        lines = gpd.GeoSeries([shape(f.geometry.model_dump()) for f in roads], crs="EPSG:4326")
        lines_m = lines.to_crs(METRIC_CRS).to_numpy()
        r_idx, b_idx = tree.query(lines_m, predicate="intersects")
        blocks_m = blocks.metric.to_numpy()
        lengths = shapely.length(shapely.intersection(lines_m[r_idx], blocks_m[b_idx]))
        for r, b, length in zip(r_idx, b_idx, lengths, strict=True):
            if length > 0:
                road_lengths.setdefault(roads[r].id, {})[int(b)] = float(length)
                total[b] += length

    # Hospital access: nearest hospital (facility_level "hospital", Kolkata's included).
    hospitals = [
        f
        for f in infra.features
        if f.properties.infra_type == "hospital"
        and f.properties.attributes.get("facility_level") == "hospital"
    ]
    snaps = net.snap_many([tuple(f.geometry.coordinates[:2]) for f in hospitals])
    times = _hospital_times(net, [s.node for s in snaps if not s.too_far])
    node_block = np.full(len(net.node_ids), -1)
    for b, geom in enumerate(blocks.geometry):
        inside = shapely.contains_xy(geom, net.node_xy[:, 0], net.node_xy[:, 1])
        node_block[inside & (node_block < 0)] = b

    shelters = np.zeros(len(blocks.codes), dtype=int)
    for f in infra.features:
        if f.properties.infra_type == "shelter" and (b := point_block.get(f.id)) is not None:
            shelters[b] += 1

    static = []
    for b in range(len(blocks.codes)):
        nodes = [net.node_ids[i] for i in np.flatnonzero(node_block == b)]
        if nodes:
            median_s = float(np.median([times.get(n, np.inf) for n in nodes]))
        else:
            median_s = np.inf
        parts = {
            "population_density": density_part(blocks.population[b], blocks.land_area_km2[b]),
            "hospital_access": hospital_access_part(median_s),
            "low_literacy": 0.0,  # off until a primary source is available (weights.py)
            "mapped_shelters": mapped_shelters_part(int(shelters[b]), blocks.population[b]),
        }
        static.append(
            BlockStatic(
                vulnerability_parts=parts,
                vulnerability=sum(W.VULNERABILITY_PARTS[k] * v for k, v in parts.items()),
                hospital_minutes=(median_s / 60 if nodes else None),
                shelters=int(shelters[b]),
                graph_nodes=len(nodes),
            )
        )
    return RiskContext(blocks, point_block, road_lengths, total, static)


# --- Per timestep -------------------------------------------------------------------------------


@dataclass
class BlockRisk:
    code: str
    name: str
    hazard_parts: dict[str, float]  # surge, wind, flood
    exposure_parts: dict[str, float]
    vulnerability_parts: dict[str, float]
    hazard: float
    exposure: float
    vulnerability: float
    score: float
    top_driver: str | None


def _hazard_parts(ctx: RiskContext, hazards: dict[str, HazardLayerCollection]) -> list[dict]:
    """Land-weighted surge share, wind part and flood severity per block."""
    n = len(ctx.blocks.codes)
    out = [{"surge": 0.0, "wind": 0.0, "flood": 0.0} for _ in range(n)]
    land = ctx.blocks.land_metric.to_numpy()
    for h, fc in hazards.items():
        if h not in ("surge", "wind", "flood") or not fc.features:
            continue
        polys = gpd.GeoSeries(
            [shape(f.geometry.model_dump()) for f in fc.features], crs="EPSG:4326"
        ).to_crs(METRIC_CRS)
        if h == "surge":
            keep = [f.properties.value >= W.SURGE_LAND_THRESHOLD_M for f in fc.features]
            polys = polys[keep]
            if polys.empty:
                continue
            flooded = shapely.union_all(polys.to_numpy())
            areas = shapely.area(shapely.intersection(land, flooded))
            for b in range(n):
                if ctx.land_area_m2[b] > 0:
                    out[b]["surge"] = clip01(areas[b] / ctx.land_area_m2[b])
            continue
        if h == "wind":
            weights = np.array([wind_part(f.properties.value) for f in fc.features])
        else:
            weights = np.array([f.properties.severity for f in fc.features])
        tree = shapely.STRtree(polys.to_numpy())
        b_idx, p_idx = tree.query(land, predicate="intersects")
        areas = shapely.area(shapely.intersection(land[b_idx], polys.to_numpy()[p_idx]))
        sums = np.zeros(n)
        np.add.at(sums, b_idx, areas * weights[p_idx])
        for b in range(n):
            if ctx.land_area_m2[b] > 0:
                out[b][h] = clip01(sums[b] / ctx.land_area_m2[b])
    return out


def _exposure_parts(ctx: RiskContext, impacts: ImpactResultCollection) -> list[dict]:
    n = len(ctx.blocks.codes)
    isolated = [set() for _ in range(n)]
    cut_subs = [set() for _ in range(n)]
    cut_roads: set[str] = set()
    for f in impacts.features:
        p = f.properties
        if p.status == "isolated" and (b := ctx.point_block.get(p.infra_id)) is not None:
            isolated[b].add(p.infra_id)
        elif p.status == "cut":
            if p.infra_id.startswith("road-"):
                cut_roads.add(p.infra_id)
            elif (
                p.infra_id.startswith("substation-")
                and (b := ctx.point_block.get(p.infra_id)) is not None
            ):
                cut_subs[b].add(p.infra_id)
    cut_m = np.zeros(n)
    for road in cut_roads:
        for b, length in ctx.road_lengths.get(road, {}).items():
            cut_m[b] += length
    out = []
    for b in range(n):
        share = cut_m[b] / ctx.total_road_m[b] if ctx.total_road_m[b] > 0 else 0.0
        out.append(
            {
                "isolated_facilities": clip01(len(isolated[b]) / W.ISOLATED_FACILITIES_CAP),
                "cut_roads": clip01(share / W.CUT_ROAD_SHARE_CAP),
                "cut_substations": clip01(len(cut_subs[b]) / W.CUT_SUBSTATIONS_CAP),
            }
        )
    return out


def _top_driver(hz: dict, ex: dict, vu: dict, score: float) -> str | None:
    if score <= 0:
        return None
    contributions = {k: W.W_EXPOSURE * W.EXPOSURE_PARTS[k] * v for k, v in ex.items()}
    contributions |= {
        k: W.W_VULNERABILITY * W.VULNERABILITY_PARTS[k] * v
        for k, v in vu.items()
        if W.VULNERABILITY_PARTS[k] > 0
    }
    best = max(contributions, key=lambda k: contributions[k])  # first wins ties (dict order)
    if contributions[best] > 0:
        return best
    hazard = {"surge": hz["surge"], "wind": hz["wind"], "flood": W.FLOOD_WEIGHT * hz["flood"]}
    return max(hazard, key=lambda k: hazard[k])


def evaluate(
    hazards: dict[str, HazardLayerCollection],
    impacts: ImpactResultCollection,
    ctx: RiskContext,
) -> list[BlockRisk]:
    """Every part, component and score per block (for the route, reports and tests)."""
    hz_all = _hazard_parts(ctx, hazards)
    ex_all = _exposure_parts(ctx, impacts)
    out = []
    for b, (hz, ex) in enumerate(zip(hz_all, ex_all, strict=True)):
        static = ctx.static[b]
        hazard = clip01(max(hz["surge"], hz["wind"]) + W.FLOOD_WEIGHT * hz["flood"])
        exposure = sum(W.EXPOSURE_PARTS[k] * v for k, v in ex.items())
        vulnerability = static.vulnerability
        score = hazard * (W.W_EXPOSURE * exposure + W.W_VULNERABILITY * vulnerability)
        out.append(
            BlockRisk(
                code=ctx.blocks.codes[b],
                name=ctx.blocks.names[b],
                hazard_parts=hz,
                exposure_parts=ex,
                vulnerability_parts=static.vulnerability_parts,
                hazard=hazard,
                exposure=exposure,
                vulnerability=vulnerability,
                score=score,
                top_driver=_top_driver(hz, ex, static.vulnerability_parts, score),
            )
        )
    return out


def compute_scores(
    hazards: dict[str, HazardLayerCollection],
    impacts: ImpactResultCollection,
    ctx: RiskContext,
    timestep: str,
) -> RiskScoreCollection:
    """One contract RiskScore per block at `timestep`, in block order."""
    features = []
    for b, r in enumerate(evaluate(hazards, impacts, ctx)):
        rid = f"{r.code}__{timestep}"
        features.append(
            RiskScore.model_validate(
                {
                    "type": "Feature",
                    "id": rid,
                    "geometry": ctx.blocks.display[b],
                    "properties": {
                        "id": rid,
                        "block_id": r.code,
                        "block_source": BLOCK_SOURCE,
                        "block_name": r.name,
                        "timestep": timestep,
                        "score": round(r.score, DECIMALS),
                        "components": {
                            "hazard": round(r.hazard, DECIMALS),
                            "exposure": round(r.exposure, DECIMALS),
                            "vulnerability": round(r.vulnerability, DECIMALS),
                        },
                        "top_driver": r.top_driver,
                    },
                }
            )
        )
    return RiskScoreCollection(features=features)
