from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/dispatch", tags=["dispatch"])


@router.get("/")
def dispatch_stub() -> None:
    # TODO: implement dispatch endpoints
    raise HTTPException(status_code=501, detail="dispatch: not implemented")
