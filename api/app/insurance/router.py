from fastapi import APIRouter, HTTPException

from app.schemas import TimestepParam, TriggerEventCollection

router = APIRouter(prefix="/insurance", tags=["insurance"])


@router.get("/triggers")
def get_triggers(timestep: TimestepParam) -> TriggerEventCollection:
    # TODO: parametric trigger evaluation per zone; "live" -> 501
    raise HTTPException(status_code=501, detail="insurance/triggers: not implemented")
