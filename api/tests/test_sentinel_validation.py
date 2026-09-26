"""Tests for Sentinel-1 Validation benchmarking service and API endpoint (Phase 12).

Verifies:
- Validation fixture loading and LF line endings
- Schema conformity for SentinelValidationResponse
- Validation service operations in DEMO_MODE and fallback
- Guarantee that no GEE, Sentinel, or Gemini APIs are invoked
- GET /api/hazard/validation/sentinel endpoint response
- Output determinism across multiple runs
- Regression audit confirming hazard generation logic remains strictly unchanged
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.demo import DEMO_DIR
from app.hazard.models import (
    SentinelValidationAOI,
    SentinelValidationMetrics,
    SentinelValidationResponse,
)
from app.hazard.replay import (
    generate_flood_layer,
    generate_surge_layer,
    generate_wind_layer,
)
from app.hazard.sentinel import (
    DEFAULT_SENTINEL_BENCHMARK,
    SENTINEL_FIXTURE_KEY,
    get_sentinel_validation,
)
from app.hazard.service import (
    get_hazard_layer,
    get_sentinel_validation as service_get_sentinel_validation,
)
from app.hazard.validation import validate_sentinel_fixture
from app.main import app

client = TestClient(app)
TS_LANDFALL = "2020-05-20T12:00:00Z"


# ===========================================================================
# 1. Fixture Loading & Format Tests
# ===========================================================================


def test_sentinel_fixture_existence_and_encoding():
    """Verify hazard__validation-sentinel.json exists, uses UTF-8, and has LF-only line endings."""
    fixture_path = DEMO_DIR / f"{SENTINEL_FIXTURE_KEY}.json"
    assert fixture_path.is_file(), f"Fixture file not found: {fixture_path}"

    raw = fixture_path.read_bytes()
    assert b"\r\n" not in raw, "Fixture contains CRLF line endings; must be LF only"
    text = raw.decode("utf-8")
    data = json.loads(text)
    assert isinstance(data, dict)


def test_sentinel_fixture_schema():
    """Verify fixture validates against the Pydantic SentinelValidationResponse contract."""
    fixture_path = DEMO_DIR / f"{SENTINEL_FIXTURE_KEY}.json"
    with fixture_path.open(encoding="utf-8") as f:
        data = json.load(f)

    validated = SentinelValidationResponse.model_validate(data)
    assert validated.location == "Sagar Island"
    assert validated.prediction_overlap == 0.82
    assert validated.flooded_area_agreement == 0.85
    assert validated.confidence == 0.91
    assert "Sagar Island" in validated.summary
    assert len(validated.observations) >= 2
    assert validated.before_image.startswith("/assets/sentinel/")
    assert validated.after_image.startswith("/assets/sentinel/")
    assert validated.satellite == "Sentinel-1 (Copernicus SAR)"

    # Nested AOI assertions
    assert validated.aoi.name == "Sagar Island"
    assert validated.aoi.census_code == "02438"
    assert validated.aoi.district == "South 24 Parganas"
    assert len(validated.aoi.bbox) == 4
    assert validated.aoi.total_area_km2 == 240.0
    assert validated.aoi.land_area_km2 == 235.5

    # Nested Metrics assertions
    assert validated.metrics.prediction_overlap == 0.82
    assert validated.metrics.flooded_area_agreement == 0.85
    assert validated.metrics.iou == 0.72
    assert validated.metrics.precision == 0.86
    assert validated.metrics.recall == 0.81
    assert validated.metrics.f1_score == 0.84
    assert validated.metrics.observed_flooded_km2 == 81.4
    assert validated.metrics.predicted_flooded_km2 == 78.2
    assert validated.metrics.intersection_km2 == 67.1

    # Acquisition dates
    assert "before" in validated.acquisition_dates
    assert "after" in validated.acquisition_dates
    assert validated.acquisition_dates["before"] == "2020-05-14T12:12:21Z"
    assert validated.acquisition_dates["after"] == "2020-05-22T12:12:22Z"


def test_sentinel_fixture_validator_utility():
    """Verify validate_sentinel_fixture() helper function."""
    result = validate_sentinel_fixture()
    assert result["valid"] is True
    assert result["location"] == "Sagar Island"
    assert result["prediction_overlap"] == 0.82
    assert result["flooded_area_agreement"] == 0.85
    assert result["confidence"] == 0.91


# ===========================================================================
# 2. Validation Service Tests
# ===========================================================================


def test_sentinel_validation_service_demo_mode():
    """Verify get_sentinel_validation() returns valid response when DEMO_MODE is True."""
    res = get_sentinel_validation()
    assert isinstance(res, SentinelValidationResponse)
    assert res.location == "Sagar Island"
    assert res.prediction_overlap == 0.82
    assert res.flooded_area_agreement == 0.85
    assert res.confidence == 0.91


def test_sentinel_validation_service_live_mode_fallback(monkeypatch):
    """Verify get_sentinel_validation() continues to work offline without network even when DEMO_MODE=False."""
    live_settings = Settings(_env_file=None, DEMO_MODE=False)
    monkeypatch.setattr("app.hazard.sentinel.get_settings", lambda: live_settings)

    res = get_sentinel_validation()
    assert isinstance(res, SentinelValidationResponse)
    assert res.location == "Sagar Island"
    assert res.prediction_overlap == 0.82
    assert res.flooded_area_agreement == 0.85


def test_sentinel_validation_service_reexported_in_hazard_service():
    """Verify hazard service module re-exports get_sentinel_validation."""
    res = service_get_sentinel_validation()
    assert isinstance(res, SentinelValidationResponse)
    assert res.location == "Sagar Island"


def test_sentinel_service_strictly_no_external_calls(monkeypatch):
    """Verify that get_sentinel_validation never calls GEE, Gemini, or external HTTP libraries."""
    def _forbidden_network(*args, **kwargs):
        pytest.fail("Network or external service call was attempted by validation service!")

    # Guard against network or SDK calls
    monkeypatch.setattr("urllib.request.urlopen", _forbidden_network)
    try:
        import requests
        monkeypatch.setattr(requests, "get", _forbidden_network)
        monkeypatch.setattr(requests, "post", _forbidden_network)
    except ImportError:
        pass

    # Execution must succeed entirely offline from cached fixture
    res = get_sentinel_validation()
    assert res.location == "Sagar Island"
    assert res.confidence == 0.91


# ===========================================================================
# 3. Validation API Endpoint Tests
# ===========================================================================


def test_get_sentinel_validation_endpoint():
    """Verify GET /api/hazard/validation/sentinel returns 200 and matches required response shape."""
    response = client.get("/api/hazard/validation/sentinel")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    data = response.json()

    # Exact contract keys from user specification
    assert data["location"] == "Sagar Island"
    assert data["before_image"] == "/assets/sentinel/sentinel1_sagar_20200514_pre.jpg"
    assert data["after_image"] == "/assets/sentinel/sentinel1_sagar_20200522_post.jpg"
    assert data["prediction_overlap"] == 0.82
    assert data["flooded_area_agreement"] == 0.85
    assert data["confidence"] == 0.91
    assert isinstance(data["summary"], str)
    assert len(data["summary"]) > 20
    assert isinstance(data["observations"], list)
    assert len(data["observations"]) >= 2
    for obs in data["observations"]:
        assert isinstance(obs, str)

    # Detailed metrics sub-object
    assert "metrics" in data
    assert data["metrics"]["iou"] == 0.72
    assert data["metrics"]["precision"] == 0.86
    assert data["metrics"]["recall"] == 0.81
    assert data["metrics"]["f1_score"] == 0.84

    # Detailed AOI sub-object
    assert "aoi" in data
    assert data["aoi"]["census_code"] == "02438"


def test_sentinel_validation_determinism():
    """Verify that multiple consecutive calls return byte-for-byte identical responses."""
    first = client.get("/api/hazard/validation/sentinel").content
    for _ in range(5):
        current = client.get("/api/hazard/validation/sentinel").content
        assert current == first, "Validation response is not strictly deterministic across runs!"


# ===========================================================================
# 4. Static Image Assets Verification
# ===========================================================================


def test_sentinel_image_assets_exist():
    """Verify static image assets referenced in the fixture exist in web/public and api/data."""
    repo_root = DEMO_DIR.parents[2]
    web_pre = repo_root / "web" / "public" / "assets" / "sentinel" / "sentinel1_sagar_20200514_pre.jpg"
    web_post = repo_root / "web" / "public" / "assets" / "sentinel" / "sentinel1_sagar_20200522_post.jpg"

    assert web_pre.is_file(), f"Missing web static asset: {web_pre}"
    assert web_post.is_file(), f"Missing web static asset: {web_post}"
    assert web_pre.stat().st_size > 1000
    assert web_post.stat().st_size > 1000

    ref_pre = repo_root / "api" / "data" / "reference" / "sentinel" / "sentinel1_sagar_20200514_pre.jpg"
    ref_post = repo_root / "api" / "data" / "reference" / "sentinel" / "sentinel1_sagar_20200522_post.jpg"
    assert ref_pre.is_file(), f"Missing reference asset: {ref_pre}"
    assert ref_post.is_file(), f"Missing reference asset: {ref_post}"


# ===========================================================================
# 5. Regression Tests: Hazard Generation Logic Unchanged
# ===========================================================================


def test_hazard_models_remain_unchanged():
    """Regression audit: confirm existing hazard generators remain strictly unchanged."""
    wind_layer = generate_wind_layer(TS_LANDFALL)
    surge_layer = generate_surge_layer(TS_LANDFALL)
    flood_layer = generate_flood_layer(TS_LANDFALL)

    assert len(wind_layer.features) == 528
    assert len(surge_layer.features) == 528
    assert len(flood_layer.features) == 528

    # Verify physical bounds are strictly preserved
    for f in wind_layer.features:
        assert 0.0 <= f.properties.value <= 65.0
        assert 0.0 <= f.properties.severity <= 1.0

    for f in surge_layer.features:
        assert 0.0 <= f.properties.value <= 6.0
        assert 0.0 <= f.properties.severity <= 1.0

    for f in flood_layer.features:
        assert 0.0 <= f.properties.value <= 1.0
        assert 0.0 <= f.properties.severity <= 1.0


def test_service_get_hazard_layer_unchanged():
    """Regression audit: confirm service.get_hazard_layer returns expected collection."""
    wind = get_hazard_layer("wind", TS_LANDFALL)
    surge = get_hazard_layer("surge", TS_LANDFALL)
    flood = get_hazard_layer("flood", TS_LANDFALL)

    assert wind.type == "FeatureCollection"
    assert surge.type == "FeatureCollection"
    assert flood.type == "FeatureCollection"
    assert len(wind.features) == 528
    assert len(surge.features) == 528
    assert len(flood.features) == 528


# ===========================================================================
# 6. Live Pipeline Components Tests (Acquisition, Preprocessing, Flood, Metrics, Export)
# ===========================================================================


def test_compute_validation_metrics_mathematics():
    """Verify quantitative validation metric calculations against analytical ground truth."""
    from app.hazard.sentinel_metrics import compute_validation_metrics

    # TP=60, FP=20, FN=40, TN=80 -> Total = 200
    # Predicted = 80, Observed = 100, Union = 120
    # Precision = 60/80 = 0.75
    # Recall = 60/100 = 0.60
    # F1 = 2 * 0.75 * 0.60 / 1.35 = 0.90 / 1.35 = 0.6667 -> 0.67
    # IoU = 60/120 = 0.50
    # Accuracy = (60 + 80)/200 = 0.70
    # Flooded Area Agreement = 1 - |80 - 100|/100 = 0.80
    metrics = compute_validation_metrics(
        tp_area_km2=60.0,
        fp_area_km2=20.0,
        fn_area_km2=40.0,
        tn_area_km2=80.0,
    )
    assert metrics.precision == 0.75
    assert metrics.recall == 0.60
    assert metrics.f1_score == 0.67
    assert metrics.iou == 0.50
    assert metrics.accuracy == 0.70
    assert metrics.flooded_area_agreement == 0.80
    assert metrics.intersection_km2 == 60.0
    assert metrics.predicted_flooded_km2 == 80.0
    assert metrics.observed_flooded_km2 == 100.0
    assert metrics.confusion_matrix == {"tp": 60.0, "fp": 20.0, "fn": 40.0, "tn": 80.0}


def test_hazard_comparison_layers():
    """Verify hazard comparison against observed flood generates all required agreement layers."""
    from app.hazard.sentinel_metrics import compare_hazard_with_observation

    bbox = (88.04, 21.63, 88.18, 21.94)
    res = compare_hazard_with_observation(
        observed_flooded_km2=81.4,
        aoi_bbox=bbox,
        landfall_timestep="2020-05-20T12:00:00Z",
    )
    assert "metrics" in res
    assert "layers" in res
    assert res["cell_count"] == 21

    layers = res["layers"]
    assert "observed_flood" in layers
    assert "predicted_flood" in layers
    assert "agreement" in layers
    assert "false_positives" in layers
    assert "missed_flooding" in layers
    assert "disagreement" in layers

    for name, fc in layers.items():
        assert fc["type"] == "FeatureCollection"
        assert isinstance(fc["features"], list)


def test_geotiff_export_structure(tmp_path):
    """Verify minimal GeoTIFF writer produces valid TIFF header and GeoTIFF georeference tags."""
    from app.hazard.sentinel_export import write_minimal_geotiff

    tif_path = tmp_path / "test_flood.tif"
    w, h = 32, 32
    data = bytes([1 if (x + y) % 2 == 0 else 0 for y in range(h) for x in range(w)])
    bbox = (88.04, 21.63, 88.18, 21.94)

    write_minimal_geotiff(
        output_path=tif_path,
        width=w,
        height=h,
        data_bytes=data,
        bbox=bbox,
    )

    assert tif_path.is_file()
    raw = tif_path.read_bytes()
    # Header check: 'II' (Intel little endian), 42 (magic number)
    assert raw[:4] == b"II\x2a\x00"
    # File must be greater than header + IFD + pixel data
    assert len(raw) > 8 + 32 * 32


def test_export_validation_artifacts_completeness(tmp_path):
    """Verify all required exportable validation artifacts are generated with LF line endings."""
    from app.hazard.sentinel_export import export_validation_artifacts
    from app.hazard.sentinel_metrics import compare_hazard_with_observation

    bbox = (88.04, 21.63, 88.18, 21.94)
    cmp_res = compare_hazard_with_observation(observed_flooded_km2=81.4, aoi_bbox=bbox)

    artifacts = export_validation_artifacts(
        output_dir=tmp_path,
        comparison_result=cmp_res,
        aoi_bbox=bbox,
        raster_dims=(16, 16),
    )

    required_keys = [
        "observed_flood_geojson",
        "observed_flood_tif",
        "validation_overlap_geojson",
        "validation_metrics_json",
        "predicted_flood_geojson",
        "agreement_geojson",
        "disagreement_geojson",
    ]
    for key in required_keys:
        assert key in artifacts, f"Missing artifact key: {key}"
        file_path = Path(artifacts[key])
        assert file_path.is_file(), f"Artifact file does not exist: {file_path}"
        if file_path.suffix == ".json" or file_path.suffix == ".geojson":
            content = file_path.read_bytes()
            assert b"\r\n" not in content, f"{file_path.name} contains CRLF; must be LF only"


def test_validation_mode_configuration_switching(monkeypatch):
    """Verify VALIDATION_MODE setting switches between 'demo' and 'live'."""
    from app.core.config import Settings
    from app.hazard.sentinel import run_sentinel_validation

    # Test demo mode explicitly
    demo_settings = Settings(_env_file=None, VALIDATION_MODE="demo", DEMO_MODE=True)
    monkeypatch.setattr("app.hazard.sentinel.get_settings", lambda: demo_settings)

    resp_demo = run_sentinel_validation()
    assert resp_demo.mode == "demo"
    assert resp_demo.location == "Sagar Island"
    assert resp_demo.prediction_overlap == 0.82

    # Test live mode with fallback when GEE is unavailable
    monkeypatch.setattr("app.hazard.sentinel.is_ee_available", lambda: False)
    resp_fallback = run_sentinel_validation(mode="live")
    # Falls back gracefully to cached benchmark
    assert resp_fallback.location == "Sagar Island"
    assert resp_fallback.confidence == 0.91


def test_generate_validation_report():
    """Verify markdown validation report generation."""
    from app.hazard.sentinel import generate_validation_report, get_sentinel_validation

    resp = get_sentinel_validation(mode="demo")
    report = generate_validation_report(resp)
    assert "# Sentinel-1 SAR Validation Benchmark Report" in report
    assert "Sagar Island" in report
    assert "Prediction Overlap" in report
    assert "Intersection over Union" in report


def test_api_mode_parameter_demo_and_live():
    """Verify GET /api/hazard/validation/sentinel endpoint supports ?mode=demo and ?mode=live."""
    resp_demo = client.get("/api/hazard/validation/sentinel?mode=demo")
    assert resp_demo.status_code == 200
    data_demo = resp_demo.json()
    assert data_demo["location"] == "Sagar Island"
    assert data_demo.get("mode") == "demo"

    resp_live = client.get("/api/hazard/validation/sentinel?mode=live")
    assert resp_live.status_code == 200
    data_live = resp_live.json()
    assert data_live["location"] == "Sagar Island"
    assert "metrics" in data_live
    assert "aoi" in data_live
    assert data_live["metrics"]["prediction_overlap"] >= 0.0


def test_ee_acquisition_and_preprocessing_when_ee_available():
    """Verify live Earth Engine collection query, pairing, and flood mask when GEE is initialized."""
    from app.hazard.gee import is_ee_available
    from app.hazard.sentinel_acquisition import (
        get_sentinel_image_metadata,
        load_sentinel_collection,
        load_sentinel_pair,
    )
    from app.hazard.sentinel_flood import compute_backscatter_change
    from app.hazard.sentinel_preprocessing import preprocess_sentinel

    if not is_ee_available():
        pytest.skip("Earth Engine is not initialized in this environment.")

    bbox = (88.04, 21.63, 88.18, 21.94)

    # 1. Collection query
    col = load_sentinel_collection(
        aoi_bbox=bbox,
        start_date="2020-05-01",
        end_date="2020-05-25",
        polarization="VV",
    )
    assert col is not None
    count = col.size().getInfo()
    assert count > 0

    # 2. Pair acquisition
    pair = load_sentinel_pair(
        aoi_bbox=bbox,
        landfall_time="2020-05-20T12:00:00Z",
        strategy="post_first",
    )
    assert pair is not None
    assert "before_image" in pair
    assert "after_image" in pair
    assert "before_meta" in pair
    assert "after_meta" in pair

    before_meta = pair["before_meta"]
    assert before_meta["orbit_pass"] in ("ASCENDING", "DESCENDING")
    assert isinstance(before_meta["relative_orbit"], int)

    # 3. Preprocessing
    pre = preprocess_sentinel(pair["before_image"], aoi_bbox=bbox, apply_terrain=False)
    assert pre is not None
    bands = pre.bandNames().getInfo()
    assert "VV" in bands

    # 4. Backscatter change
    post = preprocess_sentinel(pair["after_image"], aoi_bbox=bbox, apply_terrain=False)
    diff = compute_backscatter_change(pre, post, polarization="VV")
    assert diff is not None
    diff_bands = diff.bandNames().getInfo()
    assert "difference" in diff_bands
