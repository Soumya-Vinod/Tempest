"""Tests for Gemini Multimodal Analysis layer and API endpoint (Phase 13).

Verifies:
- Fixture existence, LF line endings, and UTF-8 encoding
- Schema validation against GeminiAnalysisResponse contract
- Service operations in DEMO_MODE and offline fallback
- Offline guarantee: strictly no network or external LLM/API requests
- GET /api/hazard/validation/gemini API endpoint response and schema compliance
- Deterministic byte-for-byte identical responses across multiple runs
- Frontend side-panel readiness (summary, confidence, observations, flooded_regions, limitations)
- TypeScript contract mirror and API client synchronization
- Regression verification: Sentinel-1 benchmark and hazard engine remain strictly unchanged
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.demo import DEMO_DIR
from app.hazard.gemini import (
    DEFAULT_GEMINI_ANALYSIS,
    GEMINI_ANALYSIS_FIXTURE_KEY,
    get_gemini_analysis,
)
from app.hazard.models import (
    GeminiAnalysisResponse,
    GeminiFinding,
    GeminiGeneratedFrom,
    SentinelValidationResponse,
)
from app.hazard.replay import (
    generate_flood_layer,
    generate_surge_layer,
    generate_wind_layer,
)
from app.hazard.sentinel import get_sentinel_validation
from app.hazard.service import (
    get_gemini_analysis as service_get_gemini_analysis,
    get_hazard_layer,
    get_sentinel_validation as service_get_sentinel_validation,
)
from app.hazard.validation import (
    validate_gemini_analysis_fixture,
    validate_sentinel_fixture,
)
from app.main import app

client = TestClient(app)
TS_LANDFALL = "2020-05-20T12:00:00Z"


# ===========================================================================
# 1. Fixture Loading & Schema Validation Tests
# ===========================================================================


def test_gemini_fixture_existence_and_encoding():
    """Verify hazard__gemini-analysis.json exists, uses UTF-8, and has LF-only line endings."""
    fixture_path = DEMO_DIR / f"{GEMINI_ANALYSIS_FIXTURE_KEY}.json"
    assert fixture_path.is_file(), f"Fixture file not found: {fixture_path}"

    raw = fixture_path.read_bytes()
    assert b"\r\n" not in raw, "Fixture contains CRLF line endings; must be LF only"
    text = raw.decode("utf-8")
    data = json.loads(text)
    assert isinstance(data, dict)


def test_gemini_fixture_schema():
    """Verify fixture validates against the Pydantic GeminiAnalysisResponse contract."""
    fixture_path = DEMO_DIR / f"{GEMINI_ANALYSIS_FIXTURE_KEY}.json"
    with fixture_path.open(encoding="utf-8") as f:
        data = json.load(f)

    validated = GeminiAnalysisResponse.model_validate(data)
    assert validated.location == "Sagar Island"
    assert 0.0 <= validated.confidence <= 1.0
    assert validated.confidence == 0.91
    assert "Sagar Island" in validated.summary
    assert len(validated.observations) >= 3
    assert len(validated.flooded_regions) >= 2
    assert len(validated.limitations) >= 2

    # Verify flooded regions structure
    for region in validated.flooded_regions:
        assert isinstance(region, GeminiFinding)
        assert isinstance(region.name, str) and len(region.name) > 0
        assert 0.0 <= region.confidence <= 1.0
        assert isinstance(region.description, str) and len(region.description) > 0

    # Verify generated_from provenance
    assert isinstance(validated.generated_from, GeminiGeneratedFrom)
    assert validated.generated_from.before_image.startswith("/assets/sentinel/")
    assert validated.generated_from.after_image.startswith("/assets/sentinel/")
    assert "Amphan" in validated.generated_from.baseline_event


def test_gemini_fixture_validator_utility():
    """Verify validate_gemini_analysis_fixture() helper function."""
    result = validate_gemini_analysis_fixture()
    assert result["valid"] is True
    assert result["location"] == "Sagar Island"
    assert result["confidence"] == 0.91
    assert result["observations_count"] >= 3
    assert result["flooded_regions_count"] >= 2


# ===========================================================================
# 2. Gemini Service Tests & Offline Guarantee
# ===========================================================================


def test_gemini_service_demo_mode():
    """Verify get_gemini_analysis() returns valid response when DEMO_MODE is True."""
    res = get_gemini_analysis()
    assert isinstance(res, GeminiAnalysisResponse)
    assert res.location == "Sagar Island"
    assert res.confidence == 0.91
    assert len(res.flooded_regions) > 0


def test_gemini_service_live_mode_fallback(monkeypatch):
    """Verify get_gemini_analysis() operates offline without network even when DEMO_MODE=False."""
    live_settings = Settings(_env_file=None, DEMO_MODE=False)
    monkeypatch.setattr("app.hazard.gemini.get_settings", lambda: live_settings)

    res = get_gemini_analysis()
    assert isinstance(res, GeminiAnalysisResponse)
    assert res.location == "Sagar Island"
    assert res.confidence == 0.91


def test_gemini_service_in_memory_fallback(monkeypatch):
    """Verify fallback to DEFAULT_GEMINI_ANALYSIS if fixture file is inaccessible."""
    monkeypatch.setattr("app.hazard.gemini.DEMO_DIR", Path("/nonexistent/directory"))
    res = get_gemini_analysis()
    assert isinstance(res, GeminiAnalysisResponse)
    assert res.location == DEFAULT_GEMINI_ANALYSIS["location"]
    assert res.confidence == DEFAULT_GEMINI_ANALYSIS["confidence"]


def test_gemini_service_reexported_in_hazard_service():
    """Verify hazard service module re-exports get_gemini_analysis."""
    res = service_get_gemini_analysis()
    assert isinstance(res, GeminiAnalysisResponse)
    assert res.location == "Sagar Island"


def test_gemini_service_strictly_no_external_calls(monkeypatch):
    """Verify that get_gemini_analysis never invokes external network APIs or LLM services."""
    def _forbidden_network(*args, **kwargs):
        pytest.fail("Network or external LLM service call was attempted by Gemini analysis service!")

    # Guard against standard python network libraries
    monkeypatch.setattr("urllib.request.urlopen", _forbidden_network)
    try:
        import requests
        monkeypatch.setattr(requests, "get", _forbidden_network)
        monkeypatch.setattr(requests, "post", _forbidden_network)
    except ImportError:
        pass

    try:
        import httpx
        monkeypatch.setattr(httpx, "get", _forbidden_network)
        monkeypatch.setattr(httpx, "post", _forbidden_network)
    except ImportError:
        pass

    # Execution must succeed entirely offline from cached fixture
    res = get_gemini_analysis()
    assert res.location == "Sagar Island"
    assert res.confidence == 0.91


# ===========================================================================
# 3. API Endpoint Tests & Determinism
# ===========================================================================


def test_get_gemini_validation_endpoint():
    """Verify GET /api/hazard/validation/gemini returns 200 and matches required response shape."""
    response = client.get("/api/hazard/validation/gemini")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    data = response.json()
    assert data["location"] == "Sagar Island"
    assert data["confidence"] == 0.91
    assert isinstance(data["summary"], str)
    assert len(data["summary"]) > 50

    # Observations array
    assert isinstance(data["observations"], list)
    assert len(data["observations"]) >= 3
    for obs in data["observations"]:
        assert isinstance(obs, str)

    # Flooded regions array
    assert isinstance(data["flooded_regions"], list)
    assert len(data["flooded_regions"]) >= 2
    for region in data["flooded_regions"]:
        assert "name" in region
        assert "confidence" in region
        assert "description" in region
        assert 0.0 <= region["confidence"] <= 1.0

    # Limitations array
    assert isinstance(data["limitations"], list)
    assert len(data["limitations"]) >= 2
    for lim in data["limitations"]:
        assert isinstance(lim, str)

    # Provenance metadata
    assert "generated_from" in data
    assert data["generated_from"]["before_image"] == "/assets/sentinel/sentinel1_sagar_20200514_pre.jpg"
    assert data["generated_from"]["after_image"] == "/assets/sentinel/sentinel1_sagar_20200522_post.jpg"
    assert "Cyclone Amphan" in data["generated_from"]["baseline_event"]


def test_gemini_validation_determinism():
    """Verify that multiple consecutive API calls return byte-for-byte identical responses."""
    first = client.get("/api/hazard/validation/gemini").content
    for _ in range(5):
        current = client.get("/api/hazard/validation/gemini").content
        assert current == first, "Gemini validation response is not strictly deterministic across calls!"


def test_side_panel_rendering_readiness():
    """Verify all elements required for frontend side-panel rendering are present and non-empty."""
    response = client.get("/api/hazard/validation/gemini")
    assert response.status_code == 200
    data = response.json()

    # Front-end side-panel critical fields
    assert data.get("summary"), "Missing summary for side-panel"
    assert "confidence" in data, "Missing confidence for side-panel"
    assert len(data.get("observations", [])) > 0, "Missing observations for side-panel"
    assert len(data.get("flooded_regions", [])) > 0, "Missing flooded regions for side-panel"
    assert len(data.get("limitations", [])) > 0, "Missing limitations for side-panel"


# ===========================================================================
# 4. TypeScript Contract Mirror Synchronization
# ===========================================================================


def test_typescript_contract_mirror_sync():
    """Verify web/src/types/contracts.ts contains GeminiFinding, GeminiGeneratedFrom, and GeminiAnalysisResponse."""
    repo_root = DEMO_DIR.parents[2]
    ts_contracts_path = repo_root / "web" / "src" / "types" / "contracts.ts"
    assert ts_contracts_path.is_file(), f"TypeScript contracts file not found: {ts_contracts_path}"

    content = ts_contracts_path.read_text(encoding="utf-8")
    assert "interface GeminiFinding" in content
    assert "interface GeminiGeneratedFrom" in content
    assert "interface GeminiAnalysisResponse" in content
    assert "flooded_regions: GeminiFinding[]" in content
    assert "generated_from: GeminiGeneratedFrom" in content


def test_web_api_client_method_sync():
    """Verify web/src/lib/api.ts contains getGeminiAnalysis client method."""
    repo_root = DEMO_DIR.parents[2]
    api_ts_path = repo_root / "web" / "src" / "lib" / "api.ts"
    assert api_ts_path.is_file(), f"Web api.ts file not found: {api_ts_path}"

    content = api_ts_path.read_text(encoding="utf-8")
    assert "getGeminiAnalysis" in content
    assert "/api/hazard/validation/gemini" in content


# ===========================================================================
# 5. Regression Tests: Sentinel-1 Benchmark and Hazard Engine Unchanged
# ===========================================================================


def test_sentinel_validation_remains_unchanged():
    """Regression audit: Sentinel-1 validation benchmark values must remain strictly unchanged."""
    sentinel_res = get_sentinel_validation()
    assert isinstance(sentinel_res, SentinelValidationResponse)
    assert sentinel_res.location == "Sagar Island"
    assert sentinel_res.prediction_overlap == 0.82
    assert sentinel_res.flooded_area_agreement == 0.85
    assert sentinel_res.confidence == 0.91
    assert sentinel_res.metrics.iou == 0.72
    assert sentinel_res.metrics.precision == 0.86
    assert sentinel_res.metrics.recall == 0.81
    assert sentinel_res.metrics.f1_score == 0.84
    assert sentinel_res.metrics.observed_flooded_km2 == 81.4
    assert sentinel_res.metrics.predicted_flooded_km2 == 78.2
    assert sentinel_res.metrics.intersection_km2 == 67.1

    # Endpoint regression test
    api_res = client.get("/api/hazard/validation/sentinel")
    assert api_res.status_code == 200
    assert api_res.json()["metrics"]["f1_score"] == 0.84


def test_hazard_engine_outputs_remain_unchanged():
    """Regression audit: Holland wind, storm surge, and flood susceptibility models remain unchanged."""
    wind_layer = generate_wind_layer(TS_LANDFALL)
    surge_layer = generate_surge_layer(TS_LANDFALL)
    flood_layer = generate_flood_layer(TS_LANDFALL)

    assert len(wind_layer.features) == 528
    assert len(surge_layer.features) == 528
    assert len(flood_layer.features) == 528

    # Physical bounds checking
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
    """Regression audit: service.get_hazard_layer returns expected collection."""
    wind = get_hazard_layer("wind", TS_LANDFALL)
    surge = get_hazard_layer("surge", TS_LANDFALL)
    flood = get_hazard_layer("flood", TS_LANDFALL)

    assert wind.type == "FeatureCollection"
    assert surge.type == "FeatureCollection"
    assert flood.type == "FeatureCollection"
    assert len(wind.features) == 528
    assert len(surge.features) == 528
    assert len(flood.features) == 528
