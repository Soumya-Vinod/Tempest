"""Hazard API endpoints for replay timeline and hazard layers (shared/contracts.md §5)."""

from fastapi import APIRouter, HTTPException

from app.hazard import service
from app.hazard.models import (
    HazardLayerCollection,
    HazardType,
    ReplayTimeline,
    TimestepParam,
)
from app.schemas.common import LIVE

router = APIRouter(prefix="/hazard", tags=["hazard"])


@router.get("/timesteps", response_model=ReplayTimeline)
def get_timesteps() -> ReplayTimeline:
    """Return the Cyclone Amphan replay timeline and landfall timestamp."""
    return service.get_replay_timeline()


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
