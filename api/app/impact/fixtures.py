"""Compact DEMO_MODE fixtures for impact results (contracts.md §7, added in v1.1).

A fixture stores only the non-ok rows. Loading adds an ok row (empty pathway) for every infra
feature and hazard type not present, in compute_impacts order, so the response is exactly what
compute_impacts would return.
"""

from app.impact.engine import HAZARD_TYPES
from app.schemas import (
    ImpactResult,
    ImpactResultCollection,
    ImpactResultProperties,
    InfraFeatureCollection,
)


def compact_timestep(timestep: str) -> str:
    """2020-05-20T12:00:00Z -> 20200520T1200Z (fixture key form, contracts.md §7)."""
    return timestep.replace("-", "").replace(":", "")[:13] + "Z"


def fixture_key(timestep: str) -> str:
    return f"impact__results__{compact_timestep(timestep)}"


def to_fixture(results: ImpactResultCollection) -> dict:
    """The non-ok rows only, as JSON-ready data."""
    kept = [f for f in results.features if f.properties.status != "ok"]
    return ImpactResultCollection(features=kept).model_dump(mode="json")


def from_fixture(
    fixture: dict, infra: InfraFeatureCollection, timestep: str
) -> ImpactResultCollection:
    """Rebuild the full collection: fixture rows plus ok rows for everything else."""
    stored = {row["id"]: row for row in fixture["features"]}
    results = []
    for f in infra.features:
        for h in HAZARD_TYPES:
            rid = f"{f.id}__{h}__{timestep}"
            if rid in stored:
                results.append(ImpactResult.model_validate(stored.pop(rid)))
                continue
            results.append(
                ImpactResult(
                    id=rid,
                    geometry=f.geometry,
                    properties=ImpactResultProperties(
                        id=rid,
                        infra_id=f.id,
                        hazard_type=h,
                        status="ok",
                        timestep=timestep,
                        pathway=[],
                    ),
                )
            )
    if stored:
        raise ValueError(f"fixture rows for unknown infra features: {sorted(stored)[:3]}…")
    return ImpactResultCollection(features=results)
