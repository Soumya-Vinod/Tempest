from fastapi import APIRouter, HTTPException

from app.exposure.service import InfraDataMissing
from app.impact import countdown, service
from app.schemas import (
    ActionCountdown,
    HazardType,
    HorizonParam,
    ImpactResultCollection,
    ImpactStatus,
    TimestepParam,
)

router = APIRouter(prefix="/impact", tags=["impact"])


@router.get("/results")
def get_results(
    timestep: TimestepParam,
    hazard_type: HazardType | None = None,
    status: ImpactStatus | None = None,
    horizon: HorizonParam = 0,
) -> ImpactResultCollection:
    """Impact results (contract §5). horizon=24 (v1.3 change, pending Dev A): on the expected
    hazard over the next 24 h. Sync `def`: it calls Dev A's synchronous get_hazard_layer."""
    try:
        return service.get_results(timestep, hazard_type, status, horizon)
    except NotImplementedError as e:
        detail = str(e)
        if "get_hazard_layer" in detail:
            detail = "hazard layers are not available yet (Dev A's get_hazard_layer)"
        raise HTTPException(status_code=501, detail=detail) from e
    except service.DemoFixtureMissing as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except (InfraDataMissing, service.GraphMissing) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/countdown")
def get_countdown(timestep: TimestepParam) -> ActionCountdown:
    """Action countdown (v1.3 change, pending Dev A): facilities expected to be cut off within
    the forecast window but not yet, soonest first; those already cut off; and the replay's key
    moments. Precomputed (app/impact/countdown.py)."""
    try:
        return countdown.get_countdown(timestep)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except (countdown.CountdownMissing, service.DemoFixtureMissing) as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except (InfraDataMissing, service.GraphMissing) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
