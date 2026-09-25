"""Google Earth Engine (GEE) integration for topographic and hazard analysis."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_ee_initialized: bool | None = None


def init_ee() -> bool:
    """Initialize Google Earth Engine using service account credentials from settings.

    Returns True if successfully initialized, False otherwise.
    """
    global _ee_initialized
    if _ee_initialized is not None:
        return _ee_initialized

    settings = get_settings()
    if not settings.GEE_SERVICE_ACCOUNT or not settings.gee_key_file:
        logger.info("GEE service account or key file not configured; GEE integration disabled.")
        _ee_initialized = False
        return False

    if not settings.gee_key_file.is_file():
        logger.warning("GEE key file does not exist at %s", settings.gee_key_file)
        _ee_initialized = False
        return False

    try:
        import ee

        credentials = ee.ServiceAccountCredentials(
            settings.GEE_SERVICE_ACCOUNT,
            str(settings.gee_key_file),
        )
        # Note: Avoid project argument to utilize direct service account authorization
        ee.Initialize(credentials=credentials)
        _ee_initialized = True
        logger.info("GEE initialized with account %s", settings.GEE_SERVICE_ACCOUNT)
        return True
    except Exception as e:
        logger.warning("Failed to initialize Google Earth Engine: %s", e)
        _ee_initialized = False
        return False


def is_ee_available() -> bool:
    """Check if GEE client is initialized and ready for queries."""
    if _ee_initialized is None:
        return init_ee()
    return _ee_initialized


def get_elevation_for_aoi(aoi_bbox: tuple[float, float, float, float]) -> float | None:
    """Query USGS SRTM elevation over the AOI rectangle.

    Returns mean elevation in meters, or None if GEE is unavailable.
    """
    if not is_ee_available():
        return None

    try:
        import ee

        min_lon, min_lat, max_lon, max_lat = aoi_bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])
        srtm = ee.Image("USGS/SRTMGL1_003")
        stats = srtm.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=1000,
            maxPixels=1e8,
        ).getInfo()
        if stats and "elevation" in stats:
            return float(stats["elevation"])
    except Exception as e:
        logger.warning("Error querying GEE elevation: %s", e)
    return None


def get_era5_wind_at_timestep(
    timestep: str, aoi_bbox: tuple[float, float, float, float]
) -> dict[str, float] | None:
    """Query ECMWF ERA5-Land hourly 10m wind components for a specific UTC timestamp."""
    if not is_ee_available():
        return None

    try:
        import ee

        dt = datetime.strptime(timestep, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        start_str = dt.strftime("%Y-%m-%dT%H:00:00")
        end_str = (dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00")

        min_lon, min_lat, max_lon, max_lat = aoi_bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

        era5_col = (
            ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
            .filterDate(start_str, end_str)
            .filterBounds(geometry)
        )
        count = era5_col.size().getInfo()
        if count == 0:
            return None

        img = era5_col.first()
        u = img.select("u_component_of_wind_10m")
        v = img.select("v_component_of_wind_10m")
        wind = u.hypot(v).rename("wind_speed")

        stats = wind.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=10000,
            maxPixels=1e7,
        ).getInfo()
        if stats and "wind_speed" in stats and stats["wind_speed"] is not None:
            return {"wind_speed_mps": float(stats["wind_speed"])}
    except Exception as e:
        logger.warning("Error querying ERA5 hourly wind for timestep %s: %s", timestep, e)
    return None
