from fastapi import APIRouter, HTTPException

from app.schemas import RiskScoreCollection, TimestepParam

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/scores")
def get_scores(timestep: TimestepParam) -> RiskScoreCollection:
    # TODO: per-block risk scores; "live" -> 501
    raise HTTPException(status_code=501, detail="risk/scores: not implemented")
