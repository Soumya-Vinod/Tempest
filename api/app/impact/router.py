from fastapi import APIRouter, HTTPException

from app.exposure.service import InfraDataMissing
from app.impact import service
from app.schemas import HazardType, ImpactResultCollection, ImpactStatus, TimestepParam

router = APIRouter(prefix="/impact", tags=["impact"])


@router.get("/results")
def get_results(
    timestep: TimestepParam,
    hazard_type: HazardType | None = None,
    status: ImpactStatus | None = None,
) -> ImpactResultCollection:
    """Impact results (contract §5). Sync `def`: it calls Dev A's synchronous get_hazard_layer."""
    try:
        return service.get_results(timestep, hazard_type, status)
    except NotImplementedError as e:
        detail = str(e)
        if "get_hazard_layer" in detail:
            detail = "hazard layers are not available yet (Dev A's get_hazard_layer)"
        raise HTTPException(status_code=501, detail=detail) from e
    except service.DemoFixtureMissing as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except (InfraDataMissing, service.GraphMissing) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
