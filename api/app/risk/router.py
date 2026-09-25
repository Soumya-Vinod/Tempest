from fastapi import APIRouter, HTTPException, Query

from app.exposure.service import InfraDataMissing
from app.impact.service import GraphMissing
from app.risk import service
from app.schemas import RiskScoreCollection, TimestepParam, UnscoredAreaCollection

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/scores")
def get_scores(
    timestep: TimestepParam,
    synthetic: bool = Query(
        False,
        description=(
            "TEMPORARY, development only: use synthetic hazards instead of Dev A's layers. "
            "Only with DEMO_MODE off. Remove once get_hazard_layer is implemented."
        ),
    ),
) -> RiskScoreCollection:
    """Risk score per block (contract §5). Sync `def`: it reaches Dev A's get_hazard_layer."""
    try:
        return service.get_scores(timestep, synthetic)
    except NotImplementedError as e:
        detail = str(e)
        if "get_hazard_layer" in detail:
            detail = "hazard layers are not available yet (Dev A's get_hazard_layer)"
        raise HTTPException(status_code=501, detail=detail) from e
    except service.DemoFixtureMissing as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except service.SyntheticNotAllowed as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (InfraDataMissing, GraphMissing, service.ReferenceDataMissing) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/unscored-areas")
def get_unscored_areas() -> UnscoredAreaCollection:
    """Kolkata and municipal areas outside the CD blocks (v1.1 change, pending Dev A)."""
    try:
        return service.get_unscored_areas()
    except service.ReferenceDataMissing as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
