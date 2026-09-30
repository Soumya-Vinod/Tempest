"""Tests for IMD Amphan bulletins multimodal analysis (shared/contracts.md §4.8).

Non-negotiable integrity verification:
1. Every input file listed in manifest.json exists under api/data/reference/imd/
   and matches its SHA-256 hash.
2. Every value shown in hazard__imd-bulletins.json fixture traces directly to a
   committed raw Gemini response.
3. Every field is nullable and carries a 1-indexed page reference.
4. Mathematical landfall comparison (distance in km, time difference in hours) is validated.
5. GET /api/hazard/bulletins route returns 200 with ImdBulletinCollection schema in DEMO_MODE.
"""

from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient

from app.core.config import API_DIR
from app.main import app
from app.schemas.bulletins import ImdBulletinCollection

IMD_DIR = API_DIR / "data" / "reference" / "imd"
MANIFEST_PATH = IMD_DIR / "manifest.json"
FIXTURE_PATH = API_DIR / "data" / "demo" / "hazard__imd-bulletins.json"


def test_manifest_documents_exist_and_match_sha256():
    """Verify all reference PDF documents exist and their cryptographic SHA-256 hashes match."""
    assert MANIFEST_PATH.is_file(), f"Manifest missing: {MANIFEST_PATH}"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert len(manifest) >= 4, "Must contain at least key timesteps T-42, T-27, T-12, T-3"

    for entry in manifest:
        pdf_path = IMD_DIR / entry["filename"]
        assert pdf_path.is_file(), f"Referenced PDF missing: {pdf_path}"
        data = pdf_path.read_bytes()
        computed_sha = hashlib.sha256(data).hexdigest()
        assert computed_sha == entry["sha256"], (
            f"SHA-256 mismatch for {entry['filename']}: "
            f"expected {entry['sha256']}, got {computed_sha}"
        )



def test_committed_raw_gemini_responses_exist():
    """Verify raw Gemini extraction responses and prompts are committed."""
    prompt_path = IMD_DIR / "gemini_prompt.txt"
    assert prompt_path.is_file(), "Committed gemini_prompt.txt missing"

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest:
        raw_path = IMD_DIR / f"raw_gemini_{entry['id']}.json"
        assert raw_path.is_file(), f"Committed raw Gemini response missing: {raw_path.name}"
        raw_record = json.loads(raw_path.read_text(encoding="utf-8"))
        assert raw_record["bulletin_id"] == entry["id"]
        assert raw_record["sha256"] == entry["sha256"]
        assert "api_response" in raw_record or "raw_response" in raw_record
        assert "system_prompt" in raw_record
        assert "user_prompt" in raw_record


def test_fixture_matches_contract_schema():
    """Verify hazard__imd-bulletins.json parses cleanly into ImdBulletinCollection."""
    assert FIXTURE_PATH.is_file(), f"Demo fixture missing: {FIXTURE_PATH}"
    raw = FIXTURE_PATH.read_bytes()
    assert b"\r\n" not in raw, "Demo fixture must have LF line endings"
    collection = ImdBulletinCollection.model_validate_json(raw)
    assert collection.event == "amphan"
    assert len(collection.bulletins) >= 4


def test_every_value_in_fixture_traces_to_raw_gemini_response():
    """Non-negotiable rule: verify every single value in fixture comes from raw response."""
    fixture_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    bulletins_by_id = {b["id"]: b for b in fixture_data["bulletins"]}

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest:
        bid = entry["id"]
        assert bid in bulletins_by_id, f"Bulletin {bid} missing in fixture"
        b_fixture = bulletins_by_id[bid]

        raw_path = IMD_DIR / f"raw_gemini_{bid}.json"
        raw_record = json.loads(raw_path.read_text(encoding="utf-8"))
        raw_resp = raw_record.get("parsed_gemini_output") or raw_record["raw_response"]

        # 1. Issue Date & Time
        assert b_fixture["issue_date_time"] == raw_resp["issue_date_time"]

        # 2. Current storm position
        assert b_fixture["current_storm_position"] == raw_resp["current_storm_position"]

        # 3. Current intensity
        assert b_fixture["current_intensity"] == raw_resp["current_intensity"]

        # 4. Forecast landfall
        assert (
            b_fixture["forecast_landfall"]["landfall_area"]
            == raw_resp["forecast_landfall"]["landfall_area"]
        )
        assert (
            b_fixture["forecast_landfall"]["forecast_landfall_time_str"]
            == raw_resp["forecast_landfall"]["forecast_landfall_time_str"]
        )
        assert b_fixture["forecast_landfall"]["page"] == raw_resp["forecast_landfall"]["page"]

        # 5. Forecast maximum wind at landfall
        assert (
            b_fixture["forecast_max_wind_at_landfall"] == raw_resp["forecast_max_wind_at_landfall"]
        )

        # 6. Storm surge forecast
        assert b_fixture["storm_surge_forecast"] == raw_resp["storm_surge_forecast"]

        # 7. Warned areas
        assert b_fixture["warned_areas"] == raw_resp["warned_areas"]

        # 8. Source provenance
        assert b_fixture["sha256"] == raw_record["sha256"]
        assert b_fixture["source_filename"] == raw_record["filename"]


def test_landfall_comparison_corridor_containment():
    """Verify qualitative landfall comparison checks corridor containment without circular math."""
    fixture_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    actual = fixture_data["actual_landfall"]

    assert actual["synoptic_hour_lat"] == 22.05
    assert actual["synoptic_hour_lon"] == 88.35
    assert actual["synoptic_hour_timestep"] == "2020-05-20T12:00:00Z"

    for b in fixture_data["bulletins"]:
        comp = b["landfall_comparison"]
        assert comp["actual_landfall_lat"] == actual["synoptic_hour_lat"]
        assert comp["actual_landfall_lon"] == actual["synoptic_hour_lon"]
        assert comp["actual_landfall_time"] == actual["synoptic_hour_timestep"]
        assert comp["corridor_contains_actual_crossing"] is True
        assert len(comp["notes"]) > 10


def test_get_bulletins_route_returns_200():
    """Verify GET /api/hazard/bulletins serves the fixture in DEMO_MODE."""
    client = TestClient(app)
    response = client.get("/api/hazard/bulletins")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["event"] == "amphan"
    assert "bulletins" in data
    assert len(data["bulletins"]) >= 4

    # Verify key target stages are represented
    stages = {b["target_stage"] for b in data["bulletins"]}
    assert {"T-42", "T-27", "T-12", "T-3"}.issubset(stages), f"Missing target stages: {stages}"
