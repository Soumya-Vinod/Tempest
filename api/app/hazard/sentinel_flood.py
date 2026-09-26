"""Observed flood extent extraction from Sentinel-1 SAR backscatter change.

Implements change detection, thresholding, permanent water exclusion, and morphological
filtering to produce a high-fidelity binary observed flood mask (0 = dry, 1 = flooded).
"""

from __future__ import annotations

import logging
from typing import Any

from app.hazard.gee import is_ee_available, load_surface_water

logger = logging.getLogger(__name__)

# Standard SAR flood detection thresholds (ESA / UN-SPIDER / Copernicus guidelines)
DEFAULT_CHANGE_THRESHOLD_DB: float = -3.0
DEFAULT_ABSOLUTE_THRESHOLD_DB: float = -16.0
DEFAULT_PERMANENT_WATER_OCCURRENCE_PCT: float = 80.0


def compute_backscatter_change(
    before_img: Any,
    after_img: Any,
    polarization: str = "VV",
) -> Any:
    """Compute backscatter intensity difference (Delta sigma0 = sigma0_after - sigma0_before) in dB.

    Inundated surfaces act as specular reflectors, scattering radar pulses away from the receiver
    and producing significant negative backscatter drops.

    Args:
        before_img: Pre-landfall preprocessed ee.Image.
        after_img: Post-landfall preprocessed ee.Image.
        polarization: Polarization band ('VV' or 'VH'). Default 'VV'.

    Returns:
        ee.Image representing difference (dB) named 'difference'.
    """
    if not is_ee_available() or before_img is None or after_img is None:
        return None

    try:
        before_band = before_img.select(polarization)
        after_band = after_img.select(polarization)
        return after_band.subtract(before_band).rename("difference")
    except Exception as e:
        logger.warning("Error computing backscatter change: %s", e)
        return None


def clean_flood_mask(
    raw_mask: Any,
    min_cluster_size_pixels: int = 5,
    radius: int = 1,
) -> Any:
    """Apply morphological filtering to remove isolated speckle noise and bridge micro-gaps.

    Applies connected pixel filtering and morphological opening (erosion followed by dilation)
    to eliminate spurious single-pixel detections.

    Args:
        raw_mask: Binary ee.Image (0 or 1).
        min_cluster_size_pixels: Minimum connected component pixel count.
        radius: Kernel radius in pixels for morphological smoothing.

    Returns:
        Cleaned binary ee.Image (0 or 1).
    """
    if not is_ee_available() or raw_mask is None:
        return raw_mask

    try:
        import ee

        # 1. Morphological opening: focal min (erosion) then focal max (dilation)
        # removes isolated 1-pixel speckles while keeping larger patches intact
        opened = raw_mask.focal_min(radius=radius, units="pixels").focal_max(radius=radius, units="pixels")

        # 2. Connected component size filtering if cluster size > 1
        if min_cluster_size_pixels > 1:
            connected = opened.connectedPixelCount(maxSize=min_cluster_size_pixels + 5, eightConnected=True)
            cleaned = opened.where(connected.lt(min_cluster_size_pixels), 0)
        else:
            cleaned = opened

        return cleaned.rename("flooded").toByte()
    except Exception as e:
        logger.warning("Error cleaning flood mask: %s", e)
        return raw_mask


def extract_flood_mask(
    before_img: Any,
    after_img: Any,
    aoi_bbox: tuple[float, float, float, float],
    polarization: str = "VV",
    change_threshold_db: float = DEFAULT_CHANGE_THRESHOLD_DB,
    absolute_threshold_db: float = DEFAULT_ABSOLUTE_THRESHOLD_DB,
    exclude_permanent_water: bool = True,
    permanent_water_occurrence: float = DEFAULT_PERMANENT_WATER_OCCURRENCE_PCT,
    clean_mask: bool = True,
    min_cluster_size_pixels: int = 5,
) -> Any:
    """Extract binary observed flood mask from pre- and post-landfall SAR images.

    Algorithm:
    1. Compute backscatter difference: Delta sigma0 = sigma0_after - sigma0_before.
    2. Candidate flooded condition: (Delta sigma0 <= change_threshold_db) AND (sigma0_after <= absolute_threshold_db).
    3. Exclude permanent water bodies using JRC Global Surface Water (occurrence > threshold).
    4. Apply morphological cleanup to suppress isolated noise.

    Args:
        before_img: Pre-landfall preprocessed ee.Image.
        after_img: Post-landfall preprocessed ee.Image.
        aoi_bbox: AOI bounding box tuple (min_lon, min_lat, max_lon, max_lat).
        polarization: Polarization band ('VV').
        change_threshold_db: Backscatter drop threshold (e.g. -3.0 dB).
        absolute_threshold_db: Absolute water threshold (e.g. -16.0 dB).
        exclude_permanent_water: If True, masks out perennial water bodies.
        permanent_water_occurrence: Minimum JRC occurrence % to consider permanent water (default 80%).
        clean_mask: If True, applies morphological opening and connected component cleanup.
        min_cluster_size_pixels: Minimum cluster size to retain.

    Returns:
        Binary ee.Image with 1 = flooded, 0 = dry.
    """
    if not is_ee_available() or before_img is None or after_img is None:
        return None

    try:
        import ee

        # 1. Backscatter change
        diff = compute_backscatter_change(before_img, after_img, polarization=polarization)
        if diff is None:
            return None

        after_band = after_img.select(polarization)

        # 2. Thresholding: significant drop AND low absolute backscatter
        is_significant_drop = diff.lte(change_threshold_db)
        is_water_level = after_band.lte(absolute_threshold_db)
        raw_flood = is_significant_drop.And(is_water_level).rename("flooded")

        # 3. Permanent water exclusion via JRC Global Surface Water
        if exclude_permanent_water:
            gsw = load_surface_water(aoi_bbox=aoi_bbox)
            if gsw is not None:
                # Permanent water if historical occurrence >= threshold
                permanent_water = gsw.gte(permanent_water_occurrence)
                # Exclude permanent water bodies so only novel flooding is counted
                raw_flood = raw_flood.where(permanent_water.eq(1), 0)

        # Ensure unflooded pixels are explicitly 0
        binary_mask = raw_flood.unmask(0).toByte()

        # 4. Morphological cleanup
        if clean_mask:
            cleaned = clean_flood_mask(
                binary_mask,
                min_cluster_size_pixels=min_cluster_size_pixels,
            )
            return cleaned

        return binary_mask
    except Exception as e:
        logger.warning("Error extracting observed flood mask: %s", e)
        return None


def calculate_flood_area_km2(
    flood_mask: Any,
    aoi_bbox: tuple[float, float, float, float],
    scale: float = 30.0,
) -> float | None:
    """Calculate the total flooded area in square kilometers from a binary flood mask ee.Image.

    Args:
        flood_mask: Binary ee.Image (1 = flooded, 0 = dry).
        aoi_bbox: AOI bounding box tuple.
        scale: Spatial evaluation resolution in meters.

    Returns:
        Flooded area in km² or None if evaluation fails.
    """
    if not is_ee_available() or flood_mask is None:
        return None

    try:
        import ee

        min_lon, min_lat, max_lon, max_lat = aoi_bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

        # Multiply binary pixel (0 or 1) by pixel area in square meters
        area_img = flood_mask.multiply(ee.Image.pixelArea())
        stats = area_img.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=geometry,
            scale=scale,
            maxPixels=1e8,
        ).getInfo()

        if stats and "flooded" in stats and stats["flooded"] is not None:
            # Convert m² to km²
            return round(float(stats["flooded"]) / 1e6, 2)
    except Exception as e:
        logger.warning("Error computing flood area in km²: %s", e)
    return None
