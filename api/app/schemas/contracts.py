"""Pydantic mirror of shared/contracts.md v1.1 (FROZEN).

Keep in sync with web/src/types/contracts.ts.
"""

from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.common import (
    AdvisoryId,
    AdvisoryStatus,
    AuditAction,
    BlockId,
    BlockSource,
    Channel,
    ChannelStatus,
    ContractModel,
    HazardType,
    ImpactStatus,
    InfraType,
    RiskDriver,
    RiskReach,
    StepType,
    Timestep,
    TimestepParam,
    TriggerMetric,
    UnitFraction,
)
from app.schemas.geojson import AreaGeometry, Feature, FeatureCollection, InfraGeometry

HAZARD_UNITS: dict[str, str] = {"wind": "m/s", "surge": "m", "flood": "index"}
METRIC_UNITS: dict[str, str] = {"wind_speed": "m/s", "surge_depth": "m"}
# <infra_type with - for _>-<osm_type>-<osm_number>, e.g. power-line-way-123 (§4.2, added in v0.9).
INFRA_ID_PATTERN = r"^(substation|power-line|road|hospital|shelter)-(node|way|relation)-\d+$"


# --- 4.1 HazardLayer (Dev A) ---


class HazardLayerProperties(ContractModel):
    """Properties for a single hazard cell feature (shared/contracts.md §4.1).

    Attributes:
        id: Unique identifier within a (hazard_type, timestep) collection.
        hazard_type: Physical hazard category ('wind', 'surge', or 'flood').
        timestep: ISO 8601 UTC timestamp of one of the 25 Amphan replay timesteps.
        value: Physical magnitude in unit (m/s for wind, m for surge, 0-1 for flood).
        unit: Required unit of measurement ('m/s' for wind, 'm' for surge, 'index' for flood).
        severity: Normalized severity score in [0, 1].
    """

    id: str
    hazard_type: HazardType
    timestep: Timestep
    value: float
    unit: Literal["m/s", "m", "index"]
    severity: UnitFraction

    @model_validator(mode="after")
    def _unit_matches_hazard(self) -> Self:
        if self.unit != HAZARD_UNITS[self.hazard_type]:
            raise ValueError(f"{self.hazard_type} must use unit {HAZARD_UNITS[self.hazard_type]}")
        return self


class HazardLayer(Feature):
    """GeoJSON Feature representing a single hazard cell or polygon (shared/contracts.md §4.1).

    Geometry must be an AreaGeometry (Polygon or MultiPolygon) in EPSG:4326.
    Feature.id must strictly equal properties.id.
    """

    geometry: AreaGeometry
    properties: HazardLayerProperties

    @model_validator(mode="before")
    @classmethod
    def _nest_properties_if_flat(cls, data: Any) -> Any:
        """Allow convenience flat construction by packaging hazard fields into properties."""
        if isinstance(data, dict) and "properties" not in data:
            prop_keys = {"hazard_type", "timestep", "value", "unit", "severity"}
            if prop_keys.issubset(data.keys()):
                data = dict(data)
                props = {k: data.pop(k) for k in prop_keys}
                props["id"] = data.get("id")
                data["properties"] = props
        return data

    @property
    def hazard_type(self) -> HazardType:
        """Hazard type from properties ('wind', 'surge', or 'flood')."""
        return self.properties.hazard_type

    @property
    def timestep(self) -> Timestep:
        """Replay timestep from properties (ISO 8601 UTC)."""
        return self.properties.timestep

    @property
    def value(self) -> float:
        """Physical magnitude value from properties in unit."""
        return self.properties.value

    @property
    def unit(self) -> Literal["m/s", "m", "index"]:
        """Unit of measurement from properties ('m/s', 'm', or 'index')."""
        return self.properties.unit

    @property
    def severity(self) -> UnitFraction:
        """Normalized hazard severity score from properties in [0, 1]."""
        return self.properties.severity


class HazardLayerCollection(FeatureCollection[HazardLayer]):
    """GeoJSON FeatureCollection containing HazardLayer features (shared/contracts.md §4.1).

    Root object returned by GET /api/hazard/layers and get_hazard_layer().
    """

    pass


# --- 4.2 InfraFeature (Dev B) ---


class InfraFeatureProperties(ContractModel):
    id: str = Field(pattern=INFRA_ID_PATTERN)
    infra_type: InfraType
    name: str | None
    osm_id: str | None = Field(pattern=r"^(node|way|relation)/\d+$")
    attributes: dict[str, Any] = Field(default_factory=dict)


class InfraFeature(Feature):
    geometry: InfraGeometry
    properties: InfraFeatureProperties


class InfraFeatureCollection(FeatureCollection[InfraFeature]):
    pass


# --- 4.3 ImpactResult (Dev B) ---


class PathwayStep(ContractModel):
    id: str
    label: str
    type: StepType


class ImpactResultProperties(ContractModel):
    id: str
    infra_id: str
    hazard_type: HazardType
    status: ImpactStatus
    timestep: Timestep
    pathway: list[PathwayStep]

    @model_validator(mode="after")
    def _ok_has_no_pathway(self) -> Self:
        if self.status == "ok" and self.pathway:
            raise ValueError("pathway must be empty when status is 'ok'")
        return self


class ImpactResult(Feature):
    geometry: InfraGeometry
    properties: ImpactResultProperties


class ImpactResultCollection(FeatureCollection[ImpactResult]):
    pass


# --- 4.4 RiskScore (Dev B) ---


class RiskComponents(ContractModel):
    hazard: UnitFraction
    exposure: UnitFraction
    vulnerability: UnitFraction


class RiskScoreProperties(ContractModel):
    id: str
    block_id: BlockId
    block_source: BlockSource
    block_name: str
    timestep: Timestep
    score: UnitFraction
    components: RiskComponents
    # added in v1.1: the largest contributing part; null when score is 0.
    top_driver: RiskDriver | None = None


class RiskScore(Feature):
    geometry: AreaGeometry
    properties: RiskScoreProperties


class RiskScoreCollection(FeatureCollection[RiskScore]):
    pass


# Areas inside the AOI clip that no block covers (§4.4, added in v1.1).
class UnscoredAreaProperties(ContractModel):
    id: str
    label: str
    area_km2: float = Field(ge=0)


class UnscoredArea(Feature):
    geometry: AreaGeometry
    properties: UnscoredAreaProperties


class UnscoredAreaCollection(FeatureCollection[UnscoredArea]):
    pass


# Per-block parts behind a RiskScore (§4.4, added in v1.1). Each part is 0-1.
class RiskHazardParts(ContractModel):
    surge: UnitFraction
    wind: UnitFraction
    flood: UnitFraction


class RiskExposureParts(ContractModel):
    isolated_facilities: UnitFraction
    cut_roads: UnitFraction
    cut_substations: UnitFraction


class RiskVulnerabilityParts(ContractModel):
    population_density: UnitFraction
    hospital_access: UnitFraction
    low_literacy: UnitFraction
    mapped_shelters: UnitFraction


class RiskBlockBreakdown(ContractModel):
    block_id: BlockId
    block_name: str
    population_2011: int = Field(ge=0)
    hospital_travel_min: float | None = Field(ge=0)  # null: no road node reaches a hospital
    reach: RiskReach  # which of hazard or exposure scaled the score
    hazard: RiskHazardParts
    exposure: RiskExposureParts
    vulnerability: RiskVulnerabilityParts


class RiskBreakdown(ContractModel):
    timestep: Timestep
    blocks: list[RiskBlockBreakdown]


# --- 4.5 Advisory (Dev B) ---


class Citation(ContractModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str
    value: float | str  # str: v1.2 change, pending Dev A (names, causes)
    unit: str | None
    source: str


# v1.2 change, pending Dev A: one Advisory per block and timestep with all three languages.
class AdvisoryText(ContractModel):
    headline: str = Field(min_length=1)
    body: str = Field(min_length=1)
    actions: list[str] = Field(min_length=3, max_length=5)


class AdvisoryTexts(ContractModel):
    en: AdvisoryText
    bn: AdvisoryText
    hi: AdvisoryText


class AdvisoryProperties(ContractModel):
    id: AdvisoryId
    block_id: BlockId
    block_name: str
    timestep: Timestep
    texts: AdvisoryTexts  # figures filled in, body prefixed with the exercise label
    templates: AdvisoryTexts  # the same text with {{key}} placeholders, no prefix
    citations: list[Citation]
    status: AdvisoryStatus
    approved_by: str | None = None
    approved_at: AwareDatetime | None = None
    rejection_reason: str | None = None
    rejected_at: AwareDatetime | None = None
    created_from: AdvisoryId | None = None  # "New draft from this"
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _status_fields(self) -> Self:
        if self.status in ("approved", "sent") and (
            not self.approved_by or self.approved_at is None
        ):
            raise ValueError("approved_by and approved_at are required once approved")
        if self.status == "rejected" and (not self.rejection_reason or self.rejected_at is None):
            raise ValueError("rejection_reason and rejected_at are required once rejected")
        return self


class Advisory(Feature):
    geometry: None = None
    properties: AdvisoryProperties


class AdvisoryCollection(FeatureCollection[Advisory]):
    pass


# --- 4.6 TriggerEvent (Dev B) ---


class TriggerEventProperties(ContractModel):
    id: str
    zone_id: str
    zone_name: str
    timestep: Timestep
    metric: TriggerMetric
    unit: Literal["m/s", "m"]
    threshold: float
    observed: float
    triggered: bool
    payout_estimate_inr: float = Field(ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.unit != METRIC_UNITS[self.metric]:
            raise ValueError(f"{self.metric} must use unit {METRIC_UNITS[self.metric]}")
        if self.triggered != (self.observed >= self.threshold):
            raise ValueError("triggered must equal observed >= threshold")
        if not self.triggered and self.payout_estimate_inr != 0:
            raise ValueError("payout_estimate_inr must be 0 when not triggered")
        return self


class TriggerEvent(Feature):
    geometry: AreaGeometry
    properties: TriggerEventProperties


class TriggerEventCollection(FeatureCollection[TriggerEvent]):
    pass


# --- 4.7 DispatchReceipt (Dev B, not GeoJSON) ---


# v1.2 change, pending Dev A: status / provider_message_id / at replace ok; the receipt gains
# dispatched_at (was sent_at), dry_run and resend.
class ChannelResult(ContractModel):
    channel: Channel
    status: ChannelStatus
    provider_message_id: str | None = None  # Telegram message ids / email Message-ID
    error: str | None = None  # set when failed; never contains a credential
    at: AwareDatetime


class DispatchReceipt(ContractModel):
    advisory_id: AdvisoryId
    dispatched_at: AwareDatetime
    dry_run: bool = False
    resend: bool = False
    channels: list[ChannelResult]


class DispatchReceipts(ContractModel):
    """GET /api/dispatch/{advisory_id}/receipts, oldest first (v1.2 change, pending Dev A)."""

    receipts: list[DispatchReceipt]


class TelegramRecipient(ContractModel):
    configured: bool
    chat_id: str | None = None  # masked


class EmailRecipients(ContractModel):
    configured: bool
    to: list[str] = []  # masked


class DispatchRecipients(ContractModel):
    """GET /api/dispatch/recipients: who a dispatch would reach, masked (v1.2 change, pending
    Dev A). Recipients come only from api/.env, never from a request."""

    telegram: TelegramRecipient
    email: EmailRecipients
    pin_configured: bool


# --- §5 route payloads ---


class ReplayTimeline(ContractModel):
    event: Literal["amphan"] = "amphan"
    landfall: Timestep
    timesteps: list[Timestep]


class AdvisoryCreate(ContractModel):
    block_id: BlockId
    timestep: TimestepParam


class AdvisoryUpdate(ContractModel):
    templates: AdvisoryTexts  # v1.2 change, pending Dev A (was { body })
    edited_by: str | None = None


class AdvisoryApprove(ContractModel):
    approved_by: str = Field(min_length=1)  # "Name (Designation)", §5


# v1.2 change, pending Dev A.
class AdvisoryReject(ContractModel):
    reason: str = Field(min_length=1)
    rejected_by: str | None = None


class AdvisoryNewDraft(ContractModel):
    created_by: str | None = None


class AuditEvent(ContractModel):
    id: int
    advisory_id: AdvisoryId | None  # null: a generation that produced no advisory
    action: AuditAction
    actor: str | None
    at: AwareDatetime
    details: str | None


class AuditLog(ContractModel):
    events: list[AuditEvent]


class AdvisorySuggestion(ContractModel):
    block_id: BlockId
    block_name: str
    score: UnitFraction


class AdvisorySuggestions(ContractModel):
    timestep: Timestep
    threshold: UnitFraction
    blocks: list[AdvisorySuggestion]


class DispatchRequest(ContractModel):
    """v1.2 change, pending Dev A: resend, dry_run and pin. No recipient fields: extra keys are
    rejected (422)."""

    channels: list[Channel] = Field(min_length=1)
    resend: bool = False
    dry_run: bool = False
    pin: str | None = None  # required for a live dispatch (DISPATCH_PIN); not for a dry run
