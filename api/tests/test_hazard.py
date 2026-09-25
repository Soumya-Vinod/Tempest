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
    compute_flood_susceptibility_metric,
    compute_holland_b,
    compute_surge_metric,
    compute_wind_metric,
    create_replay_timeline,
    generate_wind_layer,
    get_aoi_grid,
    iso_to_compact_ts,
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
    grid = get_aoi_grid(rows=8, cols=8)
    assert len(grid) == 64
    for cell in grid:
        assert isinstance(cell, GridCell)
        assert cell.id.startswith("c")
        assert 88.0 <= cell.min_lon < cell.max_lon <= 89.1
        assert 21.5 <= cell.min_lat < cell.max_lat <= 22.7
        assert cell.elevation_m >= 0.5
        assert cell.dist_to_coast_km >= 0.0
        coords = cell.polygon.coordinates[0]
        assert len(coords) == 5
        assert coords[0] == coords[-1]  # Closed polygon ring


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
    assert len(col.features) == 64
    for feat in col.features:
        assert feat.id == feat.properties.id
        assert feat.properties.hazard_type == hazard_type
        assert feat.properties.timestep == TS_LANDFALL
        assert 0.0 <= feat.properties.severity <= 1.0


def test_flood_layer_static_across_timesteps():
    f_start = get_hazard_layer("flood", TS_START)
    f_landfall = get_hazard_layer("flood", TS_LANDFALL)
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
    assert len(features) == 64

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
        assert (
            severities[i + 1] >= severities[i]
        ), f"Severity decreased from {speeds[i]} m/s to {speeds[i + 1]} m/s"

    # 3. Negative speed edge case
    assert normalize_wind_severity(-5.0) == 0.0


def test_generate_wind_layer_contract():
    """Verify generate_wind_layer returns a contract-compliant HazardLayerCollection."""
    col = generate_wind_layer(TS_LANDFALL)
    assert isinstance(col, HazardLayerCollection)
    assert len(col.features) == 64
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

        assert len(fixture_model.features) == len(generated_model.features) == 64
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
    assert len(col_demo.features) == 64

    # 2. In DEMO_MODE=False: computes directly via generate_wind_layer
    hazard_service._LAYER_CACHE.clear()
    monkeypatch.setattr(demo_mod, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=False))
    monkeypatch.setattr(
        hazard_service, "get_settings", lambda: Settings(_env_file=None, DEMO_MODE=False)
    )
    col_computed = get_hazard_layer("wind", TS_LANDFALL)
    assert isinstance(col_computed, HazardLayerCollection)
    assert len(col_computed.features) == 64

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
    assert len(data["features"]) == 64
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


def test_replay_consistency_across_all_25_timesteps():
    """Verify wind hazard layers across all 25 timesteps demonstrate continuity and bounds."""
    peak_winds_over_time: list[float] = []

    for ts in REPLAY_TIMESTEPS:
        col = generate_wind_layer(ts)
        assert len(col.features) == 64
        speeds = [f.properties.value for f in col.features]
        severities = [f.properties.severity for f in col.features]

        # Non-negative, physical bounds
        assert all(s >= 0.0 for s in speeds)
        assert all(s <= 65.0 for s in speeds)
        assert all(0.0 <= sev <= 1.0 for sev in severities)

        peak_winds_over_time.append(max(speeds))

    # At T-72h (far south in Bay of Bengal), peak AOI wind should be ambient (~6 m/s)
    assert peak_winds_over_time[0] == 6.0

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
        assert len(parsed.features) == 64

