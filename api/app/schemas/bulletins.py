"""Pydantic models for IMD Cyclone Amphan bulletins multimodal analysis (shared/contracts.md §4.8).

v1.4 change, pending Dev B.
"""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ContractModel, Timestep


class BulletinPageRef(ContractModel):
    page: int | None = Field(
        default=None, description="1-indexed PDF page number where this information appears"
    )


class BulletinIssueDateTime(ContractModel):
    date_str: str | None = Field(
        default=None, description="Issue date as printed in the bulletin, e.g. '20.05.2020'"
    )
    time_ist: str | None = Field(
        default=None, description="Issue time in Indian Standard Time (IST)"
    )
    time_utc: str | None = Field(default=None, description="Issue time in UTC if explicitly stated")
    page: int | None = Field(default=None, description="Page number where issue time is found")


class BulletinCurrentPosition(ContractModel):
    latitude_deg_north: float | None = Field(
        default=None, description="Current latitude in degrees North"
    )
    longitude_deg_east: float | None = Field(
        default=None, description="Current longitude in degrees East"
    )
    location_description: str | None = Field(
        default=None, description="Text description of storm center relative to coastal landmarks"
    )
    page: int | None = Field(default=None, description="Page number where position was found")


class BulletinCurrentIntensity(ContractModel):
    classification: str | None = Field(
        default=None, description="IMD cyclone intensity classification"
    )
    max_sustained_surface_wind_kmph: str | None = Field(
        default=None, description="Surface wind speed text in kmph"
    )
    max_sustained_surface_wind_kts: float | None = Field(
        default=None, description="Surface wind speed in knots"
    )
    estimated_central_pressure_hpa: float | None = Field(
        default=None, description="Estimated central pressure in hPa"
    )
    page: int | None = Field(default=None, description="Page number where intensity was found")


class BulletinForecastLandfall(ContractModel):
    landfall_area: str | None = Field(default=None, description="Forecast coastal landfall area")
    landfall_lat: float | None = Field(
        default=None, description="Forecast latitude at landfall if given in forecast track table"
    )
    landfall_lon: float | None = Field(
        default=None, description="Forecast longitude at landfall if given in forecast track table"
    )
    forecast_landfall_time_str: str | None = Field(
        default=None, description="Forecast landfall time description"
    )
    page: int | None = Field(
        default=None, description="Page number where landfall forecast was found"
    )


class BulletinForecastMaxWindAtLandfall(ContractModel):
    wind_description: str | None = Field(
        default=None, description="Maximum sustained wind forecast at landfall description"
    )
    max_wind_kmph: float | None = Field(default=None, description="Maximum sustained wind in kmph")
    gust_kmph: float | None = Field(default=None, description="Maximum gust in kmph")
    page: int | None = Field(default=None, description="Page number where wind forecast was found")


class BulletinStormSurgeForecast(ContractModel):
    surge_height_description: str | None = Field(
        default=None, description="Storm surge height warning description"
    )
    min_surge_height_m: float | None = Field(
        default=None, description="Minimum surge height in meters"
    )
    max_surge_height_m: float | None = Field(
        default=None, description="Maximum surge height in meters"
    )
    inundated_districts: list[str] = Field(
        default_factory=list, description="Districts warned of storm surge inundation"
    )
    specific_blocks_mentioned: list[str] = Field(
        default_factory=list, description="Specific administrative blocks/mandals warned"
    )
    page: int | None = Field(
        default=None, description="Page number where storm surge warning was found"
    )


class BulletinWarnedAreas(ContractModel):
    west_bengal_districts: list[str] = Field(
        default_factory=list, description="West Bengal coastal/inland districts warned"
    )
    odisha_districts: list[str] = Field(
        default_factory=list, description="Odisha coastal districts warned"
    )
    other_districts_or_blocks: list[str] = Field(
        default_factory=list, description="Other states, regions or blocks warned"
    )
    page: int | None = Field(default=None, description="Page number where warnings were found")


class BulletinLandfallComparison(ContractModel):
    """Comparison of bulletin forecast landfall against actual IBTrACS landfall."""

    actual_landfall_lat: float = Field(description="Actual IBTrACS landfall latitude (deg N)")
    actual_landfall_lon: float = Field(description="Actual IBTrACS landfall longitude (deg E)")
    actual_landfall_time: str = Field(description="Actual landfall time in ISO 8601 UTC")
    forecast_landfall_lat: float | None = Field(
        default=None, description="Forecast landfall latitude (deg N) or centroid"
    )
    forecast_landfall_lon: float | None = Field(
        default=None, description="Forecast landfall longitude (deg E) or centroid"
    )
    forecast_landfall_time: str | None = Field(
        default=None, description="Forecast landfall time in ISO 8601 UTC"
    )
    distance_error_km: float | None = Field(
        default=None, description="Great-circle distance error in km against actual landfall"
    )
    time_difference_hours: float | None = Field(
        default=None,
        description=(
            "Time error in hours (forecast - actual; positive = forecast late, "
            "negative = forecast early)"
        ),
    )
    notes: str | None = Field(

        default=None, description="Explanation of coordinates and comparison basis"
    )


class ImdBulletin(ContractModel):
    """A single analyzed IMD bulletin with raw Gemini multimodal extraction and landfall comparison.

    v1.4 change, pending Dev B.
    """

    id: str = Field(description="Canonical bulletin identifier, e.g. 'imd-bulletin-36'")
    bulletin_number: str = Field(
        description="Official bulletin number string, e.g. 'National Bulletin No. 36'"
    )
    nominal_timestep: Timestep = Field(
        description="Aligned 3-hourly replay timestep (contracts.md §2)"
    )
    target_stage: str = Field(
        description="Stage relative to landfall: T-72, T-42, T-27, T-12, T-3, T-0"
    )
    hours_to_landfall: float = Field(
        description="Nominal hours to landfall (-42.0 for T-42, 0.0 for T-0)"
    )
    source_url: str = Field(
        description="Exact official source download URL from IMD RSMC New Delhi"
    )
    source_filename: str = Field(
        description="Committed reference PDF filename in api/data/reference/imd/"
    )
    sha256: str = Field(description="SHA-256 cryptographic hash of the committed source PDF")
    issue_date_time: BulletinIssueDateTime
    current_storm_position: BulletinCurrentPosition
    current_intensity: BulletinCurrentIntensity
    forecast_landfall: BulletinForecastLandfall
    forecast_max_wind_at_landfall: BulletinForecastMaxWindAtLandfall
    storm_surge_forecast: BulletinStormSurgeForecast
    warned_areas: BulletinWarnedAreas
    landfall_comparison: BulletinLandfallComparison
    extraction_notes: str | None = Field(
        default=None, description="Any notable observations or limitations in the bulletin text"
    )


class ActualLandfallReference(ContractModel):
    """Ground truth reference data for Cyclone Amphan landfall (contracts.md §2)."""

    source: str = "NOAA NCEI IBTrACS / IMD RSMC Cyclone Report"
    crossing_location_name: str = "Sundarbans (West Bengal - Bangladesh border)"
    crossing_lat: float = 21.65
    crossing_lon: float = 88.30
    synoptic_hour_timestep: Timestep = "2020-05-20T12:00:00Z"
    synoptic_hour_lat: float = 22.05
    synoptic_hour_lon: float = 88.35
    landfall_time_utc: str = "2020-05-20T11:00:00Z"
    landfall_time_ist: str = "2020-05-20 16:30 IST"


class ImdBulletinCollection(ContractModel):
    """Complete collection of analyzed IMD bulletins for Cyclone Amphan.

    Response model for GET /api/hazard/bulletins.
    v1.4 change, pending Dev B.
    """

    event: str = "amphan"
    actual_landfall: ActualLandfallReference = Field(default_factory=ActualLandfallReference)
    bulletins: list[ImdBulletin]
