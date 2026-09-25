from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/exposure", tags=["exposure"])


@router.get("/")
def exposure_stub() -> None:
    # TODO: implement exposure endpoints
    raise HTTPException(status_code=501, detail="exposure: not implemented")
