"""Configuration definitions and AOI specifications for the Sentinel-1 validation pipeline.

Provides structured, immutable configuration for:
- Event definitions (e.g. Cyclone Amphan)
- Multi-block AOI registry (Sagar, Namkhana, Gosaba, Patharpratima)
- SAR acquisition query criteria (orbit matching, polarizations, temporal windows)
- Preprocessing parameters (speckle filter, terrain slope mask, resolution)
- Flood extraction thresholds (backscatter change, water occurrence, morphological kernel)
- Hazard comparison criteria (surge depth and flood susceptibility thresholds)
- Artifact export directories and georeferencing parameters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import API_DIR

# Artifact and reference directory locations
VALIDATION_ARTIFACTS_DIR = API_DIR / "data" / "artifacts" / "validation"
REFERENCE_DIR = API_DIR / "data" / "reference"
BLOCKS_GEOJSON = REFERENCE_DIR / "s24p_blocks.geojson"
BLOCKS_CSV = REFERENCE_DIR / "s24p_blocks.csv"

# Initial benchmark blocks for Cyclone Amphan (Census of India 2011 CD block codes)
BENCHMARK_BLOCK_CODES: dict[str, str] = {
    "sagar": "02438",
    "namkhana": "02439",
    "gosaba": "02435",
    "patharpratima": "02440",
}

# Reverse lookup: code -> canonical name
BLOCK_CODE_TO_NAME: dict[str, str] = {
    "02438": "Sagar",
    "02439": "Namkhana",
    "02435": "Gosaba",
    "02440": "Patharpratima",
}


@dataclass(frozen=True)
class AOIConfig:
    """Administrative block Area of Interest (AOI) specification."""

    identifier: str  # Census code or slug
    name: str  # Human-readable block name
    census_code: str  # 5-digit Census 2011 code
    district: str = "South 24 Parganas"
    state: str = "West Bengal"
    country: str = "India"


@dataclass(frozen=True)
class EventConfig:
    """Cyclonic event specification for validation benchmarking."""

    event_name: str = "Cyclone Amphan"
    landfall_timestamp: str = "2020-05-20T12:00:00Z"
    pre_window_days: int = 14
    post_window_days: int = 7
    polarization: str = "VV"
    secondary_polarization: str = "VH"
    instrument_mode: str = "IW"
    product_type: str = "GRD"
    pairing_strategy: str = "post_first"  # 'post_first' or 'pre_first'
    match_relative_orbit: bool = True
    preferred_pass: str | None = None  # 'ASCENDING', 'DESCENDING', or None


@dataclass(frozen=True)
class PreprocessingConfig:
    """SAR preprocessing parameters."""

    speckle_filter: str = "refined_lee"  # 'refined_lee', 'median', or 'boxcar'
    kernel_size: int = 7
    equivalent_number_of_looks: float = 4.4  # Sentinel-1 IW GRD ENL
    max_slope_deg: float = 5.0  # Topographic terrain slope ceiling
    target_crs: str = "EPSG:4326"
    target_scale_m: float = 30.0  # Nominal spatial resolution in meters
    min_backscatter_db: float = -30.0  # Border noise cutoff threshold
    dem_source: str = "copernicus"  # 'copernicus' (GLO-30) or 'srtm'


@dataclass(frozen=True)
class FloodExtractionConfig:
    """SAR flood inundation extraction thresholds based on operational CEMS / DLR guidelines.

    Literature Citations:
    - Relative drop threshold (-2.5 dB): Twele et al. (2016), Int. J. Remote
      Sens. 37(13), 2990-3004.
    - Absolute water ceiling (-15.5 dB): Clement et al. (2018), J. Flood Risk
      Manage. 11(2), 152-168; Copernicus Emergency Management Service (CEMS).
    """

    change_threshold_db: float = -2.5  # Backscatter drop threshold (sigma0_post - sigma0_pre)
    absolute_threshold_db: float = -15.5  # Maximum post-event backscatter for open water in VV
    exclude_permanent_water: bool = True
    permanent_water_occurrence_pct: float = 20.0  # JRC GSW occurrence threshold
    clean_mask: bool = False  # Keep fine coastal flood pixels
    min_cluster_size_pixels: int = 1  # Minimum connected component size in pixels
    morphological_radius: int = 1  # Radius for morphological opening


@dataclass(frozen=True)
class HazardComparisonConfig:
    """Deterministic hazard engine comparison thresholds."""

    surge_threshold_m: float = 0.50  # Minimum surge depth (m) indicating simulated inundation
    flood_susceptibility_threshold: float = 0.65  # Flood susceptibility severity ceiling
    cell_flood_fraction_threshold: float = 0.10  # Fraction of flooded pixels to mark cell flooded (10%)
    landfall_timestep: str = "2020-05-20T12:00:00Z"


@dataclass(frozen=True)
class ValidationPipelineConfig:
    """Master configuration bundling all pipeline parameters."""

    event: EventConfig = field(default_factory=EventConfig)
    preprocessing: PreprocessingConfig = field(default_factory=PreprocessingConfig)
    flood: FloodExtractionConfig = field(default_factory=FloodExtractionConfig)
    comparison: HazardComparisonConfig = field(default_factory=HazardComparisonConfig)
    artifacts_dir: Path = VALIDATION_ARTIFACTS_DIR
    raster_dims: tuple[int, int] = (128, 128)  # Grid dimensions for offline raster export

    def get_block_artifacts_dir(self, block_name_or_code: str) -> Path:
        """Return dedicated artifact export directory for a specific administrative block."""
        slug = block_name_or_code.lower().replace(" ", "_")
        return self.artifacts_dir / slug
