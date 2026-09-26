"""Dev A → Dev B internal interface and hazard service operations (shared/contracts.md §6)."""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.demo import load_fixture
from app.hazard.models import (
    CycloneTrack,
    CycloneTrackPoint,
    HazardLayerCollection,
    HazardType,
    ReplayTimeline,
)
from app.hazard.replay import (
    create_replay_timeline,
    generate_flood_layer,
    generate_hazard_layer,
    generate_surge_layer,
    generate_wind_layer,
    iso_to_compact_ts,
    validate_timestep,
)
from app.hazard.replay import (
    get_replay_track as replay_get_track,
)
from app.schemas.common import LIVE

logger = logging.getLogger(__name__)

# In-memory layer cache to make repeated synchronous queries instantaneous
_LAYER_CACHE: dict[tuple[HazardType, str], HazardLayerCollection] = {}


def get_replay_timeline() -> ReplayTimeline:
    """Return the 25-step Cyclone Amphan replay timeline and landfall timestamp.

    Checks for demo fixture hazard__timesteps when DEMO_MODE is active,
    falling back to the canonical ReplayTimeline model.
    """
    settings = get_settings()
    if settings.DEMO_MODE:
        try:
            data = load_fixture("hazard__timesteps")
            if data is not None:
                return ReplayTimeline.model_validate(data)
        except Exception as e:
            logger.debug("Demo fixture hazard__timesteps not loaded: %s; using default", e)

    return create_replay_timeline()


def get_replay_track() -> tuple[CycloneTrackPoint, ...]:
    """Return the canonical immutable 25-point Cyclone Amphan replay track.

    In DEMO_MODE, attempts to load from fixture hazard__track if available;
    otherwise returns the canonical computed track.
    """
    settings = get_settings()
    if settings.DEMO_MODE:
        try:
            data = load_fixture("hazard__track")
            if data is not None:
                track_model = CycloneTrack.model_validate(data)
                return tuple(track_model.points)
        except Exception as e:
            logger.debug("Demo fixture hazard__track not loaded: %s; using canonical track", e)

    return replay_get_track()


def get_hazard_layer(hazard_type: HazardType, timestep: str) -> HazardLayerCollection:
    """Return one hazard layer for a replay timestep.

    Validation rules (shared/contracts.md §2, §6):
    - Validates timestep via validate_timestep().
    - 'live' raises NotImplementedError in v0.9.
    - Other invalid timesteps raise ValueError.
    - Sync by contract, so routes calling this must be def, not async def.
    """
    clean_ts = validate_timestep(timestep)
    if clean_ts == LIVE:
        raise NotImplementedError("live mode is reserved and not implemented in v0.9")

    if hazard_type not in ("wind", "surge", "flood"):
        raise ValueError(
            f"Invalid hazard_type: {hazard_type!r}; must be 'wind', 'surge', or 'flood'"
        )

    cache_key = (hazard_type, clean_ts)
    if cache_key in _LAYER_CACHE:
        return _LAYER_CACHE[cache_key]

    settings = get_settings()
    compact_ts = iso_to_compact_ts(clean_ts)

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
    if hazard_type == "wind":
        layer_col = generate_wind_layer(clean_ts)
    elif hazard_type == "surge":
        layer_col = generate_surge_layer(clean_ts)
    elif hazard_type == "flood":
        layer_col = generate_flood_layer(clean_ts)
    else:
        layer_col = generate_hazard_layer(hazard_type, clean_ts)
    _LAYER_CACHE[cache_key] = layer_col
    return layer_col
