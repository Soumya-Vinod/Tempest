"""Unit and contract compliance tests for the hazard module (Dev A)."""

import json
from datetime import UTC

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.hazard.models import (
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
    compute_surge_metric,
    compute_wind_metric,
    create_replay_timeline,
    get_aoi_grid,
    iso_to_compact_ts,
    validate_timestep,
)
from app.hazard.service import get_hazard_layer, get_replay_timeline
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
        datetime.strptime(ts, dt_format).replace(tzinfo=UTC)
        for ts in REPLAY_TIMELINE_TIMESTEPS
    ]

    for i in range(len(parsed_dates) - 1):
        delta = parsed_dates[i + 1] - parsed_dates[i]
        assert delta == timedelta(hours=3), f"Interval between step {i} and {i+1} is not 3 hours"

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

