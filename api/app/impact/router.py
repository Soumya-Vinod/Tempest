from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/impact", tags=["impact"])


@router.get("/")
def impact_stub() -> None:
    # TODO: implement impact endpoints
    raise HTTPException(status_code=501, detail="impact: not implemented")
