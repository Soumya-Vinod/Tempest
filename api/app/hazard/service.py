"""Dev A → Dev B internal interface (shared/contracts.md §6)."""

from app.schemas import HazardLayerCollection, HazardType


def get_hazard_layer(hazard_type: HazardType, timestep: str) -> HazardLayerCollection:
    """Return one hazard layer for a replay timestep.

    `timestep` is a TimestepParam: "live" raises NotImplementedError in v0.9 and any
    other value outside the replay list raises ValueError. Sync by contract, so routes
    calling this must be `def`, not `async def`.
    """
    # TODO(Dev A): implement; serve hazard__layers-<hazard_type>__<ts> in DEMO_MODE.
    raise NotImplementedError("get_hazard_layer: not implemented")
