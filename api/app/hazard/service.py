"""Dev A → Dev B internal interface and hazard service operations (shared/contracts.md §6)."""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.demo import load_fixture
from app.hazard.models import (
    HazardLayerCollection,
    HazardType,
    ReplayTimeline,
)
from app.hazard.replay import (
    generate_hazard_layer,
    iso_to_compact_ts,
)
from app.schemas.common import (
    LANDFALL_TIMESTEP,
    LIVE,
    REPLAY_TIMESTEPS,
)

logger = logging.getLogger(__name__)

# In-memory layer cache to make repeated synchronous queries instantaneous
_LAYER_CACHE: dict[tuple[HazardType, str], HazardLayerCollection] = {}


def get_replay_timeline() -> ReplayTimeline:
    """Return the 25-step Cyclone Amphan replay timeline and landfall timestamp."""
    settings = get_settings()
    if settings.DEMO_MODE:
        try:
            data = load_fixture("hazard__timesteps")
            if data is not None:
                return ReplayTimeline.model_validate(data)
        except Exception as e:
            logger.debug("Demo fixture hazard__timesteps not loaded: %s; using default", e)

    return ReplayTimeline(
        event="amphan",
        landfall=LANDFALL_TIMESTEP,
        timesteps=list(REPLAY_TIMESTEPS),
    )


def get_hazard_layer(hazard_type: HazardType, timestep: str) -> HazardLayerCollection:
    """Return one hazard layer for a replay timestep.

    `timestep` is a TimestepParam: "live" raises NotImplementedError in v0.9 and any
    other value outside the replay list raises ValueError. Sync by contract, so routes
    calling this must be `def`, not `async def`.
    """
    if timestep == LIVE:
        raise NotImplementedError("live mode is reserved and not implemented in v0.9")

    if timestep not in REPLAY_TIMESTEPS:
        raise ValueError(
            f"Invalid timestep: {timestep!r}; must be one of the 25 Amphan replay keys"
        )

    if hazard_type not in ("wind", "surge", "flood"):
        raise ValueError(
            f"Invalid hazard_type: {hazard_type!r}; must be 'wind', 'surge', or 'flood'"
        )

    cache_key = (hazard_type, timestep)
    if cache_key in _LAYER_CACHE:
        return _LAYER_CACHE[cache_key]

    settings = get_settings()
    compact_ts = iso_to_compact_ts(timestep)

    # 1. Attempt fixture load in DEMO_MODE
    if settings.DEMO_MODE:
        fixture_key = f"hazard__layers-{hazard_type}__{compact_ts}"
        try:
            fixture_data = load_fixture(fixture_key)
            if fixture_data is not None:
                layer_col = HazardLayerCollection.model_validate(fixture_data)
                _LAYER_CACHE[cache_key] = layer_col
                return layer_col
        except Exception as e:
            logger.debug(
                "Fixture %s not loaded: %s; falling back to replay generation",
                fixture_key,
                e,
            )

    # 2. Compute via replay physics engine
    layer_col = generate_hazard_layer(hazard_type, timestep)
    _LAYER_CACHE[cache_key] = layer_col
    return layer_col
