from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/insurance", tags=["insurance"])


@router.get("/")
def insurance_stub() -> None:
    # TODO: implement insurance endpoints
    raise HTTPException(status_code=501, detail="insurance: not implemented")
