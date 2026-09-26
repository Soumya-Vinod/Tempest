"""Domain models, internal representations, and contract schema re-exports for the hazard module."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    FloodedRegion,
    GeminiAnalysisResponse,
    GeminiAnalysisSource,
    GeminiFinding,
    GeminiGeneratedFrom,
    HAZARD_UNITS,
    HazardLayer,
    HazardLayerCollection,
    HazardLayerProperties,
    ReplayTimeline,
    SentinelValidationAOI,
    SentinelValidationMetrics,
    SentinelValidationResponse,
)
from app.schemas.geojson import AreaGeometry, MultiPolygon, Polygon


class CycloneTrackPoint(BaseModel):
    """Parametric cyclone state at a specific replay timestep (shared/contracts.md §2).

    Attributes:
        timestep: Replay ISO 8601 UTC timestamp (validated against the 25 Amphan timesteps).
        lat: Latitude of storm eye center in EPSG:4326 [-90.0, 90.0].
        lon: Longitude of storm eye center in EPSG:4326 [-180.0, 180.0].
        central_pressure_hpa: Minimum central barometric pressure (hPa) [800.0, 1050.0].
        max_wind_mps: Maximum sustained 10m wind speed (m/s) [>= 0.0].
        radius_max_wind_km: Radius of maximum winds (km) [> 0.0].
        forward_speed_mps: Cyclone translation velocity (m/s) [>= 0.0].
        heading_deg: Meteorological heading azimuth (degrees, 0 = North) [0.0, 360.0).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestep: Timestep
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    central_pressure_hpa: float = Field(gt=800.0, lt=1050.0)
    max_wind_mps: float = Field(ge=0.0)
    radius_max_wind_km: float = Field(gt=0.0)
    forward_speed_mps: float = Field(ge=0.0)
    heading_deg: float = Field(ge=0.0, lt=360.0)

    def __init__(
        self,
        timestep: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        central_pressure_hpa: float | None = None,
        max_wind_mps: float | None = None,
        radius_max_wind_km: float | None = None,
        forward_speed_mps: float | None = None,
        heading_deg: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Allow positional or keyword initialization while strictly enforcing validation."""
        if timestep is not None:
            kwargs["timestep"] = timestep
        if lat is not None:
            kwargs["lat"] = lat
        if lon is not None:
            kwargs["lon"] = lon
        if central_pressure_hpa is not None:
            kwargs["central_pressure_hpa"] = central_pressure_hpa
        if max_wind_mps is not None:
            kwargs["max_wind_mps"] = max_wind_mps
        if radius_max_wind_km is not None:
            kwargs["radius_max_wind_km"] = radius_max_wind_km
        if forward_speed_mps is not None:
            kwargs["forward_speed_mps"] = forward_speed_mps
        if heading_deg is not None:
            kwargs["heading_deg"] = heading_deg
        super().__init__(**kwargs)


class CycloneTrack(BaseModel):
    """Canonical collection of replay cyclone track points (shared/contracts.md §7).

    Attributes:
        event: Tropical cyclone event name (default 'amphan').
        points: Ordered sequence of 25 CycloneTrackPoint objects.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: str = "amphan"
    points: list[CycloneTrackPoint]


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
    "CycloneTrack",
    "CycloneTrackPoint",
    "FloodedRegion",
    "GeminiAnalysisResponse",
    "GeminiAnalysisSource",
    "GeminiFinding",
    "GeminiGeneratedFrom",
    "GridCell",
    "HazardLayer",
    "HazardLayerCollection",
    "HazardLayerProperties",
    "HazardMetricResult",
    "HazardType",
    "MultiPolygon",
    "Polygon",
    "ReplayTimeline",
    "SentinelValidationAOI",
    "SentinelValidationMetrics",
    "SentinelValidationResponse",
    "Timestep",
    "TimestepParam",
    "UnitFraction",
]
