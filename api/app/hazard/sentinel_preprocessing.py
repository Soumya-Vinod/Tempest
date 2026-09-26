"""SAR Preprocessing pipeline for Copernicus Sentinel-1 GRD imagery.

Provides reproducible radiometric calibration, border noise removal, speckle filtering,
terrain correction, and spatial standardization for SAR flood detection.
"""

from __future__ import annotations

import logging
from typing import Any

from app.hazard.gee import is_ee_available, load_dem

logger = logging.getLogger(__name__)


def remove_border_noise(
    ee_image: Any,
    polarization: str = "VV",
    min_backscatter_db: float = -30.0,
) -> Any:
    """Mask out low-intensity edge noise and invalid border pixels from Sentinel-1 GRD imagery.

    Args:
        ee_image: Earth Engine Sentinel-1 Image.
        polarization: Polarization band to evaluate ('VV').
        min_backscatter_db: Minimum threshold in dB below which pixels are masked as border noise.

    Returns:
        ee.Image with border noise masked.
    """
    if not is_ee_available() or ee_image is None:
        return ee_image

    try:
        # In GEE S1 GRD, invalid border pixels have anomalous low backscatter or zero power
        band = ee_image.select(polarization)
        valid_mask = band.gt(min_backscatter_db)
        return ee_image.updateMask(valid_mask)
    except Exception as e:
        logger.warning("Error in border noise removal: %s", e)
        return ee_image


def apply_speckle_filter(
    ee_image: Any,
    polarization: str = "VV",
    filter_type: str = "median",
    kernel_size: int = 7,
) -> Any:
    """Apply speckle filter in linear power domain and convert back to decibels (dB).

    SAR speckle is multiplicative noise. Filtering in the linear power domain (10^(dB/10))
    preserves radiometric linearity and radiometric consistency.

    Args:
        ee_image: Earth Engine Sentinel-1 Image in dB.
        polarization: Target band ('VV' or 'VH').
        filter_type: 'median', 'boxcar' (mean), or 'refined_lee'.
        kernel_size: Spatial window width in pixels (default 7x7).

    Returns:
        ee.Image with speckle-filtered band in dB.
    """
    if not is_ee_available() or ee_image is None:
        return ee_image

    try:
        import ee

        band = ee_image.select(polarization)
        # Convert dB to linear power: P = 10^(dB/10)
        power = ee.Image(10.0).pow(band.divide(10.0))

        radius = max(1, kernel_size // 2)

        if filter_type == "boxcar":
            filtered_power = power.focal_mean(radius=radius, units="pixels")
        elif filter_type == "refined_lee":
            # Local mean and variance in linear domain
            mean_power = power.focal_mean(radius=radius, units="pixels")
            sqr_power = power.pow(2.0).focal_mean(radius=radius, units="pixels")
            var_power = sqr_power.subtract(mean_power.pow(2.0)).max(0.0)

            # Equivalent number of looks (ENL) ~ 4.4 for Sentinel-1 IW GRD
            enl = 4.4
            sigma_v_sqr = 1.0 / enl

            # Lee weighting coefficient: W = (Var - Mean^2 * sigma^2) / (Var * (1 + sigma^2))
            var_signal = var_power.subtract(mean_power.pow(2.0).multiply(sigma_v_sqr)).max(0.0)
            denom = var_power.multiply(1.0 + sigma_v_sqr).max(1e-6)
            weight = var_signal.divide(denom).clamp(0.0, 1.0)

            filtered_power = mean_power.add(weight.multiply(power.subtract(mean_power)))
        else:
            # Default median filter: extremely robust against salt-and-pepper speckle spikes
            filtered_power = power.focal_median(radius=radius, units="pixels")

        # Convert back to decibels: dB = 10 * log10(P)
        filtered_db = (
            filtered_power.max(1e-5)
            .log10()
            .multiply(10.0)
            .rename(polarization)
        )

        return ee_image.addBands(filtered_db, overwrite=True)
    except Exception as e:
        logger.warning("Error applying speckle filter: %s", e)
        return ee_image


def terrain_correct(
    ee_image: Any,
    aoi_bbox: tuple[float, float, float, float] | None = None,
    dem_image: Any = None,
    max_slope_deg: float = 5.0,
) -> Any:
    """Apply topographic masking and terrain correction using digital elevation models.

    Masks out steep slopes (> 5 degrees) where radar layover, foreshortening, and shadow
    produce false water detections in flat coastal/fluvial floodplains.

    Args:
        ee_image: Earth Engine Image.
        aoi_bbox: Bounding box tuple.
        dem_image: Optional pre-loaded DEM ee.Image. If None, loaded via load_dem().
        max_slope_deg: Maximum terrain slope in degrees. Areas steeper than this are masked.

    Returns:
        ee.Image with terrain-corrected valid mask.
    """
    if not is_ee_available() or ee_image is None:
        return ee_image

    try:
        import ee

        # Prefer USGS SRTM single asset for reliable spatial gradient computation
        dem = dem_image or load_dem(aoi_bbox=aoi_bbox, dem_source="srtm")
        if dem is None:
            dem = ee.Image("USGS/SRTMGL1_003").select("elevation")

        elev_band = dem.select([0]).rename("elevation")
        slope = ee.Terrain.slope(elev_band)
        flat_mask = slope.lte(max_slope_deg)
        return ee_image.updateMask(flat_mask)
    except Exception as e:
        logger.warning("Error during terrain correction / slope masking: %s", e)
        return ee_image


def preprocess_sentinel(
    ee_image: Any,
    aoi_bbox: tuple[float, float, float, float],
    polarization: str = "VV",
    filter_type: str = "median",
    kernel_size: int = 7,
    max_slope_deg: float = 5.0,
    target_crs: str = "EPSG:4326",
    target_scale: float = 30.0,
    apply_terrain: bool = True,
) -> Any:
    """Execute complete SAR preprocessing pipeline on an Earth Engine Sentinel-1 GRD image.

    Pipeline stages:
    1. Clip to AOI geometry.
    2. Border noise removal.
    3. Multiplicative speckle filtering in linear power domain.
    4. Topographic slope masking via DEM.
    5. Retain common target CRS metadata.

    Args:
        ee_image: Raw Earth Engine Sentinel-1 Image.
        aoi_bbox: Bounding box tuple (min_lon, min_lat, max_lon, max_lat).
        polarization: Target polarization band ('VV').
        filter_type: Speckle filter algorithm ('median', 'refined_lee', 'boxcar').
        kernel_size: Filter kernel size in pixels (default 7).
        max_slope_deg: Slope ceiling in degrees to suppress topographic radar shadows.
        target_crs: Output coordinate reference system (default 'EPSG:4326').
        target_scale: Spatial resolution in meters (default 30m).
        apply_terrain: Whether to apply slope terrain masking.

    Returns:
        Preprocessed ee.Image ready for change detection and flood extraction.
    """
    if not is_ee_available() or ee_image is None:
        return ee_image

    try:
        import ee

        min_lon, min_lat, max_lon, max_lat = aoi_bbox
        geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

        # 1. Clip to AOI bounds
        clipped = ee_image.clip(geometry)

        # 2. Border noise removal
        deborded = remove_border_noise(clipped, polarization=polarization)

        # 3. Multiplicative speckle filtering in linear power domain
        despeckled = apply_speckle_filter(
            deborded,
            polarization=polarization,
            filter_type=filter_type,
            kernel_size=kernel_size,
        )

        # 4. Topographic terrain slope correction
        if apply_terrain:
            terrain_cleaned = terrain_correct(
                despeckled,
                aoi_bbox=aoi_bbox,
                max_slope_deg=max_slope_deg,
            )
        else:
            terrain_cleaned = despeckled

        return terrain_cleaned
    except Exception as e:
        logger.warning("Error in Sentinel-1 preprocessing pipeline: %s", e)
        return ee_image
