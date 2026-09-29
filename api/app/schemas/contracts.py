"""Pydantic mirror of shared/contracts.md v1.2 (FROZEN).

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
    Horizon,
    ImpactStatus,
    InfraType,
    ModelProvider,
    RiskDriver,
    RiskReach,
    StepType,
    Timestep,
    TimestepParam,
    TriggerMetric,
    UnitFraction,
)
from app.schemas.geojson import (
    AreaGeometry,
    Feature,
    FeatureCollection,
    InfraGeometry,
    LineString,
)

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
    # v1.3 change, pending Dev A: 0 = the status now; 24 = expected within 24 h ("isolated" then
    # means expected to be cut off).
    horizon_h: Horizon = 0

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


# --- Action countdown (v1.3 change, pending Dev A) ---

KeyMomentKind = Literal[
    "first_alert", "first_expected_isolation", "first_actual_isolation", "landfall"
]


class CountdownFacility(ContractModel):
    """A facility in the action countdown. `expected`: cut off within the forecast window but
    not yet, with `hours_remaining` until the observed hazard cuts it off (null if it never
    does later in the replay). `cut_off`: cut off now, `since` the start of that isolation."""

    infra_id: str
    name: str
    infra_type: InfraType
    cause: str  # e.g. "ferry suspended by wind", "road cut by surge"
    cut_infra_id: str | None  # the first cut link on its usual route
    cut_name: str | None
    hours_remaining: int | None = Field(default=None, ge=0)
    since: Timestep | None = None


class KeyMoment(ContractModel):
    kind: KeyMomentKind
    timestep: Timestep | None  # null: it never happens in the replay
    label: str


class DepartureLeg(ContractModel):
    """v1.3 change, pending Dev A: one stretch of a departure route, by road or by ferry."""

    ferry: bool
    geometry: LineString  # simplified (~50 m)


class Departure(ContractModel):
    """v1.3 change, pending Dev A: the last safe departure by road for a facility that is cut off
    at some step. Times are normal-condition estimates at the replay's 3-hour resolution."""

    infra_id: str
    name: str
    infra_type: InfraType
    first_cut_off: Timestep  # first isolated at horizon 0
    # The last step before the first step at which no safe destination is reachable; null if
    # none is ever reachable.
    deadline: Timestep | None
    route_stays_open: bool  # a safe destination stays reachable to T-0
    destination_id: str | None  # the nearest safe destination reachable at the deadline
    destination_name: str | None
    travel_time_s: int | None = Field(ge=0)  # that route under normal conditions
    uses_ferry: bool | None
    at_risk: bool | None  # a link on the route is at risk at the deadline step
    legs: list[DepartureLeg]
    usual_destination_id: str | None  # the nearest safe destination on the intact network
    usual_destination_name: str | None
    note: str | None  # why there is no deadline or destination


class Departures(ContractModel):
    resolution_h: int = 3
    departures: list[Departure]  # by deadline, then name; no deadline last


class ActionCountdown(ContractModel):
    timestep: Timestep
    horizon_h: Horizon = 24  # the forecast window the expected list uses
    expected: list[CountdownFacility]  # soonest first
    cut_off: list[CountdownFacility]  # longest cut off first
    key_moments: list[KeyMoment]  # the same at every timestep


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
    horizon_h: Horizon = 0  # v1.3 change, pending Dev A: 24 = on the expected hazard


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
    # v1.3 change, pending Dev A: population_2011 x the share of inhabited land with surge >= 0.3 m,
    # an estimate (population spread evenly over inhabited land).
    surge_population: int = Field(ge=0)
    hospital_travel_min: float | None = Field(ge=0)  # null: no road node reaches a hospital
    reach: RiskReach  # which of hazard or exposure scaled the score
    hazard: RiskHazardParts
    exposure: RiskExposureParts
    vulnerability: RiskVulnerabilityParts


class RiskBreakdown(ContractModel):
    timestep: Timestep
    blocks: list[RiskBlockBreakdown]
    horizon_h: Horizon = 0  # v1.3 change, pending Dev A
    surge_population_total: int = Field(ge=0)  # v1.3 change, pending Dev A: sum over the blocks


# --- 4.5 Advisory (Dev B) ---


class Citation(ContractModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str
    value: float | str  # str: added in v1.2 (names, causes)
    unit: str | None
    source: str


# added in v1.2: one Advisory per block and timestep with all three languages.
class AdvisoryText(ContractModel):
    headline: str = Field(min_length=1)
    body: str = Field(min_length=1)
    actions: list[str] = Field(min_length=3, max_length=5)


class AdvisoryTexts(ContractModel):
    en: AdvisoryText
    bn: AdvisoryText
    hi: AdvisoryText


class GeneratedBy(ContractModel):
    """The model that wrote the draft: Gemini, or Groq as the fallback when Gemini answered 429 /
    503 (added in v1.2)."""

    provider: ModelProvider
    model: str


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
    # added in v1.2. Null on advisories stored before it existed.
    generated_by: GeneratedBy | None = None

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
    # added in v1.2: the payout tier. The feature reports the metric that sets the
    # payout (the higher of wind and surge tiers, never the sum); `threshold` is that metric's
    # threshold for the tier reached (its first tier when none); `observed` is its 90th-percentile
    # value over the zone's inhabited land (was: max over the zone).
    tier: int = Field(default=0, ge=0)  # 0 = not triggered
    payout_fraction: UnitFraction = 0.0  # of sum_insured_inr, for the current tier
    sum_insured_inr: float = Field(default=0.0, ge=0)
    # added in v1.2: payouts only go up during an event (released money is not taken
    # back): the highest tier reached at any timestep up to this one, and its payout.
    released_tier: int = Field(default=0, ge=0)
    released_payout_inr: float = Field(default=0.0, ge=0)
    # v1.3 change, pending Dev A: the tier the expected hazard (next 24 h) would reach. For
    # information only: payouts follow the observed hazard.
    expected_tier_24h: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.unit != METRIC_UNITS[self.metric]:
            raise ValueError(f"{self.metric} must use unit {METRIC_UNITS[self.metric]}")
        if self.triggered != (self.observed >= self.threshold):
            raise ValueError("triggered must equal observed >= threshold")
        if not self.triggered and self.payout_estimate_inr != 0:
            raise ValueError("payout_estimate_inr must be 0 when not triggered")
        if self.triggered != (self.tier > 0):
            raise ValueError("triggered must equal tier > 0")
        if abs(self.payout_estimate_inr - self.payout_fraction * self.sum_insured_inr) > 1:
            raise ValueError("payout_estimate_inr must be payout_fraction * sum_insured_inr")
        if self.released_tier < self.tier or self.released_payout_inr < self.payout_estimate_inr:
            raise ValueError("released amounts can't be below the current reading")
        return self


class TriggerEvent(Feature):
    geometry: AreaGeometry
    properties: TriggerEventProperties


class TriggerEventCollection(FeatureCollection[TriggerEvent]):
    pass


class InsuranceDistrictTotal(ContractModel):
    """One timestep of GET /api/insurance/summary (added in v1.2)."""

    timestep: Timestep
    released_payout_inr: float = Field(ge=0)  # sum of released_payout_inr over the zones
    triggered_zones: int = Field(ge=0)  # triggered on the current reading
    released_zones: int = Field(ge=0)  # with a payout released so far


class InsuranceZoneSummary(ContractModel):
    """A zone's first trigger and final release (added in v1.2)."""

    zone_id: str
    zone_name: str
    first_trigger_timestep: Timestep | None = None
    hours_before_landfall: int | None = None
    first_trigger_metric: TriggerMetric | None = None
    first_trigger_tier: int = Field(default=0, ge=0)
    first_trigger_payout_inr: float = Field(default=0.0, ge=0)
    final_released_tier: int = Field(default=0, ge=0)
    final_released_payout_inr: float = Field(default=0.0, ge=0)
    sum_insured_inr: float = Field(ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        triggered = self.first_trigger_timestep is not None
        if triggered != (self.first_trigger_tier > 0):
            raise ValueError("first_trigger_tier > 0 exactly when there is a first trigger")
        if self.final_released_tier < self.first_trigger_tier:
            raise ValueError("the final released tier can't be below the first trigger's")
        return self


class InsuranceSummary(ContractModel):
    """GET /api/insurance/summary: released totals per timestep (never decreasing) and each
    zone's first trigger (added in v1.2)."""

    district: list[InsuranceDistrictTotal]
    zones: list[InsuranceZoneSummary]

    @model_validator(mode="after")
    def _monotonic(self) -> Self:
        totals = [d.released_payout_inr for d in self.district]
        if any(b < a for a, b in zip(totals, totals[1:], strict=False)):
            raise ValueError("released totals can't decrease")
        return self


# --- 4.7 DispatchReceipt (Dev B, not GeoJSON) ---


# added in v1.2: status / provider_message_id / at replace ok; the receipt gains
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
    """GET /api/dispatch/{advisory_id}/receipts, oldest first (added in v1.2)."""

    receipts: list[DispatchReceipt]


class TelegramRecipient(ContractModel):
    configured: bool
    chat_id: str | None = None  # masked


class EmailRecipients(ContractModel):
    configured: bool
    to: list[str] = []  # masked


class DispatchRecipients(ContractModel):
    """GET /api/dispatch/recipients: who a dispatch would reach, masked (added in v1.2).
    Recipients come only from api/.env, never from a request."""

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
    templates: AdvisoryTexts  # added in v1.2 (was { body })
    edited_by: str | None = None


class AdvisoryApprove(ContractModel):
    approved_by: str = Field(min_length=1)  # "Name (Designation)", §5


# added in v1.2.
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


class SuggestionReason(ContractModel):
    """v1.3 change, pending Dev A: why a block is suggested."""

    kind: Literal["risk", "expected_cut_off"]
    label: str  # "risk 0.28", "Frasergunj PHC expected to be cut off"
    infra_id: str | None  # expected_cut_off: the facility


class AdvisorySuggestion(ContractModel):
    block_id: BlockId
    block_name: str
    score: UnitFraction
    reasons: list[SuggestionReason] = Field(min_length=1)  # v1.3 change, pending Dev A


class AdvisorySuggestions(ContractModel):
    timestep: Timestep
    threshold: UnitFraction
    blocks: list[AdvisorySuggestion]


class DispatchRequest(ContractModel):
    """added in v1.2: resend, dry_run and pin. No recipient fields: extra keys are
    rejected (422)."""

    channels: list[Channel] = Field(min_length=1)
    resend: bool = False
    dry_run: bool = False
    pin: str | None = None  # required for a live dispatch (DISPATCH_PIN); not for a dry run
