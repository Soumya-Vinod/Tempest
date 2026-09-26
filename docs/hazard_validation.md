# Phase 7 — Hazard Validation, Calibration & Engine Integration

## 1. Executive Summary & Objective

Phase 7 completes the validation, calibration, and architectural integration of all three deterministic hazard models of the Tempest Hazard Engine:
1. **Holland Parametric Wind Model** (Phase 4)
2. **Coupled Storm Surge Model** (Phase 5)
3. **Multi-Criteria Flood Susceptibility Model** (Phase 6)

This phase verifies that every hazard model produces physically sound, mathematically bounded, monotonic, and contract-compliant hazard layers across all 25 synoptic replay timesteps of Super Cyclonic Storm Amphan (`2020-05-17T12:00:00Z` through `2020-05-20T12:00:00Z`).

Crucially, **no new hazard models are introduced**, the public API contracts defined in `shared/contracts.md` are strictly preserved without breaking changes, and all 75 canonical DEMO_MODE fixtures (`25 wind + 25 surge + 25 flood`) are validated for byte-for-byte determinism, UTF-8 encoding, and LF line endings.

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
│                             HAZARD ENGINE                                        │
│                                                                                  │
│   Unified Dispatch: generate_hazard_layer(hazard_type, timestep)                 │
│                                                                                  │
│   ┌───────────────────────┐  ┌───────────────────────┐  ┌────────────────────┐   │
│   │   Wind Model (Ph 4)   │  │   Surge Model (Ph 5)  │  │  Flood Model (Ph 6)│   │
│   │   - Holland equations │  │   - Pressure deficit  │  │  - Copernicus DEM  │   │
│   │   - Asymmetry         │  │   - Wind stress       │  │  - Slope gradient  │   │
│   │   - Coastal / Inland  │  │   - Shallow shelf amp │  │  - Topo depression │   │
│   │   m/s [5.0, 85.0]     │  │   - Inland decay      │  │  - Water proximity │   │
│   │   severity in [0, 1]  │  │   m [0.0, 6.5]        │  │  index [0.05, 0.98]│   │
│   │                       │  │   severity in [0, 1]  │  │  severity in [0, 1]│   │
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
│                Service Retrieval Layer: get_hazard_layer(type, ts)               │
│                                                                                  │
│  - DEMO_MODE = true  ──► Fast load from api/data/demo/{type}_{ts}.json (75 files) │
│  - DEMO_MODE = false ──► Real-time deterministic physics calculation             │
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

## 3. Cross-Hazard Validation Methodology

To ensure contract compliance across all models and timesteps, the engine provides reusable validation utilities in `app.hazard.validation`:

### 3.1 Single Layer Validation (`validate_hazard_layer`)
Each feature in a hazard layer is verified against the canonical contract (`shared/contracts.md` §4.1):
1. **ID Consistency**: Top-level GeoJSON `feature.id` matches `feature.properties.id` exactly (`cell_XXX`).
2. **Hazard Type**: Exactly matches one of `{"wind", "surge", "flood"}`.
3. **Timestep Alignment**: ISO 8601 synoptic timestamp matching `REPLAY_TIMESTEPS` (`2020-05-17T12:00:00Z` to `2020-05-20T12:00:00Z`).
4. **Unit Mapping**:
   - `wind`: `"m/s"`
   - `surge`: `"m"`
   - `flood`: `"index"`
5. **Physical Value Bounds**:
   - `wind`: $v \in [0.0, 85.0]\text{ m/s}$ (observed ambient floor $\ge 5.0\text{ m/s}$)
   - `surge`: $D \in [0.0, 6.5]\text{ m}$ (strictly non-negative)
   - `flood`: $I \in [0.0, 1.0]$ (empirical range $[0.05, 0.98]$)
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

## 4. Calibration Verification & Physics Guarantees

Every hazard model underwent targeted calibration verification against empirical Bay of Bengal cyclonic benchmarks:

### 4.1 Wind Hazard Model (Phase 4)
- **Governing Formulation**: Holland (1980) parametric vortex:
  $$v_{holland}(r) = \sqrt{\frac{B}{\rho_a} \left(\frac{R_{max}}{r}\right)^B (P_{env} - P_c) \exp\left(-\left(\frac{R_{max}}{r}\right)^B\right) + \left(\frac{r f_c}{2}\right)^2} - \frac{r f_c}{2}$$
- **Shape Parameter ($B$)**: Dynamically calibrated from pressure deficit $\Delta P = P_{env} - P_c$:
  $$B = 1.0 + \frac{\Delta P}{100.0}, \quad B \in [1.0, 2.5]$$
  For Amphan peak intensity ($P_c = 907\text{ hPa}$, $\Delta P = 101\text{ hPa}$), $B = 2.01$, well within physical cyclonic bounds.
- **Ambient Floor**: Ambient baseline wind floor $v_{amb} = 5.0\text{ m/s}$ ($18\text{ km/h}$) enforced in the far field ($r \to \infty$).
- **Translational Motion & Forward Asymmetry**: Forward motion vector $(u_{trans}, v_{trans})$ introduces physical right-quadrant eyewall enhancement via empirical vector steering:
  $$\vec{v}_{total} = \vec{v}_{rot} + 0.55 \cdot \vec{v}_{trans}$$
- **Coastal Enhancement & Inland Decay**: Marine boundary layer over open water experiences minimal friction; upon landfall, roughness dissipates momentum:
  $$\text{marine factor} = 1.15, \quad \text{inland factor} = \exp\left(-\frac{d_{coast}}{120\text{ km}}\right)$$
- **Physical Ceiling**: Absolute upper bound capped at $v_{max} = 85.0\text{ m/s}$ ($306\text{ km/h}$), honoring Saffir-Simpson / IMD Super Cyclone thresholds.
- **Severity Mapping**: Monotonic continuous piece-wise linear function:
  $$S(v) = 0.0 \text{ for } v \le 17\text{ m/s}, \quad S(33) = 0.35, \quad S(45) = 0.65, \quad S(v) = 1.0 \text{ for } v \ge 60\text{ m/s}$$

### 4.2 Storm Surge Model (Phase 5)
- **Governing Formulation**: Coupled hydrodynamic formulation combining:
  1. **Pressure Deficit (Inverse Barometer Effect)**:
     $$\Delta \eta_{pres} = 0.010 \cdot (P_{env} - P_c) \quad (\text{meters})$$
     Yields $+1.01\text{ m}$ of sea surface elevation at Amphan minimum pressure ($907\text{ hPa}$).
  2. **Wind Stress & Wave Setup**:
     $$\Delta \eta_{wind} = a_{wind} \cdot v_{wind}^2, \quad a_{wind} = 0.00085\text{ s}^2/\text{m}$$
  3. **Shallow Bathymetry & Coastal Amplification**:
     Amplification factor $\alpha_{coast} \in [1.0, 2.8]$ scaling inversely with distance to shallow continental shelf:
     $$A_{shelf} = 1.0 + 1.8 \cdot \exp\left(-\frac{\max(0.0, d_{coast})}{35\text{ km}}\right)$$
  4. **Inland Attenuation & Friction Decay**:
     Surge penetrates coastal lowlands but decays exponentially inland due to vegetation, mangrove forests, and dikes:
     $$F_{atten} = \exp\left(-\frac{d_{inland}}{\lambda_{surge}}\right), \quad \lambda_{surge} = 18.0\text{ km}$$
- **Surge Depth Boundedness**: Surge depth $D \ge 0.0\text{ m}$ everywhere (strictly non-negative), maximum ceiling $D \le 6.5\text{ m}$ (matching Amphan peak observed high-water marks in Sunderbans embankments).
- **Severity Mapping**: Monotonic continuous mapping:
  $$S(D) = 0.0 \text{ for } D \le 0.1\text{ m}, \quad S(1.0) = 0.35, \quad S(2.5) = 0.70, \quad S(D) = 1.0 \text{ for } D \ge 4.5\text{ m}$$

### 4.3 Flood Susceptibility Model (Phase 6)
- **Multi-Criteria Decision Analysis (MCDA)**: Static environmental vulnerability derived from high-resolution Copernicus DEM GLO-30 / SRTM 30m dataset:
  $$I_{flood} = w_{elev} \cdot f_{elev} + w_{slope} \cdot f_{slope} + w_{dep} \cdot f_{dep} + w_{water} \cdot f_{water} + w_{rain} \cdot f_{rain}$$
- **Criteria Weights**:
  - Elevation factor ($w_{elev} = 0.35$): Lower elevations ($< 6\text{ m}$) suffer prolonged drainage failure.
  - Slope gradient ($w_{slope} = 0.20$): Low slopes ($< 0.1\%$) inhibit gravity runoff.
  - Topographic depression ($w_{dep} = 0.15$): Micro-sinks relative to 8-neighborhood hold pooled water.
  - Water proximity ($w_{water} = 0.18$): Dense estuarine channels (Matla, Raimangal, Hooghly) increase tidal waterlogging.
  - Baseline antecedent rainfall ($w_{rain} = 0.12$): Pre-cyclone monsoon soil saturation.
  - **Weight Sum**: $\sum w_i = 0.35 + 0.20 + 0.15 + 0.18 + 0.12 = 1.00$ (strictly normalized).
- **Susceptibility Bounds**: Empirical index spans $I_{flood} \in [0.05, 0.98]$.
- **Static Invariance**: Because baseline topographic, geomorphic, and drainage characteristics do not change on synoptic 3-day timescales, flood susceptibility is identical across all 25 replay timesteps.
- **Severity Mapping**:
  $$S(I) = 0.0 \text{ for } I \le 0.20, \quad S(0.50) = 0.40, \quad S(0.75) = 0.75, \quad S(I) = 1.0 \text{ for } I \ge 0.95$$

---

## 5. Replay Timeline Verification (All 25 Timesteps)

The 25 replay timesteps span from `2020-05-17T12:00:00Z` to `2020-05-20T12:00:00Z` in 3-hour increments:

| # | Timestep (ISO 8601) | Cyclone Status | Wind Range (m/s) | Surge Range (m) | Flood Index Range |
|---|---------------------|----------------|------------------|-----------------|-------------------|
| 0 | 2020-05-17T12:00:00Z | Deep Depression | 5.0 – 12.8 | 0.0 – 0.15 | 0.05 – 0.98 |
| 1 | 2020-05-17T15:00:00Z | Cyclonic Storm | 5.0 – 14.1 | 0.0 – 0.18 | 0.05 – 0.98 |
| 4 | 2020-05-18T00:00:00Z | Severe Cyclonic Storm | 5.0 – 21.2 | 0.0 – 0.42 | 0.05 – 0.98 |
| 8 | 2020-05-18T12:00:00Z | Super Cyclonic Storm | 5.0 – 38.4 | 0.0 – 1.85 | 0.05 – 0.98 |
| 12 | 2020-05-19T00:00:00Z | Super Cyclonic Storm | 5.2 – 44.1 | 0.0 – 2.45 | 0.05 – 0.98 |
| 16 | 2020-05-19T12:00:00Z | Extremely Severe CS | 6.8 – 52.6 | 0.0 – 3.82 | 0.05 – 0.98 |
| 20 | 2020-05-20T00:00:00Z | Approaching Landfall | 12.4 – 62.8 | 0.0 – 4.95 | 0.05 – 0.98 |
| 23 | 2020-05-20T09:00:00Z | Landfall (Sundarbans) | 22.5 – 68.4 | 0.2 – 5.80 | 0.05 – 0.98 |
| 24 | 2020-05-20T12:00:00Z | Post-Landfall Dissipating | 18.2 – 55.1 | 0.1 – 4.10 | 0.05 – 0.98 |

All 25 timesteps were verified across both computed and demo fixture modes:
- **No exceptions**: 100% clean execution.
- **Zero NaN / Inf**: Clean numerical stability.
- **Exact Grid Alignment**: 528 cells in identical sequence.

---

## 6. DEMO_MODE Fixture Workflow & Integrity Audit

To provide sub-millisecond response times in offline, demonstration, and continuous integration environments, canonical demo fixtures are stored in `api/data/demo/`:

- **File Naming Pattern**: `{hazard_type}_{compact_ts}.json`
  - Example: `wind_20200520T090000Z.json`, `surge_20200520T090000Z.json`, `flood_20200520T090000Z.json`
- **Total Fixtures**: Exactly 75 files (25 wind + 25 surge + 25 flood).
- **Encoding & Line Endings**:
  - Enforced UTF-8 without BOM.
  - Strict Unix LF line endings (`\n`), zero CRLF characters.
- **Byte-for-Byte Determinism**:
  - Generated via `build_wind_fixtures.py`, `build_surge_fixtures.py`, `build_flood_fixtures.py`, or unified `build_hazard_fixtures.py`.
  - Serialized with `json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"`.
  - Regenerating fixtures yields zero git diff against checked-in files.

---

## 7. Known Simplifications & Deliberate Design Decisions

1. **Parametric Wind vs. 3D Numerical NWP**:
   The engine uses a 2D Holland parametric model rather than running heavy numerical weather prediction models (e.g., WRF). This delivers sub-second deterministic responses suitable for interactive replay without sacrificing the characteristic cyclonic eyewall and asymmetric structure.
2. **Simplified Bathymetry vs. Finite-Element ADCIRC / SLOSH**:
   Storm surge combines hydrostatic pressure deficit, wind stress, shallow shelf amplification, and exponential inland decay rather than solving 2D shallow water hydrodynamic equations on unstructured triangular meshes. This ensures rapid computation while maintaining physical realism for deltaic embankments.
3. **Static Flood Susceptibility vs. 2D Hydrodynamic Inundation Routing**:
   Flood hazard reflects baseline environmental susceptibility (MCDA combining DEM, slope, depression, and water proximity) rather than transient kinematic wave overland routing. In accordance with `shared/contracts.md` §4.1, flood susceptibility highlights baseline landscape vulnerability without cutting transport links or isolating network components in downstream engines.

---

## 8. Complete Regression Audit (Phases 1–6)

A rigorous backward-compatibility audit verified that no existing functionality regressed:

| Phase | Component | Verification Check | Status |
|-------|-----------|--------------------|--------|
| **Phase 1** | Hazard Schemas | `HazardLayer`, `HazardProperties`, `HazardLayerCollection`, `HAZARD_UNITS` intact and unchanged | **VERIFIED** |
| **Phase 1** | GeoJSON RFC 7946 | Valid `FeatureCollection`, Polygon coordinates, `[lon, lat]` order, CRS EPSG:4326 | **VERIFIED** |
| **Phase 2** | Replay Timeline | 25 timesteps, 3-hour increments, chronological ordering, strict ISO validation | **VERIFIED** |
| **Phase 2** | Service Integration | `get_replay_timeline()` returns valid `ReplayTimeline` model matching contract | **VERIFIED** |
| **Phase 3** | Cyclone Replay Track | 25 track points, valid motion vector, pressure deficit, radius of maximum winds | **VERIFIED** |
| **Phase 3** | Track Fixture | `cyclone_amphan_track.json` parses and serializes roundtrip without modification | **VERIFIED** |
| **Phase 4** | Holland Wind Model | Dynamic shape parameter $B$, forward motion asymmetry, coastal enhancement, inland decay | **VERIFIED** |
| **Phase 4** | Wind Normalization | Monotonic mapping into $[0, 1]$, bounds $[5.0, 85.0]\text{ m/s}$ | **VERIFIED** |
| **Phase 4** | Wind Fixtures | All 25 wind fixtures exist, validate against schema, and match computed output | **VERIFIED** |
| **Phase 5** | Storm Surge Model | Pressure deficit, wind stress coupling, shallow shelf amplification, inland attenuation | **VERIFIED** |
| **Phase 5** | Surge Normalization | Monotonic mapping into $[0, 1]$, strictly non-negative depths $[0.0, 6.5]\text{ m}$ | **VERIFIED** |
| **Phase 5** | Surge Fixtures | All 25 surge fixtures exist, validate against schema, and match computed output | **VERIFIED** |
| **Phase 6** | Flood Susceptibility | MCDA weights sum to 1.0, DEM factor, slope factor, depression sink, water occurrence | **VERIFIED** |
| **Phase 6** | Flood Static Replay | Output identical across all 25 replay timesteps | **VERIFIED** |
| **Phase 6** | Flood Fixtures | All 25 flood fixtures exist, validate against schema, and match computed output | **VERIFIED** |
| **Phase 7** | Engine Dispatch | `generate_hazard_layer` dispatches cleanly without logic duplication | **VERIFIED** |
| **Phase 7** | Service Modes | `get_hazard_layer` supports both `DEMO_MODE=true` and `DEMO_MODE=false`; rejects `'live'` | **VERIFIED** |
| **Phase 7** | HTTP Endpoints | `/api/hazard/layers`, `/api/hazard/track`, `/api/hazard/timesteps` pass all route tests | **VERIFIED** |

---

## 9. Test Suite & Validation Summary

The full test suite validates all requirements:
- **`api/tests/test_hazard.py`**: 81 comprehensive unit and integration tests (including 8 dedicated Phase 7 validation test suites).
- **`api/tests/test_demo_fixtures.py`**: 82 fixture loading, schema validation, and LF line-ending tests.
- **Overall Project Test Suite**: 362 passing tests, 0 failures, 1 skipped.
- **Code Quality**: Clean passing `ruff check api` with zero linting or formatting warnings.
