from fastapi import APIRouter, HTTPException

from app.exposure.service import InfraDataMissing
from app.impact.service import GraphMissing
from app.risk import service
from app.schemas import (
    HorizonParam,
    RiskBreakdown,
    RiskScoreCollection,
    TimestepParam,
    UnscoredAreaCollection,
)

router = APIRouter(prefix="/risk", tags=["risk"])


def _call(fn, *args):
    try:
        return fn(*args)
    except NotImplementedError as e:
        detail = str(e)
        if "get_hazard_layer" in detail:
            detail = "hazard layers are not available yet (Dev A's get_hazard_layer)"
        raise HTTPException(status_code=501, detail=detail) from e
    except service.DemoFixtureMissing as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except (InfraDataMissing, GraphMissing, service.ReferenceDataMissing) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/scores")
def get_scores(timestep: TimestepParam, horizon: HorizonParam = 0) -> RiskScoreCollection:
    """Risk score per block (contract §5); horizon=24: expected within 24 h (v1.3 change,
    pending Dev A). Sync `def`: it reaches Dev A's get_hazard_layer."""
    return _call(service.get_scores, timestep, horizon)


@router.get("/breakdown")
def get_breakdown(timestep: TimestepParam, horizon: HorizonParam = 0) -> RiskBreakdown:
    """Per-block parts, population and hospital travel time (added in v1.1); horizon as for
    the scores."""
    return _call(service.get_breakdown, timestep, horizon)


@router.get("/unscored-areas")
def get_unscored_areas() -> UnscoredAreaCollection:
    """Kolkata and municipal areas outside the CD blocks (added in v1.1)."""
    return _call(service.get_unscored_areas)
