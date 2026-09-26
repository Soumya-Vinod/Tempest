"""Google Earth Engine (GEE) integration for topographic and hazard analysis."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

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


def load_dem(
    aoi_bbox: tuple[float, float, float, float] | None = None,
    dem_source: str = "copernicus",
) -> Any | None:
    """Load digital elevation model (DEM) over the AOI rectangle.

    Supports:
    - 'copernicus': COPERNICUS/DEM/GLO30 (primary, 30m resolution)
    - 'srtm': USGS/SRTMGL1_003 (fallback, 30m resolution)

    Returns ee.Image clipped to AOI or None if GEE is unavailable.
    """
    if not is_ee_available():
        return None
    try:
        import ee

        settings = get_settings()
        bbox = aoi_bbox or settings.aoi_bbox_tuple
        min_lon, min_lat, max_lon, max_lat = bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

        if dem_source == "copernicus":
            try:
                img = (
                    ee.ImageCollection("COPERNICUS/DEM/GLO30")
                    .select("DEM")
                    .mosaic()
                    .clip(geometry)
                )
                return img
            except Exception as e:
                logger.debug("Failed loading Copernicus DEM (%s); falling back to SRTM", e)

        return ee.Image("USGS/SRTMGL1_003").select("elevation").clip(geometry)
    except Exception as e:
        logger.warning("Error loading DEM from GEE: %s", e)
        return None


def load_rainfall(
    aoi_bbox: tuple[float, float, float, float] | None = None,
    start_date: str = "2020-05-01",
    end_date: str = "2020-05-31",
) -> Any | None:
    """Load GPM IMERG monthly/event precipitation over the AOI rectangle.

    Returns ee.Image representing cumulative or mean precipitation (mm) or None.
    """
    if not is_ee_available():
        return None
    try:
        import ee

        settings = get_settings()
        bbox = aoi_bbox or settings.aoi_bbox_tuple
        min_lon, min_lat, max_lon, max_lat = bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

        col = (
            ee.ImageCollection("NASA/GPM_L3/IMERG_MONTHLY_V06")
            .filterDate(start_date, end_date)
            .select("precipitation")
        )
        if col.size().getInfo() > 0:
            return col.mean().clip(geometry)

        daily_col = (
            ee.ImageCollection("NASA/GPM_L3/IMERG_V06")
            .filterDate(start_date, end_date)
            .select("precipitationCal")
        )
        if daily_col.size().getInfo() > 0:
            return daily_col.sum().clip(geometry)
    except Exception as e:
        logger.warning("Error loading IMERG rainfall from GEE: %s", e)
    return None


def load_worldcover(
    aoi_bbox: tuple[float, float, float, float] | None = None,
    year: int = 2020,
) -> Any | None:
    """Load ESA WorldCover 10m land cover classification over the AOI rectangle.

    Classes: 10 (Tree cover), 40 (Cropland), 50 (Built-up), 80 (Permanent water),
    90 (Herbaceous wetland), 95 (Mangroves).
    Returns ee.Image or None.
    """
    if not is_ee_available():
        return None
    try:
        import ee

        settings = get_settings()
        bbox = aoi_bbox or settings.aoi_bbox_tuple
        min_lon, min_lat, max_lon, max_lat = bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

        asset_id = "ESA/WorldCover/v100" if year <= 2020 else "ESA/WorldCover/v200"
        return ee.ImageCollection(asset_id).first().select("Map").clip(geometry)
    except Exception as e:
        logger.warning("Error loading ESA WorldCover from GEE: %s", e)
    return None


def load_surface_water(
    aoi_bbox: tuple[float, float, float, float] | None = None,
) -> Any | None:
    """Load JRC Global Surface Water occurrence (1984-2021) over the AOI rectangle.

    Returns ee.Image with 'occurrence' band [0-100%] or None.
    """
    if not is_ee_available():
        return None
    try:
        import ee

        settings = get_settings()
        bbox = aoi_bbox or settings.aoi_bbox_tuple
        min_lon, min_lat, max_lon, max_lat = bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

        return ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").clip(geometry)
    except Exception as e:
        logger.warning("Error loading JRC Surface Water from GEE: %s", e)
    return None


def export_geojson(
    ee_object: Any,
    aoi_bbox: tuple[float, float, float, float] | None = None,
    scale: float = 1000,
) -> dict[str, Any] | None:
    """Export an Earth Engine Image or FeatureCollection to a GeoJSON dictionary."""
    if not is_ee_available() or ee_object is None:
        return None
    try:
        import ee

        if isinstance(ee_object, ee.FeatureCollection):
            return ee_object.getInfo()  # type: ignore[no-any-return]
        if isinstance(ee_object, ee.Image):
            settings = get_settings()
            bbox = aoi_bbox or settings.aoi_bbox_tuple
            min_lon, min_lat, max_lon, max_lat = bbox
            geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])
            return ee_object.reduceRegion(  # type: ignore[no-any-return]
                reducer=ee.Reducer.mean(),
                geometry=geometry,
                scale=scale,
                maxPixels=1e7,
            ).getInfo()
    except Exception as e:
        logger.warning("Error exporting GeoJSON from GEE object: %s", e)
    return None


# Re-export Sentinel-1 acquisition utilities
from app.hazard.sentinel_acquisition import (  # noqa: E402
    find_post_landfall_image,
    find_pre_landfall_image,
    get_sentinel_image_metadata,
    load_sentinel_collection,
    load_sentinel_pair,
)

__all__ = [
    "init_ee",
    "is_ee_available",
    "get_elevation_for_aoi",
    "get_era5_wind_at_timestep",
    "load_dem",
    "load_rainfall",
    "load_worldcover",
    "load_surface_water",
    "export_geojson",
    "load_sentinel_collection",
    "find_pre_landfall_image",
    "find_post_landfall_image",
    "load_sentinel_pair",
    "get_sentinel_image_metadata",
]

