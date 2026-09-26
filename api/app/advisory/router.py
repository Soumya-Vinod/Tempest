"""Advisory routes (contracts.md §5; reject, new-draft, suggestions and audit: v1.2 change,
pending Dev A). Sync handlers: Gemini and SQLite calls block."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from app.advisory import service, store
from app.exposure.service import InfraDataMissing
from app.impact.service import DemoFixtureMissing, GraphMissing
from app.risk.blocks import ReferenceDataMissing
from app.schemas import (
    Advisory,
    AdvisoryApprove,
    AdvisoryCollection,
    AdvisoryCreate,
    AdvisoryNewDraft,
    AdvisoryReject,
    AdvisoryStatus,
    AdvisorySuggestions,
    AdvisoryUpdate,
    AuditLog,
    BlockId,
    Timestep,
    TimestepParam,
)

router = APIRouter(prefix="/advisory", tags=["advisory"])


def _call(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except DemoFixtureMissing as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except (service.NotFound, service.UnknownBlock) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.Locked as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except service.Invalid as e:
        detail = {"message": str(e), "problems": e.problems} if e.problems else str(e)
        raise HTTPException(status_code=422, detail=detail) from e
    except service.DraftRejected as e:
        detail = {"message": str(e), "problems": e.problems} if e.problems else str(e)
        raise HTTPException(status_code=502, detail=detail) from e
    except (service.GeminiUnavailable, InfraDataMissing, GraphMissing, ReferenceDataMissing) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/")
def list_advisories(
    status: AdvisoryStatus | None = None,
    block_id: BlockId | None = None,
    timestep: Timestep | None = None,
) -> AdvisoryCollection:
    return AdvisoryCollection(features=store.list_advisories(status, block_id, timestep))


@router.post("/")
def create_advisory(payload: AdvisoryCreate) -> Advisory:
    """Draft via Gemini (or its cached response in DEMO_MODE) for one block and timestep."""
    return _call(service.create, payload.block_id, payload.timestep)


@router.get("/suggestions")
def get_suggestions(timestep: TimestepParam) -> AdvisorySuggestions:
    """Blocks at or above the suggestion threshold (v1.2 change, pending Dev A)."""
    return _call(service.suggestions, timestep)


@router.get("/audit")
def get_audit_log() -> AuditLog:
    """Every audit event, including generations that produced no advisory (v1.2, pending)."""
    return AuditLog(events=store.events())


@router.get("/{advisory_id}")
def get_advisory(advisory_id: str) -> Advisory:
    return _call(service.get, advisory_id)


@router.patch("/{advisory_id}")
def update_advisory(advisory_id: str, payload: AdvisoryUpdate) -> Advisory:
    return _call(service.edit, advisory_id, payload.templates, payload.edited_by)


@router.post("/{advisory_id}/approve")
def approve_advisory(advisory_id: str, payload: AdvisoryApprove) -> Advisory:
    return _call(service.approve, advisory_id, payload.approved_by)


@router.post("/{advisory_id}/reject")
def reject_advisory(advisory_id: str, payload: AdvisoryReject) -> Advisory:
    """draft -> rejected; a reason is required (v1.2 change, pending Dev A)."""
    return _call(service.reject, advisory_id, payload.reason, payload.rejected_by)


@router.post("/{advisory_id}/new-draft")
def new_draft(advisory_id: str, payload: AdvisoryNewDraft | None = None) -> Advisory:
    """Copy a finished advisory into a new draft (v1.2 change, pending Dev A)."""
    return _call(service.new_draft, advisory_id, payload.created_by if payload else None)


@router.get("/{advisory_id}/audit")
def get_advisory_audit(advisory_id: str) -> AuditLog:
    """The advisory's audit events, oldest first (v1.2 change, pending Dev A)."""
    _call(service.get, advisory_id)
    return AuditLog(events=store.events(advisory_id))
