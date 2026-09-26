"""Earth Engine utilities for Copernicus Sentinel-1 Synthetic Aperture Radar (SAR) acquisition.

Provides automated, deterministic querying and pairing of Sentinel-1 C-band SAR GRD
imagery across pre-landfall baseline and post-landfall event windows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

# Avoid circular import by referencing gee module dynamically
def _is_ee_available() -> bool:
    from app.hazard.gee import is_ee_available

    return is_ee_available()

SENTINEL1_COLLECTION_ID = "COPERNICUS/S1_GRD"


def _format_date(dt: datetime | str) -> str:
    """Format datetime or ISO string to GEE date string 'YYYY-MM-DD'."""
    if isinstance(dt, str):
        # Handle ISO strings like '2020-05-20T12:00:00Z'
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d")


def _format_datetime_utc(dt: datetime | str) -> datetime:
    """Ensure datetime is timezone-aware UTC datetime."""
    if isinstance(dt, str):
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def load_sentinel_collection(
    aoi_bbox: tuple[float, float, float, float],
    start_date: str | datetime,
    end_date: str | datetime,
    polarization: str = "VV",
    orbit_pass: str | None = None,
    relative_orbit: int | None = None,
    instrument_mode: str = "IW",
) -> Any | None:
    """Load Sentinel-1 Ground Range Detected (GRD) image collection over the given AOI.

    Args:
        aoi_bbox: (min_lon, min_lat, max_lon, max_lat) in EPSG:4326.
        start_date: Start date string 'YYYY-MM-DD' or datetime.
        end_date: End date string 'YYYY-MM-DD' or datetime.
        polarization: Target polarization band ('VV' or 'VH'). Default 'VV'.
        orbit_pass: Optional orbit direction ('ASCENDING' or 'DESCENDING').
        relative_orbit: Optional relative orbit number (e.g. 12, 48, 121).
        instrument_mode: Acquisition mode, default 'IW' (Interferometric Wide Swath).

    Returns:
        ee.ImageCollection or None if GEE is unavailable.
    """
    if not _is_ee_available():
        logger.warning("Earth Engine is not initialized; cannot load Sentinel collection.")
        return None

    try:
        import ee

        min_lon, min_lat, max_lon, max_lat = aoi_bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

        s_str = _format_date(start_date)
        e_str = _format_date(end_date)

        col = (
            ee.ImageCollection(SENTINEL1_COLLECTION_ID)
            .filterBounds(geometry)
            .filterDate(s_str, e_str)
            .filter(ee.Filter.eq("instrumentMode", instrument_mode))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", polarization))
        )

        if orbit_pass:
            col = col.filter(ee.Filter.eq("orbitProperties_pass", orbit_pass.upper()))

        if relative_orbit is not None:
            col = col.filter(ee.Filter.eq("relativeOrbitNumber_start", relative_orbit))

        return col
    except Exception as e:
        logger.warning("Error loading Sentinel-1 collection from GEE: %s", e)
        return None


def get_sentinel_image_metadata(ee_image: Any) -> dict[str, Any] | None:
    """Extract deterministic metadata from an Earth Engine Sentinel-1 image.

    Returns:
        Dictionary containing image ID, acquisition timestamp, orbit direction,
        relative orbit number, instrument mode, and available bands.
    """
    if ee_image is None or not _is_ee_available():
        return None

    try:
        info = ee_image.getInfo()
        if not info:
            return None

        props = info.get("properties", {})
        time_start_ms = props.get("system:time_start")
        acq_time_iso = (
            datetime.fromtimestamp(time_start_ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if time_start_ms
            else None
        )

        return {
            "id": info.get("id"),
            "acquisition_time": acq_time_iso,
            "orbit_pass": props.get("orbitProperties_pass"),
            "relative_orbit": props.get("relativeOrbitNumber_start"),
            "instrument_mode": props.get("instrumentMode"),
            "platform": props.get("platform_number"),
            "polarizations": props.get("transmitterReceiverPolarisation", []),
            "bands": [b.get("id") for b in info.get("bands", [])],
        }
    except Exception as e:
        logger.warning("Error extracting Sentinel-1 image metadata: %s", e)
        return None


def find_pre_landfall_image(
    aoi_bbox: tuple[float, float, float, float],
    landfall_time: str | datetime,
    search_window_days: int = 14,
    polarization: str = "VV",
    orbit_pass: str | None = None,
    relative_orbit: int | None = None,
) -> tuple[Any | None, dict[str, Any] | None]:
    """Find the most recent Sentinel-1 SAR image acquired prior to cyclone landfall.

    Args:
        aoi_bbox: AOI bounding box (min_lon, min_lat, max_lon, max_lat).
        landfall_time: Cyclone landfall ISO timestamp or datetime.
        search_window_days: Number of days prior to landfall to search.
        polarization: Preferred polarization ('VV').
        orbit_pass: Optional orbit pass ('ASCENDING' or 'DESCENDING').
        relative_orbit: Optional relative orbit number.

    Returns:
        (ee.Image, metadata_dict) or (None, None) if not found.
    """
    if not _is_ee_available():
        return None, None

    try:
        dt_landfall = _format_datetime_utc(landfall_time)
        dt_start = dt_landfall - timedelta(days=search_window_days)

        col = load_sentinel_collection(
            aoi_bbox=aoi_bbox,
            start_date=dt_start,
            end_date=dt_landfall,
            polarization=polarization,
            orbit_pass=orbit_pass,
            relative_orbit=relative_orbit,
        )
        if col is None:
            return None, None

        # Sort descending by acquisition time to get closest baseline prior to landfall
        sorted_col = col.sort("system:time_start", False)
        count = sorted_col.size().getInfo()
        if count == 0:
            logger.info("No pre-landfall Sentinel-1 image found in window [%s, %s]", dt_start, dt_landfall)
            return None, None

        img = sorted_col.first()
        meta = get_sentinel_image_metadata(img)
        return img, meta
    except Exception as e:
        logger.warning("Error finding pre-landfall Sentinel-1 image: %s", e)
        return None, None


def find_post_landfall_image(
    aoi_bbox: tuple[float, float, float, float],
    landfall_time: str | datetime,
    search_window_days: int = 14,
    polarization: str = "VV",
    orbit_pass: str | None = None,
    relative_orbit: int | None = None,
) -> tuple[Any | None, dict[str, Any] | None]:
    """Find the earliest Sentinel-1 SAR image acquired after cyclone landfall.

    Args:
        aoi_bbox: AOI bounding box (min_lon, min_lat, max_lon, max_lat).
        landfall_time: Cyclone landfall ISO timestamp or datetime.
        search_window_days: Number of days after landfall to search.
        polarization: Preferred polarization ('VV').
        orbit_pass: Optional orbit pass ('ASCENDING' or 'DESCENDING').
        relative_orbit: Optional relative orbit number.

    Returns:
        (ee.Image, metadata_dict) or (None, None) if not found.
    """
    if not _is_ee_available():
        return None, None

    try:
        dt_landfall = _format_datetime_utc(landfall_time)
        dt_end = dt_landfall + timedelta(days=search_window_days)

        col = load_sentinel_collection(
            aoi_bbox=aoi_bbox,
            start_date=dt_landfall,
            end_date=dt_end,
            polarization=polarization,
            orbit_pass=orbit_pass,
            relative_orbit=relative_orbit,
        )
        if col is None:
            return None, None

        # Sort ascending by acquisition time to get earliest scene after landfall
        sorted_col = col.sort("system:time_start", True)
        count = sorted_col.size().getInfo()
        if count == 0:
            logger.info("No post-landfall Sentinel-1 image found in window [%s, %s]", dt_landfall, dt_end)
            return None, None

        img = sorted_col.first()
        meta = get_sentinel_image_metadata(img)
        return img, meta
    except Exception as e:
        logger.warning("Error finding post-landfall Sentinel-1 image: %s", e)
        return None, None


def load_sentinel_pair(
    aoi_bbox: tuple[float, float, float, float],
    landfall_time: str | datetime,
    pre_window_days: int = 14,
    post_window_days: int = 14,
    polarization: str = "VV",
    match_relative_orbit: bool = True,
    preferred_pass: str | None = None,
) -> dict[str, Any] | None:
    """Acquire a geometrically consistent pre- and post-landfall Sentinel-1 image pair.

    To maximize backscatter coherence and minimize viewing angle distortions, this function:
    1. Identifies the closest pre-landfall baseline scene (optionally with preferred_pass).
    2. Retrieves the matching post-landfall scene with the identical orbit pass and relative orbit number.
    3. Falls back to best available post-landfall scene if strict relative orbit match is unavailable.

    Returns:
        Dictionary containing:
        - 'before_image': ee.Image
        - 'after_image': ee.Image
        - 'before_meta': dict
        - 'after_meta': dict
        - 'matched_orbit': bool
        Or None if images cannot be retrieved.
    """
    if not _is_ee_available():
        return None

    # Step 1: Find pre-landfall scene
    pre_img, pre_meta = find_pre_landfall_image(
        aoi_bbox=aoi_bbox,
        landfall_time=landfall_time,
        search_window_days=pre_window_days,
        polarization=polarization,
        orbit_pass=preferred_pass,
    )
    if pre_img is None or pre_meta is None:
        logger.warning("Failed to locate pre-landfall Sentinel-1 baseline scene.")
        return None

    orbit_pass = pre_meta.get("orbit_pass")
    rel_orbit = pre_meta.get("relative_orbit") if match_relative_orbit else None

    # Step 2: Find post-landfall scene matching orbit geometry
    post_img, post_meta = find_post_landfall_image(
        aoi_bbox=aoi_bbox,
        landfall_time=landfall_time,
        search_window_days=post_window_days,
        polarization=polarization,
        orbit_pass=orbit_pass,
        relative_orbit=rel_orbit,
    )

    matched_orbit = True
    # If matching relative orbit failed, fall back to matching orbit pass only
    if post_img is None and rel_orbit is not None:
        logger.info(
            "Strict relative orbit %s match not found for post-landfall; falling back to orbit pass %s",
            rel_orbit,
            orbit_pass,
        )
        post_img, post_meta = find_post_landfall_image(
            aoi_bbox=aoi_bbox,
            landfall_time=landfall_time,
            search_window_days=post_window_days,
            polarization=polarization,
            orbit_pass=orbit_pass,
            relative_orbit=None,
        )
        matched_orbit = False

    # If still not found, try any available post-landfall scene
    if post_img is None:
        logger.info("Orbit-matched post-landfall scene not found; querying any available post-landfall scene.")
        post_img, post_meta = find_post_landfall_image(
            aoi_bbox=aoi_bbox,
            landfall_time=landfall_time,
            search_window_days=post_window_days,
            polarization=polarization,
            orbit_pass=None,
            relative_orbit=None,
        )
        matched_orbit = False

    if post_img is None or post_meta is None:
        logger.warning("Failed to locate post-landfall Sentinel-1 scene.")
        return None

    return {
        "before_image": pre_img,
        "after_image": post_img,
        "before_meta": pre_meta,
        "after_meta": post_meta,
        "matched_orbit": matched_orbit,
    }
