# Phase 4 — Holland Wind Model for the Hazard Engine

## 1. Overview & Objective

Phase 4 implements a deterministic parametric wind model for the Tempest Hazard Engine based on the classical **Holland (1980)** tropical cyclone wind field formulation.

The wind engine ingests the canonical 25-point Cyclone Amphan replay track (`api/data/demo/hazard__track.json`), evaluates sustained 10-meter surface wind speeds (in $\text{m/s}$) for each of the 64 spatial grid cells across the Sundarbans AOI ($[88.0^\circ\text{E}, 21.5^\circ\text{N}, 89.1^\circ\text{E}, 22.7^\circ\text{N}]$), normalizes wind severity into $[0.0, 1.0]$, and produces contract-compliant `HazardLayerCollection` features.

---

## 2. Mathematical Formulation & Equations

### 2.1 Atmospheric Pressure Profile
Following Holland (1980), the radial atmospheric pressure distribution $P(r)$ at great-circle distance $r$ from the cyclone center is modeled as:

$$P(r) = P_c + \Delta P \cdot \exp\left( - \left(\frac{R_{max}}{r}\right)^B \right)$$

where:
- $P_c$: Minimum central barometric pressure of the cyclone (hPa) from IBTrACS best-track.
- $P_{env}$: Environmental ambient background pressure ($1010.0\text{ hPa}$).
- $\Delta P = \max(P_{env} - P_c, 1.0) \times 100.0$: Central pressure deficit in Pascals ($\text{Pa}$).
- $R_{max}$: Radius of maximum wind ($\text{RMW}$) in kilometers.
- $r$: Geodesic Haversine distance between grid cell centroid and cyclone eye center ($\text{km}$).
- $B$: Holland peakedness shape parameter.

### 2.2 Dynamic Holland Peakedness Parameter ($B$)
In standard tropical meteorology (Holland 1980, 2008), the peakedness parameter $B$ dictates the profile curvature around the eyewall and is related to peak wind intensity and pressure drop:

$$B = \frac{\rho_a \cdot e \cdot V_{max}^2}{\Delta P}$$

where:
- $\rho_a = 1.15\text{ kg/m}^3$: Surface air density in the tropical marine boundary layer.
- $e = \exp(1) \approx 2.71828$: Euler's constant.
- $V_{max}$: Maximum sustained 10m wind speed ($\text{m/s}$) from track.
- $\Delta P$: Pressure drop ($\text{Pa}$).

Physical bounds are strictly enforced:

$$B \in [1.0, 2.5]$$

Across the 25 Amphan replay timesteps, $B$ dynamically ranges between $1.13$ and $1.55$, matching observed Bay of Bengal tropical cyclone behavior.

### 2.3 Gradient Wind Equation
Accounting for the cyclostrophic and Coriolis forces:

$$\frac{V_g^2}{r} + f \cdot V_g = \frac{1}{\rho_a} \frac{dP}{dr}$$

Solving the quadratic gradient wind equation yields:

$$V_g(r) = \sqrt{ \frac{B}{\rho_a} \left(\frac{R_{max}}{r}\right)^B \Delta P \cdot \exp\left(-\left(\frac{R_{max}}{r}\right)^B\right) + \left(\frac{r_m \cdot f}{2}\right)^2 } - \frac{r_m \cdot f}{2}$$

where:
- $f = 2 \Omega \sin(\phi)$: Coriolis parameter at cell centroid latitude $\phi$.
- $\Omega = 7.292115 \times 10^{-5}\text{ rad/s}$: Earth's angular rotation rate.
- $r_m = \max(r, 0.1) \times 1000.0$: Distance in meters ($100\text{m}$ singularity threshold).

### 2.4 Forward Translation Asymmetry
In Northern Hemisphere cyclones, translation adds forward-right asymmetric wind enhancement:

$$\theta_{rel} = \theta_{bearing} - \theta_{heading}$$

$$\text{Asymmetry Factor} = 1.0 + 0.18 \cdot \sin(\theta_{rel})$$

where $\theta_{bearing}$ is the geodesic azimuth bearing from storm eye to cell centroid, and $\theta_{heading}$ is storm forward translation heading azimuth ($0^\circ = \text{North}$).

### 2.5 Surface Boundary Layer Friction
Gradient-level winds ($\sim 1\text{km}$ altitude) are reduced to standard 10m surface winds ($V_{10}$) via surface roughness reduction factors:

$$K_m = \begin{cases} 
0.90 & \text{if } \text{dist\_to\_coast} \le 20\text{ km (marine / coastal estuary)} \\
0.82 & \text{if } \text{dist\_to\_coast} > 20\text{ km (inland deltaic terrain)}
\end{cases}$$

### 2.6 Ambient Background Wind Floor
At large radial distances ($r > 500\text{ km}$), gradient wind asymptotically decays. A distance-dependent synoptic background ambient wind floor prevents artificial zeros:

$$V_{ambient} = 6.0 + \max(0.0, 14.0 - r / 60.0)\text{ m/s}$$

$$V_{final} = \min\left(\max(V_{10} \cdot \text{asymmetry}, V_{ambient}), 65.0\right)\text{ m/s}$$

---

## 3. Physical Constants

| Parameter | Symbol | Value | Unit | Description |
|---|---|---|---|---|
| Ambient Pressure | $P_{env}$ | $1010.0$ | $\text{hPa}$ | Synoptic pre-monsoon background pressure over Bay of Bengal |
| Surface Air Density | $\rho_a$ | $1.15$ | $\text{kg/m}^3$ | Humid tropical boundary layer air density |
| Earth Angular Velocity | $\Omega$ | $7.292115 \times 10^{-5}$ | $\text{rad/s}$ | Sidereal Earth rotation rate |
| Earth Radius | $R_{\text{Earth}}$ | $6371.0$ | $\text{km}$ | Mean spherical Earth radius for Haversine distance |
| Holland $B$ Min Bound | $B_{min}$ | $1.0$ | dimensionless | Lower limit on profile peakedness |
| Holland $B$ Max Bound | $B_{max}$ | $2.5$ | dimensionless | Upper limit on profile peakedness |
| Marine Surface Factor | $K_{m,coast}$ | $0.90$ | dimensionless | Coastal/marine 10m boundary layer reduction |
| Inland Surface Factor | $K_{m,inland}$ | $0.82$ | dimensionless | Delta land surface friction reduction factor |
| Coast Distance Threshold | $d_{coast}$ | $20.0$ | $\text{km}$ | Threshold distance to demarcate inland friction |
| Physical Wind Ceiling | $V_{ceiling}$ | $65.0$ | $\text{m/s}$ | Sustained 10m physical maximum ceiling |

---

## 4. Severity Normalization Method

The normalized severity score $S \in [0.0, 1.0]$ maps continuously and monotonically to the official **India Meteorological Department (IMD)** tropical cyclone intensity scale:

| Wind Speed ($v$) | IMD Classification | Severity Formula ($S$) | Severity Range |
|---|---|---|---|
| $v \le 10.0\text{ m/s}$ | Calm to Moderate Breeze | $(v / 10.0) \times 0.20$ | $[0.00, 0.20]$ |
| $10.0 < v \le 17.0\text{ m/s}$ | Strong Breeze / Depression | $0.20 + ((v - 10.0) / 7.0) \times 0.15$ | $(0.20, 0.35]$ |
| $17.0 < v \le 24.0\text{ m/s}$ | Deep Depression / Cyclonic Storm | $0.35 + ((v - 17.0) / 7.0) \times 0.20$ | $(0.35, 0.55]$ |
| $24.0 < v \le 33.0\text{ m/s}$ | Severe Cyclonic Storm (SCS) | $0.55 + ((v - 24.0) / 9.0) \times 0.20$ | $(0.55, 0.75]$ |
| $33.0 < v < 48.0\text{ m/s}$ | Very Severe to Super Cyclone | $0.75 + ((v - 33.0) / 15.0) \times 0.25$ | $(0.75, 1.00)$ |
| $v \ge 48.0\text{ m/s}$ | Extreme Super Cyclonic Storm | $1.00$ | $1.00$ |

### Mathematical Guarantees:
- **Monotonicity:** For any $v_1 \le v_2$, $S(v_1) \le S(v_2)$ (positive piecewise slopes).
- **Boundedness:** $S(v) \in [0.0, 1.0]$ for all inputs $v \in \mathbb{R}$.
- **Determinism:** Identical input floating point speed produces identical severity score rounded to 3 decimal places.

---

## 5. Assumptions & Known Simplifications

1. **Parametric Circular Core with First-Order Asymmetry:** The Holland model assumes an analytical pressure field with empirical translation asymmetry. Full 3D Navier-Stokes numerical fluid dynamics (e.g. WRF) are replaced by this closed-form solution to achieve zero-latency deterministic replay.
2. **Constant Environmental Pressure ($P_{env} = 1010.0\text{ hPa}$):** Observed ambient pressure in the northern Bay of Bengal during mid-May typically varies between $1008$ and $1012\text{ hPa}$. A constant $1010.0\text{ hPa}$ baseline simplifies deterministic calculation without meaningful distortion.
3. **Zonal Boundary Layer Friction:** Terrain friction transition is modeled as a two-tier step function ($0.90$ marine/coastal within $20\text{ km}$, $0.82$ inland) rather than dynamic aerodynamic roughness length $z_0$ integration.
4. **Spatial Discretization:** The Sundarbans AOI is discretized into an $8 \times 8$ regular grid (64 polygon cells), where wind speed is evaluated at cell centroids.
5. **No Machine Learning or Stochastic Perturbations:** Output is 100% deterministic and reproducible across all platforms.

---

## 6. Fixture Generation Workflow

To satisfy the `DEMO_MODE=true` offline contract requirements (contracts.md §7), static fixtures for all 25 timesteps are generated using `api/scripts/build_wind_fixtures.py`:

```bash
# Execute from repo root
api\.venv\Scripts\python api\scripts\build_wind_fixtures.py
```

### Artifact Details:
- **Directory:** `api/data/demo/`
- **Pattern:** `hazard__layers-wind__<YYYYMMDDTHHMMZ>.json` (compact ISO 8601 UTC timestamp)
- **Count:** Exactly 25 files (`20200517T1200Z` to `20200520T1200Z`)
- **Encoding & Line Endings:** UTF-8 JSON, strict LF (`\n`, no `\r\n`)
- **Validation:** Automatically verified by `tests/test_demo_fixtures.py` and `tests/test_hazard.py`.

---

## 7. Service & API Integration

- **Internal Interface (`api/app/hazard/service.py`):**
  ```python
  get_hazard_layer(hazard_type="wind", timestep="2020-05-20T12:00:00Z")
  ```
  - When `DEMO_MODE=true`: Loads precomputed fixture from `api/data/demo/`.
  - When `DEMO_MODE=false`: Dynamically computes the layer via `generate_wind_layer(timestep)`.
  - Timestep `"live"`: Raises `NotImplementedError` per v0.9 contract.
  - Invalid timesteps: Raises `ValueError`.

- **HTTP API Endpoint (`GET /api/hazard/layers`):**
  - Parameters: `hazard_type=wind&timestep=2020-05-20T12:00:00Z`
  - Response: GeoJSON `FeatureCollection<HazardLayer>` with 64 features.
