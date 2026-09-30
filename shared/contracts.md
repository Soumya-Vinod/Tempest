# Tempest contracts — v1.3 (FROZEN)

The interface between **Dev A (hazard)** and **Dev B (exposure, impact, risk, advisory, dispatch,
insurance)**. This file is the source of truth. `api/app/schemas/` (Pydantic) and
`web/src/types/contracts.ts` (TypeScript) mirror it exactly.

**Change rule (active):** any change needs sign-off from both devs, a version bump here, and the
matching Pydantic + TS edits in the same commit. Proposed changes are marked *v1.4 change, pending
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
| Errors | FastAPI default `{"detail": ...}`. `404` unknown id, `409` invalid state change, `422` bad params (incl. unknown `timestep`), `501` not implemented yet, `503` required processed data missing (live mode) *(added in v0.9)*, or an upstream key missing; `502` an upstream (Gemini) response unusable *(added in v1.2)*. `403` wrong or unset dispatch PIN, `429` dispatch rate limit *(added in v1.2)*. |

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

### Forecast horizon (*added in v1.3*)
`Horizon = 0 | 24` (hours). `FORECAST_HORIZON_H = 24`. The **expected hazard** at timestep t is,
per hazard type and grid cell, the maximum `value` (and `severity`) over the replay timesteps
from t to t + 24 h, capped at landfall. Impact and risk accept `horizon` (default 0 = now, on the
observed hazard); with 24 they run unchanged on the expected hazard, so their results mean
"expected within 24 h": `isolated` at horizon 24 means *expected* to be cut off. This is a
**perfect-forecast replay** (the "forecast" is the replay's own future); operationally the same
hazard model would run on IMD's forecast track. The per-cell maximum over the window is
conservative: wind and surge peaks that never coincide are both kept. Hazard layers
(`/api/hazard/layers`) are unchanged. Insurance payouts stay on the observed hazard.

## 3. Shared types

```ts
type HazardType   = "wind" | "surge" | "flood";
type InfraType    = "substation" | "power_line" | "road" | "hospital" | "shelter";
type ImpactStatus = "ok" | "at_risk" | "cut" | "isolated";
type StepType     = "hazard" | "infra" | "service";
type Language     = "en" | "bn" | "hi";
type AdvisoryStatus = "draft" | "approved" | "sent" | "rejected";  // rejected: added in v1.2
type AuditAction = "generated" | "number_check_failed" | "invalid_response" | "edited"
  | "approved" | "rejected" | "new_draft" | "copied" | "sent"
  | "dispatched";  // added in v1.2 (dispatched: one per channel attempt)
type ChannelStatus = "sent" | "failed" | "dry_run";  // added in v1.2
type ModelProvider = "gemini" | "groq";  // added in v1.2
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
| `horizon_h` | Horizon | *added in v1.3.* 0 = the status now; 24 = expected within 24 h. Default 0. |

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

**Action countdown** (*added in v1.3*): per replay timestep, derived from the
ImpactResults at both horizons. `ActionCountdown = { timestep, horizon_h: Horizon (24), expected:
CountdownFacility[], cut_off: CountdownFacility[], key_moments: KeyMoment[] }`.
- `expected`: facilities `isolated` at horizon 24 but not at horizon 0, soonest first by
  `hours_remaining` (hours until they are first `isolated` at horizon 0; null if never later in
  the replay, listed last), then by name.
- `cut_off`: facilities `isolated` at horizon 0, by `since` (the first timestep of the current
  unbroken isolation), then by name.
- `CountdownFacility = { infra_id, name, infra_type: InfraType, cause: string, cut_infra_id:
  string | null, cut_name: string | null, hours_remaining?: int | null, since?: Timestep | null }`.
  `cause` is plain words from the isolating hazard and the first cut link on the usual route:
  `"ferry suspended by wind"` or `"road cut by <hazard_type>"`.
- `KeyMoment = { kind, timestep: Timestep | null, label: string }`, `kind` one of
  `first_alert` (the first advisory suggestion, by the rule in §4.5), `first_expected_isolation`, `first_actual_isolation`, `landfall`, in that
  order; the same at every timestep. `timestep` is null if it never happens.

**Last safe departure** (*added in v1.3*): not time-dependent.
`Departures = { resolution_h: 3, departures: Departure[] }`, by `deadline` (null last), then name.
One `Departure` per hospital or health centre (`infra_type` `hospital`; shelter stand-ins have
none) that is `isolated` at horizon 0 at some step, except
names matching the hospital-access exclusions (§4.5):
`{ infra_id, name, infra_type, first_cut_off: Timestep, deadline: Timestep | null,
route_stays_open: bool, destination_id: string | null, destination_name: string | null,
travel_time_s: int | null, uses_ferry: bool | null, at_risk: bool | null, legs: DepartureLeg[],
usual_destination_id: string | null, usual_destination_name: string | null, note: string | null }`,
`DepartureLeg = { ferry: bool, geometry: LineString }` (simplified, ~50 m), facility first.
- Safe destinations: hospital-access sources within 2 km of the road graph, in its main
  component, and never `isolated` at horizon 0 from T-72 to T-0.
- `deadline`: at each step, the road graph with that step's cut links removed (surge on roads,
  wind on ferries, as for `isolated`); the last step before the first step at which no safe
  destination is reachable. Null if none is reachable at T-72; T-0 with `route_stays_open` if
  one stays reachable.
- `destination_*`: the nearest safe destination reachable at the deadline step;
  `travel_time_s` is that route's normal-condition time; `uses_ferry` if any leg is a ferry;
  `at_risk` if any link on it is at risk at that step. `usual_destination_*`: the nearest on the
  intact network. `note` says why there is no deadline or destination.
- Times are normal-condition estimates at the replay's 3-hour resolution.
- Advisory facts add, per expected hospital or health centre with a deadline not yet passed,
  `expected_<n>_leave_by_hours` (h), `expected_<n>_destination` and `expected_<n>_route_mode`
  (`road` | `ferry`).

**Critical links** (*v1.4 change, pending Dev A*): per timestep × horizon, derived from the
last safe departure routes above (no other data).
`CriticalLinks = { timestep, horizon_h: Horizon, note: string, links: CriticalLink[] }`,
`note` = "Based on normal-condition routes to the nearest safe hospital."
`CriticalLink = { way_ids: int[], infra_ids: string[], label: string, name: string | null,
link_type: "road" | "ferry", blocks: string[], facility_count: int ≥ 1,
facilities: { infra_id, name, deadline: Timestep }[], earliest_deadline: Timestep,
geometry: LineString | MultiLineString }`.
- Counted routes: horizon 0, departures whose `deadline` has not passed (`deadline` ≥
  `timestep`); horizon 24, of those, the ones whose `deadline` is within the next 24 h
  (`route_stays_open` ones left out).
- Each OSM way counts the counted routes that use it. Ways that follow each other on a route,
  share a name (or are both unnamed, of the same type) and serve exactly the same facilities
  are one link: `way_ids` in the direction of travel, `infra_ids` the exposure road features
  (`road-way-<id>`), `geometry` theirs.
- `label`: `name`, else "Unnamed road" / "Unnamed ferry route", then the CD blocks it runs
  through in brackets, in the direction of travel of the facility with the earliest deadline:
  "Unnamed road (Sagar → Namkhana)".
- `links`: by `facility_count` (most first), then `earliest_deadline`, then `label`;
  `facilities` by `deadline`, then name. Empty once every deadline has passed.

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
| `horizon_h` | Horizon | *added in v1.3.* 24 = on the expected hazard. Default 0. |

**Unscored areas** *(added in v1.1)*: parts of the AOI clip that no block covers
(Kolkata, and South 24 Parganas municipal areas outside the CD blocks) get no RiskScore. They are
served as FC&lt;UnscoredArea&gt;: geometry `Polygon | MultiPolygon`, properties `{ id: string,
label: string, area_km2: number }`, with `label` "Municipal area, not scored".

**Risk breakdown** *(added in v1.1)*: the parts behind each block's score, for
explaining it. `RiskBreakdown = { timestep, blocks: RiskBlockBreakdown[], horizon_h }` (`horizon_h`:
*added in v1.3*) with
`RiskBlockBreakdown = { block_id, block_name, population_2011: int, surge_population: int (*added in
v1.3*), hospital_travel_min:
number | null, reach: RiskReach, hazard: { surge, wind, flood }, exposure: { isolated_facilities, cut_roads,
cut_substations }, vulnerability: { population_density, hospital_access, low_literacy,
mapped_shelters } }`; every part is a float in [0, 1]. *added in v1.3:*
`surge_population` is an estimate of the people in areas with surge ≥ 0.3 m:
`round(population_2011 × hazard.surge)`, i.e. the 2011 population spread evenly over the block's
inhabited land (at horizon 24, the worst case over the next 24 h); `RiskBreakdown` adds
`surge_population_total: int`, the sum over the blocks. `hospital_travel_min` is null when no
road node in the block reaches a hospital. `RiskReach` is `direct` (the cyclone reaches the block
through hazard on its land) or `cut_off` (it reaches it by cutting it off, i.e. through exposure):
which of the two scaled the score.

### 4.5 Advisory (Dev B)
Geometry: **null** (join to the block via `block_id`).

*added in v1.2*: one Advisory per block and timestep, holding all three languages (was one `language` and
one `body` per record).

| Property | Type | Notes |
|---|---|---|
| `id` | AdvisoryId | UUID4, lowercase. Must match `^[a-z0-9-]+$` (fixture-safe). *Added in v0.9.* |
| `block_id` | string | |
| `block_name` | string | *added in v1.2* |
| `timestep` | Timestep | The timestep whose figures it cites. |
| `texts` | `{ en, bn, hi }` of AdvisoryText | *added in v1.2* The advisory as shown: figures filled in, each `body` starting with the exercise label (below). |
| `templates` | `{ en, bn, hi }` of AdvisoryText | *added in v1.2* The same text with `{{key}}` placeholders and no label: what Gemini wrote and what edits change. |
| `citations` | Citation[] | The source of every figure and name in `texts`, all from the engines. |
| `status` | AdvisoryStatus | `draft → approved → sent`, or `draft → rejected` (*added in v1.2*). |
| `approved_by` | string \| null | Required once `approved` or `sent`. `"Name (Designation)"`, see §5. |
| `approved_at` | ISO datetime \| null | Required once `approved` or `sent`. |
| `rejection_reason` | string \| null | *added in v1.2* Required once `rejected`. |
| `rejected_at` | ISO datetime \| null | *added in v1.2* Required once `rejected`. |
| `created_from` | AdvisoryId \| null | *added in v1.2* The advisory this draft was copied from ("New draft from this"). |
| `created_at` | ISO datetime | |
| `generated_by` | `{ provider: ModelProvider, model: string }` \| null | *added in v1.2* The model that wrote the draft: Gemini (`gemini-3.7-flash`), or the Groq fallback (`GROQ_MODEL`) when Gemini answered 429, or 503 twice (one retry ~2 s later). The same checks (schema, placeholders, numbers rule, staleness) apply to both. Copied by "New draft from this"; null on advisories stored before v1.2. The `generated` audit entry records it, plus `fallback_reason` (`"gemini 429"`, `"gemini 503 x2"`) when the fallback wrote it. Demo fixtures are Gemini's only. |

`AdvisoryText = { headline: string, body: string, actions: string[] }` (*added in v1.2*): `actions` has 3 to 5
lines for local officials.

`Citation = { key: string, label: string, value: number | string, unit: string | null, source: string }`
e.g. `{"key":"risk_score","label":"Block risk score (0-1)","value":0.27,"unit":null,"source":"risk"}`.
`key` matches `^[a-z0-9_]+$`. `value` may be a string (*added in v1.2*): names and causes, e.g.
`{"key":"isolated_1_cause","label":"Cause","value":"ferry suspended by wind","unit":null,"source":"impact"}`.

**Numbers rule** (*added in v1.2*). Gemini never writes a figure: `templates` contain no digits (any script)
and no number words outside `{{key}}` placeholders, and only keys from `citations`. The server
rejects drafts and edits that break this, and fills the placeholders: Bengali numerals for `bn`,
Latin digits for `en` and `hi`, units in the text's language. The only other digits in `texts` are
the exercise label the server puts at the start of every `body`: `[EXERCISE: Cyclone Amphan 2020
replay]`, `[মহড়া: ঘূর্ণিঝড় আমফান ২০২০ রিপ্লে]`, `[अभ्यास: चक्रवात अम्फान 2020 रीप्ले]`.

**Audit log** (*added in v1.2*). Every action is recorded as
`AuditEvent = { id: int, advisory_id: AdvisoryId | null, action: AuditAction, actor: string | null,
at: ISO datetime, details: string | null }`. `advisory_id` is null for a generation that produced
no advisory (its draft failed the checks); `details` is JSON text.

`AdvisorySuggestions = { timestep, threshold: float, blocks: { block_id, block_name, score,
reasons: SuggestionReason[] }[] }` (*added in v1.2*): the suggested blocks, highest score first,
then by name. *added in v1.3:* a block is suggested when, on the expected hazard
(horizon 24), its risk score is at or above `threshold` (0.25) **or** a hospital or shelter inside
it is `isolated` in the horizon-24 impact results (expected to be cut off within 24 h, including
already cut off). Facilities whose name matches the hospital-access exclusions (nursing homes,
diagnostic centres, clinics, eye / dental / maternity; government hospitals always count) are no
reason, and are not listed in the advisory facts; they stay in the impact results.
`SuggestionReason = { kind: "risk" | "expected_cut_off", label: string, infra_id: string | null }`,
at least one per block: the risk first (`"risk 0.28"`), then one per facility by name
(`"Frasergunj PHC expected to be cut off"`, with its `infra_id`). The action countdown's
`first_alert` key moment (§4.3) uses the same rule.

### 4.6 TriggerEvent (Dev B)
One feature per insurance zone per timestep. Geometry: zone `Polygon | MultiPolygon`.
*added in v1.2:* a zone is a CD block (Census 2011 code). The feature reports the
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
| `observed` | float | *added in v1.2* (was: max over the zone): the nearest-rank 90th percentile of the cells overlapping the zone's inhabited land by ≥ 1 km², so one extreme cell can't trigger alone. |
| `triggered` | boolean | `observed >= threshold` |
| `payout_estimate_inr` | float | `0` when not triggered. *v1.2:* `payout_fraction × sum_insured_inr` (the current reading). |
| `tier` | int ≥ 0 | *added in v1.2.* 0 = not triggered; `triggered == (tier > 0)`. |
| `payout_fraction` | float [0, 1] | *added in v1.2.* Of `sum_insured_inr`, for `tier`. |
| `sum_insured_inr` | float | *added in v1.2.* |
| `released_tier` | int ≥ `tier` | *added in v1.2.* The highest tier at any timestep up to this one: released money is never taken back. |
| `released_payout_inr` | float ≥ `payout_estimate_inr` | *added in v1.2.* The payout for `released_tier`. |
| `expected_tier_24h` | int ≥ 0 | *added in v1.3.* The tier the expected hazard (next 24 h) would reach. Information only: payouts follow the observed hazard. |

**InsuranceSummary** (*added in v1.2*), `GET /api/insurance/summary`:
`{ district: [{ timestep, released_payout_inr, triggered_zones, released_zones }] (25, never
decreasing), zones: [{ zone_id, zone_name, first_trigger_timestep | null, hours_before_landfall |
null, first_trigger_metric | null, first_trigger_tier, first_trigger_payout_inr,
final_released_tier, final_released_payout_inr, sum_insured_inr }] }`.

### 4.7 DispatchReceipt (Dev B, not GeoJSON)
*added in v1.2* (was `{ advisory_id, sent_at, channels: [{ channel, ok, error }] }`):
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
characters. E-mail (Gmail SMTP with STARTTLS, or Brevo's HTTPS API; set by `EMAIL_PROVIDER`):
subject starts `[EXERCISE]`, body en then bn, the CAP attached.

**CAP 1.2** (validated against the OASIS XSD): `status` Exercise, `msgType` Alert, `scope` Public,
`sender` `tempest-s24p-exercise@invalid`; one `<info>` per language (`en-IN`, `bn-IN`, `hi-IN`),
`category` Met, `event` Cyclone, `headline`, `description` = body, `instruction` = the actions;
`<area>`: block name, the simplified block polygon (lat,lon, one per part), and `<geocode>`
`census2011_cd` = the block's Census 2011 code. Mapping from the advisory's cited figures:
`severity` from the risk score (≥ 0.6 Extreme, ≥ 0.4 Severe, ≥ 0.25 Moderate, else Minor);
`urgency` Immediate at ≤ 12 h to landfall, else Future (CAP's Expected means "within the next
hour"); `certainty` Observed at landfall, else Likely.

### 4.8 IMD Bulletins Multimodal Analysis (Dev A, not GeoJSON)
*v1.4 change, pending Dev B*:
Offline, cached multimodal analysis of real, downloaded India Meteorological Department (IMD)
RSMC New Delhi cyclone bulletins for Cyclone Amphan spanning T-72 to T-0 (landfall).
Extracted using Gemini 2.5 Flash (noted honestly due to Gemini 3.7 Flash high demand spikes).
Every value traces strictly to a committed raw Gemini response and source reference document.
Never typed in, estimated or invented.

```ts
interface ImdBulletinCollection {
  event: string;                          // "amphan"
  actual_landfall: ActualLandfallReference; // IBTrACS ground truth
  bulletins: ImdBulletin[];
}

interface ImdBulletin {
  id: string;                             // e.g. "imd-bulletin-36"
  bulletin_number: string;                // e.g. "National Bulletin No. 36"
  nominal_timestep: Timestep;             // replay timestep (contracts.md §2)
  target_stage: string;                   // "T-72", "T-42", "T-27", "T-12", "T-3", "T-0"
  hours_to_landfall: number;              // -72.0, -42.0, -27.0, -12.0, -3.0, 0.0
  source_url: string;                     // official RSMC New Delhi archive URL
  source_filename: string;                // committed PDF filename under api/data/reference/imd/
  sha256: string;                         // SHA-256 hash of the committed source document
  issue_date_time: BulletinIssueDateTime;
  current_storm_position: BulletinCurrentPosition;
  current_intensity: BulletinCurrentIntensity;
  forecast_landfall: BulletinForecastLandfall;
  forecast_max_wind_at_landfall: BulletinForecastMaxWindAtLandfall;
  storm_surge_forecast: BulletinStormSurgeForecast;
  warned_areas: BulletinWarnedAreas;
  landfall_comparison: BulletinLandfallComparison; // corridor containment vs actual crossing
  extraction_notes?: string | null;
}
```
Every extracted field is nullable and contains the 1-indexed `page` number where it was found in the official PDF.
Landfall comparison checks whether the forecast corridor contains the actual crossing location (`corridor_contains_actual_crossing: boolean`), avoiding circular numeric coordinate comparisons.
Served from static fixture `hazard__imd-bulletins.json` in DEMO_MODE. Never calls Gemini at runtime.

## 5. Routes


All under `/api`. `timestep` is always a query param of type `TimestepParam`, required unless
stated; `timestep=live` returns `501` in v1.1. FC = FeatureCollection.

| Owner | Method | Path | Params / body | Response |
|---|---|---|---|---|
| A | GET | `/api/hazard/timesteps` | — | `{ event: "amphan", landfall: Timestep, timesteps: Timestep[] }` |
| A | GET | `/api/hazard/track` | — | CycloneTrack (internal, 25 replay fixes) |
| A | GET | `/api/hazard/layers` | `hazard_type: HazardType`, `timestep` | FC&lt;HazardLayer&gt; |
| A | GET | `/api/hazard/bulletins` | — | ImdBulletinCollection (cached from `hazard__imd-bulletins.json` fixture in DEMO_MODE, static, never calls Gemini at runtime). *v1.4 change, pending Dev B* |

| A | GET | `/api/hazard/validation` | — | Validation overview: `{ execution_timestamp, event_name, aggregate_metrics, blocks[] }`. Each block includes `sar_water_km2` (pixel-area, no threshold) when GEE was online. Read-only; `503` if artifacts missing from `data/demo/validation/`. *v1.3 change, pending Dev B* |
| A | GET | `/api/hazard/validation/{block}` | — | Detailed block validation (metrics, acquisition, artifact downloads). Prediction uses **max surge depth over all 25 timesteps**. `404` unknown block; `503` if not run. *v1.3 change, pending Dev B* |
| A | GET | `/api/hazard/validation/{block}/metrics` | — | `{ block, metrics }` with IoU, Precision, Recall, F1, confusion matrix. Cell-level (~5.5 km), 10% flood-fraction threshold, surge-only prediction. `503` if not run. *v1.3 change, pending Dev B* |
| A | GET | `/api/hazard/validation/{block}/artifacts` | — | `{ block, artifacts[] }` with download URLs (GeoTIFFs, GeoJSONs, metrics JSON, acquisition metadata JSON). `404` if block missing. *v1.3 change, pending Dev B* |
| A | GET | `/api/hazard/validation/{block}/artifacts/{artifact_name}` | — | File download (cell-label GeoTIFF, GeoJSON, JSON). `404` if missing. *v1.3 change, pending Dev B* |
| B | GET | `/api/exposure/infra` | `infra_type?: InfraType` | FC&lt;InfraFeature&gt; (not time-dependent) |
| B | GET | `/api/impact/results` | `timestep`, `hazard_type?`, `status?: ImpactStatus`, `horizon?: 0 \| 24` (*added in v1.3*; other values `422`) | FC&lt;ImpactResult&gt; |
| B | GET | `/api/impact/countdown` | `timestep` | ActionCountdown (§4.3). *added in v1.3* |
| B | GET | `/api/impact/departures` | — | Departures (§4.3). *added in v1.3* |
| B | GET | `/api/impact/critical-links` | `timestep`, `horizon?: 0 \| 24` (other values `422`) | CriticalLinks (§4.3). *v1.4 change, pending Dev A* |
| B | GET | `/api/risk/scores` | `timestep`, `horizon?: 0 \| 24` (*added in v1.3*) | FC&lt;RiskScore&gt; |
| B | GET | `/api/risk/breakdown` | `timestep`, `horizon?: 0 \| 24` (*added in v1.3*) | RiskBreakdown. *added in v1.1.* |
| B | GET | `/api/risk/unscored-areas` | — | FC&lt;UnscoredArea&gt; (static; live from reference data, DEMO_MODE from the `unscored-areas` fixture). *added in v1.1.* |
| B | GET | `/api/advisory/` | `status?`, `block_id?`, `timestep?` (*added in v1.2*) | FC&lt;Advisory&gt;, newest first |
| B | POST | `/api/advisory/` | `{ block_id, timestep }` (*added in v1.2*: no `language`) | Advisory (`draft`). `502` if Gemini's draft fails the numbers rule twice; `503` with no cached response and no Gemini key. |
| B | GET | `/api/advisory/suggestions` | `timestep` | AdvisorySuggestions. *added in v1.2* |
| B | GET | `/api/advisory/audit` | — | `{ events: AuditEvent[] }`, all events. *added in v1.2* |
| B | GET | `/api/advisory/{advisory_id}` | — | Advisory |
| B | PATCH | `/api/advisory/{advisory_id}` | `{ templates, edited_by? }` (*added in v1.2*: was `{ body }`); `draft` only, else `409`; `422` if it breaks the numbers rule or removes a placeholder | Advisory |
| B | POST | `/api/advisory/{advisory_id}/approve` | `{ approved_by }` as `"Name (Designation)"`, designation `BDO`, `SDO`, `ADM (Disaster Management)`, `District Magistrate` or `Other: <role>` (*added in v1.2*), else `422`; `draft` only, else `409` | Advisory (`approved`) |
| B | POST | `/api/advisory/{advisory_id}/reject` | `{ reason, rejected_by? }`; `reason` not blank, else `422`; `draft` only, else `409` | Advisory (`rejected`). *added in v1.2* |
| B | POST | `/api/advisory/{advisory_id}/new-draft` | `{ created_by? }`; not a `draft`, else `409` | Advisory (`draft`, `created_from` set). *added in v1.2* |
| B | GET | `/api/advisory/{advisory_id}/audit` | — | `{ events: AuditEvent[] }`, oldest first. *added in v1.2* |
| B | POST | `/api/dispatch/{advisory_id}` | `{ channels: ("telegram" \| "email")[], resend?, dry_run?, pin? }` (*added in v1.2*: resend, dry_run, pin); rules in §4.7 | DispatchReceipt; advisory → `sent` |
| B | GET | `/api/dispatch/{advisory_id}/receipts` | — | `{ receipts: DispatchReceipt[] }`, oldest first. *added in v1.2* |
| B | GET | `/api/dispatch/{advisory_id}/cap.xml` | — | CAP 1.2 XML of the latest dispatch (a fresh one if approved and never sent; `409` otherwise). *added in v1.2* |
| B | GET | `/api/dispatch/recipients` | — | `{ telegram: { configured, chat_id }, email: { configured, to[] }, pin_configured }`, masked. *added in v1.2* |
| B | GET | `/api/insurance/triggers` | `timestep` | FC&lt;TriggerEvent&gt;, one per CD block |
| B | GET | `/api/insurance/summary` | — | InsuranceSummary. *added in v1.2* |
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
| `GET /api/hazard/bulletins` | `imd-bulletins` | no | ImdBulletinCollection *(v1.4 change, pending Dev B)* |

| `GET /api/exposure/infra` | `infra-<infra_type>`, one per type. Unfiltered: no fixture of its own; composed from the per-type files *(added in v0.9)* | no | FC&lt;InfraFeature&gt; |
| `GET /api/impact/results` | `results`, or `results-<filter>` with `[a-z0-9-]` filter values | yes | FC&lt;ImpactResult&gt; |
| `GET /api/impact/countdown` | `countdown`, one file for the whole replay (see below) *(added in v1.3)* | no | ActionCountdown per timestep |
| `GET /api/impact/departures` | `departures` *(added in v1.3)* | no | Departures |
| `GET /api/impact/critical-links` | `critical-links`, one file: each departure's route as ways and each way's label, type, blocks and geometry; ranked per timestep × horizon on request *(v1.4 change, pending Dev A)* | no | CriticalLinks per timestep × horizon |
| `GET /api/risk/scores` | `scores` | yes | FC&lt;RiskScore&gt; |
| `GET /api/risk/breakdown` | `breakdown` *(added in v1.1)* | yes | RiskBreakdown |
| `GET /api/risk/unscored-areas` | `unscored-areas` *(added in v1.1)* | no | FC&lt;UnscoredArea&gt; |
| `GET /api/insurance/triggers` | `triggers` (compact, see below) | yes | FC&lt;TriggerEvent&gt; |
| `GET /api/insurance/summary` | `summary` *(added in v1.2)* | no | InsuranceSummary |

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
impact__countdown.json *(added in v1.3)*
impact__departures.json *(added in v1.3)*
impact__critical-links.json *(v1.4 change, pending Dev A)*
risk__scores__20200520T1200Z.json
advisory__gemini-<census_code>__20200520T1200Z.json *(added in v1.2)*
insurance__triggers__20200520T1200Z.json
insurance__summary.json *(added in v1.2)*
```

Fixture content is exactly the route response (or the raw upstream body) as JSON, UTF-8, LF.
Advisories are local state (SQLite), not fixtures, in both modes (*added in v1.2*): the only advisory
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
*Exception (added in v1.3):* `impact__countdown` holds the whole replay:
`{ key_moments: KeyMoment[], timesteps: { <Timestep>: { expected, cut_off } } }`. The route
returns one timestep's entry with `timestep`, `horizon_h` and the shared `key_moments`. It is
built from the committed impact and risk fixtures by `api/scripts/build_countdown_fixture.py`.
*Exception (added in v1.2):* `insurance__triggers__<ts>` stores each TriggerEvent
without its `geometry`, which the route adds back from the same block reference file, as for
`risk__scores__<ts>`.
*Exception (added in v1.3):* results at `horizon=24` are deduplicated, since the
expected hazard is the same at many timesteps. Each distinct result is stored once as
`<module>__<resource>-h24-<hash>` (`impact__results-h24-…`, `risk__scores-h24-…`,
`risk__breakdown-h24-…`; hash = the first 12 hex digits of the SHA-256 of the result with its
timestep replaced by `{{timestep}}`), in the same compact form as at horizon 0, plus
`<module>__<resource>-h24-index` = `{ horizon_h: 24, files: { <timestep>: <fixture key> } }` for
all 25 timesteps. Loading substitutes the timestep back, so the response is exactly the contract
collection.
Keep each file under ~2 MB, roads up to 5 MB (`exposure__infra-road`) *(added in v0.9)*. Anything larger or regenerable goes in `api/data/cache/` (ignored).
