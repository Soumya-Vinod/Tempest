"""Parametric triggers per CD block (contracts.md §4.6; tiers, released amounts and the summary:
added in v1.2). The terms are in constants.py (illustrative).

Per timestep and block: each hazard's reading is the nearest-rank 90th percentile of the cells
overlapping the block's inhabited land by >= MIN_OVERLAP_KM2; each reading maps to a tier; the
block pays the higher tier's fraction of its sum insured (never the sum of both), and the
TriggerEvent reports that governing metric. Across timesteps, the released payout is the highest
tier so far: released money is never taken back.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import shapely
from shapely.geometry import shape

from app.exposure.ingest import METRIC_CRS
from app.insurance.constants import (
    MIN_OVERLAP_KM2,
    PERCENTILE,
    SUM_INSURED_PER_RESIDENT_INR,
    SURGE_TIERS_M,
    WIND_TIERS_MS,
)
from app.risk.blocks import Blocks
from app.schemas import (
    LANDFALL_TIMESTEP,
    HazardLayerCollection,
    InsuranceDistrictTotal,
    InsuranceSummary,
    InsuranceZoneSummary,
    TriggerEventCollection,
    TriggerEventProperties,
)

TIMESTEP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DECIMALS = 2  # readings are rounded before tiering, so observed >= threshold is exact
METRICS = {  # metric -> (hazard type, unit, tiers)
    "wind_speed": ("wind", "m/s", WIND_TIERS_MS),
    "surge_depth": ("surge", "m", SURGE_TIERS_M),
}


@dataclass(frozen=True)
class Tier:
    index: int  # 0 = not triggered, 1..3
    threshold: float  # the reached tier's threshold, or the first tier's when none
    fraction: float


def tier_of(value: float, tiers: tuple[tuple[float, float], ...]) -> Tier:
    reached = [(i, t, f) for i, (t, f) in enumerate(tiers, 1) if value >= t]
    if not reached:
        return Tier(0, tiers[0][0], 0.0)
    i, t, f = reached[-1]
    return Tier(i, t, f)


def reading(values: np.ndarray) -> float:
    """Nearest-rank ("lower") 90th percentile: never the lone highest of two or more cells."""
    if len(values) == 0:
        return 0.0
    return round(float(np.percentile(values, PERCENTILE, method="lower")), DECIMALS)


def block_cell_values(layer: HazardLayerCollection, blocks: Blocks) -> list[np.ndarray]:
    """Per block: the values of the cells overlapping its inhabited land by >= MIN_OVERLAP_KM2."""
    if not layer.features:
        return [np.array([]) for _ in blocks.codes]
    import geopandas as gpd

    cells = (
        gpd.GeoSeries([shape(f.geometry.model_dump()) for f in layer.features], crs="EPSG:4326")
        .to_crs(METRIC_CRS)
        .to_numpy()
    )
    values = np.array([f.properties.value for f in layer.features], dtype=float)
    tree = shapely.STRtree(cells)
    out = []
    for land in blocks.inhabited_metric:
        if land is None or land.is_empty:
            out.append(np.array([]))
            continue
        idx = tree.query(land, predicate="intersects")
        overlap_km2 = shapely.area(shapely.intersection(cells[idx], land)) / 1e6
        out.append(values[idx[overlap_km2 >= MIN_OVERLAP_KM2]])
    return out


@dataclass(frozen=True)
class ZoneReading:
    block_id: str
    name: str
    metric: str  # the governing metric
    observed: float
    tier: Tier
    sum_insured_inr: float
    wind_ms: float  # both readings, for the panel
    surge_m: float

    @property
    def payout_inr(self) -> float:
        return self.tier.fraction * self.sum_insured_inr


def governing(wind: float, surge: float) -> tuple[str, float, Tier]:
    """The metric that sets the payout: the higher tier; on a tie, the one further past (or,
    untriggered, closer to) its threshold; wind on an exact tie."""
    w = tier_of(wind, WIND_TIERS_MS)
    s = tier_of(surge, SURGE_TIERS_M)
    if w.index != s.index:
        return ("wind_speed", wind, w) if w.index > s.index else ("surge_depth", surge, s)
    if surge / s.threshold > wind / w.threshold:
        return "surge_depth", surge, s
    return "wind_speed", wind, w


def readings(hazards: dict[str, HazardLayerCollection], blocks: Blocks) -> list[ZoneReading]:
    wind = [reading(v) for v in block_cell_values(hazards["wind"], blocks)]
    surge = [reading(v) for v in block_cell_values(hazards["surge"], blocks)]
    out = []
    for i, code in enumerate(blocks.codes):
        metric, observed, tier = governing(wind[i], surge[i])
        out.append(
            ZoneReading(
                block_id=code,
                name=blocks.names[i],
                metric=metric,
                observed=observed,
                tier=tier,
                sum_insured_inr=float(blocks.population[i]) * SUM_INSURED_PER_RESIDENT_INR,
                wind_ms=wind[i],
                surge_m=surge[i],
            )
        )
    return out


@dataclass(frozen=True)
class Released:
    tier: int
    payout_inr: float


def released(series: list[list[ZoneReading]]) -> list[list[Released]]:
    """Per timestep (in order) and block: the highest tier (and payout) reached so far."""
    out: list[list[Released]] = []
    best: dict[str, ZoneReading] = {}
    for step in series:
        row = []
        for r in step:
            prev = best.get(r.block_id)
            if prev is None or r.tier.index > prev.tier.index:
                best[r.block_id] = r
            b = best[r.block_id]
            row.append(Released(b.tier.index, b.payout_inr))
        out.append(row)
    return out


def features(step: list[ZoneReading], released_step: list[Released], timestep: str) -> list[dict]:
    """The TriggerEvent features without geometry: the compact fixture form (contracts.md §7);
    collection_from() adds each block's polygon."""
    out = []
    for r, rel in zip(step, released_step, strict=True):
        _, unit, _ = METRICS[r.metric]
        props = TriggerEventProperties(
            id=f"{r.block_id}__{timestep}",
            zone_id=r.block_id,
            zone_name=r.name,
            timestep=timestep,
            metric=r.metric,
            unit=unit,
            threshold=r.tier.threshold,
            observed=r.observed,
            triggered=r.tier.index > 0,
            payout_estimate_inr=r.payout_inr,
            tier=r.tier.index,
            payout_fraction=r.tier.fraction,
            sum_insured_inr=r.sum_insured_inr,
            released_tier=rel.tier,
            released_payout_inr=rel.payout_inr,
        )
        out.append({"type": "Feature", "id": props.id, "properties": props.model_dump(mode="json")})
    return out


def hours_before_landfall(timestep: str) -> int:
    ts = datetime.strptime(timestep, TIMESTEP_FORMAT)
    landfall = datetime.strptime(LANDFALL_TIMESTEP, TIMESTEP_FORMAT)
    return round((landfall - ts).total_seconds() / 3600)


def summary(timesteps: list[str], series: list[list[ZoneReading]]) -> InsuranceSummary:
    rel = released(series)
    district = [
        InsuranceDistrictTotal(
            timestep=ts,
            released_payout_inr=sum(x.payout_inr for x in rel_t),
            triggered_zones=sum(r.tier.index > 0 for r in step),
            released_zones=sum(x.tier > 0 for x in rel_t),
        )
        for ts, step, rel_t in zip(timesteps, series, rel, strict=True)
    ]
    zones = []
    for i, first in enumerate(series[0]):
        hit = next(
            (
                (ts, step[i])
                for ts, step in zip(timesteps, series, strict=True)
                if step[i].tier.index
            ),
            None,
        )
        final = rel[-1][i]
        zones.append(
            InsuranceZoneSummary(
                zone_id=first.block_id,
                zone_name=first.name,
                first_trigger_timestep=hit[0] if hit else None,
                hours_before_landfall=hours_before_landfall(hit[0]) if hit else None,
                first_trigger_metric=hit[1].metric if hit else None,
                first_trigger_tier=hit[1].tier.index if hit else 0,
                first_trigger_payout_inr=hit[1].payout_inr if hit else 0.0,
                final_released_tier=final.tier,
                final_released_payout_inr=final.payout_inr,
                sum_insured_inr=first.sum_insured_inr,
            )
        )
    return InsuranceSummary(district=district, zones=zones)


def collection_from(features: list[dict], geometry: dict[str, dict]) -> TriggerEventCollection:
    """Add each block's display geometry to geometry-less features, by zone_id."""
    out = []
    for f in features:
        zone = f["properties"]["zone_id"]
        if zone not in geometry:
            raise ValueError(f"trigger for unknown zone {zone!r}")
        out.append({**f, "geometry": geometry[zone]})
    return TriggerEventCollection.model_validate({"type": "FeatureCollection", "features": out})
