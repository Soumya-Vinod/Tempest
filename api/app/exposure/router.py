from fastapi import APIRouter, HTTPException

from app.exposure import service
from app.schemas import InfraFeatureCollection, InfraType

router = APIRouter(prefix="/exposure", tags=["exposure"])


@router.get("/infra")
def get_infra(infra_type: InfraType | None = None) -> InfraFeatureCollection:
    """OSM infrastructure in the AOI, optionally one infra_type (contract §5). Sync `def`: the
    first call loads infra.parquet or the demo fixtures, which FastAPI runs in its threadpool."""
    try:
        return service.get_infra(infra_type)
    except service.InfraDataMissing as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
