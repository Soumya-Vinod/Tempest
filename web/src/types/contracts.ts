// TypeScript mirror of shared/contracts.md v1.0 (FROZEN).
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
export type AdvisoryStatus = "draft" | "approved" | "sent";
export type TriggerMetric = "wind_speed" | "surge_depth";
export type BlockSource = "census2011_cd" | "h3_r7";
export type Channel = "telegram" | "email";

/** One of the 25 Amphan replay keys, `YYYY-MM-DDTHH:MM:SSZ`. */
export type Timestep = string;
/** Accepted by every timestep parameter; "live" returns 501 in v1.0. */
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
}
export type RiskScore = Feature<AreaGeometry, RiskScoreProperties>;
export type RiskScoreCollection = FeatureCollection<RiskScore>;

// ---------- §4.5 Advisory (Dev B) ----------

export interface Citation {
  key: string;
  label: string;
  value: number;
  unit: string | null;
  source: string;
}
export interface AdvisoryProperties {
  id: AdvisoryId;
  block_id: BlockId;
  timestep: Timestep;
  language: Language;
  body: string;
  citations: Citation[];
  status: AdvisoryStatus;
  approved_by: string | null; // required once status !== "draft"
  approved_at: IsoDateTime | null; // required once status !== "draft"
  created_at: IsoDateTime;
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

export interface ChannelResult {
  channel: Channel;
  ok: boolean;
  error: string | null;
}
export interface DispatchReceipt {
  advisory_id: AdvisoryId;
  sent_at: IsoDateTime;
  channels: ChannelResult[];
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
  language: Language;
}
export interface AdvisoryUpdate {
  body: string;
}
export interface AdvisoryApprove {
  approved_by: string;
}
export interface DispatchRequest {
  channels: Channel[];
}
