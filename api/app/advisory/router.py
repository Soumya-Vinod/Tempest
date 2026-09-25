from fastapi import APIRouter, HTTPException

from app.schemas import (
    Advisory,
    AdvisoryApprove,
    AdvisoryCollection,
    AdvisoryCreate,
    AdvisoryStatus,
    AdvisoryUpdate,
    BlockId,
)

router = APIRouter(prefix="/advisory", tags=["advisory"])


@router.get("/")
def list_advisories(
    status: AdvisoryStatus | None = None, block_id: BlockId | None = None
) -> AdvisoryCollection:
    # TODO: list advisories
    raise HTTPException(status_code=501, detail="advisory: not implemented")


@router.post("/")
def create_advisory(payload: AdvisoryCreate) -> Advisory:
    # TODO: draft via Gemini (structured output, no numbers); "live" -> 501
    raise HTTPException(status_code=501, detail="advisory: not implemented")


@router.get("/{advisory_id}")
def get_advisory(advisory_id: str) -> Advisory:
    # TODO: fetch one advisory; 404 if unknown
    raise HTTPException(status_code=501, detail="advisory: not implemented")


@router.patch("/{advisory_id}")
def update_advisory(advisory_id: str, payload: AdvisoryUpdate) -> Advisory:
    # TODO: edit body; draft only, else 409
    raise HTTPException(status_code=501, detail="advisory: not implemented")


@router.post("/{advisory_id}/approve")
def approve_advisory(advisory_id: str, payload: AdvisoryApprove) -> Advisory:
    # TODO: draft -> approved; else 409
    raise HTTPException(status_code=501, detail="advisory: not implemented")
