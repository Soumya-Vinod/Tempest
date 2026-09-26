"""Compact DEMO_MODE fixtures for risk scores (contracts.md §7, v1.1 change pending Dev A).

A risk__scores__<ts> fixture stores each RiskScore without its block polygon, which is the same
at every timestep. Loading adds the geometry back from s24p_blocks.geojson (the same display
geometry the live route uses), so the response is exactly what to_collection returns.
The breakdown has no geometry, so its fixture is the response as is.
"""

from app.risk.blocks import Blocks
from app.schemas import RiskScoreCollection


def to_fixture(scores: RiskScoreCollection) -> dict:
    """The collection as JSON-ready data, without geometry."""
    data = scores.model_dump(mode="json")
    for f in data["features"]:
        del f["geometry"]
    return data


def from_fixture(fixture: dict, blocks: Blocks) -> RiskScoreCollection:
    """Add each block's display geometry back, by block_id."""
    geometry = dict(zip(blocks.codes, blocks.display, strict=True))
    features = []
    for f in fixture["features"]:
        block_id = f["properties"]["block_id"]
        if block_id not in geometry:
            raise ValueError(f"fixture row for unknown block {block_id!r}")
        features.append({**f, "geometry": geometry[block_id]})
    return RiskScoreCollection.model_validate({**fixture, "features": features})
