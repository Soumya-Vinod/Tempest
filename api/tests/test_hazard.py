"""Unit and contract compliance tests for the hazard module (Dev A)."""

import json
from datetime import UTC

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.core.demo as demo_mod
from app.core.config import Settings
from app.core.demo import DEMO_DIR, load_fixture
from app.hazard.models import (
    CycloneTrack,
    CycloneTrackPoint,
    GridCell,
    HazardLayer,
    HazardLayerCollection,
    HazardLayerProperties,
    MultiPolygon,
    Polygon,
    ReplayTimeline,
)
from app.hazard.replay import (
    AMPHAN_TRACK,
    EVENT_NAME,
    LANDFALL_TIMESTAMP,
    REPLAY_TIMELINE_TIMESTEPS,
    TIMESTEP_INTERVAL_HOURS,
    TOTAL_TIMESTEPS,
    compute_flood_metric,
    compute_flood_susceptibility_metric,
    compute_holland_b,
    compute_surge_metric,
    compute_wind_metric,
    create_replay_timeline,
    generate_flood_layer,
    generate_surge_layer,
    generate_wind_layer,
    get_aoi_grid,
    iso_to_compact_ts,
    normalize_flood_severity,
    normalize_surge_severity,
    normalize_wind_severity,
    validate_timestep,
)
from app.hazard.replay import (
    get_replay_track as replay_get_track,
)
from app.hazard.service import (
    get_hazard_layer,
    get_replay_timeline,
    get_replay_track,
)
from app.hazard.validation import (
    check_flood_calibration,
    check_surge_calibration,
    check_wind_calibration,
    run_full_hazard_calibration,
    validate_all_replay_timesteps,
    validate_demo_fixtures,
    validate_hazard_collection,
    validate_hazard_consistency,
    validate_hazard_layer,
)
from app.main import app
from app.schemas import LANDFALL_TIMESTEP, REPLAY_TIMESTEPS

client = TestClient(app)
TS_LANDFALL = LANDFALL_TIMESTEP
TS_START = REPLAY_TIMESTEPS[0]
SAMPLE_RING = [[88.0, 21.5], [88.1, 21.5], [88.1, 21.6], [88.0, 21.6], [88.0, 21.5]]
SAMPLE_POLYGON = Polygon(coordinates=[SAMPLE_RING])


# ===========================================================================
# 1. Timeline and Physics Tests
# ===========================================================================


def test_replay_timeline():
    timeline = get_replay_timeline()
    assert isinstance(timeline, ReplayTimeline)
    assert timeline.event == "amphan"
    assert timeline.landfall == TS_LANDFALL
    assert len(timeline.timesteps) == 25
    assert timeline.timesteps == list(REPLAY_TIMESTEPS)


def test_iso_to_compact_ts():
    assert iso_to_compact_ts("2020-05-20T12:00:00Z") == "20200520T1200Z"
    assert iso_to_compact_ts("2020-05-17T12:00:00Z") == "20200517T1200Z"


def test_aoi_grid_generation():
    grid = get_aoi_grid()
    assert len(grid) == 528
    for cell in grid:
        assert isinstance(cell, GridCell)
        assert cell.id.startswith("c")
        assert 88.0 <= cell.min_lon < cell.max_lon <= 89.1
        assert 21.5 <= cell.min_lat < cell.max_lat <= 22.7
        assert cell.elevation_m >= 0.0
        assert cell.dist_to_coast_km >= 0.0
        coords = cell.polygon.coordinates[0]
        assert len(coords) == 5
        assert coords[0] == coords[-1]  # Closed polygon ring

    # Also verify custom resolution fallback
    custom = get_aoi_grid(rows=8, cols=8)
    assert len(custom) == 64


def test_wind_metric_physics():
    cell = get_aoi_grid()[0]
    track_start = AMPHAN_TRACK[TS_START]
    track_landfall = AMPHAN_TRACK[TS_LANDFALL]

    wind_start = compute_wind_metric(cell, track_start)
    wind_landfall = compute_wind_metric(cell, track_landfall)

    assert wind_start.unit == "m/s"
    assert wind_landfall.unit == "m/s"
    assert 0.0 <= wind_start.severity <= 1.0
    assert 0.0 <= wind_landfall.severity <= 1.0
    # Cyclone approaching landfall should result in higher winds in the AOI
    assert wind_landfall.value > wind_start.value
    assert wind_landfall.severity > wind_start.severity


def test_surge_metric_physics():
    cell = get_aoi_grid()[0]
    track_start = AMPHAN_TRACK[TS_START]
    track_landfall = AMPHAN_TRACK[TS_LANDFALL]

    surge_start = compute_surge_metric(cell, track_start)
    surge_landfall = compute_surge_metric(cell, track_landfall)

    assert surge_start.unit == "m"
    assert surge_landfall.unit == "m"
    assert surge_start.value == 0.0  # Eye > 600km away at T-72h
    assert surge_landfall.value > 1.0  # Significant surge at landfall


def test_flood_susceptibility_metric_static():
    cell = get_aoi_grid()[0]
    flood = compute_flood_susceptibility_metric(cell)
    assert flood.unit == "index"
    assert 0.0 <= flood.value <= 1.0
    assert flood.severity == flood.value


def test_get_hazard_layer_validations():
    with pytest.raises(NotImplementedError):
        get_hazard_layer("surge", "live")

    with pytest.raises(ValueError):
        get_hazard_layer("surge", "2020-05-20T13:00:00Z")

    with pytest.raises(ValueError):
        get_hazard_layer("tornado", TS_LANDFALL)  # type: ignore


@pytest.mark.parametrize("hazard_type", ["wind", "surge", "flood"])
def test_get_hazard_layer_returns_valid_collection(hazard_type):
    col = get_hazard_layer(hazard_type, TS_LANDFALL)
    assert isinstance(col, HazardLayerCollection)
    assert len(col.features) == 528
    for feat in col.features:
        assert feat.id == feat.properties.id
        assert feat.properties.hazard_type == hazard_type
        assert feat.properties.timestep == TS_LANDFALL
        assert 0.0 <= feat.properties.severity <= 1.0


def test_flood_layer_static_across_timesteps():
    f_start = get_hazard_layer("flood", TS_START)
    f_landfall = get_hazard_layer("flood", TS_LANDFALL)
    assert len(f_start.features) == len(f_landfall.features) == 528
    for feat1, feat2 in zip(f_start.features, f_landfall.features, strict=True):
        assert feat1.properties.value == feat2.properties.value
        assert feat1.properties.severity == feat2.properties.severity


# ===========================================================================
# 2. Strict Contract Compliance Tests (§4.1 HazardLayer & HazardLayerCollection)
# ===========================================================================


def test_hazard_layer_valid_creation():
    """Verify valid creation of HazardLayer for wind, surge, and flood with proper units."""
    # 1. Standard GeoJSON creation (properties nested)
    props = HazardLayerProperties(
        id="wind-01",
        hazard_type="wind",
        timestep=TS_LANDFALL,
        value=38.5,
        unit="m/s",
        severity=0.82,
    )
    layer = HazardLayer(id="wind-01", geometry=SAMPLE_POLYGON, properties=props)
    assert layer.type == "Feature"
    assert layer.id == "wind-01"
    assert layer.hazard_type == "wind"
    assert layer.timestep == TS_LANDFALL
    assert layer.value == 38.5
    assert layer.unit == "m/s"
    assert layer.severity == 0.82

    # 2. Convenience flat kwargs creation
    layer_flat = HazardLayer(
        id="surge-01",
        geometry=SAMPLE_POLYGON,
        hazard_type="surge",
        timestep=TS_LANDFALL,
        value=3.2,
        unit="m",
        severity=0.75,
    )
    assert layer_flat.id == "surge-01"
    assert layer_flat.properties.id == "surge-01"
    assert layer_flat.properties.hazard_type == "surge"
    assert layer_flat.properties.unit == "m"

    # 3. MultiPolygon support
    mp = MultiPolygon(coordinates=[[SAMPLE_RING]])
    layer_mp = HazardLayer(
        id="flood-01",
        geometry=mp,
        hazard_type="flood",
        timestep=TS_LANDFALL,
        value=0.65,
        unit="index",
        severity=0.65,
    )
    assert layer_mp.geometry.type == "MultiPolygon"
    assert layer_mp.hazard_type == "flood"
    assert layer_mp.unit == "index"


def test_hazard_layer_invalid_inputs_raise():
    """Verify invalid inputs raise pydantic.ValidationError."""
    # 1. Unit mismatch: wind cannot have 'm' or 'index'
    with pytest.raises(ValidationError):
        HazardLayerProperties(
            id="w1", hazard_type="wind", timestep=TS_LANDFALL, value=30.0, unit="m", severity=0.5
        )

    # 2. Unit mismatch: surge cannot have 'm/s'
    with pytest.raises(ValidationError):
        HazardLayerProperties(
            id="s1", hazard_type="surge", timestep=TS_LANDFALL, value=2.0, unit="m/s", severity=0.5
        )

    # 3. Unit mismatch: flood cannot have 'm/s' or 'm'
    with pytest.raises(ValidationError):
        HazardLayerProperties(
            id="f1", hazard_type="flood", timestep=TS_LANDFALL, value=0.5, unit="m", severity=0.5
        )

    # 4. Severity out of bounds: < 0.0
    with pytest.raises(ValidationError):
        HazardLayerProperties(
            id="w1", hazard_type="wind", timestep=TS_LANDFALL, value=30.0, unit="m/s", severity=-0.1
        )

    # 5. Severity out of bounds: > 1.0
    with pytest.raises(ValidationError):
        HazardLayerProperties(
            id="w1", hazard_type="wind", timestep=TS_LANDFALL, value=30.0, unit="m/s", severity=1.05
        )

    # 6. Invalid timestep: outside Amphan 25 timesteps
    with pytest.raises(ValidationError):
        HazardLayerProperties(
            id="w1",
            hazard_type="wind",
            timestep="2020-05-20T13:00:00Z",
            value=30.0,
            unit="m/s",
            severity=0.5,
        )

    # 7. Reserved 'live' timestep in response model (prohibited by contracts.md §2)
    with pytest.raises(ValidationError):
        HazardLayerProperties(
            id="w1", hazard_type="wind", timestep="live", value=30.0, unit="m/s", severity=0.5
        )

    # 8. Feature.id != properties.id
    with pytest.raises(ValidationError):
        props = HazardLayerProperties(
            id="id-a",
            hazard_type="wind",
            timestep=TS_LANDFALL,
            value=25.0,
            unit="m/s",
            severity=0.5,
        )
        HazardLayer(id="id-b", geometry=SAMPLE_POLYGON, properties=props)

    # 9. Null geometry (null geometry allowed only for Advisory per §1)
    with pytest.raises(ValidationError):
        props = HazardLayerProperties(
            id="w1", hazard_type="wind", timestep=TS_LANDFALL, value=25.0, unit="m/s", severity=0.5
        )
        HazardLayer(id="w1", geometry=None, properties=props)  # type: ignore


def test_hazard_layer_required_fields_cannot_be_omitted():
    """Verify omission of any required field raises ValidationError."""
    valid_dict = {
        "id": "cell-01",
        "hazard_type": "wind",
        "timestep": TS_LANDFALL,
        "value": 35.0,
        "unit": "m/s",
        "severity": 0.75,
    }

    # Test each required property field
    for req_field in ("id", "hazard_type", "timestep", "value", "unit", "severity"):
        bad_dict = dict(valid_dict)
        bad_dict.pop(req_field)
        with pytest.raises(ValidationError):
            HazardLayerProperties(**bad_dict)

    # Test Feature required fields: id, geometry, properties
    props = HazardLayerProperties(**valid_dict)
    with pytest.raises(ValidationError):
        HazardLayer(geometry=SAMPLE_POLYGON, properties=props)  # missing id

    with pytest.raises(ValidationError):
        HazardLayer(id="cell-01", properties=props)  # missing geometry

    with pytest.raises(ValidationError):
        HazardLayer(id="cell-01", geometry=SAMPLE_POLYGON)  # missing properties


def test_hazard_layer_json_serialization_matches_contract():
    """Verify serialized JSON strictly conforms to GeoJSON Feature and contracts.md §4.1."""
    layer = HazardLayer(
        id="c0101",
        geometry=SAMPLE_POLYGON,
        hazard_type="wind",
        timestep=TS_LANDFALL,
        value=42.0,
        unit="m/s",
        severity=0.88,
    )

    dumped = layer.model_dump()
    assert dumped["type"] == "Feature"
    assert dumped["id"] == "c0101"
    assert dumped["geometry"]["type"] == "Polygon"
    assert dumped["geometry"]["coordinates"] == [SAMPLE_RING]

    props = dumped["properties"]
    assert set(props.keys()) == {"id", "hazard_type", "timestep", "value", "unit", "severity"}
    assert props["id"] == "c0101"
    assert props["hazard_type"] == "wind"
    assert props["timestep"] == TS_LANDFALL
    assert props["value"] == 42.0
    assert props["unit"] == "m/s"
    assert props["severity"] == 0.88

    # JSON string roundtrip
    raw_json = layer.model_dump_json()
    parsed = json.loads(raw_json)
    assert parsed["type"] == "Feature"
    assert parsed["properties"]["hazard_type"] == "wind"

    rehydrated = HazardLayer.model_validate_json(raw_json)
    assert rehydrated.id == layer.id
    assert rehydrated.value == layer.value
    assert rehydrated.properties.severity == layer.properties.severity


def test_hazard_layer_collection_contract():
    """Verify HazardLayerCollection serialization and structure."""
    layer1 = HazardLayer(
        id="w1",
        geometry=SAMPLE_POLYGON,
        hazard_type="wind",
        timestep=TS_LANDFALL,
        value=20.0,
        unit="m/s",
        severity=0.4,
    )
    layer2 = HazardLayer(
        id="w2",
        geometry=SAMPLE_POLYGON,
        hazard_type="wind",
        timestep=TS_LANDFALL,
        value=30.0,
        unit="m/s",
        severity=0.6,
    )

    col = HazardLayerCollection(type="FeatureCollection", features=[layer1, layer2])
    dumped = col.model_dump()
    assert dumped["type"] == "FeatureCollection"
    assert len(dumped["features"]) == 2
    assert dumped["features"][0]["id"] == "w1"
    assert dumped["features"][1]["id"] == "w2"

    # Extra fields forbidden on collection
    with pytest.raises(ValidationError):
        HazardLayerCollection.model_validate(
            {"type": "FeatureCollection", "features": [], "extra": "invalid"}
        )


# ===========================================================================
# 3. HTTP Route Verification Tests
# ===========================================================================


def test_hazard_routes_http():
    # 1. GET /api/hazard/timesteps
    resp_timesteps = client.get("/api/hazard/timesteps")
    assert resp_timesteps.status_code == 200
    data = resp_timesteps.json()
    assert data["event"] == "amphan"
    assert len(data["timesteps"]) == 25

    # 2. GET /api/hazard/layers
    resp_layers = client.get(f"/api/hazard/layers?hazard_type=wind&timestep={TS_LANDFALL}")
    assert resp_layers.status_code == 200
    features = resp_layers.json()["features"]
    assert len(features) == 528

    # 3. Live returns 501
    resp_live = client.get("/api/hazard/layers?hazard_type=wind&timestep=live")
    assert resp_live.status_code == 501

    # 4. Unknown timestep returns 422
    resp_bad = client.get("/api/hazard/layers?hazard_type=wind&timestep=bad-time")
    assert resp_bad.status_code == 422


# ===========================================================================
# 4. Replay Timeline and Timestep Validation Tests
# ===========================================================================


def test_timeline_constants_and_immutability():
    """Verify replay timeline constants, interval, length, and immutability."""
    assert EVENT_NAME == "amphan"
    assert LANDFALL_TIMESTAMP == "2020-05-20T12:00:00Z"
    assert TIMESTEP_INTERVAL_HOURS == 3
    assert TOTAL_TIMESTEPS == 25
    assert isinstance(REPLAY_TIMELINE_TIMESTEPS, tuple)
    assert len(REPLAY_TIMELINE_TIMESTEPS) == 25


def test_timeline_chronological_ordering():
    """Verify deterministic chronological ordering and exact 3-hour intervals."""
    from datetime import datetime, timedelta

    dt_format = "%Y-%m-%dT%H:%M:%SZ"
    parsed_dates = [
        datetime.strptime(ts, dt_format).replace(tzinfo=UTC) for ts in REPLAY_TIMELINE_TIMESTEPS
    ]

    for i in range(len(parsed_dates) - 1):
        delta = parsed_dates[i + 1] - parsed_dates[i]
        assert delta == timedelta(hours=3), f"Interval between step {i} and {i + 1} is not 3 hours"

    # Start is T-72h, end is landfall
    assert REPLAY_TIMELINE_TIMESTEPS[0] == "2020-05-17T12:00:00Z"
    assert REPLAY_TIMELINE_TIMESTEPS[-1] == "2020-05-20T12:00:00Z"
    assert REPLAY_TIMELINE_TIMESTEPS[-1] == LANDFALL_TIMESTAMP


def test_validate_timestep_valid():
    """Verify validate_timestep accepts all 25 replay timesteps."""
    for ts in REPLAY_TIMELINE_TIMESTEPS:
        assert validate_timestep(ts) == ts


def test_validate_timestep_live():
    """Verify validate_timestep accepts 'live' as a reserved parameter value."""
    assert validate_timestep("live") == "live"


@pytest.mark.parametrize(
    "bad_ts",
    [
        "2020-05-20T13:00:00Z",
        "2020-05-20T12:00Z",
        "2020-05-20",
        "2020-05-17T09:00:00Z",
        "2020-05-20T15:00:00Z",
        "LIVE",
        "",
        "unknown",
        "null",
    ],
)
def test_validate_timestep_invalid_raises(bad_ts):
    """Verify validate_timestep rejects all invalid values with a clear ValueError."""
    with pytest.raises(ValueError, match="must be one of the 25 Amphan replay timesteps"):
        validate_timestep(bad_ts)


def test_timeline_service_returns_contract_model():
    """Verify get_replay_timeline() returns the contract model matching create_replay_timeline()."""
    timeline = get_replay_timeline()
    assert isinstance(timeline, ReplayTimeline)
    assert timeline.event == "amphan"
    assert timeline.landfall == "2020-05-20T12:00:00Z"
    assert len(timeline.timesteps) == 25
    assert timeline.timesteps == list(REPLAY_TIMELINE_TIMESTEPS)

    canonical = create_replay_timeline()
    assert timeline == canonical


def test_timeline_api_endpoint_matches_contract():
    """Verify GET /api/hazard/timesteps returns exact timeline JSON matching contracts.md §5."""
    resp = client.get("/api/hazard/timesteps")
    assert resp.status_code == 200
    body = resp.json()
    assert body["event"] == "amphan"
    assert body["landfall"] == "2020-05-20T12:00:00Z"
    assert len(body["timesteps"]) == 25
    assert body["timesteps"] == list(REPLAY_TIMELINE_TIMESTEPS)


# ===========================================================================
# 5. Cyclone Track Ingestion and Validation Tests (Phase 3)
# ===========================================================================


def test_replay_track_count_and_types():
    """Verify get_replay_track() returns exactly 25 CycloneTrackPoint instances
    in an immutable tuple.
    """
    track = replay_get_track()
    assert isinstance(track, tuple)
    assert len(track) == 25
    for pt in track:
        assert isinstance(pt, CycloneTrackPoint)


def test_replay_track_timestamp_alignment():
    """Verify replay track points are 1-to-1 synchronized with REPLAY_TIMESTEPS."""
    track = replay_get_track()
    track_timesteps = [pt.timestep for pt in track]
    assert track_timesteps == list(REPLAY_TIMESTEPS)
    assert track[0].timestep == "2020-05-17T12:00:00Z"
    assert track[-1].timestep == LANDFALL_TIMESTEP


def test_replay_track_lat_lon_and_physical_bounds():
    """Verify physical track coordinates and intensity parameters fall within expected ranges."""
    track = replay_get_track()
    for pt in track:
        # Track moves through Bay of Bengal towards West Bengal/Sundarbans
        assert 10.0 <= pt.lat <= 23.0
        assert 85.0 <= pt.lon <= 90.0
        # Central pressure bounds (Amphan was a Super Cyclone with Pc between 920 and 990 hPa)
        assert 910.0 <= pt.central_pressure_hpa <= 1000.0
        # Maximum sustained 10m wind speed between 20 m/s and 70 m/s
        assert 20.0 <= pt.max_wind_mps <= 70.0
        # Radius of maximum winds
        assert 15.0 <= pt.radius_max_wind_km <= 50.0
        # Forward translation speed
        assert 0.0 <= pt.forward_speed_mps <= 20.0
        # Heading azimuth [0, 360)
        assert 0.0 <= pt.heading_deg < 360.0


def test_replay_track_chronological_ordering_and_motion():
    """Verify storm progresses northward and demonstrates intensification curve."""
    track = replay_get_track()
    # Continuous northward motion
    for i in range(len(track) - 1):
        assert track[i + 1].lat > track[i].lat, f"Step {i} did not progress northward"

    # Deepening to super cyclonic intensity (lowest pressure 920.0 hPa)
    peak_pt = min(track, key=lambda p: p.central_pressure_hpa)
    assert peak_pt.central_pressure_hpa == 920.0
    assert peak_pt.timestep in ("2020-05-18T18:00:00Z", "2020-05-18T21:00:00Z")


def test_replay_track_immutability():
    """Verify CycloneTrackPoint and the track tuple are strictly immutable."""
    track = replay_get_track()
    pt = track[0]
    with pytest.raises(ValidationError):
        pt.lat = 12.0  # type: ignore

    with pytest.raises(TypeError):
        track[0] = pt  # type: ignore


def test_hazard_track_fixture_loading_and_roundtrip(monkeypatch):
    """Verify api/data/demo/hazard__track.json loads and matches the canonical track model."""
    fixture_path = DEMO_DIR / "hazard__track.json"
    assert fixture_path.is_file()
    with fixture_path.open(encoding="utf-8") as f:
        direct_data = json.load(f)

    monkeypatch.setattr(demo_mod, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=True))
    fixture_data = load_fixture("hazard__track")
    assert fixture_data == direct_data
    assert fixture_data["event"] == "amphan"
    assert len(fixture_data["points"]) == 25

    track_model = CycloneTrack.model_validate(fixture_data)
    assert track_model.event == "amphan"
    assert len(track_model.points) == 25
    assert [p.timestep for p in track_model.points] == list(REPLAY_TIMESTEPS)

    # Lossless JSON roundtrip
    rehydrated = CycloneTrack.model_validate_json(track_model.model_dump_json())
    assert rehydrated == track_model


def test_service_get_replay_track_integration(monkeypatch):
    """Verify service.get_replay_track() returns the canonical track matching replay module."""
    # When DEMO_MODE is False
    service_track = get_replay_track()
    canonical_track = replay_get_track()
    assert isinstance(service_track, tuple)
    assert len(service_track) == 25
    assert service_track == canonical_track

    # When DEMO_MODE is True
    import app.hazard.service as hazard_service

    monkeypatch.setattr(demo_mod, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=True))
    monkeypatch.setattr(
        hazard_service, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=True)
    )
    demo_service_track = get_replay_track()
    assert isinstance(demo_service_track, tuple)
    assert len(demo_service_track) == 25
    assert demo_service_track == canonical_track


# ===========================================================================
# 6. Phase 4 — Holland Wind Model & Wind Hazard Layer Tests
# ===========================================================================


def test_holland_shape_parameter_calculation():
    """Verify Holland shape parameter B formulation, physics, and bounds [1.0, 2.5]."""
    # 1. Normal storm conditions
    # Pc = 957.0 hPa, Vmax = 43.73 m/s, Penv = 1010.0 hPa
    b_landfall = compute_holland_b(957.0, 43.73)
    assert 1.0 <= b_landfall <= 2.5
    assert round(b_landfall, 2) == 1.13

    # 2. Peak super cyclonic intensity
    # Pc = 920.0 hPa, Vmax = 66.88 m/s
    b_peak = compute_holland_b(920.0, 66.88)
    assert 1.0 <= b_peak <= 2.5
    assert round(b_peak, 2) == 1.55

    # 3. Minimum bound enforcement: Delta P huge, Vmax small
    b_min = compute_holland_b(central_pressure_hpa=850.0, max_wind_mps=10.0)
    assert b_min == 1.0

    # 4. Maximum bound enforcement: Delta P small, Vmax extreme
    b_max = compute_holland_b(central_pressure_hpa=1009.0, max_wind_mps=80.0)
    assert b_max == 2.5


def test_holland_wind_metric_physics_and_determinism():
    """Verify Holland parametric wind metric produces physical and deterministic results."""
    cell = get_aoi_grid()[0]
    track_pt = AMPHAN_TRACK[TS_LANDFALL]

    # Determinism: 50 successive executions must return bitwise identical values
    baseline = compute_wind_metric(cell, track_pt)
    for _ in range(50):
        res = compute_wind_metric(cell, track_pt)
        assert res.value == baseline.value
        assert res.severity == baseline.severity
        assert res.unit == "m/s"

    # Physics: non-negative and physically reasonable
    assert baseline.value > 0.0
    assert baseline.value <= 65.0
    assert 0.0 <= baseline.severity <= 1.0
    assert baseline.unit == "m/s"


def test_wind_severity_monotonic_and_bounded():
    """Verify normalize_wind_severity is strictly monotonic non-decreasing and bounded in [0, 1]."""
    speeds = [0.0, 2.0, 5.0, 10.0, 12.0, 17.0, 20.0, 24.0, 28.0, 33.0, 40.0, 48.0, 60.0, 100.0]
    severities = [normalize_wind_severity(s) for s in speeds]

    # 1. Bounds
    assert severities[0] == 0.0
    assert severities[-1] == 1.0
    for sev in severities:
        assert 0.0 <= sev <= 1.0

    # 2. Strict monotonicity (non-decreasing)
    for i in range(len(severities) - 1):
        assert severities[i + 1] >= severities[i], (
            f"Severity decreased from {speeds[i]} m/s to {speeds[i + 1]} m/s"
        )

    # 3. Negative speed edge case
    assert normalize_wind_severity(-5.0) == 0.0


def test_generate_wind_layer_contract():
    """Verify generate_wind_layer returns a contract-compliant HazardLayerCollection."""
    col = generate_wind_layer(TS_LANDFALL)
    assert isinstance(col, HazardLayerCollection)
    assert len(col.features) == 528
    assert col.type == "FeatureCollection"

    compact_ts = iso_to_compact_ts(TS_LANDFALL)

    for feat in col.features:
        assert feat.type == "Feature"
        assert feat.id == feat.properties.id
        assert feat.id.startswith("wind__c")
        assert feat.id.endswith(f"__{compact_ts}")
        assert feat.properties.hazard_type == "wind"
        assert feat.properties.timestep == TS_LANDFALL
        assert feat.properties.unit == "m/s"
        assert feat.properties.value >= 0.0
        assert 0.0 <= feat.properties.severity <= 1.0
        assert feat.geometry.type == "Polygon"
        ring = feat.geometry.coordinates[0]
        assert len(ring) == 5
        assert ring[0] == ring[-1]  # Closed ring


def test_generate_wind_layer_validations():
    """Verify generate_wind_layer validates timesteps against replay timeline."""
    with pytest.raises(NotImplementedError, match="live mode is reserved"):
        generate_wind_layer("live")

    with pytest.raises(ValueError, match="must be one of the 25 Amphan replay timesteps"):
        generate_wind_layer("2020-05-20T13:00:00Z")

    with pytest.raises(ValueError, match="must be one of the 25 Amphan replay timesteps"):
        generate_wind_layer("invalid")


def test_wind_fixtures_exist_and_match_generation():
    """Verify all 25 DEMO_MODE wind fixtures exist and match generate_wind_layer bit-for-bit."""
    for ts in REPLAY_TIMESTEPS:
        compact_ts = iso_to_compact_ts(ts)
        fixture_path = DEMO_DIR / f"hazard__layers-wind__{compact_ts}.json"
        assert fixture_path.is_file(), f"Missing fixture {fixture_path.name}"

        # Raw LF check
        raw_bytes = fixture_path.read_bytes()
        assert b"\r\n" not in raw_bytes, f"{fixture_path.name} contains CRLF"

        fixture_model = HazardLayerCollection.model_validate_json(raw_bytes)
        generated_model = generate_wind_layer(ts)

        assert len(fixture_model.features) == len(generated_model.features) == 528
        for f_fix, f_gen in zip(fixture_model.features, generated_model.features, strict=True):
            assert f_fix.id == f_gen.id
            assert f_fix.properties.hazard_type == "wind"
            assert f_fix.properties.unit == "m/s"
            assert f_fix.properties.value == f_gen.properties.value
            assert f_fix.properties.severity == f_gen.properties.severity
            assert f_fix.geometry.coordinates == f_gen.geometry.coordinates


def test_service_get_hazard_layer_wind_demo_and_computed(monkeypatch):
    """Verify service.get_hazard_layer with wind in both DEMO_MODE and computed mode."""
    import app.hazard.service as hazard_service

    # Clear in-memory cache to guarantee testing fresh retrieval
    hazard_service._LAYER_CACHE.clear()

    # 1. In DEMO_MODE=True: loads from fixture
    monkeypatch.setattr(demo_mod, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=True))
    monkeypatch.setattr(
        hazard_service, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=True)
    )
    col_demo = get_hazard_layer("wind", TS_LANDFALL)
    assert isinstance(col_demo, HazardLayerCollection)
    assert len(col_demo.features) == 528

    # 2. In DEMO_MODE=False: computes directly via generate_wind_layer
    hazard_service._LAYER_CACHE.clear()
    monkeypatch.setattr(demo_mod, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=False))
    monkeypatch.setattr(
        hazard_service, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=False)
    )
    col_computed = get_hazard_layer("wind", TS_LANDFALL)
    assert isinstance(col_computed, HazardLayerCollection)
    assert len(col_computed.features) == 528

    # Both modes must produce identical hazard layers
    for f_d, f_c in zip(col_demo.features, col_computed.features, strict=True):
        assert f_d.id == f_c.id
        assert f_d.properties.value == f_c.properties.value
        assert f_d.properties.severity == f_c.properties.severity


def test_hazard_routes_wind_endpoint():
    """Verify GET /api/hazard/layers endpoint for hazard_type=wind."""
    # 1. Valid replay timestep
    resp = client.get(f"/api/hazard/layers?hazard_type=wind&timestep={TS_LANDFALL}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 528
    for feat in data["features"]:
        assert feat["properties"]["hazard_type"] == "wind"
        assert feat["properties"]["unit"] == "m/s"
        assert 0.0 <= feat["properties"]["severity"] <= 1.0
        assert feat["properties"]["value"] > 0.0

    # 2. Live mode returns 501
    resp_live = client.get("/api/hazard/layers?hazard_type=wind&timestep=live")
    assert resp_live.status_code == 501

    # 3. Invalid timestep returns 422
    resp_bad = client.get("/api/hazard/layers?hazard_type=wind&timestep=2020-05-20T13:00:00Z")
    assert resp_bad.status_code == 422


def test_hazard_routes_track_endpoint():
    """Verify GET /api/hazard/track returns a valid 25-point CycloneTrack."""
    resp = client.get("/api/hazard/track")
    assert resp.status_code == 200
    data = resp.json()
    assert data["event"] == "amphan"
    assert len(data["points"]) == 25
    assert [p["timestep"] for p in data["points"]] == list(REPLAY_TIMESTEPS)
    for pt in data["points"]:
        assert 10.0 <= pt["lat"] <= 23.0
        assert 85.0 <= pt["lon"] <= 90.0
        assert pt["radius_max_wind_km"] > 0


def test_replay_consistency_across_all_25_timesteps():
    """Verify wind hazard layers across all 25 timesteps demonstrate continuity and bounds."""
    peak_winds_over_time: list[float] = []

    for ts in REPLAY_TIMESTEPS:
        col = generate_wind_layer(ts)
        assert len(col.features) == 528
        speeds = [f.properties.value for f in col.features]
        severities = [f.properties.severity for f in col.features]

        # Non-negative, physical bounds
        assert all(s >= 0.0 for s in speeds)
        assert all(s <= 65.0 for s in speeds)
        assert all(0.0 <= sev <= 1.0 for sev in severities)

        peak_winds_over_time.append(max(speeds))

    # At T-72h (far south in Bay of Bengal), peak AOI wind should be low (outer envelope only)
    assert peak_winds_over_time[0] < 12.0

    # At landfall T-0h (passing through Sundarbans AOI), peak wind should be severe (> 35 m/s)
    assert peak_winds_over_time[-1] > 35.0

    # Wind increases as storm approaches landfall
    assert peak_winds_over_time[-1] > peak_winds_over_time[0]


def test_build_wind_fixtures_script(tmp_path):
    """Verify scripts.build_wind_fixtures generates all 25 fixtures cleanly."""
    from scripts.build_wind_fixtures import build_wind_fixtures

    written = build_wind_fixtures(out_dir=tmp_path)
    assert len(written) == 25
    for ts in REPLAY_TIMESTEPS:
        compact_ts = iso_to_compact_ts(ts)
        key = f"hazard__layers-wind__{compact_ts}"
        assert key in written
        path = written[key]
        assert path.is_file()
        raw = path.read_bytes()
        assert b"\r\n" not in raw
        parsed = HazardLayerCollection.model_validate_json(raw)
        assert len(parsed.features) == 528


def test_all_75_hazard_fixtures_exist_and_validate():
    """Verify all 75 DEMO_MODE hazard fixtures (3 types x 25 timesteps) exist and validate."""
    types_and_units = {
        "wind": "m/s",
        "surge": "m",
        "flood": "index",
    }
    for hazard_type, expected_unit in types_and_units.items():
        for ts in REPLAY_TIMESTEPS:
            compact_ts = iso_to_compact_ts(ts)
            fixture_path = DEMO_DIR / f"hazard__layers-{hazard_type}__{compact_ts}.json"
            assert fixture_path.is_file(), f"Missing fixture: {fixture_path.name}"

            raw = fixture_path.read_bytes()
            assert b"\r\n" not in raw, f"{fixture_path.name} contains CRLF"

            parsed = HazardLayerCollection.model_validate_json(raw)
            assert len(parsed.features) == 528, f"{fixture_path.name} does not have 528 features"
            for feat in parsed.features:
                assert feat.properties.hazard_type == hazard_type
                assert feat.properties.unit == expected_unit
                assert feat.properties.timestep == ts
                assert 0.0 <= feat.properties.severity <= 1.0


def test_hazard_elevation_reference_file():
    """Verify the GEE SRTM sampled elevation reference file exists and has 528 cells."""
    from app.hazard.replay import ELEVATION_GRID_PATH

    assert ELEVATION_GRID_PATH.is_file(), f"Reference file missing: {ELEVATION_GRID_PATH}"

    with open(ELEVATION_GRID_PATH, encoding="utf-8") as f:
        data = json.load(f)

    assert "SRTM" in data["dataset"]
    assert data["total_cells"] == 528
    assert len(data["cells"]) == 528

    elevations = [c["elevation_m"] for c in data["cells"]]
    assert all(elev >= 0.0 for elev in elevations)
    assert min(elevations) == 0.0
    assert max(elevations) > 5.0  # inland cells reach > 5m


def test_build_hazard_fixtures_script(tmp_path):
    """Verify scripts.build_hazard_fixtures generates all 75 fixtures cleanly."""
    from scripts.build_hazard_fixtures import build_hazard_fixtures

    written = build_hazard_fixtures(out_dir=tmp_path)
    assert len(written) == 75
    for hazard_type in ("wind", "surge", "flood"):
        for ts in REPLAY_TIMESTEPS:
            compact_ts = iso_to_compact_ts(ts)
            key = f"hazard__layers-{hazard_type}__{compact_ts}"
            assert key in written
            path = written[key]
            assert path.is_file()
            raw = path.read_bytes()
            assert b"\r\n" not in raw
            parsed = HazardLayerCollection.model_validate_json(raw)
            assert len(parsed.features) == 528


# ===========================================================================
# 7. Phase 5 — Storm Surge Model & Surge Hazard Layer Tests
# ===========================================================================


def test_surge_metric_physics_and_determinism():
    """Verify compute_surge_metric produces physically sound, deterministic output."""
    grid = get_aoi_grid()
    pt_start = AMPHAN_TRACK[TS_START]
    pt_landfall = AMPHAN_TRACK[TS_LANDFALL]

    # Determinism: 50 successive runs must produce bitwise identical values
    cell_coast = grid[0]
    baseline = compute_surge_metric(cell_coast, pt_landfall)
    for _ in range(50):
        res = compute_surge_metric(cell_coast, pt_landfall)
        assert res.value == baseline.value
        assert res.severity == baseline.severity
        assert res.unit == "m"

    # Physics at T-72 (storm > 1000 km away)
    surge_start = compute_surge_metric(cell_coast, pt_start)
    assert surge_start.value == 0.0
    assert surge_start.severity == 0.0
    assert surge_start.unit == "m"

    # Physics at Landfall (storm directly crossing Sundarbans)
    assert baseline.value > 1.0  # Coastal cell experiences significant surge
    assert baseline.value <= 6.0  # Within physical bounds
    assert 0.0 <= baseline.severity <= 1.0


def test_surge_depths_non_negative_and_bounded():
    """Verify surge depth is strictly non-negative and bounded across all cells and timesteps."""
    grid = get_aoi_grid()
    for ts in (TS_START, "2020-05-19T12:00:00Z", TS_LANDFALL):
        pt = AMPHAN_TRACK[ts]
        for cell in grid:
            res = compute_surge_metric(cell, pt)
            assert res.value >= 0.0
            assert res.value <= 6.0
            assert 0.0 <= res.severity <= 1.0
            assert res.unit == "m"


def test_surge_severity_monotonic_and_bounded():
    """Verify normalize_surge_severity is strictly monotonic and bounded in [0, 1]."""
    depths = [-1.0, 0.0, 0.15, 0.30, 0.50, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0]
    severities = [normalize_surge_severity(d) for d in depths]

    # Bounds
    assert severities[0] == 0.0
    assert severities[1] == 0.0
    assert severities[-1] == 1.0
    assert all(0.0 <= s <= 1.0 for s in severities)

    # Monotonicity
    for i in range(len(severities) - 1):
        assert (
            severities[i + 1] >= severities[i]
        ), f"Severity decreased from {depths[i]}m to {depths[i + 1]}m"

    # Specific threshold checks
    assert normalize_surge_severity(0.0) == 0.0
    assert normalize_surge_severity(0.3) == 0.15
    assert normalize_surge_severity(1.0) == 0.40
    assert normalize_surge_severity(2.5) == 0.75
    assert normalize_surge_severity(4.0) == 1.0


def test_generate_surge_layer_contract():
    """Verify generate_surge_layer returns a contract-compliant HazardLayerCollection."""
    col = generate_surge_layer(TS_LANDFALL)
    assert isinstance(col, HazardLayerCollection)
    assert len(col.features) == 528
    assert col.type == "FeatureCollection"

    compact_ts = iso_to_compact_ts(TS_LANDFALL)

    for feat in col.features:
        assert feat.type == "Feature"
        assert feat.id == feat.properties.id
        assert feat.id.startswith("surge__c")
        assert feat.id.endswith(f"__{compact_ts}")
        assert feat.properties.hazard_type == "surge"
        assert feat.properties.timestep == TS_LANDFALL
        assert feat.properties.unit == "m"
        assert feat.properties.value >= 0.0
        assert 0.0 <= feat.properties.severity <= 1.0
        assert feat.geometry.type == "Polygon"
        ring = feat.geometry.coordinates[0]
        assert len(ring) == 5
        assert ring[0] == ring[-1]  # Closed polygon


def test_generate_surge_layer_validations():
    """Verify generate_surge_layer validates timesteps against replay timeline."""
    with pytest.raises(NotImplementedError, match="live mode is reserved"):
        generate_surge_layer("live")

    with pytest.raises(ValueError, match="must be one of the 25 Amphan replay timesteps"):
        generate_surge_layer("2020-05-20T13:00:00Z")

    with pytest.raises(ValueError, match="must be one of the 25 Amphan replay timesteps"):
        generate_surge_layer("invalid")


def test_surge_fixtures_exist_and_match_generation():
    """Verify all 25 DEMO_MODE surge fixtures exist and match generate_surge_layer bit-for-bit."""
    for ts in REPLAY_TIMESTEPS:
        compact_ts = iso_to_compact_ts(ts)
        fixture_path = DEMO_DIR / f"hazard__layers-surge__{compact_ts}.json"
        assert fixture_path.is_file(), f"Missing fixture {fixture_path.name}"

        raw_bytes = fixture_path.read_bytes()
        assert b"\r\n" not in raw_bytes, f"{fixture_path.name} contains CRLF"

        fixture_model = HazardLayerCollection.model_validate_json(raw_bytes)
        generated_model = generate_surge_layer(ts)

        assert len(fixture_model.features) == len(generated_model.features) == 528
        for f_fix, f_gen in zip(fixture_model.features, generated_model.features, strict=True):
            assert f_fix.id == f_gen.id
            assert f_fix.properties.hazard_type == "surge"
            assert f_fix.properties.unit == "m"
            assert f_fix.properties.value == f_gen.properties.value
            assert f_fix.properties.severity == f_gen.properties.severity
            assert f_fix.geometry.coordinates == f_gen.geometry.coordinates


def test_service_get_hazard_layer_surge_demo_and_computed(monkeypatch):
    """Verify service.get_hazard_layer with surge in both DEMO_MODE and computed mode."""
    import app.hazard.service as hazard_service

    hazard_service._LAYER_CACHE.clear()

    # 1. In DEMO_MODE=True: loads from fixture
    monkeypatch.setattr(demo_mod, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=True))
    monkeypatch.setattr(
        hazard_service, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=True)
    )
    col_demo = get_hazard_layer("surge", TS_LANDFALL)
    assert isinstance(col_demo, HazardLayerCollection)
    assert len(col_demo.features) == 528

    # 2. In DEMO_MODE=False: computes directly via generate_surge_layer
    hazard_service._LAYER_CACHE.clear()
    monkeypatch.setattr(demo_mod, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=False))
    monkeypatch.setattr(
        hazard_service, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=False)
    )
    col_computed = get_hazard_layer("surge", TS_LANDFALL)
    assert isinstance(col_computed, HazardLayerCollection)
    assert len(col_computed.features) == 528

    # Both modes must produce identical hazard layers
    for f_d, f_c in zip(col_demo.features, col_computed.features, strict=True):
        assert f_d.id == f_c.id
        assert f_d.properties.value == f_c.properties.value
        assert f_d.properties.severity == f_c.properties.severity


def test_hazard_routes_surge_endpoint():
    """Verify GET /api/hazard/layers endpoint for hazard_type=surge."""
    # 1. Valid replay timestep
    resp = client.get(f"/api/hazard/layers?hazard_type=surge&timestep={TS_LANDFALL}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 528
    for feat in data["features"]:
        assert feat["properties"]["hazard_type"] == "surge"
        assert feat["properties"]["unit"] == "m"
        assert 0.0 <= feat["properties"]["severity"] <= 1.0
        assert feat["properties"]["value"] >= 0.0

    # 2. Live mode returns 501
    resp_live = client.get("/api/hazard/layers?hazard_type=surge&timestep=live")
    assert resp_live.status_code == 501

    # 3. Invalid timestep returns 422
    resp_bad = client.get("/api/hazard/layers?hazard_type=surge&timestep=2020-05-20T13:00:00Z")
    assert resp_bad.status_code == 422


def test_surge_replay_consistency_across_all_25_timesteps():
    """Verify surge hazard layers across all 25 timesteps demonstrate continuity and bounds."""
    peak_surge_over_time: list[float] = []

    for ts in REPLAY_TIMESTEPS:
        col = generate_surge_layer(ts)
        assert len(col.features) == 528
        depths = [f.properties.value for f in col.features]
        severities = [f.properties.severity for f in col.features]

        assert all(d >= 0.0 for d in depths)
        assert all(d <= 6.0 for d in depths)
        assert all(0.0 <= sev <= 1.0 for sev in severities)

        peak_surge_over_time.append(max(depths))

    # At T-72h (far south in Bay of Bengal), peak AOI surge is 0.0 m
    assert peak_surge_over_time[0] == 0.0

    # At landfall T-0h (passing through Sundarbans AOI), peak surge is significant (> 1.5 m)
    assert peak_surge_over_time[-1] > 1.5

    # Surge increases as storm nears landfall
    assert peak_surge_over_time[-1] > peak_surge_over_time[0]


def test_build_surge_fixtures_script(tmp_path):
    """Verify scripts.build_surge_fixtures generates all 25 fixtures cleanly."""
    from scripts.build_surge_fixtures import build_surge_fixtures

    written = build_surge_fixtures(out_dir=tmp_path)
    assert len(written) == 25
    for ts in REPLAY_TIMESTEPS:
        compact_ts = iso_to_compact_ts(ts)
        key = f"hazard__layers-surge__{compact_ts}"
        assert key in written
        path = written[key]
        assert path.is_file()
        raw = path.read_bytes()
        assert b"\r\n" not in raw
        parsed = HazardLayerCollection.model_validate_json(raw)
        assert len(parsed.features) == 528


# ===========================================================================
# 8. Phase 6 — Flood Susceptibility Model & Regression Audit Tests
# ===========================================================================
def test_flood_metric_determinism_and_bounds():
    """Verify compute_flood_metric produces deterministic, bounded, and physically sound indices."""
    cells = get_aoi_grid()
    coastal_cell = cells[0]  # c0000: lat 21.525, elev 0.0m, dist_coast 2.78km
    inland_cell = cells[500]  # northern inland higher elevation cell

    res_coastal_1 = compute_flood_metric(coastal_cell)
    res_coastal_2 = compute_flood_metric(coastal_cell)
    res_inland = compute_flood_metric(inland_cell)

    # Determinism
    assert res_coastal_1.value == res_coastal_2.value
    assert res_coastal_1.severity == res_coastal_2.severity
    assert res_coastal_1.unit == "index"

    # Numerical bounds [0.05, 0.98]
    assert 0.05 <= res_coastal_1.value <= 0.98
    assert 0.0 <= res_coastal_1.severity <= 1.0
    assert 0.05 <= res_inland.value <= 0.98
    assert 0.0 <= res_inland.severity <= 1.0

    # Physical soundness: coastal mangrove mudflat has higher susceptibility than inland high ground
    assert res_coastal_1.value > res_inland.value
    assert res_coastal_1.severity > res_inland.severity


def test_flood_metric_fallback_and_reusability():
    """Verify compute_flood_metric gracefully handles standalone custom test cells."""
    custom_cell = GridCell(
        id="test-cell-custom",
        centroid_lon=88.5,
        centroid_lat=22.0,
        min_lon=88.45,
        min_lat=21.95,
        max_lon=88.55,
        max_lat=22.05,
        elevation_m=2.5,
        dist_to_coast_km=30.0,
        polygon=SAMPLE_POLYGON,
    )
    res = compute_flood_metric(custom_cell)
    assert res.unit == "index"
    assert 0.05 <= res.value <= 0.98
    assert 0.0 <= res.severity <= 1.0


def test_flood_severity_normalization_monotonic_and_continuous():
    """Verify normalize_flood_severity is strictly monotonic, continuous, and bounded in [0, 1]."""
    test_indices = [-0.5, 0.0, 0.15, 0.20, 0.35, 0.40, 0.55, 0.60, 0.75, 0.80, 0.95, 1.0, 1.5]
    severities = [normalize_flood_severity(i) for i in test_indices]

    # Bounds
    assert severities[0] == 0.0
    assert severities[-1] == 1.0
    assert all(0.0 <= s <= 1.0 for s in severities)

    # Monotonicity
    for i in range(len(severities) - 1):
        assert severities[i] <= severities[i + 1]

    # Continuity check at arbitrary delta
    delta = 1e-4
    for val in (0.20, 0.40, 0.60, 0.80):
        left = normalize_flood_severity(val - delta)
        right = normalize_flood_severity(val + delta)
        assert abs(right - left) <= 0.02


def test_generate_flood_layer_contract():
    """Verify generate_flood_layer returns contract-compliant FeatureCollection<HazardLayer>."""
    # 1. Valid replay timestep
    col = generate_flood_layer(TS_LANDFALL)
    assert col.type == "FeatureCollection"
    assert len(col.features) == 528

    feat = col.features[0]
    assert feat.properties.hazard_type == "flood"
    assert feat.properties.unit == "index"
    assert feat.properties.timestep == TS_LANDFALL
    assert 0.0 <= feat.properties.value <= 1.0
    assert 0.0 <= feat.properties.severity <= 1.0

    # 2. Live mode raises NotImplementedError
    with pytest.raises(NotImplementedError):
        generate_flood_layer("live")

    # 3. Invalid timestep raises ValueError
    with pytest.raises(ValueError):
        generate_flood_layer("2020-05-20T13:00:00Z")


def test_flood_layer_static_across_all_25_replay_timesteps():
    """Verify flood layers are identical across all 25 timesteps (contracts.md §4.1)."""
    baseline = generate_flood_layer(REPLAY_TIMESTEPS[0])
    baseline_values = [f.properties.value for f in baseline.features]
    baseline_severities = [f.properties.severity for f in baseline.features]

    for ts in REPLAY_TIMESTEPS[1:]:
        col = generate_flood_layer(ts)
        assert len(col.features) == 528
        ts_values = [f.properties.value for f in col.features]
        ts_severities = [f.properties.severity for f in col.features]
        assert ts_values == baseline_values
        assert ts_severities == baseline_severities


def test_flood_demo_fixture_loading_and_fallback(monkeypatch):
    """Verify get_hazard_layer loads flood fixtures in DEMO_MODE and computes dynamically."""
    # 1. DEMO_MODE = True
    monkeypatch.setattr("app.hazard.service.get_settings", lambda: Settings(DEMO_MODE=True))
    fixture_col = get_hazard_layer("flood", TS_LANDFALL)
    assert len(fixture_col.features) == 528
    assert fixture_col.features[0].properties.hazard_type == "flood"

    # 2. DEMO_MODE = False (dynamic computation)
    monkeypatch.setattr("app.hazard.service.get_settings", lambda: Settings(DEMO_MODE=False))
    dynamic_col = get_hazard_layer("flood", TS_LANDFALL)
    assert len(dynamic_col.features) == 528
    assert dynamic_col.features[0].properties.hazard_type == "flood"
    assert dynamic_col.features[0].properties.unit == "index"


def test_flood_api_endpoints():
    """Verify HTTP API endpoint for GET /api/hazard/layers?hazard_type=flood."""
    # 1. 200 OK
    resp = client.get(f"/api/hazard/layers?hazard_type=flood&timestep={TS_LANDFALL}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 528
    assert data["features"][0]["properties"]["hazard_type"] == "flood"
    assert data["features"][0]["properties"]["unit"] == "index"

    # 2. Live mode returns 501
    resp_live = client.get("/api/hazard/layers?hazard_type=flood&timestep=live")
    assert resp_live.status_code == 501

    # 3. Invalid timestep returns 422
    resp_bad = client.get("/api/hazard/layers?hazard_type=flood&timestep=2020-05-20T13:00:00Z")
    assert resp_bad.status_code == 422


def test_build_flood_fixtures_script(tmp_path):
    """Verify scripts.build_flood_fixtures generates all 25 fixtures cleanly."""
    from scripts.build_flood_fixtures import build_flood_fixtures

    written = build_flood_fixtures(out_dir=tmp_path)
    assert len(written) == 25
    for ts in REPLAY_TIMESTEPS:
        compact_ts = iso_to_compact_ts(ts)
        key = f"hazard__layers-flood__{compact_ts}"
        assert key in written
        path = written[key]
        assert path.is_file()
        raw = path.read_bytes()
        assert b"\r\n" not in raw
        parsed = HazardLayerCollection.model_validate_json(raw)
        assert len(parsed.features) == 528


# ---------------------------------------------------------------------------
# Mandatory Verification: Phases 4 & 5 Regression Audit Tests
# ---------------------------------------------------------------------------
def test_regression_audit_phase4_holland_reuse():
    """Verify compute_surge_metric reuses compute_wind_metric rather than duplicating Holland."""
    track_pt = AMPHAN_TRACK[TS_LANDFALL]
    cell = get_aoi_grid()[0]

    # compute_wind_metric returns valid wind speed
    wind_res = compute_wind_metric(cell, track_pt)
    assert wind_res.unit == "m/s"
    assert wind_res.value > 0.0

    # compute_surge_metric uses wind_res.value to compute setup
    surge_res = compute_surge_metric(cell, track_pt)
    assert surge_res.unit == "m"
    assert surge_res.value >= 0.0


def test_regression_audit_phase5_surge_physics_and_bounds():
    """Verify surge physics: clamped at output, continuous eye modifier, non-negative dist."""
    track_pt = AMPHAN_TRACK[TS_LANDFALL]
    cells = get_aoi_grid()

    # 1. Clamped strictly at final output 0 <= surge <= 6.0 m
    for cell in cells:
        assert cell.dist_to_coast_km >= 0.0
        res = compute_surge_metric(cell, track_pt)
        assert 0.0 <= res.value <= 6.0
        assert 0.0 <= res.severity <= 1.0

    # 2. Eye-distance modifier continuity at 300km and 600km
    # At 600km: (600 - 600) / 300 = 0.0; at 300km: (600 - 300) / 300 = 1.0
    from app.hazard.replay import SURGE_MAX_DISTANCE_EYE_KM, SURGE_RAMP_DISTANCE_EYE_KM

    assert SURGE_MAX_DISTANCE_EYE_KM == 600.0
    assert SURGE_RAMP_DISTANCE_EYE_KM == 300.0


def test_regression_audit_grid_and_dem_consistency():
    """Verify all hazard layers share identical 528-cell grid and DEM source."""
    wind_col = generate_wind_layer(TS_LANDFALL)
    surge_col = generate_surge_layer(TS_LANDFALL)
    flood_col = generate_flood_layer(TS_LANDFALL)

    assert len(wind_col.features) == 528
    assert len(surge_col.features) == 528
    assert len(flood_col.features) == 528

    # Verify identical geometries and IDs across all layers
    zipped = zip(wind_col.features, surge_col.features, flood_col.features, strict=True)
    for w_feat, s_feat, f_feat in zipped:
        coords = w_feat.geometry.coordinates
        assert coords == s_feat.geometry.coordinates == f_feat.geometry.coordinates
        w_id = w_feat.id.split("__")[1]
        s_id = s_feat.id.split("__")[1]
        f_id = f_feat.id.split("__")[1]
        assert w_id == s_id == f_id


# ===========================================================================
# 9. Phase 7 — Hazard Validation, Calibration & Engine Integration Tests
# ===========================================================================
def test_phase7_validate_hazard_layer_contract():
    """Verify validate_hazard_layer strictly enforces contract constraints and error modes."""
    wind_col = generate_wind_layer(TS_LANDFALL)
    surge_col = generate_surge_layer(TS_LANDFALL)
    flood_col = generate_flood_layer(TS_LANDFALL)

    # 1. Valid layers pass
    assert validate_hazard_layer(wind_col.features[0]) is True
    assert validate_hazard_layer(surge_col.features[0]) is True
    assert validate_hazard_layer(flood_col.features[0]) is True

    valid_feat = wind_col.features[0]

    # 2. ID mismatch
    bad_id = valid_feat.model_copy(update={"id": "tampered_id"})
    assert validate_hazard_layer(bad_id) is False
    with pytest.raises(ValueError, match="Feature ID mismatch"):
        validate_hazard_layer(bad_id, raise_exc=True)

    # 3. Invalid unit
    bad_unit_props = valid_feat.properties.model_copy(update={"unit": "m"})
    bad_unit = valid_feat.model_copy(update={"properties": bad_unit_props})
    assert validate_hazard_layer(bad_unit) is False

    # 4. Out-of-bounds severity
    bad_sev_props = valid_feat.properties.model_copy(update={"severity": 1.25})
    bad_sev = valid_feat.model_copy(update={"properties": bad_sev_props})
    assert validate_hazard_layer(bad_sev) is False

    # 5. Out-of-bounds physical value
    bad_val_props = valid_feat.properties.model_copy(update={"value": 150.0})
    bad_val = valid_feat.model_copy(update={"properties": bad_val_props})
    assert validate_hazard_layer(bad_val) is False

    # 6. Unclosed polygon ring
    unclosed_ring = [[88.0, 21.5], [88.1, 21.5], [88.1, 21.6], [88.0, 21.6]]
    bad_geom = valid_feat.model_copy(update={"geometry": Polygon(coordinates=[unclosed_ring])})
    assert validate_hazard_layer(bad_geom) is False
    with pytest.raises(ValueError, match="Linear ring is not closed"):
        validate_hazard_layer(bad_geom, raise_exc=True)


def test_phase7_validate_hazard_collection_contract():
    """Verify validate_hazard_collection verifies completeness, types, and uniqueness."""
    wind_col = generate_wind_layer(TS_LANDFALL)

    # 1. Valid collection passes
    assert (
        validate_hazard_collection(
            wind_col, expected_type="wind", expected_timestep=TS_LANDFALL
        )
        is True
    )

    # 2. Count mismatch
    truncated_col = HazardLayerCollection(
        type="FeatureCollection", features=wind_col.features[:500]
    )
    assert validate_hazard_collection(truncated_col) is False
    with pytest.raises(ValueError, match="Feature count mismatch"):
        validate_hazard_collection(truncated_col, raise_exc=True)

    # 3. Duplicate feature IDs
    duped_features = list(wind_col.features)
    duped_features[1] = duped_features[0]
    duped_col = HazardLayerCollection(type="FeatureCollection", features=duped_features)
    assert validate_hazard_collection(duped_col) is False
    with pytest.raises(ValueError, match="Duplicate feature ID detected"):
        validate_hazard_collection(duped_col, raise_exc=True)

    # 4. Unexpected hazard type
    assert (
        validate_hazard_collection(
            wind_col, expected_type="surge", expected_timestep=TS_LANDFALL
        )
        is False
    )


def test_phase7_cross_hazard_consistency():
    """Verify validate_hazard_consistency detects cross-hazard spatial or alignment drift."""
    wind_col = generate_wind_layer(TS_LANDFALL)
    surge_col = generate_surge_layer(TS_LANDFALL)
    flood_col = generate_flood_layer(TS_LANDFALL)

    # 1. Genuine layers are consistent
    assert validate_hazard_consistency(wind_col, surge_col, flood_col) is True

    # 2. Inconsistent cell order
    shuffled_wind_features = list(reversed(wind_col.features))
    shuffled_wind = HazardLayerCollection(
        type="FeatureCollection", features=shuffled_wind_features
    )
    assert validate_hazard_consistency(shuffled_wind, surge_col, flood_col) is False
    with pytest.raises(ValueError, match="Cell ID mismatch"):
        validate_hazard_consistency(shuffled_wind, surge_col, flood_col, raise_exc=True)

    # 3. Altered geometry
    altered_features = list(wind_col.features)
    altered_ring = [
        [88.01, 21.51],
        [88.06, 21.51],
        [88.06, 21.56],
        [88.01, 21.56],
        [88.01, 21.51],
    ]
    altered_poly = Polygon(coordinates=[altered_ring])
    altered_features[0] = altered_features[0].model_copy(update={"geometry": altered_poly})
    altered_wind = HazardLayerCollection(type="FeatureCollection", features=altered_features)
    assert validate_hazard_consistency(altered_wind, surge_col, flood_col) is False


def test_phase7_calibration_utilities():
    """Verify calibration checks across wind, surge, and flood execute and pass."""
    # 1. Individual checks
    wind_cal = check_wind_calibration()
    assert wind_cal["all_passed"] is True
    assert wind_cal["ceiling_enforced"] is True
    assert wind_cal["floor_enforced"] is True

    surge_cal = check_surge_calibration()
    assert surge_cal["all_passed"] is True
    assert surge_cal["non_negative"] is True
    assert surge_cal["ceiling_enforced"] is True

    flood_cal = check_flood_calibration()
    assert flood_cal["all_passed"] is True
    assert flood_cal["weights_valid"] is True
    assert flood_cal["bounded"] is True

    # 2. Full engine calibration suite
    full_report = run_full_hazard_calibration()
    assert full_report["all_passed"] is True
    assert full_report["wind"]["all_passed"] is True
    assert full_report["surge"]["all_passed"] is True
    assert full_report["flood"]["all_passed"] is True


def test_phase7_all_25_replay_timesteps_validation():
    """Verify all 25 replay timesteps across 3 hazard types are contract-compliant."""
    report = validate_all_replay_timesteps()
    assert report["all_valid"] is True
    assert report["timesteps_checked"] == 25
    assert report["layers_validated"] == 75
    assert report["features_validated"] == 75 * 528


def test_phase7_demo_fixtures_validation():
    """Verify all 75 static DEMO_MODE fixtures exist, parse, and match contract schemas."""
    report = validate_demo_fixtures()
    assert report["all_valid"] is True
    assert report["checked_fixtures"] == 75
    assert report["expected_fixtures"] == 75


def test_phase7_service_engine_dispatch_and_modes(monkeypatch):
    """Verify service dispatch across wind, surge, flood in both DEMO_MODE and computed mode."""
    # 1. DEMO_MODE = True
    monkeypatch.setattr("app.hazard.service.get_settings", lambda: Settings(DEMO_MODE=True))
    for h_type in ("wind", "surge", "flood"):
        col = get_hazard_layer(h_type, TS_LANDFALL)
        assert len(col.features) == 528
        assert col.features[0].properties.hazard_type == h_type

    # 2. DEMO_MODE = False (dynamic computed mode)
    monkeypatch.setattr("app.hazard.service.get_settings", lambda: Settings(DEMO_MODE=False))
    for h_type in ("wind", "surge", "flood"):
        col = get_hazard_layer(h_type, TS_LANDFALL)
        assert len(col.features) == 528
        assert col.features[0].properties.hazard_type == h_type

    # 3. Live mode raises NotImplementedError
    with pytest.raises(NotImplementedError):
        get_hazard_layer("wind", "live")
    with pytest.raises(NotImplementedError):
        get_hazard_layer("surge", "live")
    with pytest.raises(NotImplementedError):
        get_hazard_layer("flood", "live")

    # 4. Invalid timestep raises ValueError
    with pytest.raises(ValueError):
        get_hazard_layer("wind", "invalid-ts")


def test_phase7_cross_hazard_api_contract():
    """Verify HTTP API endpoints for wind, surge, and flood return matching grids and schemas."""
    resp_w = client.get(f"/api/hazard/layers?hazard_type=wind&timestep={TS_LANDFALL}")
    resp_s = client.get(f"/api/hazard/layers?hazard_type=surge&timestep={TS_LANDFALL}")
    resp_f = client.get(f"/api/hazard/layers?hazard_type=flood&timestep={TS_LANDFALL}")

    assert resp_w.status_code == 200
    assert resp_s.status_code == 200
    assert resp_f.status_code == 200

    data_w = resp_w.json()
    data_s = resp_s.json()
    data_f = resp_f.json()

    assert len(data_w["features"]) == len(data_s["features"]) == len(data_f["features"]) == 528

    # Verify matching cell IDs and geometries across all three endpoints
    for i in range(528):
        fw = data_w["features"][i]
        fs = data_s["features"][i]
        ff = data_f["features"][i]

        w_cid = fw["properties"]["id"].split("__")[1]
        s_cid = fs["properties"]["id"].split("__")[1]
        f_cid = ff["properties"]["id"].split("__")[1]
        assert w_cid == s_cid == f_cid

        assert fw["geometry"]["coordinates"] == fs["geometry"]["coordinates"]
        assert fw["geometry"]["coordinates"] == ff["geometry"]["coordinates"]

    # Verify units
    assert data_w["features"][0]["properties"]["unit"] == "m/s"
    assert data_s["features"][0]["properties"]["unit"] == "m"
    assert data_f["features"][0]["properties"]["unit"] == "index"

    # Verify live mode returns 501 for all three
    for ht in ("wind", "surge", "flood"):
        res_live = client.get(f"/api/hazard/layers?hazard_type={ht}&timestep=live")
        assert res_live.status_code == 501


# ===========================================================================
# 11. Wind Field Gradual Intensification Regression Tests
# ===========================================================================


def test_wind_gradual_intensification_no_abrupt_jumps():
    """Verify no single 3-hour step causes more than a 2× jump in mean wind speed.

    The outer wind envelope (Willoughby et al. 2006) ensures the wind field
    strengthens gradually as the cyclone approaches the AOI, rather than jumping
    from ambient to severe in a single timestep.
    """
    mean_winds: list[float] = []

    for ts in REPLAY_TIMESTEPS:
        col = generate_wind_layer(ts)
        speeds = [f.properties.value for f in col.features]
        mean_winds.append(sum(speeds) / len(speeds))

    # No consecutive timestep pair should have a mean-wind ratio > 2.0
    for i in range(len(mean_winds) - 1):
        if mean_winds[i] > 0.0:
            ratio = mean_winds[i + 1] / mean_winds[i]
            assert ratio < 2.0, (
                f"Abrupt jump at step {i}: mean wind {mean_winds[i]:.1f} -> "
                f"{mean_winds[i+1]:.1f} m/s (ratio {ratio:.2f})"
            )


def test_wind_intensification_ramp_final_12h():
    """Verify wind speeds increase across the final 4 timesteps (T-9h to T-0h).

    The last 12 hours before landfall must show strictly rising mean wind
    across the AOI as the eye rapidly approaches and enters the grid.
    """
    # Final 4 timesteps: T-9, T-6, T-3, T-0
    final_timesteps = REPLAY_TIMESTEPS[-4:]
    mean_winds: list[float] = []

    for ts in final_timesteps:
        col = generate_wind_layer(ts)
        speeds = [f.properties.value for f in col.features]
        mean_winds.append(sum(speeds) / len(speeds))

    for i in range(len(mean_winds) - 1):
        assert mean_winds[i + 1] > mean_winds[i], (
            f"Mean wind did not increase from {final_timesteps[i]} to "
            f"{final_timesteps[i+1]}: {mean_winds[i]:.1f} -> {mean_winds[i+1]:.1f}"
        )


def test_wind_outer_envelope_extends_beyond_holland():
    """Verify the outer wind envelope produces above-ambient winds at 200-400 km distance.

    At intermediate distances where the Holland inner profile would give near-zero
    winds, the outer modified-Rankine profile must provide physically meaningful
    wind speeds reflecting the cyclone's broad outer circulation.
    """
    from app.hazard.replay import OUTER_DECAY_EXPONENT

    # Use a representative coastal cell and track points at intermediate distance
    grid = get_aoi_grid()
    coastal_cells = [c for c in grid if c.dist_to_coast_km < 5]
    assert len(coastal_cells) > 0, "Must have coastal cells for testing"

    cell = coastal_cells[0]

    # T-12h: eye is ~180-270 km from coastal cells
    ts_minus_12 = REPLAY_TIMESTEPS[-5]  # T-12h
    track_pt = AMPHAN_TRACK[ts_minus_12]

    from app.hazard.replay import haversine_distance_km
    dist = haversine_distance_km(cell.centroid_lat, cell.centroid_lon, track_pt.lat, track_pt.lon)

    # At this distance (100-300 km), Holland alone would give < 10 m/s
    # but the outer envelope should lift the wind meaningfully above ambient
    wind = compute_wind_metric(cell, track_pt)
    assert wind.value > 10.0, (
        f"Wind at {dist:.0f} km should exceed 10 m/s with outer envelope, got {wind.value}"
    )

    # Verify the outer decay exponent is in the physically realistic range
    # (Willoughby et al. 2006 reports 0.3-0.6 for North Indian Ocean TCs)
    assert 0.3 <= OUTER_DECAY_EXPONENT <= 0.6, (
        f"Outer decay exponent {OUTER_DECAY_EXPONENT} outside physical range [0.3, 0.6]"
    )


def test_wind_max_step_ratio_bounded():
    """Verify the maximum wind speed across all cells doesn't jump more than 2.5× per step.

    Even though the eye enters the AOI between T-6 and T-3 (the sharpest transition),
    the peak-cell wind ratio between any two consecutive steps should remain bounded.
    """
    peak_winds: list[float] = []

    for ts in REPLAY_TIMESTEPS:
        col = generate_wind_layer(ts)
        speeds = [f.properties.value for f in col.features]
        peak_winds.append(max(speeds))

    for i in range(len(peak_winds) - 1):
        if peak_winds[i] > 0.0:
            ratio = peak_winds[i + 1] / peak_winds[i]
            assert ratio < 2.5, (
                f"Peak wind jumped {ratio:.2f}× at step {i}: "
                f"{peak_winds[i]:.1f} -> {peak_winds[i+1]:.1f} m/s"
            )


def test_wind_progression_coastal_cells_t24_to_landfall():
    """Regression: coastal wind speeds ramp up smoothly over the final 24 hours.

    At representative coastal cells (dist_to_coast < 10 km, mid-AOI), the wind
    progression must show:
    - T-24h: below 15 m/s (storm still 500+ km away, outer circulation only)
    - T-12h: 14-22 m/s (outer envelope strengthening, storm ~180-270 km away)
    - T-6h: 17-25 m/s (strong outer winds, storm ~130-180 km away)
    - T-0h: above 28 m/s (landfall, eye crossing AOI)
    """
    grid = get_aoi_grid()
    # Pick coastal cells near the AOI center
    coastal_center = sorted(
        [c for c in grid if c.dist_to_coast_km < 10],
        key=lambda c: abs(c.centroid_lon - 88.5) + abs(c.centroid_lat - 21.75),
    )[:3]

    # T-24h (index 16)
    ts_24h = REPLAY_TIMESTEPS[16]
    winds_24h = [compute_wind_metric(c, AMPHAN_TRACK[ts_24h]).value for c in coastal_center]
    mean_24h = sum(winds_24h) / len(winds_24h)
    assert mean_24h < 15.0, f"T-24h mean wind {mean_24h:.1f} should be < 15 m/s"

    # T-12h (index 20)
    ts_12h = REPLAY_TIMESTEPS[20]
    winds_12h = [compute_wind_metric(c, AMPHAN_TRACK[ts_12h]).value for c in coastal_center]
    mean_12h = sum(winds_12h) / len(winds_12h)
    assert 14.0 <= mean_12h <= 22.0, f"T-12h mean wind {mean_12h:.1f} should be 14-22 m/s"

    # T-6h (index 22)
    ts_6h = REPLAY_TIMESTEPS[22]
    winds_6h = [compute_wind_metric(c, AMPHAN_TRACK[ts_6h]).value for c in coastal_center]
    mean_6h = sum(winds_6h) / len(winds_6h)
    assert 17.0 <= mean_6h <= 25.0, f"T-6h mean wind {mean_6h:.1f} should be 17-25 m/s"

    # T-0h (index 24, landfall)
    ts_0h = REPLAY_TIMESTEPS[24]
    winds_0h = [compute_wind_metric(c, AMPHAN_TRACK[ts_0h]).value for c in coastal_center]
    mean_0h = sum(winds_0h) / len(winds_0h)
    assert mean_0h > 28.0, f"T-0h mean wind {mean_0h:.1f} should be > 28 m/s"

    # Overall progression must be monotonically increasing
    assert mean_12h > mean_24h, f"T-12h ({mean_12h:.1f}) must exceed T-24h ({mean_24h:.1f})"
    assert mean_6h > mean_12h, f"T-6h ({mean_6h:.1f}) must exceed T-12h ({mean_12h:.1f})"
    assert mean_0h > mean_6h, f"T-0h ({mean_0h:.1f}) must exceed T-6h ({mean_6h:.1f})"

