"""SYNTHETIC HAZARDS FOR DEVELOPMENT ONLY. NOT AMPHAN DATA.

Made-up but contract-valid HazardLayerCollections so the impact engine can be developed and
tested before Dev A's get_hazard_layer exists. Every feature id starts with "synthetic-"
(HazardLayerProperties has no field for a flag). Never write these to api/data/demo/, never
show them as real, and remove the ?synthetic=true route parameter once real hazards exist.

- Surge: a coastal band whose landward edge moves north and whose depth grows towards landfall.
- Wind: a vortex moving north to the landfall point, strengthening over time.
- Flood: seeded random patches; static across timesteps, as the contract says flood is (§4.1).
"""

from functools import lru_cache

import numpy as np

from app.schemas import REPLAY_TIMESTEPS, HazardLayerCollection

AOI = (88.0, 21.5, 89.1, 22.7)
CELL_DEG = 0.05
LANDFALL_LONLAT = (88.75, 21.75)  # made up: roughly where the synthetic vortex comes ashore
START_LONLAT = (88.40, 18.50)  # vortex centre at T-72
MAX_SURGE_M = 3.0
MAX_WIND_MS = 50.0
BASE_WIND_MS = 5.0
VORTEX_RADIUS_KM = 90.0
FLOOD_SEED = 20200520
FLOOD_PATCHES = 14


def _progress(timestep: str) -> float:
    """0 at T-72, 1 at landfall. Raises ValueError for a timestep outside the replay list."""
    return REPLAY_TIMESTEPS.index(timestep) / (len(REPLAY_TIMESTEPS) - 1)


def _cells():
    min_lon, min_lat, max_lon, max_lat = AOI
    nx_ = round((max_lon - min_lon) / CELL_DEG)
    ny_ = round((max_lat - min_lat) / CELL_DEG)
    for i in range(nx_):
        for j in range(ny_):
            x0, y0 = min_lon + i * CELL_DEG, min_lat + j * CELL_DEG
            ring = [
                [round(x0, 5), round(y0, 5)],
                [round(x0 + CELL_DEG, 5), round(y0, 5)],
                [round(x0 + CELL_DEG, 5), round(y0 + CELL_DEG, 5)],
                [round(x0, 5), round(y0 + CELL_DEG, 5)],
                [round(x0, 5), round(y0, 5)],
            ]
            yield i, j, x0 + CELL_DEG / 2, y0 + CELL_DEG / 2, ring


def _feature(hazard: str, fid: str, ring, timestep: str, value: float, unit: str, severity: float):
    return {
        "type": "Feature",
        "id": fid,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {
            "id": fid,
            "hazard_type": hazard,
            "timestep": timestep,
            "value": round(value, 3),
            "unit": unit,
            "severity": round(min(1.0, max(0.0, severity)), 3),
        },
    }


def _surge(timestep: str, p: float) -> list[dict]:
    front = AOI[1] + 0.1 + 0.5 * p  # landward edge of the band moves north
    out = []
    for i, j, _, lat, ring in _cells():
        if lat >= front:
            continue
        depth = MAX_SURGE_M * p**1.5 * (front - lat) / (front - AOI[1])
        if depth >= 0.01:
            fid = f"synthetic-surge-{i}-{j}"
            out.append(_feature("surge", fid, ring, timestep, depth, "m", depth / MAX_SURGE_M))
    return out


def _wind(timestep: str, p: float) -> list[dict]:
    cx = START_LONLAT[0] + (LANDFALL_LONLAT[0] - START_LONLAT[0]) * p
    cy = START_LONLAT[1] + (LANDFALL_LONLAT[1] - START_LONLAT[1]) * p
    vmax = 15.0 + (MAX_WIND_MS - 15.0) * p
    out = []
    for i, j, lon, lat, ring in _cells():
        dist_km = np.hypot((lon - cx) * 103.0, (lat - cy) * 110.6)
        speed = BASE_WIND_MS + (vmax - BASE_WIND_MS) * np.exp(-dist_km / VORTEX_RADIUS_KM)
        out.append(
            _feature("wind", f"synthetic-wind-{i}-{j}", ring, timestep, speed, "m/s", speed / 60)
        )
    return out


@lru_cache(maxsize=1)
def _flood_patches() -> tuple[tuple[float, float, float, float], ...]:
    rng = np.random.default_rng(FLOOD_SEED)
    return tuple(
        (
            rng.uniform(AOI[0], AOI[2]),
            rng.uniform(AOI[1], AOI[3]),
            rng.uniform(0.03, 0.10),  # radius, degrees
            rng.uniform(0.3, 1.0),  # severity
        )
        for _ in range(FLOOD_PATCHES)
    )


def _flood(timestep: str) -> list[dict]:
    out = []
    for i, j, lon, lat, ring in _cells():
        severity = max(
            (s for x, y, r, s in _flood_patches() if np.hypot(lon - x, lat - y) <= r), default=0.0
        )
        if severity > 0:
            fid = f"synthetic-flood-{i}-{j}"
            out.append(_feature("flood", fid, ring, timestep, severity, "index", severity))
    return out


def synthetic_hazards(timestep: str) -> dict[str, HazardLayerCollection]:
    """Synthetic wind, surge and flood layers for one replay timestep. DEVELOPMENT ONLY."""
    p = _progress(timestep)
    layers = {"wind": _wind(timestep, p), "surge": _surge(timestep, p), "flood": _flood(timestep)}
    return {
        h: HazardLayerCollection.model_validate({"type": "FeatureCollection", "features": fs})
        for h, fs in layers.items()
    }
