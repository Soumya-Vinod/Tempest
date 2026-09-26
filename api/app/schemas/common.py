"""Shared enums, ids and the Amphan replay timeline (contracts.md §2–3)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

HazardType = Literal["wind", "surge", "flood"]
InfraType = Literal["substation", "power_line", "road", "hospital", "shelter"]
ImpactStatus = Literal["ok", "at_risk", "cut", "isolated"]
StepType = Literal["hazard", "infra", "service"]
Language = Literal["en", "bn", "hi"]
# "rejected": added in v1.2.
AdvisoryStatus = Literal["draft", "approved", "sent", "rejected"]
# Advisory audit log actions (§4.5, added in v1.2).
AuditAction = Literal[
    "generated",
    "number_check_failed",
    "invalid_response",
    "edited",
    "approved",
    "rejected",
    "new_draft",
    "copied",
    "sent",
    "dispatched",  # one per channel attempt, incl. dry runs (added in v1.2)
]
TriggerMetric = Literal["wind_speed", "surge_depth"]
BlockSource = Literal["census2011_cd", "h3_r7"]
# The largest contributing part of a RiskScore (§4.4, added in v1.1).
RiskDriver = Literal[
    "surge",
    "wind",
    "flood",
    "isolated_facilities",
    "cut_roads",
    "cut_substations",
    "population_density",
    "hospital_access",
    "low_literacy",
    "mapped_shelters",
]
# How the cyclone reaches a block: hazard on its inhabited land, or cut off (exposure)
# (§4.4 risk breakdown, added in v1.1).
RiskReach = Literal["direct", "cut_off"]
Channel = Literal["telegram", "email"]
# Forecast horizon in hours (v1.3 change, pending Dev A): 0 = now (the observed hazard), 24 =
# expected within 24 h (the cell-wise max of the hazard over the next 24 h; a perfect-forecast
# replay, see app/impact/horizon.py).
Horizon = Literal[0, 24]


def _int_from_query(value: object) -> object:
    """Query strings arrive as text; a Literal of ints doesn't coerce "24" on its own."""
    return int(value) if isinstance(value, str) and value.isdigit() else value


# The `horizon` query parameter: "0" or "24" (anything else: 422).
HorizonParam = Annotated[Horizon, BeforeValidator(_int_from_query)]
# The model that wrote an advisory draft (added in v1.2).
ModelProvider = Literal["gemini", "groq"]
# dry_run: built and validated, not sent (added in v1.2).
ChannelStatus = Literal["sent", "failed", "dry_run"]

TIMESTEP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
LANDFALL = datetime(2020, 5, 20, 12, tzinfo=UTC)
REPLAY_START = LANDFALL - timedelta(hours=72)
REPLAY_STEP = timedelta(hours=3)
REPLAY_TIMESTEPS: tuple[str, ...] = tuple(
    (REPLAY_START + i * REPLAY_STEP).strftime(TIMESTEP_FORMAT) for i in range(25)
)
LANDFALL_TIMESTEP = LANDFALL.strftime(TIMESTEP_FORMAT)
LIVE = "live"

_REPLAY_SET = frozenset(REPLAY_TIMESTEPS)


def _check_timestep(value: str) -> str:
    if value not in _REPLAY_SET:
        raise ValueError("timestep must be one of the 25 Amphan replay keys")
    return value


def _check_timestep_param(value: str) -> str:
    return value if value == LIVE else _check_timestep(value)


# In responses: a replay key only.
Timestep = Annotated[str, AfterValidator(_check_timestep)]
# In parameters: a replay key or "live" (501 / NotImplementedError in v1.1).
TimestepParam = Annotated[str, AfterValidator(_check_timestep_param)]

BlockId = Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
# Lowercase UUID4 in practice; fixture-safe for advisory__item-<id> / dispatch__receipt-<id>.
AdvisoryId = Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
UnitFraction = Annotated[float, Field(ge=0, le=1)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
