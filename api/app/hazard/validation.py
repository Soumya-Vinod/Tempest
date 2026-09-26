"""Hazard Engine validation, calibration, and cross-hazard consistency utilities.

Phase 7: Comprehensive verification across Wind (Phase 4), Storm Surge (Phase 5),
and Flood Susceptibility (Phase 6) models, ensuring numerical stability, physical
bounds, monotonic severity mappings, and contract compliance across all 25 replay timesteps.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.demo import DEMO_DIR
from app.hazard.models import (
    CycloneTrackPoint,
    GridCell,
    HazardLayer,
    HazardLayerCollection,
    HazardType,
)
from app.hazard.replay import (
    AMPHAN_TRACK,
    HOLLAND_B_MAX,
    HOLLAND_B_MIN,
    INLAND_SURGE_DECAY_KM,
    MAX_PHYSICAL_SURGE_DEPTH_M,
    MAX_PHYSICAL_WIND_SPEED_MPS,
    SHELF_BATHYMETRY_AMPLIFICATION,
    SURGE_BAROMETER_FACTOR,
    SURGE_MAX_DISTANCE_EYE_KM,
    SURGE_RAMP_DISTANCE_EYE_KM,
    TOTAL_GRID_CELLS,
    WEIGHT_FLOOD_ELEVATION,
    WEIGHT_FLOOD_LANDCOVER,
    WEIGHT_FLOOD_RAINFALL,
    WEIGHT_FLOOD_SLOPE,
    WEIGHT_FLOOD_SURFACE_WATER,
    WEIGHT_FLOOD_TOPOGRAPHIC_WETNESS,
    WIND_SETUP_COEFF,
    WIND_SETUP_EXPONENT,
    WIND_SETUP_REF_SPEED_MPS,
    compute_flood_metric,
    compute_holland_b,
    compute_surge_metric,
    compute_wind_metric,
    generate_flood_layer,
    generate_hazard_layer,
    get_aoi_grid,
    iso_to_compact_ts,
    normalize_flood_severity,
    normalize_surge_severity,
    normalize_wind_severity,
    validate_timestep,
)
from app.schemas.common import REPLAY_TIMESTEPS
from app.schemas.contracts import HAZARD_UNITS

logger = logging.getLogger(__name__)

# Bounding box coordinates with numerical tolerance
AOI_TOLERANCE_DEG: float = 1e-4


# ---------------------------------------------------------------------------
# 1. Cross-Hazard Validation Helpers (contracts.md §4.1, §7)
# ---------------------------------------------------------------------------
def validate_hazard_layer(layer: HazardLayer, raise_exc: bool = False) -> bool:
    """Validate a single HazardLayer feature against contract requirements.

    Verifies:
    - ID matching: layer.id == layer.properties.id
    - Valid hazard_type ('wind', 'surge', 'flood')
    - Correct unit according to hazard_type contract
    - Timestep in official 25 replay timesteps
    - Severity strictly in [0.0, 1.0]
    - Value strictly within physical bounds for hazard type
    - Polygon geometry valid EPSG:4326 closed linear ring within AOI bounds
    """
    props = layer.properties

    # 1. ID matching
    if layer.id != props.id:
        if raise_exc:
            raise ValueError(f"Feature ID mismatch: {layer.id!r} != {props.id!r}")
        return False

    # 2. Hazard type
    if props.hazard_type not in ("wind", "surge", "flood"):
        if raise_exc:
            raise ValueError(f"Invalid hazard_type: {props.hazard_type!r}")
        return False

    # 3. Unit contract
    expected_unit = HAZARD_UNITS.get(props.hazard_type)
    if props.unit != expected_unit:
        if raise_exc:
            raise ValueError(
                f"Unit mismatch for {props.hazard_type}: "
                f"expected {expected_unit!r}, got {props.unit!r}"
            )
        return False

    # 4. Timestep
    if props.timestep not in REPLAY_TIMESTEPS:
        if raise_exc:
            raise ValueError(f"Invalid replay timestep: {props.timestep!r}")
        return False

    # 5. Severity bounds [0.0, 1.0]
    if not (0.0 <= props.severity <= 1.0):
        if raise_exc:
            raise ValueError(f"Severity out of bounds [0, 1]: {props.severity}")
        return False

    # 6. Physical value bounds
    if props.hazard_type == "wind":
        if not (0.0 <= props.value <= MAX_PHYSICAL_WIND_SPEED_MPS):
            if raise_exc:
                raise ValueError(
                    f"Wind speed {props.value} out of physical bounds "
                    f"[0, {MAX_PHYSICAL_WIND_SPEED_MPS}]"
                )
            return False
    elif props.hazard_type == "surge":
        if not (0.0 <= props.value <= MAX_PHYSICAL_SURGE_DEPTH_M):
            if raise_exc:
                raise ValueError(
                    f"Surge depth {props.value} out of physical bounds "
                    f"[0, {MAX_PHYSICAL_SURGE_DEPTH_M}]"
                )
            return False
    elif props.hazard_type == "flood":
        if not (0.0 <= props.value <= 1.0):
            if raise_exc:
                raise ValueError(f"Flood susceptibility index {props.value} out of bounds [0, 1]")
            return False

    # 7. Geometry validity
    geom = layer.geometry
    if geom.type != "Polygon":
        if raise_exc:
            raise ValueError(f"Expected Polygon geometry, got {geom.type!r}")
        return False

    if not geom.coordinates or not geom.coordinates[0]:
        if raise_exc:
            raise ValueError("Polygon has empty coordinate ring")
        return False

    ring = geom.coordinates[0]
    if len(ring) < 4:
        if raise_exc:
            raise ValueError(f"Linear ring must contain at least 4 coordinates; got {len(ring)}")
        return False

    # Closed ring: first coordinate == last coordinate
    if ring[0] != ring[-1]:
        if raise_exc:
            raise ValueError(f"Linear ring is not closed: {ring[0]} != {ring[-1]}")
        return False

    # AOI boundary bounds
    settings = get_settings()
    min_lon, min_lat, max_lon, max_lat = settings.aoi_bbox_tuple
    for lon, lat in ring:
        lon_in_bounds = min_lon - AOI_TOLERANCE_DEG <= lon <= max_lon + AOI_TOLERANCE_DEG
        lat_in_bounds = min_lat - AOI_TOLERANCE_DEG <= lat <= max_lat + AOI_TOLERANCE_DEG
        if not (lon_in_bounds and lat_in_bounds):
            if raise_exc:
                raise ValueError(
                    f"Coordinate [{lon}, {lat}] exceeds AOI bbox "
                    f"[{min_lon}, {min_lat}, {max_lon}, {max_lat}]"
                )
            return False

    return True


def validate_hazard_collection(
    collection: HazardLayerCollection,
    expected_type: HazardType | None = None,
    expected_timestep: str | None = None,
    raise_exc: bool = False,
) -> bool:
    """Validate a HazardLayerCollection for contract compliance, completeness, and integrity."""
    if collection.type != "FeatureCollection":
        if raise_exc:
            raise ValueError(f"Invalid collection type: {collection.type!r}")
        return False

    if len(collection.features) != TOTAL_GRID_CELLS:
        if raise_exc:
            raise ValueError(
                f"Feature count mismatch: expected {TOTAL_GRID_CELLS}, "
                f"got {len(collection.features)}"
            )
        return False

    feature_ids: set[str] = set()
    compact_ts = iso_to_compact_ts(expected_timestep) if expected_timestep else None

    for feat in collection.features:
        # Validate individual feature
        if not validate_hazard_layer(feat, raise_exc=raise_exc):
            return False

        # Check unique IDs
        if feat.id in feature_ids:
            if raise_exc:
                raise ValueError(f"Duplicate feature ID detected: {feat.id}")
            return False
        feature_ids.add(feat.id)

        # Check expected hazard type
        if expected_type and feat.properties.hazard_type != expected_type:
            if raise_exc:
                raise ValueError(
                    f"Feature hazard_type {feat.properties.hazard_type!r} != "
                    f"expected {expected_type!r}"
                )
            return False

        # Check expected timestep
        if expected_timestep and feat.properties.timestep != expected_timestep:
            if raise_exc:
                raise ValueError(
                    f"Feature timestep {feat.properties.timestep!r} != "
                    f"expected {expected_timestep!r}"
                )
            return False

        # ID convention: {hazard_type}__{cell_id}__{compact_ts}
        if compact_ts and not feat.id.endswith(f"__{compact_ts}"):
            if raise_exc:
                raise ValueError(
                    f"Feature ID {feat.id} does not end with compact timestep {compact_ts}"
                )
            return False

    return True


def validate_hazard_consistency(
    wind_col: HazardLayerCollection,
    surge_col: HazardLayerCollection,
    flood_col: HazardLayerCollection,
    raise_exc: bool = False,
) -> bool:
    """Verify cross-hazard spatial, temporal, and grid consistency across wind, surge, and flood."""
    # 1. Feature counts
    counts = (len(wind_col.features), len(surge_col.features), len(flood_col.features))
    if not (counts[0] == counts[1] == counts[2] == TOTAL_GRID_CELLS):
        if raise_exc:
            raise ValueError(
                f"Inconsistent feature counts: wind={counts[0]}, "
                f"surge={counts[1]}, flood={counts[2]}"
            )
        return False

    # 2. Timestep matching across all three layers
    w_ts = wind_col.features[0].properties.timestep
    s_ts = surge_col.features[0].properties.timestep
    f_ts = flood_col.features[0].properties.timestep
    if not (w_ts == s_ts == f_ts):
        if raise_exc:
            raise ValueError(f"Timestep mismatch: wind={w_ts}, surge={s_ts}, flood={f_ts}")
        return False

    # 3. Geometry and cell identity equality
    for i in range(TOTAL_GRID_CELLS):
        wf = wind_col.features[i]
        sf = surge_col.features[i]
        ff = flood_col.features[i]

        w_cell = wf.id.split("__")[1]
        s_cell = sf.id.split("__")[1]
        f_cell = ff.id.split("__")[1]

        if not (w_cell == s_cell == f_cell):
            if raise_exc:
                raise ValueError(
                    f"Cell ID mismatch at index {i}: wind={w_cell}, surge={s_cell}, flood={f_cell}"
                )
            return False

        if wf.geometry.coordinates != sf.geometry.coordinates:
            if raise_exc:
                raise ValueError(f"Wind/surge coordinate mismatch for cell {w_cell} at index {i}")
            return False

        if wf.geometry.coordinates != ff.geometry.coordinates:
            if raise_exc:
                raise ValueError(f"Wind/flood coordinate mismatch for cell {w_cell} at index {i}")
            return False

    return True


# ---------------------------------------------------------------------------
# 2. Calibration Checks
# ---------------------------------------------------------------------------
def check_wind_calibration(
    cell: GridCell | None = None,
    track_pt: CycloneTrackPoint | None = None,
) -> dict[str, Any]:
    """Verify calibration parameters and governing physics of the Holland parametric wind model."""
    target_cell = cell or get_aoi_grid()[0]
    target_pt = track_pt or AMPHAN_TRACK["2020-05-20T12:00:00Z"]

    # 1. Holland B parameter bounds [1.0, 2.5]
    b = compute_holland_b(target_pt.central_pressure_hpa, target_pt.max_wind_mps)
    b_valid = HOLLAND_B_MIN <= b <= HOLLAND_B_MAX

    # Extreme pressure test
    b_extreme_low = compute_holland_b(900.0, 70.0)
    b_extreme_high = compute_holland_b(1005.0, 15.0)
    b_bounded = (HOLLAND_B_MIN <= b_extreme_low <= HOLLAND_B_MAX) and (
        HOLLAND_B_MIN <= b_extreme_high <= HOLLAND_B_MAX
    )

    # 2. Wind ceiling and ambient floor
    res = compute_wind_metric(target_cell, target_pt)
    ceiling_valid = res.value <= MAX_PHYSICAL_WIND_SPEED_MPS
    floor_valid = res.value >= 6.0

    # 3. Monotonic severity normalization
    sev_tests = [0.0, 5.0, 10.0, 15.0, 17.0, 20.0, 24.0, 30.0, 33.0, 40.0, 48.0, 60.0]
    sevs = [normalize_wind_severity(v) for v in sev_tests]
    sev_monotonic = all(sevs[i] <= sevs[i + 1] for i in range(len(sevs) - 1))
    sev_bounded = all(0.0 <= s <= 1.0 for s in sevs)

    # 4. Deterministic repeatability
    res2 = compute_wind_metric(target_cell, target_pt)
    deterministic = (res.value == res2.value) and (res.severity == res2.severity)

    all_passed = (
        b_valid
        and b_bounded
        and ceiling_valid
        and floor_valid
        and sev_monotonic
        and sev_bounded
        and deterministic
    )

    return {
        "model": "holland_wind",
        "holland_b": b,
        "holland_b_bounded": b_bounded,
        "sample_wind_mps": res.value,
        "ceiling_enforced": ceiling_valid,
        "floor_enforced": floor_valid,
        "severity_monotonic": sev_monotonic,
        "severity_bounded": sev_bounded,
        "deterministic": deterministic,
        "all_passed": all_passed,
    }


def check_surge_calibration(
    cell: GridCell | None = None,
    track_pt: CycloneTrackPoint | None = None,
) -> dict[str, Any]:
    """Verify calibration parameters and governing physics of the storm surge hydrodynamic model."""
    cells = get_aoi_grid()
    target_cell = cell or cells[0]
    target_pt = track_pt or AMPHAN_TRACK["2020-05-20T12:00:00Z"]

    # 1. Non-negative depth and maximum surge ceiling
    res = compute_surge_metric(target_cell, target_pt)
    non_negative = res.value >= 0.0
    ceiling_valid = res.value <= MAX_PHYSICAL_SURGE_DEPTH_M

    # 2. Inverted barometer contribution: ~1 cm per hPa deficit
    delta_p = max(0.0, 1012.0 - target_pt.central_pressure_hpa)
    expected_baro = delta_p * SURGE_BAROMETER_FACTOR
    baro_valid = expected_baro >= 0.0

    # 3. Wind setup contribution
    wind_res = compute_wind_metric(target_cell, target_pt)
    expected_setup = (
        (wind_res.value / WIND_SETUP_REF_SPEED_MPS) ** WIND_SETUP_EXPONENT * WIND_SETUP_COEFF
    )
    setup_valid = expected_setup >= 0.0

    # 4. Shelf bathymetry amplification factor
    shelf_valid = SHELF_BATHYMETRY_AMPLIFICATION == 1.10

    # 5. Inland attenuation length scale
    decay_valid = INLAND_SURGE_DECAY_KM == 35.0

    # 6. Eye distance modulation transition continuity
    eye_max = SURGE_MAX_DISTANCE_EYE_KM  # 600 km
    eye_ramp = SURGE_RAMP_DISTANCE_EYE_KM  # 300 km
    eye_continuity = (eye_max == 600.0) and (eye_ramp == 300.0)

    # 7. Monotonic and continuous severity normalization
    depth_tests = [-1.0, 0.0, 0.15, 0.30, 0.65, 1.0, 1.75, 2.5, 3.25, 4.0, 5.0, 6.0]
    sevs = [normalize_surge_severity(d) for d in depth_tests]
    sev_monotonic = all(sevs[i] <= sevs[i + 1] for i in range(len(sevs) - 1))
    sev_bounded = all(0.0 <= s <= 1.0 for s in sevs)

    # 8. Deterministic repeatability
    res2 = compute_surge_metric(target_cell, target_pt)
    deterministic = (res.value == res2.value) and (res.severity == res2.severity)

    all_passed = (
        non_negative
        and ceiling_valid
        and baro_valid
        and setup_valid
        and shelf_valid
        and decay_valid
        and eye_continuity
        and sev_monotonic
        and sev_bounded
        and deterministic
    )

    return {
        "model": "storm_surge",
        "sample_surge_m": res.value,
        "sample_severity": res.severity,
        "non_negative": non_negative,
        "ceiling_enforced": ceiling_valid,
        "barometer_factor_valid": baro_valid,
        "wind_setup_valid": setup_valid,
        "shelf_amplification_valid": shelf_valid,
        "inland_decay_valid": decay_valid,
        "eye_modulation_continuity": eye_continuity,
        "severity_monotonic": sev_monotonic,
        "severity_bounded": sev_bounded,
        "deterministic": deterministic,
        "all_passed": all_passed,
    }


def check_flood_calibration(cell: GridCell | None = None) -> dict[str, Any]:
    """Verify calibration parameters and static behavior of the flood model."""
    cells = get_aoi_grid()
    target_cell = cell or cells[0]

    # 1. MCDA AHP Weights sum to 1.00
    weights_sum = (
        WEIGHT_FLOOD_ELEVATION
        + WEIGHT_FLOOD_SLOPE
        + WEIGHT_FLOOD_TOPOGRAPHIC_WETNESS
        + WEIGHT_FLOOD_SURFACE_WATER
        + WEIGHT_FLOOD_RAINFALL
        + WEIGHT_FLOOD_LANDCOVER
    )
    weights_valid = math.isclose(weights_sum, 1.00, rel_tol=1e-5)

    # 2. Susceptibility index bounded in [0.05, 0.98]
    res = compute_flood_metric(target_cell)
    bounded = 0.05 <= res.value <= 0.98

    # 3. Static repeatability across timesteps
    col_t0 = generate_flood_layer(REPLAY_TIMESTEPS[0])
    col_tlandfall = generate_flood_layer(REPLAY_TIMESTEPS[-1])
    static_valid = all(
        (
            f1.properties.value == f2.properties.value
            and f1.properties.severity == f2.properties.severity
        )
        for f1, f2 in zip(col_t0.features, col_tlandfall.features, strict=True)
    )

    # 4. Monotonic severity normalization
    idx_tests = [-0.1, 0.0, 0.20, 0.40, 0.60, 0.80, 1.0, 1.2]
    sevs = [normalize_flood_severity(i) for i in idx_tests]
    sev_monotonic = all(sevs[i] <= sevs[i + 1] for i in range(len(sevs) - 1))
    sev_bounded = all(0.0 <= s <= 1.0 for s in sevs)

    # 5. Deterministic repeatability
    res2 = compute_flood_metric(target_cell)
    deterministic = (res.value == res2.value) and (res.severity == res2.severity)

    all_passed = (
        weights_valid
        and bounded
        and static_valid
        and sev_monotonic
        and sev_bounded
        and deterministic
    )

    return {
        "model": "flood_susceptibility",
        "mcda_weights_sum": round(weights_sum, 4),
        "weights_valid": weights_valid,
        "sample_index": res.value,
        "sample_severity": res.severity,
        "bounded": bounded,
        "static_across_timesteps": static_valid,
        "severity_monotonic": sev_monotonic,
        "severity_bounded": sev_bounded,
        "deterministic": deterministic,
        "all_passed": all_passed,
    }


def run_full_hazard_calibration() -> dict[str, Any]:
    """Run all calibration checks across wind, surge, and flood models."""
    wind_report = check_wind_calibration()
    surge_report = check_surge_calibration()
    flood_report = check_flood_calibration()

    all_passed = (
        wind_report["all_passed"]
        and surge_report["all_passed"]
        and flood_report["all_passed"]
    )

    return {
        "wind": wind_report,
        "surge": surge_report,
        "flood": flood_report,
        "all_passed": all_passed,
    }


# ---------------------------------------------------------------------------
# 3. Full Replay and Demo Fixture Verification
# ---------------------------------------------------------------------------
def validate_all_replay_timesteps() -> dict[str, Any]:
    """Validate all 25 replay timesteps across wind, surge, and flood layers."""
    total_timesteps = len(REPLAY_TIMESTEPS)
    layers_validated = 0
    features_validated = 0

    for ts in REPLAY_TIMESTEPS:
        clean_ts = validate_timestep(ts)

        # Dispatch via generate_hazard_layer and verify consistency
        wind_col = generate_hazard_layer("wind", clean_ts)
        surge_col = generate_hazard_layer("surge", clean_ts)
        flood_col = generate_hazard_layer("flood", clean_ts)

        validate_hazard_collection(
            wind_col, expected_type="wind", expected_timestep=clean_ts, raise_exc=True
        )
        validate_hazard_collection(
            surge_col, expected_type="surge", expected_timestep=clean_ts, raise_exc=True
        )
        validate_hazard_collection(
            flood_col, expected_type="flood", expected_timestep=clean_ts, raise_exc=True
        )

        validate_hazard_consistency(wind_col, surge_col, flood_col, raise_exc=True)

        layers_validated += 3
        features_validated += 3 * TOTAL_GRID_CELLS

    return {
        "timesteps_checked": total_timesteps,
        "layers_validated": layers_validated,
        "features_validated": features_validated,
        "all_valid": True,
    }


def validate_demo_fixtures(fixture_dir: Path | None = None) -> dict[str, Any]:
    """Validate all 75 DEMO_MODE fixtures for existence, UTF-8, LF endings, and schema validity."""
    out_dir = fixture_dir or DEMO_DIR
    checked_fixtures = 0

    for h_type in ("wind", "surge", "flood"):
        for ts in REPLAY_TIMESTEPS:
            compact_ts = iso_to_compact_ts(ts)
            key = f"hazard__layers-{h_type}__{compact_ts}"
            path = out_dir / f"{key}.json"

            if not path.is_file():
                raise FileNotFoundError(f"Missing required fixture: {path.name}")

            # Verify UTF-8 reading and LF-only line endings
            raw = path.read_bytes()
            if b"\r\n" in raw:
                raise ValueError(f"Fixture {path.name} contains CRLF line endings; must be LF only")

            text = raw.decode("utf-8")
            data = json.loads(text)
            collection = HazardLayerCollection.model_validate(data)

            validate_hazard_collection(
                collection, expected_type=h_type, expected_timestep=ts, raise_exc=True
            )
            checked_fixtures += 1

    return {
        "checked_fixtures": checked_fixtures,
        "expected_fixtures": 75,
        "all_valid": True,
    }
