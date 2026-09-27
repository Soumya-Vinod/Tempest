"""Hazard API endpoints for replay timeline, hazard layers, and Sentinel-1 validation."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.hazard import service
from app.hazard.models import (
    CycloneTrack,
    HazardLayerCollection,
    HazardType,
    ReplayTimeline,
    TimestepParam,
)
from app.hazard.validation import service as val_service
from app.schemas.common import LIVE

router = APIRouter(prefix="/hazard", tags=["hazard"])


@router.get("/timesteps", response_model=ReplayTimeline)
def get_timesteps() -> ReplayTimeline:
    """Return the Cyclone Amphan replay timeline and landfall timestamp."""
    return service.get_replay_timeline()


@router.get("/track", response_model=CycloneTrack)
def get_track() -> CycloneTrack:
    """The 25-point Amphan replay track (contracts.md §5, internal)."""
    return CycloneTrack(points=list(service.get_replay_track()))


@router.get("/layers", response_model=HazardLayerCollection)
def get_layers(hazard_type: HazardType, timestep: TimestepParam) -> HazardLayerCollection:
    """Return hazard layer polygons for a specific hazard type and replay timestep.

    Live mode ('timestep=live') returns 501 Not Implemented in v0.9.
    Sync handler by contract so FastAPI runs it in the threadpool.
    """
    if timestep == LIVE:
        raise HTTPException(status_code=501, detail="live mode is not implemented in v0.9")

    try:
        return service.get_hazard_layer(hazard_type, timestep)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Sentinel-1 Observational Validation Endpoints (Phase 10)
# ---------------------------------------------------------------------------
@router.get("/validation")
def get_validation_overview() -> dict:
    """Overview summary of Sentinel-1 observational validation across all benchmarked blocks."""
    return val_service.get_validation_overview()


@router.get("/validation/{block}")
def get_block_validation(block: str) -> dict:
    """Detailed Sentinel-1 validation report for a specific coastal administrative block."""
    res = val_service.get_block_validation(block)
    if res is None:
        raise HTTPException(
            status_code=404,
            detail=f"Administrative block '{block}' not found in validation benchmark suite.",
        )
    return res


@router.get("/validation/{block}/metrics")
def get_block_metrics(block: str) -> dict:
    """Quantitative validation metrics and confusion matrix for a specific block."""
    res = val_service.get_block_metrics(block)
    if res is None:
        raise HTTPException(
            status_code=404,
            detail=f"Administrative block '{block}' metrics not found.",
        )
    return res


@router.get("/validation/{block}/artifacts")
def get_block_artifacts(block: str) -> dict:
    """List available exported artifacts (GeoTIFFs, GeoJSONs, JSON) for a block."""
    res = val_service.get_block_artifacts(block)
    if res is None:
        raise HTTPException(
            status_code=404,
            detail=f"Artifacts for block '{block}' not found.",
        )
    return res


@router.get("/validation/{block}/artifacts/{artifact_name}")
def download_block_artifact(block: str, artifact_name: str) -> FileResponse:
    """Download an exported validation artifact (GeoTIFF, GeoJSON, or JSON)."""
    file_path = val_service.get_artifact_file_path(block, artifact_name)
    if file_path is None or not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Artifact '{artifact_name}' for block '{block}' not found.",
        )

    suffix = file_path.suffix.lower()
    media_types = {
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".geojson": "application/geo+json",
        ".json": "application/json",
        ".md": "text/markdown",
    }
    media_type = media_types.get(suffix, "application/octet-stream")
    return FileResponse(path=file_path, media_type=media_type, filename=file_path.name)
