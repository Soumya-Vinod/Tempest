"""Risk engine: one RiskScore per block per timestep (contracts.md §4.4).

    score = hazard x (W_EXPOSURE * exposure + W_VULNERABILITY * vulnerability)

compute_scores is pure: hazards and impact results are passed in (the route takes both from the
impact service's cache). The static part (vulnerability, block membership, road lengths) is built
once by build_context. Weights and fixed scales live in weights.py.
"""

from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely
from shapely.geometry import shape

from app.exposure.ingest import METRIC_CRS
from app.impact.engine import network_for
from app.impact.network import ImpactNetwork, nearest_sources
from app.risk import weights as W
from app.risk.blocks import BLOCK_SOURCE, Blocks
from app.schemas import (
    HazardLayerCollection,
    ImpactResultCollection,
    InfraFeatureCollection,
    RiskBreakdown,
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
    hospital_sources: int = 0  # hospitals used as access sources (snapped, not too far)
    # Per block: hospitals, health centres and shelters that could be isolated (baseline
    # reachable from the main component and not snap_too_far); the isolated share's divisor.
    eligible_facilities: np.ndarray | None = None
    inhabited_area_m2: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.inhabited_area_m2 = self.blocks.inhabited_metric.area.to_numpy()


def _hospital_times(net: ImpactNetwork, sources: dict[str, Any]) -> dict[Any, float]:
    """Seconds from every reached node to its nearest hospital (multi-source Dijkstra)."""
    return {n: found[0][0] for n, found in nearest_sources(net, sources).items() if found}


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

    # Hospital access: nearest general hospital (facility_level "hospital", Kolkata's
    # included, minus nursing homes and specialist clinics: weights.is_access_hospital).
    hospitals = [
        f
        for f in infra.features
        if W.is_access_source(f.properties.infra_type, f.properties.attributes, f.properties.name)
    ]
    snaps = net.snap_many([tuple(f.geometry.coordinates[:2]) for f in hospitals])
    sources = {f.id: s.node for f, s in zip(hospitals, snaps, strict=True) if not s.too_far}
    times = _hospital_times(net, sources)
    node_block = np.full(len(net.node_ids), -1)
    for b, geom in enumerate(blocks.geometry):
        inside = shapely.contains_xy(geom, net.node_xy[:, 0], net.node_xy[:, 1])
        node_block[inside & (node_block < 0)] = b

    eligible = np.zeros(len(blocks.codes), dtype=int)
    for f in infra.features:
        if f.properties.infra_type not in ("hospital", "shelter"):
            continue
        if (b := point_block.get(f.id)) is None:
            continue
        snap = net.snap(f.id, *f.geometry.coordinates[:2])
        if not snap.too_far and snap.node in net.main:
            eligible[b] += 1

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
            "population_density": density_part(blocks.population[b], blocks.inhabited_area_km2[b]),
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
    return RiskContext(blocks, point_block, road_lengths, total, static, len(sources), eligible)


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
    reach: str = "direct"  # direct (hazard) or cut_off (exposure), see weights.py


def _hazard_parts(ctx: RiskContext, hazards: dict[str, HazardLayerCollection]) -> list[dict]:
    """Surge share, wind part and flood severity per block, weighted by inhabited land."""
    n = len(ctx.blocks.codes)
    out = [{"surge": 0.0, "wind": 0.0, "flood": 0.0} for _ in range(n)]
    land = ctx.blocks.inhabited_metric.to_numpy()
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
                if ctx.inhabited_area_m2[b] > 0:
                    out[b]["surge"] = clip01(areas[b] / ctx.inhabited_area_m2[b])
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
            if ctx.inhabited_area_m2[b] > 0:
                out[b][h] = clip01(sums[b] / ctx.inhabited_area_m2[b])
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
                "isolated_facilities": (
                    clip01(len(isolated[b]) / ctx.eligible_facilities[b])
                    if ctx.eligible_facilities[b] > 0
                    else 0.0
                ),
                "cut_roads": clip01(share),
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
        reach = "direct" if hazard >= exposure else "cut_off"
        score = max(hazard, exposure) * (
            W.W_EXPOSURE * exposure + W.W_VULNERABILITY * vulnerability
        )
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
                reach=reach,
            )
        )
    return out


def to_collection(
    risks: list[BlockRisk], ctx: RiskContext, timestep: str, horizon_h: int = 0
) -> RiskScoreCollection:
    """Contract RiskScores from evaluated blocks, in block order."""
    features = []
    for b, r in enumerate(risks):
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
                        "horizon_h": horizon_h,
                    },
                }
            )
        )
    return RiskScoreCollection(features=features)


def surge_population(population: float, hazard_parts: dict[str, float]) -> int:
    """People in the surge zone (estimate): population x the share of inhabited land with surge
    >= W.SURGE_LAND_THRESHOLD_M, i.e. the population spread evenly over inhabited land."""
    return round(float(population) * hazard_parts["surge"])


def to_breakdown(
    risks: list[BlockRisk], ctx: RiskContext, timestep: str, horizon_h: int = 0
) -> RiskBreakdown:
    """Every part per block, plus population and hospital travel time (added in v1.1)."""

    def rounded(parts: dict[str, float]) -> dict[str, float]:
        return {k: round(v, DECIMALS) for k, v in parts.items()}

    blocks = []
    for b, r in enumerate(risks):
        minutes = ctx.static[b].hospital_minutes
        blocks.append(
            {
                "block_id": r.code,
                "block_name": r.name,
                "population_2011": int(ctx.blocks.population[b]),
                # v1.3 change, pending Dev A: an estimate, population spread evenly over the
                # block's inhabited land, times the (unrounded) share with surge >= 0.3 m.
                "surge_population": surge_population(ctx.blocks.population[b], r.hazard_parts),
                "hospital_travel_min": (
                    round(minutes, 1) if minutes is not None and np.isfinite(minutes) else None
                ),
                "reach": r.reach,
                "hazard": rounded(r.hazard_parts),
                "exposure": rounded(r.exposure_parts),
                "vulnerability": rounded(r.vulnerability_parts),
            }
        )
    return RiskBreakdown.model_validate(
        {
            "timestep": timestep,
            "blocks": blocks,
            "horizon_h": horizon_h,
            "surge_population_total": sum(b["surge_population"] for b in blocks),
        }
    )


def compute_scores(
    hazards: dict[str, HazardLayerCollection],
    impacts: ImpactResultCollection,
    ctx: RiskContext,
    timestep: str,
) -> RiskScoreCollection:
    """One contract RiskScore per block at `timestep`, in block order."""
    return to_collection(evaluate(hazards, impacts, ctx), ctx, timestep)
