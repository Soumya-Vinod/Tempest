from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/advisory", tags=["advisory"])


@router.get("/")
def advisory_stub() -> None:
    # TODO: implement advisory endpoints
    raise HTTPException(status_code=501, detail="advisory: not implemented")
