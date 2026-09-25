from fastapi import APIRouter, HTTPException

from app.schemas import HazardLayerCollection, HazardType, ReplayTimeline, TimestepParam

router = APIRouter(prefix="/hazard", tags=["hazard"])


@router.get("/timesteps")
def get_timesteps() -> ReplayTimeline:
    # TODO(Dev A): return the Amphan replay timeline
    raise HTTPException(status_code=501, detail="hazard/timesteps: not implemented")


@router.get("/layers")
def get_layers(hazard_type: HazardType, timestep: TimestepParam) -> HazardLayerCollection:
    # TODO(Dev A): return get_hazard_layer(hazard_type, timestep); "live" -> 501
    raise HTTPException(status_code=501, detail="hazard/layers: not implemented")
