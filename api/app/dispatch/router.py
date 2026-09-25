from fastapi import APIRouter, HTTPException

from app.schemas import DispatchReceipt, DispatchRequest

router = APIRouter(prefix="/dispatch", tags=["dispatch"])


@router.post("/{advisory_id}")
def dispatch_advisory(advisory_id: str, payload: DispatchRequest) -> DispatchReceipt:
    # TODO: send via Telegram / Resend; approved only, else 409; advisory -> sent
    raise HTTPException(status_code=501, detail="dispatch: not implemented")
