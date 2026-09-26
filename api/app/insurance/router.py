"""Insurance routes (contracts.md §5; /summary: v1.2 change, pending Dev A). ILLUSTRATIVE terms."""

from fastapi import APIRouter, HTTPException

from app.exposure.service import InfraDataMissing
from app.impact.service import GraphMissing
from app.insurance import service
from app.schemas import InsuranceSummary, TimestepParam, TriggerEventCollection

router = APIRouter(prefix="/insurance", tags=["insurance"])


def _call(fn, *args):
    try:
        return fn(*args)
    except NotImplementedError as e:
        detail = str(e)
        if "get_hazard_layer" in detail:
            detail = "hazard layers are not available yet (Dev A's get_hazard_layer)"
        raise HTTPException(status_code=501, detail=detail) from e
    except service.DemoFixtureMissing as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except (InfraDataMissing, GraphMissing, service.ReferenceDataMissing) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/triggers")
def get_triggers(timestep: TimestepParam) -> TriggerEventCollection:
    """One TriggerEvent per CD block: the current reading and the amount released so far."""
    return _call(service.get_triggers, timestep)


@router.get("/summary")
def get_summary() -> InsuranceSummary:
    """Released district totals per timestep and each block's first trigger (v1.2)."""
    return _call(service.get_summary)
