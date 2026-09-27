"""Observed flood inundation extraction from Sentinel-1 SAR backscatter change.

Pipeline stages:
1. Sentinel Before
2. Sentinel After
3. Backscatter Change (Delta sigma0 = sigma0_post - sigma0_pre in dB)
4. Dual Thresholding (significant drop AND water-like post backscatter)
5. Permanent Water Removal (JRC Global Surface Water occurrence exclusion)
6. Morphological Cleanup (opening and connected component filtering)
7. Observed Flood Mask (binary raster: 1 = flooded, 0 = dry)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app.hazard.gee import is_ee_available
from app.hazard.validation.config import FloodExtractionConfig
from app.hazard.validation.datasets import SurfaceWaterDataset

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Earth Engine Flood Extraction Implementation
# ---------------------------------------------------------------------------
def compute_backscatter_difference(
    before_img: Any,
    after_img: Any,
    polarization: str = "VV",
) -> Any:
    """Compute backscatter change: Delta sigma0 = sigma0_after - sigma0_before (dB)."""
    if not is_ee_available() or before_img is None or after_img is None:
        return None

    try:
        before_band = before_img.select(polarization)
        after_band = after_img.select(polarization)
        return after_band.subtract(before_band).rename("difference")
    except Exception as e:
        logger.warning("Error computing Earth Engine backscatter difference: %s", e)
        return None


def apply_flood_thresholding(
    difference_img: Any,
    after_img: Any,
    polarization: str = "VV",
    change_threshold_db: float = -2.5,
    absolute_threshold_db: float = -15.5,
) -> Any:
    """Apply dual thresholding to isolate specular radar reflection caused by water."""
    if not is_ee_available() or difference_img is None or after_img is None:
        return None

    try:
        after_band = after_img.select(polarization)
        is_significant_drop = difference_img.lte(change_threshold_db)
        is_water_level = after_band.lte(absolute_threshold_db)
        return is_significant_drop.And(is_water_level).rename("flooded")
    except Exception as e:
        logger.warning("Error applying flood thresholding in Earth Engine: %s", e)
        return None


def remove_permanent_water(
    flood_img: Any,
    aoi_bbox: tuple[float, float, float, float],
    occurrence_pct: float = 20.0,
) -> Any:
    """Exclude perennial water bodies (rivers, ocean) using JRC Global Surface Water."""
    if not is_ee_available() or flood_img is None:
        return flood_img

    try:
        gsw = SurfaceWaterDataset.load_occurrence(aoi_bbox=aoi_bbox)
        if gsw is None:
            return flood_img

        permanent_water = gsw.gte(occurrence_pct)
        # Set permanent water locations to 0 so only novel cyclonic flooding remains
        return flood_img.where(permanent_water.eq(1), 0)
    except Exception as e:
        logger.warning("Error removing permanent water in Earth Engine: %s", e)
        return flood_img


def apply_morphological_cleanup(
    binary_mask: Any,
    radius: int = 1,
    min_cluster_size_pixels: int = 5,
) -> Any:
    """Remove single-pixel speckle noise and bridge micro-gaps via morphological opening."""
    if not is_ee_available() or binary_mask is None:
        return binary_mask

    try:
        # Morphological opening: focal min (erosion) then focal max (dilation)
        opened = (
            binary_mask.focal_min(radius=radius, units="pixels")
            .focal_max(radius=radius, units="pixels")
        )

        if min_cluster_size_pixels > 1:
            connected = opened.connectedPixelCount(
                maxSize=min_cluster_size_pixels + 5, eightConnected=True
            )
            cleaned = opened.where(connected.lt(min_cluster_size_pixels), 0)
        else:
            cleaned = opened

        return cleaned.rename("flooded").toByte()
    except Exception as e:
        logger.warning("Error during Earth Engine morphological cleanup: %s", e)
        return binary_mask


def extract_flood_mask_gee(
    before_img: Any,
    after_img: Any,
    aoi_bbox: tuple[float, float, float, float],
    config: FloodExtractionConfig | None = None,
    polarization: str = "VV",
) -> Any:
    """Execute SAR flood extraction pipeline on pre- and post-landfall Earth Engine images."""
    if not is_ee_available() or before_img is None or after_img is None:
        return None

    cfg = config or FloodExtractionConfig()

    try:
        # Step 1: Backscatter difference
        diff = compute_backscatter_difference(before_img, after_img, polarization=polarization)
        if diff is None:
            return None

        # Step 2: Thresholding
        thresholded = apply_flood_thresholding(
            diff,
            after_img,
            polarization=polarization,
            change_threshold_db=cfg.change_threshold_db,
            absolute_threshold_db=cfg.absolute_threshold_db,
        )
        if thresholded is None:
            return None

        # Step 3: Permanent water exclusion
        if cfg.exclude_permanent_water:
            water_cleaned = remove_permanent_water(
                thresholded,
                aoi_bbox=aoi_bbox,
                occurrence_pct=cfg.permanent_water_occurrence_pct,
            )
        else:
            water_cleaned = thresholded

        # Explicitly ensure unflooded background is 0
        binary_mask = water_cleaned.unmask(0).toByte()

        # Step 4: Morphological cleanup
        if cfg.clean_mask:
            final_mask = apply_morphological_cleanup(
                binary_mask,
                radius=cfg.morphological_radius,
                min_cluster_size_pixels=cfg.min_cluster_size_pixels,
            )
        else:
            final_mask = binary_mask

        return final_mask
    except Exception as e:
        logger.warning("Error extracting observed flood mask in Earth Engine: %s", e)
        return None


def calculate_flood_area_km2(
    flood_mask: Any,
    aoi_bbox: tuple[float, float, float, float],
    scale: float = 30.0,
) -> float | None:
    """Calculate observed flooded area in km² directly from Earth Engine raster."""
    if not is_ee_available() or flood_mask is None:
        return None

    try:
        import ee

        min_lon, min_lat, max_lon, max_lat = aoi_bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

        area_img = flood_mask.multiply(ee.Image.pixelArea())
        stats = area_img.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=geometry,
            scale=scale,
            maxPixels=1e8,
        ).getInfo()

        if stats and "flooded" in stats and stats["flooded"] is not None:
            return round(float(stats["flooded"]) / 1e6, 2)
    except Exception as e:
        logger.warning("Error calculating Earth Engine flood area in km²: %s", e)
    return None


# ---------------------------------------------------------------------------
# 2. Numpy Flood Extraction (Offline / Deterministic Testing)
# ---------------------------------------------------------------------------
def extract_flood_mask_numpy(
    before_arr: np.ndarray,
    after_arr: np.ndarray,
    perm_water_arr: np.ndarray | None = None,
    change_threshold_db: float = -2.5,
    absolute_threshold_db: float = -15.5,
    perm_water_threshold_pct: float = 20.0,
    min_cluster_size: int = 3,
) -> np.ndarray:
    """Numpy implementation of SAR change detection and flood mask extraction."""
    diff = after_arr - before_arr
    is_flood = (diff <= change_threshold_db) & (after_arr <= absolute_threshold_db)

    if perm_water_arr is not None:
        is_permanent = perm_water_arr >= perm_water_threshold_pct
        is_flood[is_permanent] = False

    mask = is_flood.astype(np.uint8)

    # Simple 2D morphological opening (erosion followed by dilation)
    h, w = mask.shape
    eroded = np.zeros_like(mask)
    for i in range(1, h - 1):
        for j in range(1, w - 1):
            if np.all(mask[i - 1 : i + 2, j - 1 : j + 2] == 1):
                eroded[i, j] = 1

    dilated = np.zeros_like(mask)
    for i in range(1, h - 1):
        for j in range(1, w - 1):
            if np.any(eroded[i - 1 : i + 2, j - 1 : j + 2] == 1):
                dilated[i, j] = 1

    return dilated
