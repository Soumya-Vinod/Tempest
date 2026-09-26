# Phase 5 — Storm Surge Model for the Hazard Engine

## 1. Overview & Objective

Phase 5 implements a deterministic hydrodynamic storm surge model for the Tempest Hazard Engine. The model computes coastal and estuarine surge inundation depths above ground level (in meters) across the 528 spatial grid cells of the Sundarbans Area of Interest (AOI) ($[88.0^\circ\text{E}, 21.5^\circ\text{N}, 89.1^\circ\text{E}, 22.7^\circ\text{N}]$) throughout the 25 synoptic timesteps of Cyclone Amphan (May 17–20, 2020).

The surge model builds directly upon the Phase 4 Holland wind field, the canonical IBTrACS cyclone track, and high-resolution NASA SRTM GL1 30m / Copernicus DEM terrain elevation data.

---

## 2. Governing Equations

### 2.1 Atmospheric Pressure Drop (Inverse Barometer Effect)
A barometric pressure deficit over open water induces an upward static sea-surface rise:

$$\eta_{barometer} = \max(0.0, P_{env} - P_c) \cdot c_{ibe}$$

where:
- $P_c$: Cyclone central barometric pressure (hPa) from the replay track.
- $P_{env} = 1012.0\text{ hPa}$: Synoptic pre-monsoon ambient pressure over the Bay of Bengal.
- $c_{ibe} = 0.010\text{ m/hPa}$: Theoretical hydrostatic inverted barometer constant ($\approx 1\text{ cm}$ sea surface elevation per $1\text{ hPa}$ pressure drop).

### 2.2 Shallow-Shelf Wind Stress Setup
Wind stress $\tau_w = \rho_a C_d V_{10}^2$ acting over the wide, shallow northern Bay of Bengal continental shelf generates onshore water piling:

$$\eta_{wind} = \left(\frac{V_{wind}}{V_{ref}}\right)^\gamma \cdot c_{wind}$$

where:
- $V_{wind}$: Sustained 10-meter wind speed ($\text{m/s}$) computed by the Phase 4 Holland parametric wind model.
- $V_{ref} = 20.0\text{ m/s}$: Reference scaling wind speed.
- $\gamma = 2.2$: Non-linear wind stress setup exponent on shallow bathymetry.
- $c_{wind} = 0.85\text{ m}$: Empirical coastal wind setup amplitude coefficient.

### 2.3 Estuarine Funneling & Bathymetric Convergence
The head of the Bay of Bengal features a converging funnel shape and shallow deltaic bathymetry ($< 20\text{ m}$ depth), which amplifies the incoming surge wave:

$$\eta_{coastal} = (\eta_{barometer} + \eta_{wind}) \cdot K_{shelf}$$

where:
- $K_{shelf} = 1.10$: Shallow shelf and estuarine inlet convergence amplification factor.

### 2.4 Storm Eye Distance Modulation
When the storm is far south in the central or southern Bay of Bengal, the surge wave has not yet reached the northern Bengal shelf:

$$\Psi(d_{eye}) = \begin{cases} 
0.0 & \text{if } d_{eye} > 600\text{ km} \\
\frac{600 - d_{eye}}{300} & \text{if } 300\text{ km} < d_{eye} \le 600\text{ km} \\
1.0 & \text{if } d_{eye} \le 300\text{ km}
\end{cases}$$

where $d_{eye}$ is the Haversine great-circle distance from the grid cell centroid to the cyclone eye center.

### 2.5 Inland Wetland & Deltaic Dissipation
As the coastal surge wave propagates inland through mangrove forests, tidal mudflats, and intricate deltaic river channels, bottom friction causes exponential dissipation:

$$\eta_{inland} = \eta_{coastal} \cdot \exp\left( - \frac{d_{coast}}{\lambda_{decay}} \right)$$

where:
- $d_{coast}$: Shortest distance from the cell centroid to the southern marine coast ($\text{km}$).
- $\lambda_{decay} = 35.0\text{ km}$: Characteristic dissipation length scale for mangrove wetlands and estuarine channels.

### 2.6 Topographic Reduction & Inundation Depth
The physical surge depth experienced at ground level ($m$) accounts for terrain elevation:

$$H_{inundation} = \max\left(0.0, \eta_{inland} - \alpha_{topo} \cdot Z_{elev}\right) \cdot \Psi(d_{eye})$$

$$H_{final} = \min\left(H_{inundation}, H_{max}\right)$$

where:
- $Z_{elev}$: Local ground surface elevation above mean sea level from the SRTM 30m reference dataset (`hazard_elevation_grid.json`).
- $\alpha_{topo} = 0.25$: Topographic attenuation factor (representing partial polder embankment defense and tidal canal drainage).
- $H_{max} = 6.0\text{ m}$: Physical ceiling for ground-level surge inundation depth.

---

## 3. Physical Constants

| Parameter | Symbol | Value | Unit | Description |
|---|---|---|---|---|
| Ambient Atmospheric Pressure | $P_{env}$ | $1012.0$ | $\text{hPa}$ | Ambient pre-monsoon pressure over Bay of Bengal |
| Inverted Barometer Constant | $c_{ibe}$ | $0.010$ | $\text{m/hPa}$ | Hydrostatic sea-surface elevation per hPa deficit |
| Reference Wind Speed | $V_{ref}$ | $20.0$ | $\text{m/s}$ | Normalization velocity for wind stress setup |
| Wind Setup Exponent | $\gamma$ | $2.2$ | dimensionless | Non-linear wind stress power scaling on shelf |
| Coastal Setup Amplitude | $c_{wind}$ | $0.85$ | $\text{m}$ | Coastal wind setup scaling coefficient |
| Shelf Convergence Factor | $K_{shelf}$ | $1.10$ | dimensionless | Estuarine funneling & shallow shelf amplification |
| Inland Decay Length Scale | $\lambda_{decay}$ | $35.0$ | $\text{km}$ | Wetland and mangrove vegetation dissipation scale |
| Topographic Factor | $\alpha_{topo}$ | $0.25$ | dimensionless | Ground elevation reduction factor |
| Surge Eye Cutoff Distance | $d_{eye,max}$ | $600.0$ | $\text{km}$ | Eye distance beyond which surge is zero |
| Surge Ramp Distance | $d_{eye,ramp}$ | $300.0$ | $\text{km}$ | Eye distance where surge decay begins |
| Maximum Physical Surge Depth | $H_{max}$ | $6.0$ | $\text{m}$ | Upper bound on ground inundation depth |

---

## 4. Severity Normalization Method

The normalized severity score $S \in [0.0, 1.0]$ maps continuously and monotonically to disaster management inundation thresholds:

| Inundation Depth ($d$) | Severity Formula ($S$) | Severity Range | Physical & Structural Impact |
|---|---|---|---|
| $d \le 0.0\text{ m}$ | $0.00$ | $0.00$ | Dry ground / no inundation |
| $0.0 < d \le 0.3\text{ m}$ | $(d / 0.30) \times 0.15$ | $(0.00, 0.15]$ | Minor nuisance splash, puddle flooding, traffic disruption |
| $0.3 < d \le 1.0\text{ m}$ | $0.15 + ((d - 0.30) / 0.70) \times 0.25$ | $(0.15, 0.40]$ | Moderate flooding, ground-floor ingress, vehicle stalling |
| $1.0 < d \le 2.5\text{ m}$ | $0.40 + ((d - 1.0) / 1.5) \times 0.35$ | $(0.40, 0.75]$ | Severe flooding, residential submergence, mandatory evacuation |
| $2.5 < d \le 4.0\text{ m}$ | $0.75 + ((d - 2.5) / 1.5) \times 0.25$ | $(0.75, 1.00]$ | Extreme / catastrophic destruction, wave-induced structural collapse |
| $d \ge 4.0\text{ m}$ | $1.00$ | $1.00$ | Complete destruction of non-engineered buildings |

### Mathematical Guarantees:
- **Strict Monotonicity:** For any $d_1 \le d_2$, $S(d_1) \le S(d_2)$ (positive piecewise slopes).
- **Exact Continuity:** Values match exactly across all threshold boundaries ($0.0, 0.3, 1.0, 2.5, 4.0\text{ m}$).
- **Strict Boundedness:** $S(d) \in [0.0, 1.0]$ for all inputs $d \in \mathbb{R}$.
- **Determinism:** Pure analytical mapping rounded to 3 decimal places without stochastic noise.

---

## 5. DEMO_MODE Fixture Generation Workflow

To fulfill the `DEMO_MODE=true` offline contract requirements (contracts.md §7), static fixtures for all 25 timesteps are generated using `api/scripts/build_surge_fixtures.py`:

```bash
# Execute from repo root
api\.venv\Scripts\python api\scripts\build_surge_fixtures.py
```

### Artifact Details:
- **Target Directory:** `api/data/demo/`
- **Filename Pattern:** `hazard__layers-surge__<YYYYMMDDTHHMMZ>.json` (compact ISO 8601 UTC timestamp)
- **Count:** Exactly 25 files (`20200517T1200Z` to `20200520T1200Z`)
- **Features per File:** Exactly 528 GeoJSON polygon features spanning the Sundarbans AOI ($0.05^\circ$ resolution)
- **Encoding & Line Endings:** UTF-8 JSON with strict LF (`\n`, no `\r\n`)
- **Verification:** Automatically validated by `tests/test_demo_fixtures.py` and `tests/test_hazard.py`.

---

## 6. Service & API Integration

- **Internal Interface (`api/app/hazard/service.py`):**
  ```python
  get_hazard_layer(hazard_type="surge", timestep="2020-05-20T12:00:00Z")
  ```
  - When `DEMO_MODE=true`: Loads precomputed fixture from `api/data/demo/`.
  - When `DEMO_MODE=false`: Dynamically computes via `generate_surge_layer(timestep)`.
  - Timestep `"live"`: Raises `NotImplementedError` per v0.9 contract.
  - Invalid timesteps: Raises `ValueError`.

- **HTTP API Endpoint (`GET /api/hazard/layers`):**
  - Query parameters: `hazard_type=surge&timestep=2020-05-20T12:00:00Z`
  - Response: GeoJSON `FeatureCollection<HazardLayer>` with 528 features (`unit="m"`).

---

## 7. Limitations of the Simplified Model

1. **Closed-Form Parametric Hydrodynamics:** The model provides a fast, zero-latency closed-form solution rather than numerically integrating full 2D/3D shallow water equations (e.g., ADCIRC, SLOSH, Delft3D). This is suitable for instantaneous replay and parametric risk evaluation.
2. **Astronomical Tide Superposition:** Tidal oscillations (semi-diurnal spring tides of $3\text{--}5\text{ m}$ in the Sundarbans) are not dynamically coupled with the surge wave; water depth represents the meteorological surge component above ground level.
3. **Polder Embankment Breach Dynamics:** Flood attenuation assumes generalized resistance ($\alpha_{topo} = 0.25$) rather than explicit hydrodynamic simulation of individual earthen embankment (bundh) overtopping or structural breach.
