"""Tempest Hazard Engine Validation Package.

Provides both internal physical model verification/calibration checks
and the generalized Sentinel-1 SAR observational validation pipeline.
"""

from app.hazard.validation.acquisition import (
    SentinelPairResult,
    find_post_landfall_image,
    find_pre_landfall_image,
    select_sentinel_pair,
)
from app.hazard.validation.benchmark import (
    BlockBenchmarkResult,
    MultiBlockBenchmarkResult,
    generate_benchmark_report,
    run_block_validation,
    run_validation,
)
from app.hazard.validation.calibration import (
    AOI_TOLERANCE_DEG,
    check_flood_calibration,
    check_surge_calibration,
    check_wind_calibration,
    run_full_hazard_calibration,
    validate_all_replay_timesteps,
    validate_demo_fixtures,
    validate_hazard_collection,
    validate_hazard_consistency,
    validate_hazard_layer,
)
from app.hazard.validation.comparison import (
    CellEvaluation,
    HazardComparisonResult,
    compare_hazard_with_sar,
)
from app.hazard.validation.config import (
    BENCHMARK_BLOCK_CODES,
    BLOCK_CODE_TO_NAME,
    VALIDATION_ARTIFACTS_DIR,
    AOIConfig,
    EventConfig,
    FloodExtractionConfig,
    HazardComparisonConfig,
    PreprocessingConfig,
    ValidationPipelineConfig,
)
from app.hazard.validation.datasets import (
    AdminBlock,
    AdminBoundariesDataset,
    DemDataset,
    HazardOutputDataset,
    Sentinel1Dataset,
    SentinelSceneMetadata,
    SurfaceWaterDataset,
)
from app.hazard.validation.export import (
    ExportedArtifacts,
    export_block_validation_artifacts,
    rasterize_cell_evaluations,
    write_geotiff,
)
from app.hazard.validation.flood import (
    apply_flood_thresholding,
    apply_morphological_cleanup,
    calculate_flood_area_km2,
    compute_backscatter_difference,
    extract_flood_mask_gee,
    extract_flood_mask_numpy,
    remove_permanent_water,
)
from app.hazard.validation.metrics import (
    BenchmarkMetrics,
    compute_benchmark_metrics,
)
from app.hazard.validation.preprocessing import (
    apply_speckle_filter,
    numpy_border_noise_removal,
    numpy_speckle_filter,
    preprocess_sentinel_image,
    remove_border_noise,
    reproject_and_clip,
    terrain_mask,
)

__all__ = [
    "AOI_TOLERANCE_DEG",
    "BENCHMARK_BLOCK_CODES",
    "BLOCK_CODE_TO_NAME",
    "VALIDATION_ARTIFACTS_DIR",
    "AOIConfig",
    "AdminBlock",
    "AdminBoundariesDataset",
    "BenchmarkMetrics",
    "BlockBenchmarkResult",
    "CellEvaluation",
    "DemDataset",
    "EventConfig",
    "ExportedArtifacts",
    "FloodExtractionConfig",
    "HazardComparisonConfig",
    "HazardComparisonResult",
    "HazardOutputDataset",
    "MultiBlockBenchmarkResult",
    "PreprocessingConfig",
    "Sentinel1Dataset",
    "SentinelPairResult",
    "SentinelSceneMetadata",
    "SurfaceWaterDataset",
    "ValidationPipelineConfig",
    "apply_flood_thresholding",
    "apply_morphological_cleanup",
    "apply_speckle_filter",
    "calculate_flood_area_km2",
    "check_flood_calibration",
    "check_surge_calibration",
    "check_wind_calibration",
    "compare_hazard_with_sar",
    "compute_backscatter_difference",
    "compute_benchmark_metrics",
    "export_block_validation_artifacts",
    "extract_flood_mask_gee",
    "extract_flood_mask_numpy",
    "find_post_landfall_image",
    "find_pre_landfall_image",
    "generate_benchmark_report",
    "numpy_border_noise_removal",
    "numpy_speckle_filter",
    "preprocess_sentinel_image",
    "rasterize_cell_evaluations",
    "remove_border_noise",
    "remove_permanent_water",
    "reproject_and_clip",
    "run_block_validation",
    "run_full_hazard_calibration",
    "run_validation",
    "select_sentinel_pair",
    "terrain_mask",
    "validate_all_replay_timesteps",
    "validate_demo_fixtures",
    "validate_hazard_collection",
    "validate_hazard_consistency",
    "validate_hazard_layer",
    "write_geotiff",
]
