# Tempest contracts — v0.9 (DRAFT — pending Dev A review)

The interface between **Dev A (hazard)** and **Dev B (exposure, impact, risk, advisory, dispatch,
insurance)**. This file is the source of truth. `api/app/schemas/` (Pydantic) and
`web/src/types/contracts.ts` (TypeScript) mirror it exactly.

**Change rule (from v1.0 onward):** any change needs sign-off from both devs, a version bump here,
and the matching Pydantic + TS edits in the same commit. While in v0.9 draft, edits are open
pending Dev A's review.

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
| Errors | FastAPI default `{"detail": ...}`. `404` unknown id, `409` invalid state change, `422` bad params (incl. unknown `timestep`), `501` not implemented yet. |

## 2. Replay timeline — Cyclone Amphan

- **Landfall timestep:** `2020-05-20T12:00:00Z`. IMD reports Amphan crossed the West Bengal–Bangladesh
  coast over the Sundarbans between 10:00 and 12:00 UTC on 20 May 2020. 12:00Z is the first
  3-hourly synoptic hour by which the crossing is complete.
- **Start:** T-72h = `2020-05-17T12:00:00Z`.
- **Step:** 3 hours → **25 timesteps**, T-72h … T-0 inclusive.
- **Timestep key:** the ISO string itself, e.g. `2020-05-18T03:00:00Z`.
- **Reserved value `"live"`:** every `timestep` parameter (HTTP query param or Python argument) also
  accepts `"live"`. In v0.9, `"live"` returns `501` from routes and raises `NotImplementedError` from
  Python functions. `"live"` never appears in a response's `timestep` property.
- Any other `timestep` value not in the list returns `422`.

```
2020-05-17T12:00:00Z  T-72     2020-05-19T00:00:00Z  T-36
2020-05-17T15:00:00Z  T-69     ...
...                            2020-05-20T09:00:00Z  T-3
2020-05-18T12:00:00Z  T-48     2020-05-20T12:00:00Z  T-0 (landfall)
```

Live mode is reserved but not implemented in v0.9. See the `"live"` value above.

## 3. Shared types

```ts
type HazardType   = "wind" | "surge" | "flood";
type InfraType    = "substation" | "power_line" | "road" | "hospital" | "shelter";
type ImpactStatus = "ok" | "at_risk" | "cut" | "isolated";
type StepType     = "hazard" | "infra" | "service";
type Language     = "en" | "bn" | "hi";
type AdvisoryStatus = "draft" | "approved" | "sent";
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
| `severity` | float [0, 1] | Normalised by Dev A. Dev B uses only this for thresholds. |

### 4.2 InfraFeature (Dev B)
Geometry: `Point` (substation, hospital, shelter) or `LineString | MultiLineString` (power_line, road).
Polygons from OSM are reduced to their centroid.

| Property | Type | Notes |
|---|---|---|
| `id` | string | Stable id: `<infra_type>-<osm_type>-<osm_number>`, e.g. `substation-way-123456`. `_` in `infra_type` is written `-` (`power-line-way-123`); must match `^(substation\|power-line\|road\|hospital\|shelter)-(node\|way\|relation)-\d+$`. *v0.9 addition, pending Dev A review.* |
| `infra_type` | InfraType | |
| `name` | string \| null | OSM `name`, null if missing. |
| `osm_id` | string \| null | `"<node\|way\|relation>/<number>"`, e.g. `"way/123456"`. Null for non-OSM sources. |
| `attributes` | object | Free-form extras (OSM tags, voltage, beds, capacity…). Keys set by the OSM ingest are listed below. |

OSM ingest attributes and scope *(v0.9 addition, pending Dev A review)*:

| infra_type | OSM source | `attributes` keys |
|---|---|---|
| `substation` | `power=substation` | `voltage`, `operator` (when tagged) |
| `power_line` | `power=line` (+ `minor_line` if ≤ 10,000 ways) | `voltage`, `operator` (when tagged) |
| `road` | `highway` motorway…tertiary (+ `_link`), unclassified; `route=ferry` | `highway`, `ref`, `bridge` (when tagged); `ferry`: boolean; `baseline_component`: int \| null; `baseline_reachable_from_main`: boolean (see §4.3) |
| `hospital` | `amenity=hospital\|clinic`, `healthcare=hospital\|clinic\|centre` | `facility_level`: `"hospital"` \| `"health_centre"` |
| `shelter` | cyclone/flood shelters, `emergency=assembly_point`, `amenity=school` | `shelter_kind`: `"cyclone_shelter"` \| `"assembly_point"` \| `"school_proxy"` |

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

**`isolated` vs baseline connectivity** *(v0.9 addition, pending Dev A review)*. `isolated` means
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

### 4.5 Advisory (Dev B)
Geometry: **null** (join to the block via `block_id`).

| Property | Type | Notes |
|---|---|---|
| `id` | AdvisoryId | UUID4, lowercase. Must match `^[a-z0-9-]+$` (fixture-safe). *v0.9 addition, pending Dev A review.* |
| `block_id` | string | |
| `timestep` | Timestep | The timestep whose figures it cites. |
| `language` | Language | |
| `body` | string | Written by Gemini; contains **no numbers except those in `citations`**. |
| `citations` | Citation[] | The source figures, all from the risk engine. |
| `status` | AdvisoryStatus | `draft → approved → sent` only. |
| `approved_by` | string \| null | Required once `status ≠ draft`. |
| `approved_at` | ISO datetime \| null | Required once `status ≠ draft`. |
| `created_at` | ISO datetime | |

`Citation = { key: string, label: string, value: number, unit: string | null, source: string }`
e.g. `{"key":"risk_score","label":"Block risk score","value":0.82,"unit":null,"source":"risk"}`

### 4.6 TriggerEvent (Dev B)
One feature per insurance zone per timestep. Geometry: zone `Polygon | MultiPolygon`.

| Property | Type | Notes |
|---|---|---|
| `id` | string | `<zone_id>__<timestep>` |
| `zone_id` | string | |
| `zone_name` | string | |
| `timestep` | Timestep | |
| `metric` | TriggerMetric | Read from HazardLayer `value` (not severity). |
| `unit` | `"m/s" \| "m"` | |
| `threshold` | float | |
| `observed` | float | Max over the zone at this timestep. |
| `triggered` | boolean | `observed >= threshold` |
| `payout_estimate_inr` | float | `0` when not triggered. |

### 4.7 DispatchReceipt (Dev B, not GeoJSON)
`{ advisory_id: AdvisoryId, sent_at: ISO datetime, channels: [{ channel: "telegram" | "email", ok: boolean, error: string | null }] }`
(`AdvisoryId` as in §4.5.)

## 5. Routes

All under `/api`. `timestep` is always a query param of type `TimestepParam`, required unless
stated; `timestep=live` returns `501` in v0.9. FC = FeatureCollection.

| Owner | Method | Path | Params / body | Response |
|---|---|---|---|---|
| A | GET | `/api/hazard/timesteps` | — | `{ event: "amphan", landfall: Timestep, timesteps: Timestep[] }` |
| A | GET | `/api/hazard/layers` | `hazard_type: HazardType`, `timestep` | FC&lt;HazardLayer&gt; |
| B | GET | `/api/exposure/infra` | `infra_type?: InfraType` | FC&lt;InfraFeature&gt; (not time-dependent) |
| B | GET | `/api/impact/results` | `timestep`, `hazard_type?`, `status?: ImpactStatus` | FC&lt;ImpactResult&gt; |
| B | GET | `/api/risk/scores` | `timestep` | FC&lt;RiskScore&gt; |
| B | GET | `/api/advisory/` | `status?`, `block_id?` | FC&lt;Advisory&gt; |
| B | POST | `/api/advisory/` | `{ block_id, timestep, language }` | Advisory (`draft`) |
| B | GET | `/api/advisory/{advisory_id}` | — | Advisory |
| B | PATCH | `/api/advisory/{advisory_id}` | `{ body }`; `draft` only, else `409` | Advisory |
| B | POST | `/api/advisory/{advisory_id}/approve` | `{ approved_by }`; `draft` only, else `409` | Advisory (`approved`) |
| B | POST | `/api/dispatch/{advisory_id}` | `{ channels: ("telegram" \| "email")[] }`; `approved` only, else `409` | DispatchReceipt; advisory → `sent` |
| B | GET | `/api/insurance/triggers` | `timestep` | FC&lt;TriggerEvent&gt; |
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
| `timestep` | A `TimestepParam`. `"live"` raises `NotImplementedError` in v0.9; any other value not in the replay list raises `ValueError`. |
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

**Route fixture resources** *(v0.9 addition, pending Dev A review)*. Every route response
fixture uses one of these resources. `tests/test_demo_fixtures.py` validates each file against
the schema listed here, and fails on any route resource not in this table.

| Route | Resource | Timestep suffix | Schema |
|---|---|---|---|
| `GET /api/hazard/timesteps` | `timesteps` | no | ReplayTimeline |
| `GET /api/hazard/layers` | `layers-<hazard_type>` | yes | FC&lt;HazardLayer&gt; |
| `GET /api/exposure/infra` | `infra`, or `infra-<infra_type>` when filtered | no | FC&lt;InfraFeature&gt; |
| `GET /api/impact/results` | `results`, or `results-<filter>` with `[a-z0-9-]` filter values | yes | FC&lt;ImpactResult&gt; |
| `GET /api/risk/scores` | `scores` | yes | FC&lt;RiskScore&gt; |
| `GET /api/advisory/` | `list` | no | FC&lt;Advisory&gt; |
| `GET /api/advisory/{advisory_id}` | `item-<advisory_id>` | no | Advisory |
| `POST /api/dispatch/{advisory_id}` | `receipt-<advisory_id>` | no | DispatchReceipt |
| `GET /api/insurance/triggers` | `triggers` | yes | FC&lt;TriggerEvent&gt; |

Enum values containing `_` (e.g. `power_line`) are written with `-` in resource names:
`exposure__infra-power-line`. `advisory_id` is fixture-safe by §4.5, so it is used as is.

Examples:
```
hazard__timesteps.json
hazard__layers-surge__20200520T1200Z.json
hazard__gee-flood-susceptibility.json
exposure__infra.json
exposure__infra-power-line.json
exposure__overpass-substations.json
impact__results__20200519T0000Z.json
risk__scores__20200520T1200Z.json
advisory__gemini-draft-bn-<block_id>__20200520T1200Z.json
advisory__list.json
advisory__item-<advisory_id>.json
dispatch__receipt-<advisory_id>.json
insurance__triggers__20200520T1200Z.json
```

Fixture content is exactly the route response (or the raw upstream body) as JSON, UTF-8, LF.
Keep each file under ~2 MB. Anything larger or regenerable goes in `api/data/cache/` (ignored).
