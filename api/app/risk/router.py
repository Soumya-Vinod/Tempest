from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/")
def risk_stub() -> None:
    # TODO: implement risk endpoints
    raise HTTPException(status_code=501, detail="risk: not implemented")
