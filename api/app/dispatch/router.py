"""Dispatch routes (contracts.md §5; receipts, cap.xml and recipients: added in v1.2). Sync
handlers: SMTP, Telegram and SQLite calls block."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from app.dispatch import service
from app.schemas import (
    AdvisoryId,
    DispatchReceipt,
    DispatchReceipts,
    DispatchRecipients,
    DispatchRequest,
)

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

_STATUS: dict[type[Exception], int] = {
    service.NotFound: 404,
    service.Locked: 409,
    service.Forbidden: 403,
    service.RateLimited: 429,
}


def _call(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except tuple(_STATUS) as e:
        raise HTTPException(status_code=_STATUS[type(e)], detail=str(e)) from e


@router.get("/recipients")
def get_recipients() -> DispatchRecipients:
    """Who a dispatch would reach (from api/.env), masked."""
    return service.recipients()


@router.post("/{advisory_id}")
def dispatch_advisory(advisory_id: AdvisoryId, payload: DispatchRequest) -> DispatchReceipt:
    return _call(service.dispatch, advisory_id, payload)


@router.get("/{advisory_id}/receipts")
def get_receipts(advisory_id: AdvisoryId) -> DispatchReceipts:
    return DispatchReceipts(receipts=_call(service.receipts, advisory_id))


@router.get("/{advisory_id}/cap.xml")
def get_cap(advisory_id: AdvisoryId) -> Response:
    xml = _call(service.cap_xml, advisory_id)
    return Response(
        content=xml.encode("utf-8"),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="tempest-cap-{advisory_id}.xml"'},
    )
