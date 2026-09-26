// TypeScript mirror of shared/contracts.md v1.1 (FROZEN).
// Keep in sync with api/app/schemas/. Changing anything here breaks the other dev: flag it.

// ---------- GeoJSON (EPSG:4326, [lon, lat]) ----------

export type Position = [number, number] | [number, number, number];

export interface Point {
  type: "Point";
  coordinates: Position;
}
export interface LineString {
  type: "LineString";
  coordinates: Position[];
}
export interface MultiLineString {
  type: "MultiLineString";
  coordinates: Position[][];
}
export interface Polygon {
  type: "Polygon";
  coordinates: Position[][];
}
export interface MultiPolygon {
  type: "MultiPolygon";
  coordinates: Position[][][];
}

export type AreaGeometry = Polygon | MultiPolygon;
export type InfraGeometry = Point | LineString | MultiLineString;

export interface Feature<G, P extends { id: string }> {
  type: "Feature";
  id: string; // always equals properties.id
  geometry: G;
  properties: P;
}

export interface FeatureCollection<F> {
  type: "FeatureCollection";
  features: F[];
}

// ---------- §3 Shared types ----------

export type HazardType = "wind" | "surge" | "flood";
export type InfraType = "substation" | "power_line" | "road" | "hospital" | "shelter";
export type ImpactStatus = "ok" | "at_risk" | "cut" | "isolated";
export type StepType = "hazard" | "infra" | "service";
export type Language = "en" | "bn" | "hi";
/** "rejected": v1.2 change, pending Dev A. */
export type AdvisoryStatus = "draft" | "approved" | "sent" | "rejected";
/** Advisory audit log actions (§4.5, v1.2 change pending Dev A). */
export type AuditAction =
  | "generated"
  | "number_check_failed"
  | "invalid_response"
  | "edited"
  | "approved"
  | "rejected"
  | "new_draft"
  | "copied"
  | "sent"
  | "dispatched"; // one per channel attempt (v1.2 change pending Dev A)
export type TriggerMetric = "wind_speed" | "surge_depth";
export type BlockSource = "census2011_cd" | "h3_r7";
/** The largest contributing part of a RiskScore (§4.4, added in v1.1). */
export type RiskDriver =
  | "surge"
  | "wind"
  | "flood"
  | "isolated_facilities"
  | "cut_roads"
  | "cut_substations"
  | "population_density"
  | "hospital_access"
  | "low_literacy"
  | "mapped_shelters";
/** How the cyclone reaches a block (§4.4 risk breakdown, added in v1.1). */
export type RiskReach = "direct" | "cut_off";
export type Channel = "telegram" | "email";
/** dry_run: built and validated, not sent (v1.2 change pending Dev A). */
export type ChannelStatus = "sent" | "failed" | "dry_run";
/** v1.2 change pending Dev A. */
export type ModelProvider = "gemini" | "groq";
/** The model that wrote an advisory draft (v1.2 change pending Dev A). */
export interface GeneratedBy {
  provider: ModelProvider;
  model: string;
}

/** One of the 25 Amphan replay keys, `YYYY-MM-DDTHH:MM:SSZ`. */
export type Timestep = string;
/** Accepted by every timestep parameter; "live" returns 501 in v1.1. */
export type TimestepParam = Timestep | "live";
/** ISO 8601 UTC datetime. */
export type IsoDateTime = string;
/** Opaque, matches ^[a-z0-9-]+$. */
export type BlockId = string;
/** UUID4, lowercase; matches ^[a-z0-9-]+$ (fixture-safe, contracts.md §4.5). */
export type AdvisoryId = string;

// ---------- §4.1 HazardLayer (Dev A) ----------

export interface HazardLayerProperties {
  id: string;
  hazard_type: HazardType;
  timestep: Timestep;
  value: number;
  unit: "m/s" | "m" | "index";
  severity: number; // [0, 1]
}
export type HazardLayer = Feature<AreaGeometry, HazardLayerProperties>;
export type HazardLayerCollection = FeatureCollection<HazardLayer>;

// ---------- §4.2 InfraFeature (Dev B) ----------

export interface InfraFeatureProperties {
  id: string; // ^(substation|power-line|road|hospital|shelter)-(node|way|relation)-\d+$
  infra_type: InfraType;
  name: string | null;
  osm_id: string | null; // "node/123" | "way/123" | "relation/123"
  attributes: Record<string, unknown>;
}
export type InfraFeature = Feature<InfraGeometry, InfraFeatureProperties>;
export type InfraFeatureCollection = FeatureCollection<InfraFeature>;

// ---------- §4.3 ImpactResult (Dev B) ----------

export interface PathwayStep {
  id: string;
  label: string;
  type: StepType;
}
export interface ImpactResultProperties {
  id: string;
  infra_id: string;
  hazard_type: HazardType;
  status: ImpactStatus;
  timestep: Timestep;
  pathway: PathwayStep[]; // ordered, cause first; empty when status is "ok"
}
export type ImpactResult = Feature<InfraGeometry, ImpactResultProperties>;
export type ImpactResultCollection = FeatureCollection<ImpactResult>;

// ---------- §4.4 RiskScore (Dev B) ----------

export interface RiskComponents {
  hazard: number;
  exposure: number;
  vulnerability: number;
}
export interface RiskScoreProperties {
  id: string;
  block_id: BlockId;
  block_source: BlockSource;
  block_name: string;
  timestep: Timestep;
  score: number; // [0, 1]
  components: RiskComponents;
  top_driver?: RiskDriver | null; // added in v1.1; null when score is 0
}
export type RiskScore = Feature<AreaGeometry, RiskScoreProperties>;
export type RiskScoreCollection = FeatureCollection<RiskScore>;

/** Areas inside the AOI clip that no block covers (added in v1.1). */
export interface UnscoredAreaProperties {
  id: string;
  label: string; // "Municipal area, not scored"
  area_km2: number;
}
export type UnscoredArea = Feature<AreaGeometry, UnscoredAreaProperties>;
export type UnscoredAreaCollection = FeatureCollection<UnscoredArea>;

/** The parts behind each block's score (added in v1.1). Every part is in [0, 1]. */
export interface RiskHazardParts {
  surge: number;
  wind: number;
  flood: number;
}
export interface RiskExposureParts {
  isolated_facilities: number;
  cut_roads: number;
  cut_substations: number;
}
export interface RiskVulnerabilityParts {
  population_density: number;
  hospital_access: number;
  low_literacy: number;
  mapped_shelters: number;
}
export interface RiskBlockBreakdown {
  block_id: BlockId;
  block_name: string;
  population_2011: number;
  hospital_travel_min: number | null; // null: no road node reaches a hospital
  reach: RiskReach; // direct: hazard on its land; cut_off: exposure (the storm cut it off)
  hazard: RiskHazardParts;
  exposure: RiskExposureParts;
  vulnerability: RiskVulnerabilityParts;
}
export interface RiskBreakdown {
  timestep: Timestep;
  blocks: RiskBlockBreakdown[];
}

// ---------- §4.5 Advisory (Dev B) ----------

export interface Citation {
  key: string; // ^[a-z0-9_]+$
  label: string;
  value: number | string; // string: v1.2 change pending Dev A (names, causes)
  unit: string | null;
  source: string;
}
/** v1.2 change pending Dev A: one Advisory per block and timestep, all three languages. */
export interface AdvisoryText {
  headline: string;
  body: string;
  actions: string[]; // 3 to 5
}
export type AdvisoryTexts = Record<Language, AdvisoryText>;
export interface AdvisoryProperties {
  id: AdvisoryId;
  block_id: BlockId;
  block_name: string; // v1.2 change pending Dev A
  timestep: Timestep;
  texts: AdvisoryTexts; // figures filled in; body starts with the exercise label
  templates: AdvisoryTexts; // {{key}} placeholders, no label
  citations: Citation[];
  status: AdvisoryStatus;
  approved_by: string | null; // required once approved or sent: "Name (Designation)"
  approved_at: IsoDateTime | null; // required once approved or sent
  rejection_reason: string | null; // required once rejected (v1.2 change pending Dev A)
  rejected_at: IsoDateTime | null; // required once rejected
  created_from: AdvisoryId | null; // "New draft from this" (v1.2 change pending Dev A)
  created_at: IsoDateTime;
  generated_by?: GeneratedBy | null; // v1.2 change pending Dev A; null on older advisories
}
/** v1.2 change pending Dev A. advisory_id null: a generation that produced no advisory. */
export interface AuditEvent {
  id: number;
  advisory_id: AdvisoryId | null;
  action: AuditAction;
  actor: string | null;
  at: IsoDateTime;
  details: string | null; // JSON text
}
export interface AuditLog {
  events: AuditEvent[];
}
/** v1.2 change pending Dev A. */
export interface AdvisorySuggestion {
  block_id: BlockId;
  block_name: string;
  score: number;
}
export interface AdvisorySuggestions {
  timestep: Timestep;
  threshold: number;
  blocks: AdvisorySuggestion[];
}
export type Advisory = Feature<null, AdvisoryProperties>;
export type AdvisoryCollection = FeatureCollection<Advisory>;

// ---------- §4.6 TriggerEvent (Dev B) ----------

export interface TriggerEventProperties {
  id: string;
  zone_id: string;
  zone_name: string;
  timestep: Timestep;
  metric: TriggerMetric;
  unit: "m/s" | "m";
  threshold: number;
  observed: number;
  triggered: boolean;
  payout_estimate_inr: number; // 0 when not triggered
}
export type TriggerEvent = Feature<AreaGeometry, TriggerEventProperties>;
export type TriggerEventCollection = FeatureCollection<TriggerEvent>;

// ---------- §4.7 DispatchReceipt (Dev B) ----------

/** v1.2 change pending Dev A: status / provider_message_id / at replace ok. */
export interface ChannelResult {
  channel: Channel;
  status: ChannelStatus;
  provider_message_id: string | null;
  error: string | null;
  at: IsoDateTime;
}
/** v1.2 change pending Dev A: dispatched_at (was sent_at), dry_run, resend. */
export interface DispatchReceipt {
  advisory_id: AdvisoryId;
  dispatched_at: IsoDateTime;
  dry_run: boolean;
  resend: boolean;
  channels: ChannelResult[];
}
/** GET /api/dispatch/{advisory_id}/receipts (v1.2 change pending Dev A). */
export interface DispatchReceipts {
  receipts: DispatchReceipt[];
}
/** GET /api/dispatch/recipients, masked (v1.2 change pending Dev A). */
export interface DispatchRecipients {
  telegram: { configured: boolean; chat_id: string | null };
  email: { configured: boolean; to: string[] };
  pin_configured: boolean;
}

// ---------- Cyclone track (Dev A; GET /api/hazard/track, internal, added in v1.1) ----------
// Mirrors api/app/hazard/models.py CycloneTrackPoint / CycloneTrack exactly. Closes Dev A's
// follow-up: the TypeScript mirror of the track route's schema was missing.

export interface CycloneTrackPoint {
  timestep: Timestep;
  lat: number; // storm eye, EPSG:4326 [-90, 90]
  lon: number; // [-180, 180]
  central_pressure_hpa: number; // (800, 1050)
  max_wind_mps: number; // max sustained 10 m wind, >= 0
  radius_max_wind_km: number; // > 0
  forward_speed_mps: number; // >= 0
  heading_deg: number; // meteorological, 0 = north, [0, 360)
}
export interface CycloneTrack {
  event: string; // default "amphan"
  points: CycloneTrackPoint[]; // the 25 replay timesteps, in order
}

// ---------- §5 Route payloads ----------

export interface ReplayTimeline {
  event: "amphan";
  landfall: Timestep;
  timesteps: Timestep[];
}
export interface AdvisoryCreate {
  block_id: BlockId;
  timestep: TimestepParam;
}
export interface AdvisoryUpdate {
  templates: AdvisoryTexts; // v1.2 change pending Dev A (was { body })
  edited_by?: string | null;
}
export interface AdvisoryApprove {
  approved_by: string; // "Name (Designation)"
}
/** v1.2 change pending Dev A. */
export interface AdvisoryReject {
  reason: string;
  rejected_by?: string | null;
}
export interface AdvisoryNewDraft {
  created_by?: string | null;
}
/** v1.2 change pending Dev A: resend, dry_run, pin. Never recipients. */
export interface DispatchRequest {
  channels: Channel[];
  resend?: boolean;
  dry_run?: boolean;
  pin?: string | null; // required for a live dispatch
}
