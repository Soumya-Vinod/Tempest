// TypeScript mirror of shared/contracts.md v1.3 (FROZEN).
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
/** "rejected": added in v1.2. */
export type AdvisoryStatus = "draft" | "approved" | "sent" | "rejected";
/** Advisory audit log actions (§4.5, added in v1.2). */
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
  | "dispatched"; // one per channel attempt (added in v1.2)
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
/** dry_run: built and validated, not sent (added in v1.2). */
export type ChannelStatus = "sent" | "failed" | "dry_run";
/**
 * Forecast horizon in hours (v1.3 change pending Dev A): 0 = now, 24 = expected within 24 h
 * (the cell-wise max of the hazard over the next 24 h; a perfect-forecast replay).
 */
export type Horizon = 0 | 24;
/** added in v1.2. */
export type ModelProvider = "gemini" | "groq";
/** The model that wrote an advisory draft (added in v1.2). */
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
  horizon_h?: Horizon; // v1.3 change pending Dev A: 24 = expected within 24 h
}
export type ImpactResult = Feature<InfraGeometry, ImpactResultProperties>;
export type ImpactResultCollection = FeatureCollection<ImpactResult>;

// ---------- Action countdown (v1.3 change pending Dev A) ----------

export type KeyMomentKind =
  | "first_alert"
  | "first_expected_isolation"
  | "first_actual_isolation"
  | "landfall";

/** expected: cut off within the forecast window but not yet; cut_off: cut off now. */
export interface CountdownFacility {
  infra_id: string;
  name: string;
  infra_type: InfraType;
  cause: string; // e.g. "ferry suspended by wind", "road cut by surge"
  cut_infra_id: string | null; // the first cut link on its usual route
  cut_name: string | null;
  hours_remaining?: number | null; // expected: until the observed hazard cuts it off; null: never later
  since?: Timestep | null; // cut_off: the start of this isolation
}

// ---------- Last safe departure (v1.3 change pending Dev A) ----------

export interface DepartureLeg {
  ferry: boolean;
  geometry: LineString; // simplified (~50 m)
}

/** Normal-condition estimates at the replay's 3-hour resolution. */
export interface Departure {
  infra_id: string;
  name: string;
  infra_type: InfraType;
  first_cut_off: Timestep;
  deadline: Timestep | null; // last step a safe destination is reachable by road; null: never
  route_stays_open: boolean;
  destination_id: string | null; // nearest safe destination reachable at the deadline
  destination_name: string | null;
  travel_time_s: number | null; // that route, normal conditions
  uses_ferry: boolean | null;
  at_risk: boolean | null; // a link on the route is at risk at the deadline step
  legs: DepartureLeg[];
  usual_destination_id: string | null; // nearest on the intact network
  usual_destination_name: string | null;
  note: string | null;
}

export interface Departures {
  resolution_h: number;
  departures: Departure[];
}

// Critical links (v1.4 change pending Dev A): the roads and ferry crossings the most last safe
// departure routes use, per timestep × horizon.
export interface CriticalLinkFacility {
  infra_id: string;
  name: string;
  deadline: Timestep; // its last safe departure
}

export interface CriticalLink {
  way_ids: number[]; // OSM way ids, in the direction of travel
  infra_ids: string[]; // the exposure road features, road-way-<id>
  label: string; // name or "Unnamed road" / "Unnamed ferry route", then the CD block(s)
  name: string | null;
  link_type: "road" | "ferry";
  blocks: string[]; // in the direction of travel
  facility_count: number;
  facilities: CriticalLinkFacility[]; // by deadline, then name
  earliest_deadline: Timestep;
  geometry: LineString | MultiLineString;
}

export interface CriticalLinks {
  timestep: Timestep;
  horizon_h: Horizon; // 0: deadline not passed; 24: deadline within the next 24 h
  note: string;
  links: CriticalLink[]; // most facilities first, then earliest deadline, then label
}

export interface KeyMoment {
  kind: KeyMomentKind;
  timestep: Timestep | null; // null: it never happens in the replay
  label: string;
}

export interface ActionCountdown {
  timestep: Timestep;
  horizon_h: Horizon; // the forecast window the expected list uses (24)
  expected: CountdownFacility[]; // soonest first
  cut_off: CountdownFacility[]; // longest cut off first
  key_moments: KeyMoment[]; // the same at every timestep
}

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
  horizon_h?: Horizon; // v1.3 change pending Dev A
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
  surge_population: number; // v1.3 change pending Dev A: estimate, population x share with surge >= 0.3 m
  hospital_travel_min: number | null; // null: no road node reaches a hospital
  reach: RiskReach; // direct: hazard on its land; cut_off: exposure (the storm cut it off)
  hazard: RiskHazardParts;
  exposure: RiskExposureParts;
  vulnerability: RiskVulnerabilityParts;
}
export interface RiskBreakdown {
  timestep: Timestep;
  blocks: RiskBlockBreakdown[];
  horizon_h?: Horizon; // v1.3 change pending Dev A
  surge_population_total: number; // v1.3 change pending Dev A: sum over the blocks
}

// ---------- §4.5 Advisory (Dev B) ----------

export interface Citation {
  key: string; // ^[a-z0-9_]+$
  label: string;
  value: number | string; // string: added in v1.2 (names, causes)
  unit: string | null;
  source: string;
}
/** added in v1.2: one Advisory per block and timestep, all three languages. */
export interface AdvisoryText {
  headline: string;
  body: string;
  actions: string[]; // 3 to 5
}
export type AdvisoryTexts = Record<Language, AdvisoryText>;
export interface AdvisoryProperties {
  id: AdvisoryId;
  block_id: BlockId;
  block_name: string; // added in v1.2
  timestep: Timestep;
  texts: AdvisoryTexts; // figures filled in; body starts with the exercise label
  templates: AdvisoryTexts; // {{key}} placeholders, no label
  citations: Citation[];
  status: AdvisoryStatus;
  approved_by: string | null; // required once approved or sent: "Name (Designation)"
  approved_at: IsoDateTime | null; // required once approved or sent
  rejection_reason: string | null; // required once rejected (added in v1.2)
  rejected_at: IsoDateTime | null; // required once rejected
  created_from: AdvisoryId | null; // "New draft from this" (added in v1.2)
  created_at: IsoDateTime;
  generated_by?: GeneratedBy | null; // added in v1.2; null on older advisories
}
/** added in v1.2. advisory_id null: a generation that produced no advisory. */
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
/** added in v1.2. */
/** v1.3 change pending Dev A: why a block is suggested. */
export interface SuggestionReason {
  kind: "risk" | "expected_cut_off";
  label: string; // "risk 0.28", "Frasergunj PHC expected to be cut off"
  infra_id: string | null; // expected_cut_off: the facility
}
export interface AdvisorySuggestion {
  block_id: BlockId;
  block_name: string;
  score: number;
  reasons: SuggestionReason[]; // v1.3 change pending Dev A, at least one
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
  observed: number; // added in v1.2: 90th percentile over inhabited land (was max)
  triggered: boolean;
  payout_estimate_inr: number; // 0 when not triggered; the current reading
  // added in v1.2: the governing metric's tier, and what has been released so far.
  tier: number; // 0 = not triggered
  payout_fraction: number;
  sum_insured_inr: number;
  released_tier: number; // highest tier up to this timestep (never taken back)
  released_payout_inr: number;
  // v1.3 change pending Dev A: the tier the expected hazard (next 24 h) would reach; information
  // only (payouts follow the observed hazard).
  expected_tier_24h?: number;
}
export type TriggerEvent = Feature<AreaGeometry, TriggerEventProperties>;
export type TriggerEventCollection = FeatureCollection<TriggerEvent>;

/** GET /api/insurance/summary (added in v1.2). */
export interface InsuranceDistrictTotal {
  timestep: Timestep;
  released_payout_inr: number;
  triggered_zones: number;
  released_zones: number;
}
export interface InsuranceZoneSummary {
  zone_id: string;
  zone_name: string;
  first_trigger_timestep: Timestep | null;
  hours_before_landfall: number | null;
  first_trigger_metric: TriggerMetric | null;
  first_trigger_tier: number;
  first_trigger_payout_inr: number;
  final_released_tier: number;
  final_released_payout_inr: number;
  sum_insured_inr: number;
}
export interface InsuranceSummary {
  district: InsuranceDistrictTotal[]; // 25, never decreasing
  zones: InsuranceZoneSummary[];
}

// ---------- §4.7 DispatchReceipt (Dev B) ----------

/** added in v1.2: status / provider_message_id / at replace ok. */
export interface ChannelResult {
  channel: Channel;
  status: ChannelStatus;
  provider_message_id: string | null;
  error: string | null;
  at: IsoDateTime;
}
/** added in v1.2: dispatched_at (was sent_at), dry_run, resend. */
export interface DispatchReceipt {
  advisory_id: AdvisoryId;
  dispatched_at: IsoDateTime;
  dry_run: boolean;
  resend: boolean;
  channels: ChannelResult[];
}
/** GET /api/dispatch/{advisory_id}/receipts (added in v1.2). */
export interface DispatchReceipts {
  receipts: DispatchReceipt[];
}
/** GET /api/dispatch/recipients, masked (added in v1.2). */
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
  templates: AdvisoryTexts; // added in v1.2 (was { body })
  edited_by?: string | null;
}
export interface AdvisoryApprove {
  approved_by: string; // "Name (Designation)"
}
/** added in v1.2. */
export interface AdvisoryReject {
  reason: string;
  rejected_by?: string | null;
}
export interface AdvisoryNewDraft {
  created_by?: string | null;
}
/** added in v1.2: resend, dry_run, pin. Never recipients. */
export interface DispatchRequest {
  channels: Channel[];
  resend?: boolean;
  dry_run?: boolean;
  pin?: string | null; // required for a live dispatch
}

// ---------- §4.8 IMD Bulletins Multimodal Analysis (v1.4 change, pending Dev B) ----------

export interface BulletinIssueDateTime {
  date_str?: string | null;
  time_ist?: string | null;
  time_utc?: string | null;
  page?: number | null;
}

export interface BulletinCurrentPosition {
  latitude_deg_north?: number | null;
  longitude_deg_east?: number | null;
  location_description?: string | null;
  page?: number | null;
}

export interface BulletinCurrentIntensity {
  classification?: string | null;
  max_sustained_surface_wind_kmph?: string | null;
  max_sustained_surface_wind_kts?: number | null;
  estimated_central_pressure_hpa?: number | null;
  page?: number | null;
}

export interface BulletinForecastLandfall {
  landfall_area?: string | null;
  forecast_landfall_time_str?: string | null;
  page?: number | null;
}

export interface BulletinForecastMaxWindAtLandfall {
  wind_description?: string | null;
  max_wind_kmph?: number | null;
  gust_kmph?: number | null;
  page?: number | null;
}

export interface BulletinStormSurgeForecast {
  surge_height_description?: string | null;
  min_surge_height_m?: number | null;
  max_surge_height_m?: number | null;
  inundated_districts: string[];
  page?: number | null;
}

export interface BulletinWarnedAreas {
  west_bengal_districts: string[];
  odisha_districts: string[];
  other_districts_or_blocks: string[];
  page?: number | null;
}

export interface BulletinLandfallComparison {
  actual_landfall_lat: number;
  actual_landfall_lon: number;
  actual_landfall_time: string;
  corridor_contains_actual_crossing: boolean;
  notes: string;
}

export interface ImdBulletin {
  id: string;
  bulletin_number: string;
  nominal_timestep: Timestep;
  target_stage: string;
  hours_to_landfall: number;
  source_url: string;
  source_filename: string;
  sha256: string;
  issue_date_time: BulletinIssueDateTime;
  current_storm_position: BulletinCurrentPosition;
  current_intensity: BulletinCurrentIntensity;
  forecast_landfall: BulletinForecastLandfall;
  forecast_max_wind_at_landfall: BulletinForecastMaxWindAtLandfall;
  storm_surge_forecast: BulletinStormSurgeForecast;
  warned_areas: BulletinWarnedAreas;
  landfall_comparison: BulletinLandfallComparison;
  extraction_notes?: string | null;
}

export interface ActualLandfallReference {
  source: string;
  crossing_location_name: string;
  crossing_lat: number;
  crossing_lon: number;
  synoptic_hour_timestep: Timestep;
  synoptic_hour_lat: number;
  synoptic_hour_lon: number;
  landfall_time_utc: string;
  landfall_time_ist: string;
}

export interface ImdBulletinCollection {
  event: string;
  actual_landfall: ActualLandfallReference;
  bulletins: ImdBulletin[];
}

