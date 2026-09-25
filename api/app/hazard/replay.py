"""Cyclone Amphan replay timeline, parametric wind/surge physics, and hazard grid generation."""

from __future__ import annotations

import json
import math
from functools import lru_cache

from app.core.config import get_settings
from app.core.demo import DEMO_DIR
from app.hazard.models import (
    CycloneTrackPoint,
    GridCell,
    HazardLayer,
    HazardLayerCollection,
    HazardLayerProperties,
    HazardMetricResult,
    HazardType,
    Polygon,
    ReplayTimeline,
)
from app.schemas.common import (
    LANDFALL_TIMESTEP,
    LIVE,
    REPLAY_TIMESTEPS,
)

# ---------------------------------------------------------------------------
# Replay Timeline Definition (shared/contracts.md §2)
# ---------------------------------------------------------------------------
EVENT_NAME: str = "amphan"
LANDFALL_TIMESTAMP: str = LANDFALL_TIMESTEP
TIMESTEP_INTERVAL_HOURS: int = 3
TOTAL_TIMESTEPS: int = 25
REPLAY_TIMELINE_TIMESTEPS: tuple[str, ...] = REPLAY_TIMESTEPS


def validate_timestep(timestep: str) -> str:
    """Validate a timestep string against the Cyclone Amphan replay timeline.

    Validation rules (shared/contracts.md §2):
    - Accepts any of the 25 official Amphan replay ISO 8601 UTC timesteps.
    - Accepts 'live' as a reserved parameter value.
    - Rejects all other values with a clear ValueError.

    Args:
        timestep: ISO 8601 UTC string (e.g. '2020-05-20T12:00:00Z') or 'live'.

    Returns:
        The validated timestep string.

    Raises:
        ValueError: If timestep is not in the 25 replay timesteps and not 'live'.
    """
    if timestep == LIVE:
        return LIVE
    if timestep in REPLAY_TIMESTEPS:
        return timestep
    raise ValueError(
        f"Invalid timestep: {timestep!r}; must be one of the 25 Amphan replay timesteps or 'live'"
    )


def create_replay_timeline() -> ReplayTimeline:
    """Construct an immutable contract-compliant ReplayTimeline model.

    Contains:
    - event: 'amphan'
    - landfall: '2020-05-20T12:00:00Z' (official IMD crossing complete timestep)
    - timesteps: exactly 25 timesteps, 3-hour intervals, strictly ordered from T-72 to T-0.
    """
    return ReplayTimeline(
        event=EVENT_NAME,
        landfall=LANDFALL_TIMESTAMP,
        timesteps=list(REPLAY_TIMESTEPS),
    )


# ---------------------------------------------------------------------------
# 1. Official IBTrACS Cyclone Amphan Best-Track Waypoints (May 17-20, 2020)
# ---------------------------------------------------------------------------
# hazard__track.json is a generated artifact produced by api/scripts/ingest_track.py
# from the official IBTrACS dataset. The repository uses the generated fixture at runtime
# to ensure deterministic replay behavior and avoid network dependencies.
#
# (timestep, lat, lon, central_pressure_hpa, max_wind_mps, rmw_km, fwd_speed_mps, heading_deg)
_AMPHAN_WAYPOINTS: tuple[tuple[str, float, float, float, float, float, float, float], ...] = (
    ("2020-05-17T12:00:00Z", 11.9, 86.2, 978.0, 36.01, 37.0, 6.06, 15.5),
    ("2020-05-17T15:00:00Z", 12.4675, 86.3612, 972.0, 38.58, 31.5, 0.35, 341.4),
    ("2020-05-17T18:00:00Z", 12.5, 86.35, 970.0, 41.16, 27.8, 3.93, 17.09),
    ("2020-05-17T21:00:00Z", 12.865, 86.4651, 962.0, 46.3, 22.2, 3.15, 338.53),
    ("2020-05-18T00:00:00Z", 13.15, 86.35, 952.0, 51.44, 18.5, 1.7, 317.31),
    ("2020-05-18T03:00:00Z", 13.2713, 86.235, 936.0, 59.16, 18.5, 1.37, 345.18),
    ("2020-05-18T06:00:00Z", 13.4, 86.2, 930.0, 61.73, 18.5, 3.21, 6.26),
    ("2020-05-18T09:00:00Z", 13.71, 86.235, 930.0, 61.73, 18.5, 3.68, 18.16),
    ("2020-05-18T12:00:00Z", 14.05, 86.35, 926.0, 64.31, 18.5, 4.49, 12.83),
    ("2020-05-18T15:00:00Z", 14.475, 86.45, 926.0, 64.31, 18.5, 3.99, 14.45),
    ("2020-05-18T18:00:00Z", 14.85, 86.55, 920.0, 66.88, 18.5, 3.38, 17.1),
    ("2020-05-18T21:00:00Z", 15.1637, 86.65, 920.0, 66.88, 20.4, 4.1, 14.0),
    ("2020-05-19T00:00:00Z", 15.55, 86.75, 926.0, 64.31, 22.2, 4.71, 12.59),
    ("2020-05-19T03:00:00Z", 15.9963, 86.8537, 930.0, 61.73, 20.4, 5.27, 10.39),
    ("2020-05-19T06:00:00Z", 16.5, 86.95, 936.0, 59.16, 18.5, 4.64, 3.5),
    ("2020-05-19T09:00:00Z", 16.95, 86.9788, 942.0, 56.59, 18.5, 4.18, 9.64),
    ("2020-05-19T12:00:00Z", 17.35, 87.05, 946.0, 54.02, 18.5, 6.17, 6.16),
    ("2020-05-19T15:00:00Z", 17.9462, 87.1176, 948.0, 51.44, 18.5, 4.23, 10.96),
    ("2020-05-19T18:00:00Z", 18.35, 87.2, 948.0, 51.44, 18.5, 3.8, 9.43),
    ("2020-05-19T21:00:00Z", 18.7137, 87.2638, 948.0, 51.44, 18.5, 5.05, 27.08),
    ("2020-05-20T00:00:00Z", 19.15, 87.5, 952.0, 48.87, 18.5, 6.91, 15.98),
    ("2020-05-20T03:00:00Z", 19.795, 87.6963, 954.0, 48.87, 18.5, 8.15, 17.46),
    ("2020-05-20T06:00:00Z", 20.55, 87.95, 956.0, 46.3, 18.5, 8.52, 8.76),
    ("2020-05-20T09:00:00Z", 21.3674, 88.0853, 960.0, 46.3, 18.5, 7.47, 19.76),
    ("2020-05-20T12:00:00Z", 22.05, 88.35, 957.0, 43.73, 18.5, 7.47, 19.76),
)


def _load_track_dict() -> dict[str, CycloneTrackPoint]:
    """Load canonical track points from demo fixture if present, else fallback."""
    fixture_path = DEMO_DIR / "hazard__track.json"
    if fixture_path.is_file():
        try:
            with fixture_path.open(encoding="utf-8") as f:
                data = json.load(f)
                return {
                    pt["timestep"]: CycloneTrackPoint.model_validate(pt) for pt in data["points"]
                }
        except Exception:
            pass
    return {row[0]: CycloneTrackPoint(*row) for row in _AMPHAN_WAYPOINTS}


AMPHAN_TRACK: dict[str, CycloneTrackPoint] = _load_track_dict()


@lru_cache(maxsize=1)
def get_replay_track() -> tuple[CycloneTrackPoint, ...]:
    """Return the canonical immutable 25-point Cyclone Amphan replay track.

    Source Dataset:
        Official IBTrACS Cyclone Amphan track (IBTrACS.NI.2020137N10087.v04r00) and
        India Meteorological Department (IMD) RSMC Best Track Report for Super Cyclonic
        Storm AMPHAN (16–21 May 2020).

    Provenance:
        hazard__track.json is a generated artifact produced by api/scripts/ingest_track.py
        from the official IBTrACS dataset. The repository uses the generated fixture at runtime
        to ensure deterministic replay behavior and avoid network dependencies.

    Sampling:
        One track point per 3-hour synoptic timestep over the 72-hour replay window
        from 2020-05-17T12:00:00Z to landfall at 2020-05-20T12:00:00Z (25 points).

    Derived Fields:
        - forward_speed_mps: Translation velocity computed via Haversine great-circle
          distance between consecutive 3-hourly fixes divided by 10800s.
        - heading_deg: Meteorological forward heading azimuth (0° = North, 90° = East)
          computed using spherical forward geodesic bearing between consecutive fixes.
    """
    track_dict = _load_track_dict()
    return tuple(track_dict[ts] for ts in REPLAY_TIMESTEPS)


def iso_to_compact_ts(timestep: str) -> str:
    """Convert ISO 8601 UTC timestamp to compact format: 2020-05-20T12:00:00Z -> 20200520T1200Z."""
    return timestep.replace("-", "").replace(":", "")[:13] + "Z"


def compact_to_iso_ts(compact: str) -> str:
    """Convert compact timestamp to ISO 8601 UTC: 20200520T1200Z -> 2020-05-20T12:00:00Z."""
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}T{compact[9:11]}:{compact[11:13]}:00Z"


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers using the Haversine formula."""
    r = 6371.0  # Earth's radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# 2. AOI Spatial Grid Generation
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_aoi_grid(rows: int = 8, cols: int = 8) -> list[GridCell]:
    """Generate non-overlapping regular polygon grid cells spanning the Sundarbans AOI."""
    settings = get_settings()
    min_lon, min_lat, max_lon, max_lat = settings.aoi_bbox_tuple

    dx = (max_lon - min_lon) / cols
    dy = (max_lat - min_lat) / rows

    cells: list[GridCell] = []
    coastline_lat = min_lat + 0.05  # Approximate southern marine boundary

    for r in range(rows):
        for c in range(cols):
            c_min_lon = min_lon + c * dx
            c_max_lon = c_min_lon + dx
            c_min_lat = min_lat + r * dy
            c_max_lat = c_min_lat + dy

            centroid_lon = (c_min_lon + c_max_lon) / 2.0
            centroid_lat = (c_min_lat + c_max_lat) / 2.0

            # Distance to southern coast (km)
            dist_km = max(
                0.0,
                haversine_distance_km(centroid_lat, centroid_lon, coastline_lat, centroid_lon),
            )

            # Realistic elevation across Sundarbans: 1.0m south coast up to ~6.5m northern interior
            rel_north = (centroid_lat - min_lat) / (max_lat - min_lat)
            elevation = 1.0 + rel_north * 5.0 + 0.5 * math.sin(centroid_lon * 10.0)
            elevation = max(0.5, round(elevation, 2))

            # GeoJSON Polygon coordinates in EPSG:4326: [[[lon, lat], ...]] (closed ring)
            ring = [
                [round(c_min_lon, 5), round(c_min_lat, 5)],
                [round(c_max_lon, 5), round(c_min_lat, 5)],
                [round(c_max_lon, 5), round(c_max_lat, 5)],
                [round(c_min_lon, 5), round(c_max_lat, 5)],
                [round(c_min_lon, 5), round(c_min_lat, 5)],
            ]
            polygon = Polygon(coordinates=[ring])

            cell_id = f"c{r:02d}{c:02d}"
            cells.append(
                GridCell(
                    id=cell_id,
                    centroid_lon=centroid_lon,
                    centroid_lat=centroid_lat,
                    min_lon=c_min_lon,
                    min_lat=c_min_lat,
                    max_lon=c_max_lon,
                    max_lat=c_max_lat,
                    elevation_m=elevation,
                    dist_to_coast_km=dist_km,
                    polygon=polygon,
                )
            )

    return cells


# ---------------------------------------------------------------------------
# 3. Parametric Physics: Wind, Surge, Flood Susceptibility
# ---------------------------------------------------------------------------
def compute_wind_metric(cell: GridCell, track_pt: CycloneTrackPoint) -> HazardMetricResult:
    """Compute physical 10m sustained wind speed (m/s) and normalized severity [0, 1].

    Uses modified Holland parametric wind profile with translation asymmetry and surface friction.
    """
    dist_km = haversine_distance_km(
        cell.centroid_lat, cell.centroid_lon, track_pt.lat, track_pt.lon
    )

    # Holland wind profile formulation
    rmw = track_pt.radius_max_wind_km
    r = max(dist_km, 5.0)
    b = 1.25  # Holland scaling parameter
    ratio = (rmw / r) ** b
    v_gradient = track_pt.max_wind_mps * math.sqrt(ratio * math.exp(1.0 - ratio))

    # Inflow angle and storm motion enhancement
    # Stronger winds on the east / north-east (forward-right) quadrant of the cyclone
    d_lon = cell.centroid_lon - track_pt.lon
    d_lat = cell.centroid_lat - track_pt.lat
    bearing = math.degrees(math.atan2(d_lon, d_lat)) % 360.0
    relative_angle = math.radians(bearing - track_pt.heading_deg)
    asymmetry_factor = 1.0 + 0.18 * math.sin(relative_angle)

    # Surface friction reduction over land
    friction_factor = 0.82 if cell.dist_to_coast_km > 20.0 else 0.90

    wind_speed = v_gradient * asymmetry_factor * friction_factor

    # Ambient environmental wind floor (increases as storm approaches Bay of Bengal head)
    ambient_floor = 6.0 + max(0.0, 14.0 - dist_km / 60.0)
    wind_speed = max(wind_speed, ambient_floor)
    wind_speed = min(round(wind_speed, 1), 60.0)

    # Severity normalization [0, 1] mapped to IMD storm severity categories
    if wind_speed <= 10.0:
        severity = (wind_speed / 10.0) * 0.20
    elif wind_speed <= 17.0:
        severity = 0.20 + ((wind_speed - 10.0) / 7.0) * 0.15
    elif wind_speed <= 24.0:
        severity = 0.35 + ((wind_speed - 17.0) / 7.0) * 0.20
    elif wind_speed <= 33.0:
        severity = 0.55 + ((wind_speed - 24.0) / 9.0) * 0.20
    else:
        severity = 0.75 + min(0.25, ((wind_speed - 33.0) / 15.0) * 0.25)

    severity = max(0.0, min(1.0, round(severity, 3)))
    return HazardMetricResult(value=wind_speed, unit="m/s", severity=severity)


def compute_surge_metric(cell: GridCell, track_pt: CycloneTrackPoint) -> HazardMetricResult:
    """Compute coastal and estuary storm surge depth (m) above ground and severity [0, 1].

    Driven by atmospheric pressure drop, onshore wind stress, and coastal inundation decay.
    """
    dist_to_eye = haversine_distance_km(
        cell.centroid_lat, cell.centroid_lon, track_pt.lat, track_pt.lon
    )

    # 1. Inverted barometer effect: ~1 cm surge per 1 hPa pressure deficit
    delta_p = max(0.0, 1012.0 - track_pt.central_pressure_hpa)
    h_barometer = delta_p * 0.010  # meters

    # 2. Wind setup: peak onshore winds pushing water into the shallow northern Bay of Bengal shelf
    wind_res = compute_wind_metric(cell, track_pt)
    v_wind = wind_res.value
    h_wind_setup = (v_wind / 20.0) ** 2.2 * 0.85

    total_coastal_surge = h_barometer + h_wind_setup

    # Distance attenuation: surge decays as it travels inland across the delta
    decay = math.exp(-cell.dist_to_coast_km / 35.0)
    inland_surge = total_coastal_surge * decay

    # Subtract terrain elevation to obtain flood depth above ground level
    depth = max(0.0, inland_surge - 0.25 * cell.elevation_m)

    # If the eye is far away (>600 km), surge is minimal
    if dist_to_eye > 600.0:
        depth = 0.0
    elif dist_to_eye > 300.0:
        depth *= max(0.0, (600.0 - dist_to_eye) / 300.0)

    depth = round(min(depth, 5.5), 2)

    # Severity normalization: 0m -> 0.0, 1.0m -> 0.30, 2.5m -> 0.70, >=4.0m -> 1.0
    if depth <= 0.05:
        severity = 0.0
    elif depth <= 1.0:
        severity = 0.05 + (depth / 1.0) * 0.25
    elif depth <= 2.5:
        severity = 0.30 + ((depth - 1.0) / 1.5) * 0.40
    else:
        severity = 0.70 + min(0.30, ((depth - 2.5) / 1.5) * 0.30)

    severity = max(0.0, min(1.0, round(severity, 3)))
    return HazardMetricResult(value=depth, unit="m", severity=severity)


def compute_flood_susceptibility_metric(cell: GridCell) -> HazardMetricResult:
    """Compute static baseline topographical and estuarine flood susceptibility index [0, 1].

    Static across all timesteps according to contracts.md §4.1.
    """
    # Low elevation (< 3m) strongly elevates flood vulnerability
    elevation_score = 1.0 - min(1.0, cell.elevation_m / 6.0)

    # Proximity to coast and tidal mangrove creeks (< 25km)
    coast_proximity_score = math.exp(-cell.dist_to_coast_km / 25.0)

    # Combined index (0 - 1)
    index_val = 0.65 * elevation_score + 0.35 * coast_proximity_score
    index_val = max(0.05, min(0.98, round(index_val, 2)))

    return HazardMetricResult(value=index_val, unit="index", severity=index_val)


# ---------------------------------------------------------------------------
# 4. Feature Collection Generator
# ---------------------------------------------------------------------------
def generate_hazard_layer(hazard_type: HazardType, timestep: str) -> HazardLayerCollection:
    """Generate a validated FeatureCollection<HazardLayer> for the requested hazard and timestep."""
    if timestep not in AMPHAN_TRACK:
        raise ValueError(f"Unknown replay timestep: {timestep}")

    track_pt = AMPHAN_TRACK[timestep]
    grid_cells = get_aoi_grid()
    compact_ts = iso_to_compact_ts(timestep)

    features: list[HazardLayer] = []
    for cell in grid_cells:
        if hazard_type == "wind":
            metric = compute_wind_metric(cell, track_pt)
        elif hazard_type == "surge":
            metric = compute_surge_metric(cell, track_pt)
        elif hazard_type == "flood":
            metric = compute_flood_susceptibility_metric(cell)
        else:
            raise ValueError(f"Unsupported hazard_type: {hazard_type}")

        # Unique feature ID across (hazard_type, timestep)
        feature_id = f"{hazard_type}__{cell.id}__{compact_ts}"

        props = HazardLayerProperties(
            id=feature_id,
            hazard_type=hazard_type,
            timestep=timestep,
            value=metric.value,
            unit=metric.unit,
            severity=metric.severity,
        )

        layer_feature = HazardLayer(
            id=feature_id,
            geometry=cell.polygon,
            properties=props,
        )
        features.append(layer_feature)

    return HazardLayerCollection(type="FeatureCollection", features=features)
