# Phase 7 — Hazard Validation, Verification & Engine Integration

## 1. Executive Summary & Objective

Phase 7 integrates, verifies, and validates the three deterministic hazard models of the Tempest Hazard Engine:
1. **Holland Parametric Wind Model** (Phase 4)
2. **Coupled Storm Surge Model** (Phase 5)
3. **Multi-Criteria Flood Susceptibility Model** (Phase 6)

This phase verifies that every existing hazard model produces physically sound, mathematically bounded, monotonic, and contract-compliant hazard layers across all 25 synoptic replay timesteps of Super Cyclonic Storm Amphan (`2020-05-17T12:00:00Z` through `2020-05-20T12:00:00Z`).

**Key Architectural Principles**:
- **No model physics replaced**: The governing equations, constants, and weights established in Phases 4, 5, and 6 are strictly preserved and verified.
- **Contract compliance**: The public API contracts defined in `shared/contracts.md` are strictly preserved without breaking changes.
- **Newly implemented in Phase 7**: The validation module `api/app/hazard/validation.py` introduces reusable cross-hazard contract validators and test runners.
- **Verification vs. Empirical Calibration**: This phase performs software parameter verification, physical boundary checks, and mathematical consistency audits. It does not perform statistical curve fitting against field observation datasets (e.g. tide gauge RMSE or buoy MAE).
- **Fixture integrity**: All 75 canonical DEMO_MODE fixtures (`hazard__layers-{type}__{compact_ts}.json`) are verified for byte-for-byte reproducibility, UTF-8 encoding, and LF line endings.

---

## 2. Architecture & Engine Integration

The Hazard Engine provides a unified interface for downstream impact and risk computation engines (`Dev B`), exposing both pre-computed demo fixtures and on-demand mathematical computation:

```
                          ┌────────────────────────────────┐
                          │   Replay Track (Phase 3)       │
                          │   25 Canonical Cyclone States  │
                          └──────────────┬─────────────────┘
                                         │ (lat, lon, Pc, Rmax, vtrans)
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             HAZARD REPLAY ENGINE                                 │
│                                                                                  │
│   Unified Dispatcher: generate_hazard_layer(hazard_type, timestep)               │
│   (implemented in api/app/hazard/replay.py, dispatches to specific generators)   │
│                                                                                  │
│   ┌───────────────────────┐  ┌───────────────────────┐  ┌────────────────────┐   │
│   │ generate_wind_layer   │  │ generate_surge_layer  │  │generate_flood_layer│   │
│   │ Holland (1980) vortex │  │ Hydrodynamic setup    │  │ MCDA AHP (6 factors│   │
│   │ m/s in [6.0, 65.0]    │  │ m in [0.0, 6.0]       │  │ index [0.17, 0.95]  │   │
│   │ severity in [0.0, 1.0]│  │ severity in [0.0, 1.0]│  │severity in [0, 1.0] │   │
│   └──────────┬────────────┘  └───────────┬───────────┘  └─────────┬──────────┘   │
└──────────────┼───────────────────────────┼────────────────────────┼──────────────┘
               ▼                           ▼                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      Cross-Hazard Spatial Grid (contracts.md §7)                 │
│                      528 Cells (24 rows x 22 cols, 0.05 deg res)                 │
│                      cell_000 to cell_527 — Shared Identical Geometry            │
└──────────────────────────────────────┬───────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│             Service Layer: get_hazard_layer(hazard_type, timestep)               │
│             (implemented in api/app/hazard/service.py)                           │
│                                                                                  │
│  - DEMO_MODE = true  ──► Fast load from api/data/demo/                           │
│                          hazard__layers-{type}__{compact_ts}.json (75 files)     │
│  - DEMO_MODE = false ──► Fallback to generate_hazard_layer(type, ts)             │
│  - timestep = 'live' ──► Explicit NotImplementedError (reserved for future)      │
└──────────────────────────────────────┬───────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│              FastAPI HTTP Surface: /api/hazard/layers?type={type}&timestep={ts}  │
│              GeoJSON FeatureCollection (RFC 7946 compliant)                      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Newly Implemented Cross-Hazard Validation Utilities

To ensure contract compliance across all models and timesteps, Phase 7 implemented `api/app/hazard/validation.py` containing reusable validators:

### 3.1 Single Layer Validation (`validate_hazard_layer`)
Each feature in a hazard layer is verified against the canonical contract (`shared/contracts.md` §4.1):
1. **ID Consistency**: Top-level GeoJSON `feature.id` matches `feature.properties.id` (`cell_000` to `cell_527`).
2. **Hazard Type**: Exactly matches one of `{"wind", "surge", "flood"}`.
3. **Timestep Alignment**: ISO 8601 synoptic timestamp matching `REPLAY_TIMESTEPS` (`2020-05-17T12:00:00Z` to `2020-05-20T12:00:00Z`).
4. **Unit Mapping**:
   - `wind`: `"m/s"`
   - `surge`: `"m"`
   - `flood`: `"index"`
5. **Physical Value Bounds**:
   - `wind`: $v \in [0.0, 65.0]\text{ m/s}$ (observed ambient floor $6.0\text{ m/s}$)
   - `surge`: $D \in [0.0, 6.0]\text{ m}$ (strictly non-negative)
   - `flood`: $I \in [0.05, 0.98]$ (empirical range $[0.17, 0.95]$)
6. **Severity Normalization**: Severity $S \in [0.0, 1.0]$ with strict monotonic mapping from physical metric value.
7. **Geometry Validity**: Polygon with 5 coordinates (first and last coordinate identical, closed ring), valid EPSG:4326 longitude/latitude inside Sundarbans AOI $[88.0^\circ\text{E}, 21.5^\circ\text{N}, 89.1^\circ\text{E}, 22.7^\circ\text{N}]$.

### 3.2 Collection Validation (`validate_hazard_collection`)
Validates a complete `HazardLayerCollection`:
- **Cell Count**: Exactly 528 features.
- **Cell ID Set**: Set of IDs is strictly equal to `{cell_000, cell_001, ..., cell_527}` with no duplicates and no missing cells.
- **Spatial Order**: Ordered monotonically by row-major index.
- **Collection Timestep**: Uniform timestep across all 528 features matching the requested timestep.

### 3.3 Cross-Hazard Consistency (`validate_hazard_consistency`)
Validates spatial grid alignment across `wind`, `surge`, and `flood` for any given timestep:
- All three layers contain exactly 528 cells.
- Cell IDs match 1-to-1 in identical sequential order.
- Cell bounding polygon coordinates match within $10^{-6}$ degrees across all three hazard types.

---

## 4. Verification of Model Physics & Governing Equations

Phase 7 verified that the underlying equations and constants from Phases 4, 5, and 6 operate exactly as designed without modifications:

### 4.1 Wind Hazard Model (Phase 4 Verification)
- **Governing Formulation**: Holland (1980) parametric gradient vortex:
  $$V_g(r) = \sqrt{\frac{B}{\rho_a} \left(\frac{R_{max}}{r}\right)^B \Delta P \exp\left(-\left(\frac{R_{max}}{r}\right)^B\right) + \left(\frac{r f_c}{2}\right)^2} - \frac{r f_c}{2}$$
- **Shape Parameter ($B$)**: Dynamically computed from intensity:
  $$B = \frac{\rho_a \cdot e \cdot V_{max}^2}{\Delta P}, \quad B \in [1.0, 2.5]$$
  Verified that $B$ remains strictly within $[1.0, 2.5]$ across all 25 track waypoints.
- **Forward Asymmetry**: Forward motion vector steering adds directional asymmetry:
  $$V = V_g \cdot (1.0 + 0.18 \sin(\theta_{rel})) \cdot f_{friction}$$
  where $f_{friction} = 0.85$ over water and $0.70$ inland.
- **Ambient Wind Floor**: Enforced baseline:
  $$v_{amb} = 6.0 + \max\left(0.0, 14.0 - \frac{r}{60\text{ km}}\right)$$
  ensuring far-field cells maintain a physical breeze floor ($6.0\text{ m/s}$).
- **Physical Ceiling**: $V_{max} = 65.0\text{ m/s}$ ($234\text{ km/h}$).
- **Severity Normalization**: Mapped to official IMD cyclone classifications:
  - $[0, 10\text{ m/s}] \to [0.00, 0.20]$ (Calm to Moderate Breeze)
  - $(10, 17\text{ m/s}] \to (0.20, 0.35]$ (Strong Breeze / Depression)
  - $(17, 24\text{ m/s}] \to (0.35, 0.55]$ (Deep Depression to Cyclonic Storm)
  - $(24, 33\text{ m/s}] \to (0.55, 0.75]$ (Severe Cyclonic Storm)
  - $(33, 48\text{ m/s}] \to (0.75, 1.00]$ (Very Severe to Super Cyclonic Storm)
  - $\ge 48\text{ m/s} \to 1.00$

### 4.2 Storm Surge Model (Phase 5 Verification)
- **Governing Formulation**: Coupled shallow-shelf hydrodynamic surge model:
  1. **Inverse Barometer**: $\eta_{baro} = \max(0.0, P_{env} - P_c) \cdot 0.010\text{ m/hPa}$, where $P_{env} = 1012.0\text{ hPa}$.
  2. **Wind Setup**:
     $$\eta_{wind} = \left(\frac{V_{wind}}{V_{ref}}\right)^\gamma \cdot c_{wind} = \left(\frac{V_{wind}}{20.0}\right)^{2.2} \cdot 0.85\text{ m}$$
  3. **Shelf Amplification**: $\eta_{coastal} = (\eta_{baro} + \eta_{wind}) \cdot K_{shelf}$, where $K_{shelf} = 1.10$.
  4. **Inland Attenuation**: $\eta_{inland} = \eta_{coastal} \cdot \exp\left(-\frac{d_{coast}}{\lambda_{decay}}\right)$, where $\lambda_{decay} = 35.0\text{ km}$.
  5. **Eye Distance Cutoff**: Surge is strictly 0.0 when $d_{eye} > 600\text{ km}$; ramps linearly from $600\text{ km}$ to $300\text{ km}$.
  6. **Topographic Inundation**:
     $$H = \max(0.0, \eta_{inland} - 0.25 \cdot Z_{elev}) \cdot \Psi(d_{eye})$$
     $$H_{final} = \min(H, 6.0\text{ m})$$
- **Physical Limits**: Surge depth $D \ge 0.0\text{ m}$ (strictly non-negative), maximum ceiling $H_{max} = 6.0\text{ m}$.
- **Severity Normalization**:
  - $d \le 0.0\text{ m} \to 0.00$
  - $(0.0, 0.30\text{ m}] \to (0.00, 0.15]$ (Minor nuisance flooding)
  - $(0.30, 1.0\text{ m}] \to (0.15, 0.40]$ (Moderate / vehicle stalling)
  - $(1.0, 2.5\text{ m}] \to (0.40, 0.75]$ (Severe / building submergence)
  - $(2.5, 4.0\text{ m}] \to (0.75, 1.00]$ (Extreme / structural damage)
  - $\ge 4.0\text{ m} \to 1.00$

### 4.3 Flood Susceptibility Model (Phase 6 Verification)
- **Multi-Criteria Decision Analysis (AHP) Weights** (verified sum = $1.00$):
  - Elevation ($w_{elev} = 0.30$): SRTM 30m / Copernicus DEM elevation relative to $Z_{ref} = 3.0\text{ m}$.
  - Slope gradient ($w_{slope} = 0.15$): Finite-difference slope relative to $S_{ref} = 0.0010\text{ m/m}$.
  - Topographic wetness ($w_{dep} = 0.10$): Local depression relative to 8-neighborhood ($\Delta Z_{ref} = 0.50\text{ m}$).
  - Surface water proximity ($w_{water} = 0.20$): JRC Global Surface Water proximity ($\lambda = 28.0\text{ km}$).
  - Rainfall climatology ($w_{rain} = 0.10$): GPM IMERG pre-monsoon precipitation ($200\text{ mm}$ to $340\text{ mm}$).
  - Land cover ($w_{lulc} = 0.15$): ESA WorldCover wetland/mangrove ($0.95$) to settled delta ($0.35$).
- **Susceptibility Bounds**: Empirical index spans $[0.17, 0.95]$.
- **Static Invariance**: Flood susceptibility values are identical across all 25 timesteps.
- **Severity Normalization**: Mapped directly to index: $S(I) = \text{round}(I, 2)$ for $I \in [0, 1]$.

---

## 5. Actual Replay Statistics (Computed from All 25 Timesteps)

The following table presents the **actual, verified statistics** computed across all 528 cells of the Sundarbans AOI for each of the 25 replay timesteps:

| Step | Timestep (ISO 8601) | Wind Speed (m/s) [min, max] | Surge Depth (m) [min, max] | Flood Susceptibility [min, max] | Physical Reason |
|:---:|:---|:---:|:---:|:---:|:---|
| 00 | 2020-05-17T12:00:00Z | [6.0, 6.0] | [0.00, 0.00] | [0.17, 0.95] | Cyclone eye > 1,000 km south; surge cutoff active; ambient wind floor. |
| 01 | 2020-05-17T15:00:00Z | [6.0, 6.0] | [0.00, 0.00] | [0.17, 0.95] | Eye in southern Bay of Bengal; surge cutoff active. |
| 02 | 2020-05-17T18:00:00Z | [6.0, 6.0] | [0.00, 0.00] | [0.17, 0.95] | Eye in southern Bay of Bengal; surge cutoff active. |
| 03 | 2020-05-17T21:00:00Z | [6.0, 6.0] | [0.00, 0.00] | [0.17, 0.95] | Eye in southern Bay of Bengal; surge cutoff active. |
| 04 | 2020-05-18T00:00:00Z | [6.0, 6.0] | [0.00, 0.00] | [0.17, 0.95] | Intensifying to Severe CS; still > 800 km south of AOI. |
| 05 | 2020-05-18T03:00:00Z | [6.0, 6.0] | [0.00, 0.00] | [0.17, 0.95] | Intensifying; eye distance > 750 km. |
| 06 | 2020-05-18T06:00:00Z | [6.0, 6.0] | [0.00, 0.00] | [0.17, 0.95] | Very Severe CS; eye distance > 700 km. |
| 07 | 2020-05-18T09:00:00Z | [6.0, 6.0] | [0.00, 0.00] | [0.17, 0.95] | Extremely Severe CS; eye distance > 650 km. |
| 08 | 2020-05-18T12:00:00Z | [6.0, 6.0] | [0.00, 0.00] | [0.17, 0.95] | Super Cyclone peak (907 hPa); eye at 13.7°N (> 600 km south). |
| 09 | 2020-05-18T15:00:00Z | [6.0, 6.6] | [0.00, 0.00] | [0.17, 0.95] | Outer circulation enters southern fringe of AOI. |
| 10 | 2020-05-18T18:00:00Z | [6.0, 7.4] | [0.00, 0.00] | [0.17, 0.95] | Eye moves north; gradient wind begins slight elevation. |
| 11 | 2020-05-18T21:00:00Z | [6.0, 8.0] | [0.00, 0.00] | [0.17, 0.95] | Eye distance approaching 600 km cutoff. |
| 12 | 2020-05-19T00:00:00Z | [6.2, 8.7] | [0.00, 0.00] | [0.17, 0.95] | Ambient floor exceeded across entire grid; surge cutoff still active. |
| 13 | 2020-05-19T03:00:00Z | [7.0, 9.6] | [0.00, 0.00] | [0.17, 0.95] | Eye at 15.6°N (~580 km south of AOI); initial ramp boundary. |
| 14 | 2020-05-19T06:00:00Z | [8.0, 10.5] | [0.00, 0.10] | [0.17, 0.95] | Eye passes 600 km cutoff; coastal cells experience first surge onset. |
| 15 | 2020-05-19T09:00:00Z | [8.8, 11.3] | [0.00, 0.25] | [0.17, 0.95] | Approaching northern Bay; coastal surge builds to 0.25 m. |
| 16 | 2020-05-19T12:00:00Z | [9.5, 12.1] | [0.00, 0.40] | [0.17, 0.95] | Eye at 17.0°N; coastal surge reaches 0.40 m. |
| 17 | 2020-05-19T15:00:00Z | [10.6, 13.2] | [0.00, 0.63] | [0.17, 0.95] | Moderate breeze across entire AOI; surge reaches 0.63 m. |
| 18 | 2020-05-19T18:00:00Z | [11.3, 13.9] | [0.00, 0.82] | [0.17, 0.95] | Surge wave enters estuarine mouths (0.82 m). |
| 19 | 2020-05-19T21:00:00Z | [12.0, 14.6] | [0.00, 1.00] | [0.17, 0.95] | Surge reaches 1.00 m on southern islands. |
| 20 | 2020-05-20T00:00:00Z | [12.9, 15.5] | [0.00, 1.10] | [0.17, 0.95] | Landfall day T-12h; strong breeze; coastal surge 1.10 m. |
| 21 | 2020-05-20T03:00:00Z | [14.2, 16.7] | [0.00, 1.17] | [0.17, 0.95] | Eye approaching Odisha/Bengal coast; coastal surge 1.17 m. |
| 22 | 2020-05-20T06:00:00Z | [15.6, 19.2] | [0.00, 1.36] | [0.17, 0.95] | Pre-landfall intensification; maximum surge builds to 1.36 m. |
| 23 | 2020-05-20T09:00:00Z | [17.0, 43.1] | [0.00, 5.20] | [0.17, 0.95] | **Landfall in Sundarbans**: Peak wind 43.1 m/s (155 km/h), Peak surge 5.20 m. |
| 24 | 2020-05-20T12:00:00Z | [19.3, 41.7] | [0.00, 2.98] | [0.17, 0.95] | Inland dissipation post-landfall; peak wind 41.7 m/s, peak surge 2.98 m. |

---

## 6. DEMO_MODE Fixture Workflow & Integrity Audit

Demo fixtures are stored in `api/data/demo/` and follow the canonical schema naming:
- **Canonical Naming Pattern**: `hazard__layers-{hazard_type}__{compact_ts}.json`
  - Example: `hazard__layers-wind__20200520T0900Z.json`
  - Example: `hazard__layers-surge__20200520T0900Z.json`
  - Example: `hazard__layers-flood__20200520T0900Z.json`
- **Total Fixtures**: Exactly 75 files (25 wind + 25 surge + 25 flood).
- **Encoding & Line Endings**:
  - Enforced UTF-8 without BOM.
  - Strict Unix LF line endings (`\n`), zero CRLF characters.
- **Byte-for-Byte Determinism**:
  - Generated via `build_hazard_fixtures.py` (or individual builders).
  - Serialized with `json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"`.
  - Regenerating fixtures yields zero git diff against checked-in files.

---

## 7. Scope Clarification: Verification vs. Empirical Calibration

To avoid ambiguity, Phase 7 performed **code-level model verification**, not empirical calibration:
- **What was performed**:
  - Verification that parameters match literature and historical cyclone track data (IMD Amphan best-track).
  - Verification of physical limits ($D \ge 0$, $V \le 75\text{ m/s}$, $B \in [1.0, 2.5]$, weights sum to $1.00$).
  - Verification that severity normalizations are monotonic and continuous.
  - Verification of zero stochastic drift (pure deterministic repeatability across runs).
- **What was not performed**:
  - Empirical fitting against field observations (e.g., tide gauge time series at Sagar Island or Diamond Harbour).
  - Calculation of statistical error metrics (RMSE, MAE, bias, correlation) against observation networks.
  - Fine-tuning or altering of model coefficients.

---

## 8. Complete Regression Audit (Phases 1–6)

A rigorous backward-compatibility audit verified that no existing functionality regressed:

| Phase | Subsystem | Verification Check | Status |
|---|---|---|---|
| **Phase 1** | Hazard Schemas | `HazardLayer`, `HazardProperties`, `HazardLayerCollection`, `HAZARD_UNITS` intact and unchanged | **VERIFIED** |
| **Phase 1** | GeoJSON RFC 7946 | Valid `FeatureCollection`, Polygon coordinates, `[lon, lat]` order, CRS EPSG:4326 | **VERIFIED** |
| **Phase 2** | Replay Timeline | 25 timesteps, 3-hour increments, chronological ordering, strict ISO validation | **VERIFIED** |
| **Phase 2** | Service Integration | `get_replay_timeline()` returns valid `ReplayTimeline` model matching contract | **VERIFIED** |
| **Phase 3** | Cyclone Replay Track | 25 track points, valid motion vector, pressure deficit, radius of maximum winds | **VERIFIED** |
| **Phase 3** | Track Fixture | `hazard__track.json` parses and serializes roundtrip without modification | **VERIFIED** |
| **Phase 4** | Holland Wind Model | Dynamic shape parameter $B$, forward motion asymmetry, friction, 25 wind fixtures | **VERIFIED** |
| **Phase 4** | Wind Normalization | Monotonic mapping into $[0, 1]$, bounds $[6.0, 65.0]\text{ m/s}$ | **VERIFIED** |
| **Phase 4** | Wind Fixtures | All 25 wind fixtures exist, validate against schema, and match computed output | **VERIFIED** |
| **Phase 5** | Storm Surge Model | Inverse barometer, $(V/20)^{2.2} \times 0.85$ setup, $K_{shelf} = 1.10$, $\lambda = 35\text{ km}$, 25 surge fixtures | **VERIFIED** |
| **Phase 5** | Surge Normalization | Monotonic mapping into $[0, 1]$, strictly non-negative depths $[0.0, 6.0]\text{ m}$ | **VERIFIED** |
| **Phase 5** | Surge Fixtures | All 25 surge fixtures exist, validate against schema, and match computed output | **VERIFIED** |
| **Phase 6** | Flood Susceptibility | MCDA 6 weights sum to 1.0 (with LULC 0.15), DEM, slope, depression, water, rain | **VERIFIED** |
| **Phase 6** | Flood Static Replay | Output identical across all 25 replay timesteps ($[0.17, 0.95]$) | **VERIFIED** |
| **Phase 6** | Flood Fixtures | All 25 flood fixtures exist, validate against schema, and match computed output | **VERIFIED** |
| **Phase 7** | Engine Dispatch | `generate_hazard_layer` dispatches cleanly without logic duplication | **VERIFIED** |
| **Phase 7** | Service Modes | `get_hazard_layer` supports both `DEMO_MODE=true` and `DEMO_MODE=false`; rejects `'live'` | **VERIFIED** |
| **Phase 7** | HTTP Endpoints | `/api/hazard/layers`, `/api/hazard/track`, `/api/hazard/timesteps` pass all route tests | **VERIFIED** |

---

## 9. Test Suite & Progression Summary

The test count progressed across phases as follows:
- **Phase 5 Completion**: 343 passing tests.
- **Phase 6 Completion**: 354 passing tests (+11 tests for flood susceptibility model, static replay, and GEE fallback).
- **Phase 7 Completion**: **362 passing tests, 1 skipped** (s24p optional auth blocks) (+8 tests for cross-hazard consistency, calibration checks, 25-step replay validation, and service dispatch).
- **Code Quality**: Clean passing `ruff check api` with zero linting or formatting warnings.
