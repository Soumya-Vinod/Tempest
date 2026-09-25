from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/hazard", tags=["hazard"])


@router.get("/")
def hazard_stub() -> None:
    # TODO: implement hazard endpoints
    raise HTTPException(status_code=501, detail="hazard: not implemented")
