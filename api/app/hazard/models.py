"""Domain models, internal representations, and contract schema re-exports for the hazard module."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import (
    LANDFALL_TIMESTEP,
    LIVE,
    REPLAY_TIMESTEPS,
    HazardType,
    Timestep,
    TimestepParam,
    UnitFraction,
)
from app.schemas.contracts import (
    HAZARD_UNITS,
    HazardLayer,
    HazardLayerCollection,
    HazardLayerProperties,
    ReplayTimeline,
)
from app.schemas.geojson import AreaGeometry, MultiPolygon, Polygon


@dataclass(frozen=True, slots=True)
class CycloneTrackPoint:
    """Parametric cyclone state at a specific replay timestep.

    Attributes:
        timestep: Replay ISO 8601 UTC timestamp.
        lat: Latitude of storm eye center.
        lon: Longitude of storm eye center.
        central_pressure_hpa: Minimum central barometric pressure (hPa).
        max_wind_mps: Maximum sustained 10m wind speed (m/s).
        radius_max_wind_km: Radius of maximum winds (km).
        forward_speed_mps: Cyclone translation velocity (m/s).
        heading_deg: Meteorological heading azimuth (degrees, 0 = North).
    """

    timestep: str
    lat: float
    lon: float
    central_pressure_hpa: float
    max_wind_mps: float
    radius_max_wind_km: float
    forward_speed_mps: float
    heading_deg: float


@dataclass(frozen=True, slots=True)
class GridCell:
    """Spatial cell representation within the Sundarbans / AOI grid.

    Attributes:
        id: Stable cell identifier (e.g. 'c0000').
        centroid_lon: Longitude of cell center in EPSG:4326.
        centroid_lat: Latitude of cell center in EPSG:4326.
        min_lon: Western boundary longitude.
        min_lat: Southern boundary latitude.
        max_lon: Eastern boundary longitude.
        max_lat: Northern boundary latitude.
        elevation_m: Average ground surface elevation in meters above sea level.
        dist_to_coast_km: Distance to nearest coastal/estuary boundary in kilometers.
        polygon: GeoJSON Polygon geometry representing cell boundary in EPSG:4326.
    """

    id: str
    centroid_lon: float
    centroid_lat: float
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    elevation_m: float
    dist_to_coast_km: float
    polygon: Polygon


class HazardMetricResult(BaseModel):
    """Computed physical and severity values for a single hazard cell.

    Attributes:
        value: Physical magnitude in unit ('m/s' for wind, 'm' for surge, 'index' for flood).
        unit: Physical unit matching the hazard type contract.
        severity: Normalized severity score in [0.0, 1.0].
    """

    value: float
    unit: Literal["m/s", "m", "index"]
    severity: UnitFraction = Field(ge=0.0, le=1.0)


__all__ = [
    "HAZARD_UNITS",
    "LANDFALL_TIMESTEP",
    "LIVE",
    "REPLAY_TIMESTEPS",
    "AreaGeometry",
    "CycloneTrackPoint",
    "GridCell",
    "HazardLayer",
    "HazardLayerCollection",
    "HazardLayerProperties",
    "HazardMetricResult",
    "HazardType",
    "MultiPolygon",
    "Polygon",
    "ReplayTimeline",
    "Timestep",
    "TimestepParam",
    "UnitFraction",
]
