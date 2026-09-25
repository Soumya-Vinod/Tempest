from fastapi import APIRouter, HTTPException

from app.schemas import HazardType, ImpactResultCollection, ImpactStatus, TimestepParam

router = APIRouter(prefix="/impact", tags=["impact"])


@router.get("/results")
def get_results(
    timestep: TimestepParam,
    hazard_type: HazardType | None = None,
    status: ImpactStatus | None = None,
) -> ImpactResultCollection:
    # TODO: compute impacts from get_hazard_layer + exposure; "live" -> 501
    raise HTTPException(status_code=501, detail="impact/results: not implemented")
