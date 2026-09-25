from fastapi import APIRouter, HTTPException

from app.schemas import InfraFeatureCollection, InfraType

router = APIRouter(prefix="/exposure", tags=["exposure"])


@router.get("/infra")
def get_infra(infra_type: InfraType | None = None) -> InfraFeatureCollection:
    # TODO: return OSM infrastructure in the AOI
    raise HTTPException(status_code=501, detail="exposure/infra: not implemented")
