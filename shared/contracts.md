# Tempest contracts — v1.1 (FROZEN)

The interface between **Dev A (hazard)** and **Dev B (exposure, impact, risk, advisory, dispatch,
insurance)**. This file is the source of truth. `api/app/schemas/` (Pydantic) and
`web/src/types/contracts.ts` (TypeScript) mirror it exactly.

**Change rule (active):** any change needs sign-off from both devs, a version bump here, and the
matching Pydantic + TS edits in the same commit. Proposed changes are marked *v1.2 change, pending
Dev A* (or *Dev B*) until both devs sign off and the version is bumped.

---

## 1. Conventions

| Topic | Rule |
|---|---|
| CRS | All geometry is GeoJSON in **EPSG:4326**, `[lon, lat]` order. No `crs` member. |
| AOI | bbox `[88.0, 21.5, 89.1, 22.7]` = `[min_lon, min_lat, max_lon, max_lat]` (South 24 Parganas / Sundarbans). Features outside the AOI are not returned. |
| Field names | `snake_case` in JSON, Pydantic and TS alike. |
| Enums | Lowercase `snake_case` strings (e.g. `at_risk`, `power_line`). |
| Scores | `severity`, `score` and all risk components are floats in **[0, 1]**. |
| Units | Wind speed **m/s**; surge depth **m** above ground; money **INR**. |
| Timestamps | ISO 8601 UTC, always `YYYY-MM-DDTHH:MM:SSZ` (e.g. `2020-05-20T12:00:00Z`). |
| Null geometry | Allowed only where stated (Advisory). |
| Errors | FastAPI default `{"detail": ...}`. `404` unknown id, `409` invalid state change, `422` bad params (incl. unknown `timestep`), `501` not implemented yet, `503` required processed data missing (live mode) *(added in v0.9)*, or an upstream key missing; `502` an upstream (Gemini) response unusable *(v1.2 change, pending Dev A)*. `403` wrong or unset dispatch PIN, `429` dispatch rate limit *(v1.2 change, pending Dev A)*. |

## 2. Replay timeline — Cyclone Amphan

- **Landfall timestep:** `2020-05-20T12:00:00Z`. IMD reports Amphan crossed the West Bengal–Bangladesh
  coast over the Sundarbans between 10:00 and 12:00 UTC on 20 May 2020. 12:00Z is the first
  3-hourly synoptic hour by which the crossing is complete.
- **Start:** T-72h = `2020-05-17T12:00:00Z`.
- **Step:** 3 hours → **25 timesteps**, T-72h … T-0 inclusive.
- **Timestep key:** the ISO string itself, e.g. `2020-05-18T03:00:00Z`.
- **Reserved value `"live"`:** every `timestep` parameter (HTTP query param or Python argument) also
  accepts `"live"`. In v1.1, `"live"` returns `501` from routes and raises `NotImplementedError` from
  Python functions. `"live"` never appears in a response's `timestep` property.
- Any other `timestep` value not in the list returns `422`.

```
2020-05-17T12:00:00Z  T-72     2020-05-19T00:00:00Z  T-36
2020-05-17T15:00:00Z  T-69     ...
...                            2020-05-20T09:00:00Z  T-3
2020-05-18T12:00:00Z  T-48     2020-05-20T12:00:00Z  T-0 (landfall)
```

Live mode is reserved but not implemented in v1.1. See the `"live"` value above.

## 3. Shared types

```ts
type HazardType   = "wind" | "surge" | "flood";
type InfraType    = "substation" | "power_line" | "road" | "hospital" | "shelter";
type ImpactStatus = "ok" | "at_risk" | "cut" | "isolated";
type StepType     = "hazard" | "infra" | "service";
type Language     = "en" | "bn" | "hi";
type AdvisoryStatus = "draft" | "approved" | "sent" | "rejected";  // rejected: v1.2 change, pending Dev A
type AuditAction = "generated" | "number_check_failed" | "invalid_response" | "edited"
  | "approved" | "rejected" | "new_draft" | "copied" | "sent"
  | "dispatched";  // v1.2 change, pending Dev A (dispatched: one per channel attempt)
type ChannelStatus = "sent" | "failed" | "dry_run";  // v1.2 change, pending Dev A
type ModelProvider = "gemini" | "groq";  // v1.2 change, pending Dev A
type TriggerMetric  = "wind_speed" | "surge_depth";
type BlockSource    = "census2011_cd" | "h3_r7";
type Timestep = string;       // one of the 25 replay keys (in responses)
type TimestepParam = Timestep | "live";  // accepted by every timestep parameter
```

Every schema below is a GeoJSON `Feature` (`{"type": "Feature", "id", "geometry", "properties"}`).
The tables list the `properties`. List endpoints return a `FeatureCollection` of that feature type.
`Feature.id` always equals `properties.id` (or the stated key).

## 4. Schemas

### 4.1 HazardLayer (Dev A)
One feature per hazard cell/polygon. Geometry: `Polygon | MultiPolygon`.

| Property | Type | Notes |
|---|---|---|
| `id` | string | Unique within a (hazard_type, timestep) collection. |
| `hazard_type` | HazardType | |
| `timestep` | Timestep | Flood susceptibility is static; Dev A repeats it at every timestep. |
| `value` | float | Physical value in `unit`. |
| `unit` | `"m/s" \| "m" \| "index"` | wind → `m/s`, surge → `m`, flood → `index` (0–1). |
| `severity` | float [0, 1] | Normalised by Dev A. *added in v1.1:* impact and insurance use `value` for physical thresholds (surge in m, wind in m/s); flood uses `severity`. |

*added in v1.1:* Grid resolution is 0.05° (~5.5 km, 24 rows × 22 columns = 528 cells)
spanning the AOI bbox. Terrain elevation per cell is sampled from NASA SRTM GL1 30m / Copernicus DEM
once via GEE and committed as `api/data/reference/hazard_elevation_grid.json` to ensure realistic
coastal surge and flood susceptibility modeling while remaining deterministic offline.

*added in v1.1:* HazardLayer Pydantic model provides hybrid attribute access (e.g.
`layer.hazard_type`, `layer.value`) mirroring `layer.properties` for caller convenience.

*added in v1.1:* flood `severity` is treated as susceptibility (static, repeated at
every timestep), not as an event, so flood never cuts roads and never makes a feature `isolated`;
it only marks roads, substations, hospitals and shelters `at_risk` (severity >= 0.7).

### 4.2 InfraFeature (Dev B)
Geometry: `Point` (substation, hospital, shelter) or `LineString | MultiLineString` (power_line, road).
Polygons from OSM are reduced to their centroid.

| Property | Type | Notes |
|---|---|---|
| `id` | string | Stable id: `<infra_type>-<osm_type>-<osm_number>`, e.g. `substation-way-123456`. `_` in `infra_type` is written `-` (`power-line-way-123`); must match `^(substation\|power-line\|road\|hospital\|shelter)-(node\|way\|relation)-\d+$`. *Added in v0.9.* |
| `infra_type` | InfraType | |
| `name` | string \| null | OSM `name`, null if missing. |
| `osm_id` | string \| null | `"<node\|way\|relation>/<number>"`, e.g. `"way/123456"`. Null for non-OSM sources. |
| `attributes` | object | Free-form extras (OSM tags, voltage, beds, capacity…). Keys set by the OSM ingest are listed below. |

OSM ingest attributes and scope *(added in v0.9)*:

| infra_type | OSM source | `attributes` keys |
|---|---|---|
| `substation` | `power=substation` | `voltage`, `operator` (when tagged) |
| `power_line` | `power=line` (+ `minor_line` if ≤ 10,000 ways) | `voltage`, `operator` (when tagged) |
| `road` | `highway` motorway…tertiary (+ `_link`), unclassified; `route=ferry` | `highway`, `ref`, `bridge` (when tagged); `ferry`: boolean; `baseline_component`: int \| null; `baseline_reachable_from_main`: boolean (see §4.3) |
| `hospital` | `amenity=hospital\|clinic`, `healthcare=hospital\|clinic\|centre` | `facility_level`: `"hospital"` \| `"health_centre"`; plus the access keys below |
| `shelter` | cyclone/flood shelters, assembly points and stand-in buildings (see below) | `shelter_kind` (see below); plus the access keys below |

Access keys on hospitals and shelters *(added in v1.1)*, from the impact engine's
road network: `snap_distance_m` (float, to the nearest graph node), `snap_too_far` (boolean,
more than 2 km: such a facility is never marked `isolated`), `hospital_travel_time_s`
(number \| null: usual road travel time to the nearest access hospital, the same sources as the
risk engine's hospital access (facility_level `hospital` minus nursing homes and specialist
clinics); for such a hospital itself, to the nearest *other* one; null when too far or with no
road route to one) and `baseline_travel_time_s` (number \| null: network travel time from the
Diamond Harbour anchor; null when too far or not in the anchor's component). The anchor time is
**internal** (the impact engine's baseline); display `hospital_travel_time_s` instead.

`shelter_kind` values *(added in v0.9)*, highest priority first. An OSM element
matching several gets the first. The `*_proxy` kinds are **stand-ins**: buildings that could shelter
people but are not designated shelters.

| `shelter_kind` | OSM source |
|---|---|
| `cyclone_shelter` | `shelter_type` / `emergency` / `building` etc. matching cyclone or flood, or a cyclone / flood shelter name |
| `assembly_point` | `emergency=assembly_point` |
| `school_proxy` | `amenity=school\|college\|university`, `building=school` |
| `community_proxy` | `amenity=community_centre\|townhall` |
| `public_building_proxy` | `office=government`, `building=public\|civic` |

Stand-ins within 50 m of another stand-in with the same normalised name (or, both unnamed, the same
`shelter_kind`) are merged into the higher-priority one.

`infra_type = "hospital"` therefore covers all health facilities; filter on `facility_level`.
Features are clipped to the South 24 Parganas + Kolkata district boundaries, with river channels up
to 4 km wide between them filled in (never across a neighbouring district or Bangladesh).
`name` stays null when OSM has neither `name` nor `name:en`; clients display "Unnamed …".

### 4.3 ImpactResult (Dev B)
One feature per (infra, hazard, timestep). Geometry: same as the referenced InfraFeature.

| Property | Type | Notes |
|---|---|---|
| `id` | string | `<infra_id>__<hazard_type>__<timestep>` |
| `infra_id` | string | InfraFeature `id`. |
| `hazard_type` | HazardType | |
| `status` | ImpactStatus | |
| `timestep` | Timestep | |
| `pathway` | PathwayStep[] | Ordered, cause first. Empty when `status = "ok"`. |

`PathwayStep = { id: string, label: string, type: StepType }`
- `hazard` step: `id = "hazard:<hazard_type>"`, e.g. `{"id":"hazard:surge","label":"Surge 2.4 m","type":"hazard"}`
- `infra` step: `id` = an InfraFeature `id`
- `service` step: `id = "service:<slug>"`, e.g. `service:hospital-power`

Example: surge → substation flooded → power line de-energised → hospital loses power (`isolated`).

**`isolated` vs baseline connectivity** *(added in v0.9)*. `isolated` means
reachable at baseline and unreachable under the hazard. The road graph (OSM, with ferries) is not
fully connected even without a hazard: some islands have no mapped ferry, and some road
fragments join the network only through minor roads outside the ingest's road classes. So:

- Every road graph node and every `road` InfraFeature carries `baseline_component` (int; `0` is the
  largest, i.e. main, component; `null` for a road feature with no edge in the graph) and
  `baseline_reachable_from_main` (boolean, `baseline_component == 0`).
- A feature not reachable from the main component at baseline is **never** marked `isolated`; the
  impact engine leaves it to the baseline flag instead, so hazard isolation is not overstated.

### 4.4 RiskScore (Dev B)
One feature per block per timestep. A block is a Census 2011 CD block or, if block boundaries
aren't available, an H3 resolution-7 cell. Geometry: block `Polygon | MultiPolygon`.

| Property | Type | Notes |
|---|---|---|
| `id` | string | `<block_id>__<timestep>` |
| `block_id` | string | Opaque identifier; consumers must not parse it. Must match `^[a-z0-9-]+$` (fixture-safe). |
| `block_source` | BlockSource | `census2011_cd` (CD block code) or `h3_r7` (H3 res-7 cell index). |
| `block_name` | string | |
| `timestep` | Timestep | |
| `score` | float [0, 1] | |
| `components` | `{ hazard, exposure, vulnerability }` | Each a float in [0, 1]. The formula belongs to the risk engine, not this contract. |
| `top_driver` | RiskDriver \| null, optional | *added in v1.1.* The largest contributing part: `surge`, `wind`, `flood`, `isolated_facilities`, `cut_roads`, `cut_substations`, `population_density`, `hospital_access`, `low_literacy`, `mapped_shelters`. Null when `score` is 0. |

**Unscored areas** *(added in v1.1)*: parts of the AOI clip that no block covers
(Kolkata, and South 24 Parganas municipal areas outside the CD blocks) get no RiskScore. They are
served as FC&lt;UnscoredArea&gt;: geometry `Polygon | MultiPolygon`, properties `{ id: string,
label: string, area_km2: number }`, with `label` "Municipal area, not scored".

**Risk breakdown** *(added in v1.1)*: the parts behind each block's score, for
explaining it. `RiskBreakdown = { timestep, blocks: RiskBlockBreakdown[] }` with
`RiskBlockBreakdown = { block_id, block_name, population_2011: int, hospital_travel_min:
number | null, reach: RiskReach, hazard: { surge, wind, flood }, exposure: { isolated_facilities, cut_roads,
cut_substations }, vulnerability: { population_density, hospital_access, low_literacy,
mapped_shelters } }`; every part is a float in [0, 1]. `hospital_travel_min` is null when no
road node in the block reaches a hospital. `RiskReach` is `direct` (the cyclone reaches the block
through hazard on its land) or `cut_off` (it reaches it by cutting it off, i.e. through exposure):
which of the two scaled the score.

### 4.5 Advisory (Dev B)
Geometry: **null** (join to the block via `block_id`).

*v1.2 change, pending Dev A*: one Advisory per block and timestep, holding all three languages (was one `language` and
one `body` per record).

| Property | Type | Notes |
|---|---|---|
| `id` | AdvisoryId | UUID4, lowercase. Must match `^[a-z0-9-]+$` (fixture-safe). *Added in v0.9.* |
| `block_id` | string | |
| `block_name` | string | *v1.2 change, pending Dev A* |
| `timestep` | Timestep | The timestep whose figures it cites. |
| `texts` | `{ en, bn, hi }` of AdvisoryText | *v1.2 change, pending Dev A* The advisory as shown: figures filled in, each `body` starting with the exercise label (below). |
| `templates` | `{ en, bn, hi }` of AdvisoryText | *v1.2 change, pending Dev A* The same text with `{{key}}` placeholders and no label: what Gemini wrote and what edits change. |
| `citations` | Citation[] | The source of every figure and name in `texts`, all from the engines. |
| `status` | AdvisoryStatus | `draft → approved → sent`, or `draft → rejected` (*v1.2 change, pending Dev A*). |
| `approved_by` | string \| null | Required once `approved` or `sent`. `"Name (Designation)"`, see §5. |
| `approved_at` | ISO datetime \| null | Required once `approved` or `sent`. |
| `rejection_reason` | string \| null | *v1.2 change, pending Dev A* Required once `rejected`. |
| `rejected_at` | ISO datetime \| null | *v1.2 change, pending Dev A* Required once `rejected`. |
| `created_from` | AdvisoryId \| null | *v1.2 change, pending Dev A* The advisory this draft was copied from ("New draft from this"). |
| `created_at` | ISO datetime | |
| `generated_by` | `{ provider: ModelProvider, model: string }` \| null | *v1.2 change, pending Dev A* The model that wrote the draft: Gemini (`gemini-3.7-flash`), or the Groq fallback (`GROQ_MODEL`) when Gemini answered 429, or 503 twice (one retry ~2 s later). The same checks (schema, placeholders, numbers rule, staleness) apply to both. Copied by "New draft from this"; null on advisories stored before v1.2. The `generated` audit entry records it, plus `fallback_reason` (`"gemini 429"`, `"gemini 503 x2"`) when the fallback wrote it. Demo fixtures are Gemini's only. |

`AdvisoryText = { headline: string, body: string, actions: string[] }` (*v1.2 change, pending Dev A*): `actions` has 3 to 5
lines for local officials.

`Citation = { key: string, label: string, value: number | string, unit: string | null, source: string }`
e.g. `{"key":"risk_score","label":"Block risk score (0-1)","value":0.27,"unit":null,"source":"risk"}`.
`key` matches `^[a-z0-9_]+$`. `value` may be a string (*v1.2 change, pending Dev A*): names and causes, e.g.
`{"key":"isolated_1_cause","label":"Cause","value":"ferry suspended by wind","unit":null,"source":"impact"}`.

**Numbers rule** (*v1.2 change, pending Dev A*). Gemini never writes a figure: `templates` contain no digits (any script)
and no number words outside `{{key}}` placeholders, and only keys from `citations`. The server
rejects drafts and edits that break this, and fills the placeholders: Bengali numerals for `bn`,
Latin digits for `en` and `hi`, units in the text's language. The only other digits in `texts` are
the exercise label the server puts at the start of every `body`: `[EXERCISE: Cyclone Amphan 2020
replay]`, `[মহড়া: ঘূর্ণিঝড় আমফান ২০২০ রিপ্লে]`, `[अभ्यास: चक्रवात अम्फान 2020 रीप्ले]`.

**Audit log** (*v1.2 change, pending Dev A*). Every action is recorded as
`AuditEvent = { id: int, advisory_id: AdvisoryId | null, action: AuditAction, actor: string | null,
at: ISO datetime, details: string | null }`. `advisory_id` is null for a generation that produced
no advisory (its draft failed the checks); `details` is JSON text.

`AdvisorySuggestions = { timestep, threshold: float, blocks: { block_id, block_name, score }[] }`
(*v1.2 change, pending Dev A*): the blocks at or above the suggestion threshold (0.25), highest first.

### 4.6 TriggerEvent (Dev B)
One feature per insurance zone per timestep. Geometry: zone `Polygon | MultiPolygon`.
*v1.2 change, pending Dev A:* a zone is a CD block (Census 2011 code). The feature reports the
metric that sets the payout: of wind and surge, the higher tier (never the sum of both); on a
tie, the one further past its threshold (untriggered: closer to its first threshold). Terms are
illustrative (`api/app/insurance/constants.py`): wind ≥ 33 / 46 / 62 m/s and surge ≥ 1 / 2 / 3 m
pay 25 / 50 / 100 % of a sum insured of ₹1,000 per resident (2011 population).

| Property | Type | Notes |
|---|---|---|
| `id` | string | `<zone_id>__<timestep>` |
| `zone_id` | string | |
| `zone_name` | string | |
| `timestep` | Timestep | |
| `metric` | TriggerMetric | Read from HazardLayer `value` (not severity). *v1.2:* the governing metric. |
| `unit` | `"m/s" \| "m"` | |
| `threshold` | float | *v1.2:* the governing metric's threshold for the tier reached (its first tier when none). |
| `observed` | float | *v1.2 change, pending Dev A* (was: max over the zone): the nearest-rank 90th percentile of the cells overlapping the zone's inhabited land by ≥ 1 km², so one extreme cell can't trigger alone. |
| `triggered` | boolean | `observed >= threshold` |
| `payout_estimate_inr` | float | `0` when not triggered. *v1.2:* `payout_fraction × sum_insured_inr` (the current reading). |
| `tier` | int ≥ 0 | *v1.2 change, pending Dev A.* 0 = not triggered; `triggered == (tier > 0)`. |
| `payout_fraction` | float [0, 1] | *v1.2 change, pending Dev A.* Of `sum_insured_inr`, for `tier`. |
| `sum_insured_inr` | float | *v1.2 change, pending Dev A.* |
| `released_tier` | int ≥ `tier` | *v1.2 change, pending Dev A.* The highest tier at any timestep up to this one: released money is never taken back. |
| `released_payout_inr` | float ≥ `payout_estimate_inr` | *v1.2 change, pending Dev A.* The payout for `released_tier`. |

**InsuranceSummary** (*v1.2 change, pending Dev A*), `GET /api/insurance/summary`:
`{ district: [{ timestep, released_payout_inr, triggered_zones, released_zones }] (25, never
decreasing), zones: [{ zone_id, zone_name, first_trigger_timestep | null, hours_before_landfall |
null, first_trigger_metric | null, first_trigger_tier, first_trigger_payout_inr,
final_released_tier, final_released_payout_inr, sum_insured_inr }] }`.

### 4.7 DispatchReceipt (Dev B, not GeoJSON)
*v1.2 change, pending Dev A* (was `{ advisory_id, sent_at, channels: [{ channel, ok, error }] }`):
```ts
interface DispatchReceipt {
  advisory_id: AdvisoryId;
  dispatched_at: string;            // ISO datetime
  dry_run: boolean;                 // true: built and validated, nothing sent, not stored
  resend: boolean;                  // the advisory was already sent
  channels: ChannelResult[];        // one per requested channel, each attempted on its own
}
interface ChannelResult {
  channel: Channel;                 // "telegram" | "email"
  status: ChannelStatus;            // "sent" | "failed" | "dry_run"
  provider_message_id: string | null; // Telegram message ids (comma-separated) / e-mail Message-ID
  error: string | null;             // when failed; never contains a credential
  at: string;                       // ISO datetime
}
```
(`AdvisoryId` as in §4.5.) Rules: only `approved` advisories (`409`); a `sent` one needs
`resend: true` (`409`). A live dispatch needs `pin` matching `DISPATCH_PIN` in `api/.env`
(`403` if wrong or unset); dry runs need none. At most 10 live dispatches per rolling hour
(`429`). Recipients come only from `api/.env` (Telegram chat, e-mail list), never from a request.
Each channel attempt is audited (`dispatched`, details = the ChannelResult); the advisory becomes
`sent` (audit `sent`) if at least one channel succeeded. Live receipts are stored in SQLite; dry
runs only in the audit log. Dispatch sends for real in DEMO_MODE too (a human-approved action,
not a data fetch).

**Channels.** Telegram: plain text, one message per language (bn, then en), split at 4096
characters. E-mail (Gmail SMTP, STARTTLS): subject starts `[EXERCISE]`, body en then bn, the CAP
attached.

**CAP 1.2** (validated against the OASIS XSD): `status` Exercise, `msgType` Alert, `scope` Public,
`sender` `tempest-s24p-exercise@invalid`; one `<info>` per language (`en-IN`, `bn-IN`, `hi-IN`),
`category` Met, `event` Cyclone, `headline`, `description` = body, `instruction` = the actions;
`<area>`: block name, the simplified block polygon (lat,lon, one per part), and `<geocode>`
`census2011_cd` = the block's Census 2011 code. Mapping from the advisory's cited figures:
`severity` from the risk score (≥ 0.6 Extreme, ≥ 0.4 Severe, ≥ 0.25 Moderate, else Minor);
`urgency` Immediate at ≤ 12 h to landfall, else Future (CAP's Expected means "within the next
hour"); `certainty` Observed at landfall, else Likely.

## 5. Routes

All under `/api`. `timestep` is always a query param of type `TimestepParam`, required unless
stated; `timestep=live` returns `501` in v1.1. FC = FeatureCollection.

| Owner | Method | Path | Params / body | Response |
|---|---|---|---|---|
| A | GET | `/api/hazard/timesteps` | — | `{ event: "amphan", landfall: Timestep, timesteps: Timestep[] }` |
| A | GET | `/api/hazard/layers` | `hazard_type: HazardType`, `timestep` | FC&lt;HazardLayer&gt; |
| A | GET | `/api/hazard/validation` | — | Validation overview: `{ execution_timestamp, event_name, aggregate_metrics, blocks[] }`. Each block includes `sar_water_km2` (pixel-area, no threshold) when GEE was online. Read-only; `503` if artifacts missing from `data/demo/validation/`. *v1.3 change, pending Dev B* |
| A | GET | `/api/hazard/validation/{block}` | — | Detailed block validation (metrics, acquisition, artifact downloads). Prediction uses **max surge depth over all 25 timesteps**. `404` unknown block; `503` if not run. *v1.3 change, pending Dev B* |
| A | GET | `/api/hazard/validation/{block}/metrics` | — | `{ block, metrics }` with IoU, Precision, Recall, F1, confusion matrix. Cell-level (~5.5 km), 10% flood-fraction threshold, surge-only prediction. `503` if not run. *v1.3 change, pending Dev B* |
| A | GET | `/api/hazard/validation/{block}/artifacts` | — | `{ block, artifacts[] }` with download URLs (GeoTIFFs, GeoJSONs, metrics JSON, acquisition metadata JSON). `404` if block missing. *v1.3 change, pending Dev B* |
| A | GET | `/api/hazard/validation/{block}/artifacts/{artifact_name}` | — | File download (cell-label GeoTIFF, GeoJSON, JSON). `404` if missing. *v1.3 change, pending Dev B* |
| B | GET | `/api/exposure/infra` | `infra_type?: InfraType` | FC&lt;InfraFeature&gt; (not time-dependent) |
| B | GET | `/api/impact/results` | `timestep`, `hazard_type?`, `status?: ImpactStatus` | FC&lt;ImpactResult&gt; |
| B | GET | `/api/risk/scores` | `timestep` | FC&lt;RiskScore&gt; |
| B | GET | `/api/risk/breakdown` | `timestep` | RiskBreakdown. *added in v1.1.* |
| B | GET | `/api/risk/unscored-areas` | — | FC&lt;UnscoredArea&gt; (static; live from reference data, DEMO_MODE from the `unscored-areas` fixture). *added in v1.1.* |
| B | GET | `/api/advisory/` | `status?`, `block_id?`, `timestep?` (*v1.2 change, pending Dev A*) | FC&lt;Advisory&gt;, newest first |
| B | POST | `/api/advisory/` | `{ block_id, timestep }` (*v1.2 change, pending Dev A*: no `language`) | Advisory (`draft`). `502` if Gemini's draft fails the numbers rule twice; `503` with no cached response and no Gemini key. |
| B | GET | `/api/advisory/suggestions` | `timestep` | AdvisorySuggestions. *v1.2 change, pending Dev A* |
| B | GET | `/api/advisory/audit` | — | `{ events: AuditEvent[] }`, all events. *v1.2 change, pending Dev A* |
| B | GET | `/api/advisory/{advisory_id}` | — | Advisory |
| B | PATCH | `/api/advisory/{advisory_id}` | `{ templates, edited_by? }` (*v1.2 change, pending Dev A*: was `{ body }`); `draft` only, else `409`; `422` if it breaks the numbers rule or removes a placeholder | Advisory |
| B | POST | `/api/advisory/{advisory_id}/approve` | `{ approved_by }` as `"Name (Designation)"`, designation `BDO`, `SDO`, `ADM (Disaster Management)`, `District Magistrate` or `Other: <role>` (*v1.2 change, pending Dev A*), else `422`; `draft` only, else `409` | Advisory (`approved`) |
| B | POST | `/api/advisory/{advisory_id}/reject` | `{ reason, rejected_by? }`; `reason` not blank, else `422`; `draft` only, else `409` | Advisory (`rejected`). *v1.2 change, pending Dev A* |
| B | POST | `/api/advisory/{advisory_id}/new-draft` | `{ created_by? }`; not a `draft`, else `409` | Advisory (`draft`, `created_from` set). *v1.2 change, pending Dev A* |
| B | GET | `/api/advisory/{advisory_id}/audit` | — | `{ events: AuditEvent[] }`, oldest first. *v1.2 change, pending Dev A* |
| B | POST | `/api/dispatch/{advisory_id}` | `{ channels: ("telegram" \| "email")[], resend?, dry_run?, pin? }` (*v1.2 change, pending Dev A*: resend, dry_run, pin); rules in §4.7 | DispatchReceipt; advisory → `sent` |
| B | GET | `/api/dispatch/{advisory_id}/receipts` | — | `{ receipts: DispatchReceipt[] }`, oldest first. *v1.2 change, pending Dev A* |
| B | GET | `/api/dispatch/{advisory_id}/cap.xml` | — | CAP 1.2 XML of the latest dispatch (a fresh one if approved and never sent; `409` otherwise). *v1.2 change, pending Dev A* |
| B | GET | `/api/dispatch/recipients` | — | `{ telegram: { configured, chat_id }, email: { configured, to[] }, pin_configured }`, masked. *v1.2 change, pending Dev A* |
| B | GET | `/api/insurance/triggers` | `timestep` | FC&lt;TriggerEvent&gt;, one per CD block |
| B | GET | `/api/insurance/summary` | — | InsuranceSummary. *v1.2 change, pending Dev A* |
| — | GET | `/health` | — | not part of this contract (see README) |

The `/api/hazard/*` routes are for the web client only. Dev B reads hazard data through §6.

## 6. Internal interface (Dev A → Dev B)

Dev A owns and implements this function. Dev B's modules import it and **never make HTTP calls to
`/api/hazard/*` routes**, and never edit `app/hazard/`.

```python
# api/app/hazard/service.py
def get_hazard_layer(hazard_type: HazardType, timestep: str) -> HazardLayerCollection: ...
```

| Aspect | Rule |
|---|---|
| `hazard_type` | `"wind" \| "surge" \| "flood"` |
| `timestep` | A `TimestepParam`. `"live"` raises `NotImplementedError` in v1.1; any other value not in the replay list raises `ValueError`. |
| Returns | `HazardLayerCollection` = FeatureCollection&lt;HazardLayer&gt; (Pydantic model from `app.schemas`), same content as `GET /api/hazard/layers`. |
| DEMO_MODE | Served from Dev A's `hazard__layers-<hazard_type>__<ts>` fixture. |
| Calling | Synchronous. Callers may cache results per (hazard_type, timestep). |
| Route handlers | Any route that calls `get_hazard_layer` (directly or indirectly) must be a sync `def` handler, **not** `async def`, so FastAPI runs it in its threadpool instead of blocking the event loop. |

## 7. DEMO_MODE fixtures (`api/data/demo/`)

With `DEMO_MODE=true`, every external call (GEE, Open-Meteo, GDACS, Gemini, Overpass) and every
computed route response is served from a fixture. Load with `app.core.demo.load_fixture(key)`.

**File name = `<key>.json`, key = `<module>__<resource>[__<ts>]`**

| Part | Rule |
|---|---|
| `module` | The owning package: `hazard`, `exposure`, `impact`, `risk`, `advisory`, `dispatch`, `insurance`. You only write fixtures for your own modules. |
| `resource` | Lowercase `[a-z0-9-]+`. Route responses use the route's last path segment plus distinguishing params (`layers-surge`, `infra`). Raw upstream responses are prefixed with the source: `gee-`, `openmeteo-`, `gdacs-`, `gemini-`, `overpass-`. |
| `ts` | Only if time-dependent. **Compact** form `YYYYMMDDTHHMMZ` (e.g. `20200520T1200Z`), because `:` is invalid in Windows file names. |
| Separator | Double underscore `__` between parts. Single `_` never appears. |
| Allowed chars | `load_fixture` accepts keys matching `^[A-Za-z0-9_-]+$` only: no dots, no slashes. |

**Route fixture resources** *(added in v0.9)*. Every route response
fixture uses one of these resources. `tests/test_demo_fixtures.py` validates each file against
the schema listed here, and fails on any route resource not in this table.

| Route | Resource | Timestep suffix | Schema |
|---|---|---|---|
| `GET /api/hazard/timesteps` | `timesteps` | no | ReplayTimeline |
| `GET /api/hazard/track` (internal) | `track` | no | CycloneTrack *(added in v1.1)* |
| `GET /api/hazard/layers` | `layers-<hazard_type>` | yes | FC&lt;HazardLayer&gt; |
| `GET /api/exposure/infra` | `infra-<infra_type>`, one per type. Unfiltered: no fixture of its own; composed from the per-type files *(added in v0.9)* | no | FC&lt;InfraFeature&gt; |
| `GET /api/impact/results` | `results`, or `results-<filter>` with `[a-z0-9-]` filter values | yes | FC&lt;ImpactResult&gt; |
| `GET /api/risk/scores` | `scores` | yes | FC&lt;RiskScore&gt; |
| `GET /api/risk/breakdown` | `breakdown` *(added in v1.1)* | yes | RiskBreakdown |
| `GET /api/risk/unscored-areas` | `unscored-areas` *(added in v1.1)* | no | FC&lt;UnscoredArea&gt; |
| `GET /api/insurance/triggers` | `triggers` (compact, see below) | yes | FC&lt;TriggerEvent&gt; |
| `GET /api/insurance/summary` | `summary` *(v1.2 change, pending Dev A)* | no | InsuranceSummary |

Enum values containing `_` (e.g. `power_line`) are written with `-` in resource names:
`exposure__infra-power-line`. `advisory_id` is fixture-safe by §4.5, so it is used as is.

Examples:
```
hazard__timesteps.json
hazard__track.json *(added in v1.1)*
hazard__layers-surge__20200520T1200Z.json
hazard__gee-flood-susceptibility.json
exposure__infra-power-line.json
exposure__overpass-substations.json
impact__results__20200519T0000Z.json
risk__scores__20200520T1200Z.json
advisory__gemini-<census_code>__20200520T1200Z.json *(v1.2 change, pending Dev A)*
insurance__triggers__20200520T1200Z.json
insurance__summary.json *(v1.2 change, pending Dev A)*
```

Fixture content is exactly the route response (or the raw upstream body) as JSON, UTF-8, LF.
Advisories are local state (SQLite), not fixtures, in both modes (*v1.2 change, pending Dev A*): the only advisory
fixtures are Gemini's raw responses, `advisory__gemini-<census_code>__<ts>`, one per block and
timestep with all three languages. In DEMO_MODE a cached response is used when present, else the
live Gemini key if set, else `503`.
*Exception (added in v1.1):* `impact__results__<ts>` stores only the non-`ok` rows.
When loading it, the route adds an `ok` row (empty `pathway`) for every InfraFeature and hazard
type not present, so the response is exactly the full contract collection.
*Exception (added in v1.1):* `risk__scores__<ts>` stores each RiskScore without its
`geometry` (the block polygon, the same at every timestep). When loading it, the route adds the
geometry back from the block reference file (`api/data/reference/s24p_blocks.geojson`), so the
response is exactly the full contract collection. `risk__breakdown__<ts>` has no geometry and is
stored as is.
*Exception (v1.2 change, pending Dev A):* `insurance__triggers__<ts>` stores each TriggerEvent
without its `geometry`, which the route adds back from the same block reference file, as for
`risk__scores__<ts>`.
Keep each file under ~2 MB, roads up to 5 MB (`exposure__infra-road`) *(added in v0.9)*. Anything larger or regenerable goes in `api/data/cache/` (ignored).
