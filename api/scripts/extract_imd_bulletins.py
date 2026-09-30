"""Extract structured cyclone information from official IMD Amphan bulletins using Gemini 2.5 Flash.

Integrity rules:
- Saves every raw prompt and raw Gemini JSON response under:
  api/data/reference/imd/raw_gemini_<id>.json.
- Leaves fields null if not available in the document.

Run from repo root:
    .venv\\Scripts\\python api/scripts/extract_imd_bulletins.py
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

# Add api to path
API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app.core.config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_imd_bulletins")

IMD_DIR = API_DIR / "data" / "reference" / "imd"
MANIFEST_PATH = IMD_DIR / "manifest.json"
MODEL_NAME = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "You are an expert meteorological archivist and data analyst. Your task is to accurately "
    "extract structured information from the provided official India Meteorological Department "
    "(IMD) cyclone bulletin.\n"
    "STRICT INTEGRITY RULES:\n"
    "1. Do not invent, estimate, hallucinate, or extrapolate any value. Extract only what is "
    "explicitly printed in the bulletin.\n"
    "2. If any metric, district, block, or coordinate is not mentioned or available, leave it "
    "null (or an empty list).\n"
    "3. For every field or section, record the exact 1-indexed PDF page number where that "
    "information appears in the document.\n"
    "4. For landfall forecasts: record the exact descriptive landfall area (e.g. 'between Digha "
    "and Hatiya Islands close to Sundarbans'), and the expected landfall time window as stated.\n"
    "5. In the storm surge forecast: extract the predicted surge height and specifically named "
    "districts warned of storm surge inundation.\n"
    "6. In warned areas: extract districts mentioned under wind / rainfall warnings for West "
    "Bengal and Odisha.\n"
)

USER_PROMPT = (
    "Carefully analyze this official IMD cyclone bulletin and extract all requested parameters "
    "according to the schema. Ensure page numbers are accurately populated for each section."
)



class IssueDateTimeExtraction(BaseModel):
    date_str: str | None = Field(default=None, description="Issue date as printed, e.g. 20.05.2020")
    time_ist: str | None = Field(default=None, description="Issue time in IST, e.g. 1640 HOURS IST")
    time_utc: str | None = Field(
        default=None, description="Issue time in UTC if explicitly stated, e.g. 1110 UTC"
    )
    page: int | None = Field(default=None, description="1-indexed page number")


class CurrentPositionExtraction(BaseModel):
    latitude_deg_north: float | None = Field(
        default=None, description="Current latitude in degrees North"
    )
    longitude_deg_east: float | None = Field(
        default=None, description="Current longitude in degrees East"
    )
    location_description: str | None = Field(
        default=None, description="Relative position description as printed"
    )
    page: int | None = Field(default=None, description="1-indexed page number")


class CurrentIntensityExtraction(BaseModel):
    classification: str | None = Field(
        default=None, description="Storm classification, e.g. Extremely Severe Cyclonic Storm"
    )
    max_sustained_surface_wind_kmph: str | None = Field(
        default=None, description="Wind speed text, e.g. 160-170 gusting to 190 kmph"
    )
    max_sustained_surface_wind_kts: float | None = Field(
        default=None, description="Wind speed in knots if stated"
    )
    estimated_central_pressure_hpa: float | None = Field(
        default=None, description="Estimated central pressure in hPa if stated"
    )
    page: int | None = Field(default=None, description="1-indexed page number")


class ForecastLandfallExtraction(BaseModel):
    landfall_area: str | None = Field(
        default=None, description="Forecast coastal landfall area description"
    )
    forecast_landfall_time_str: str | None = Field(
        default=None, description="Forecast landfall timing description as printed"
    )
    page: int | None = Field(default=None, description="1-indexed page number")


class ForecastMaxWindAtLandfall(BaseModel):
    wind_description: str | None = Field(
        default=None, description="Maximum sustained wind forecast at landfall description"
    )
    max_wind_kmph: float | None = Field(default=None, description="Maximum sustained wind in kmph")
    gust_kmph: float | None = Field(default=None, description="Maximum gust in kmph")
    page: int | None = Field(default=None, description="1-indexed page number")


class StormSurgeExtraction(BaseModel):
    surge_height_description: str | None = Field(
        default=None, description="Storm surge height warning description"
    )
    min_surge_height_m: float | None = Field(
        default=None, description="Minimum surge height in meters"
    )
    max_surge_height_m: float | None = Field(
        default=None, description="Maximum surge height in meters"
    )
    inundated_districts: list[str] = Field(
        default_factory=list, description="Districts warned of storm surge inundation"
    )
    page: int | None = Field(default=None, description="1-indexed page number")


class WarnedAreasExtraction(BaseModel):
    west_bengal_districts: list[str] = Field(
        default_factory=list, description="West Bengal districts warned"
    )
    odisha_districts: list[str] = Field(default_factory=list, description="Odisha districts warned")
    other_districts_or_blocks: list[str] = Field(
        default_factory=list, description="Other states or districts warned"
    )
    page: int | None = Field(default=None, description="1-indexed page number")


class ImdBulletinExtraction(BaseModel):
    bulletin_number: str | None = Field(default=None, description="Bulletin number as printed")
    issue_date_time: IssueDateTimeExtraction = Field(default_factory=IssueDateTimeExtraction)
    current_storm_position: CurrentPositionExtraction = Field(
        default_factory=CurrentPositionExtraction
    )
    current_intensity: CurrentIntensityExtraction = Field(
        default_factory=CurrentIntensityExtraction
    )
    forecast_landfall: ForecastLandfallExtraction = Field(
        default_factory=ForecastLandfallExtraction
    )
    forecast_max_wind_at_landfall: ForecastMaxWindAtLandfall = Field(
        default_factory=ForecastMaxWindAtLandfall
    )
    storm_surge_forecast: StormSurgeExtraction = Field(default_factory=StormSurgeExtraction)
    warned_areas: WarnedAreasExtraction = Field(default_factory=WarnedAreasExtraction)
    extraction_notes: str | None = Field(
        default=None, description="Any notable observations or limitations in the bulletin text"
    )


def extract_bulletin(
    client: genai.Client,
    pdf_path: Path,
    bulletin_meta: dict,
    max_retries: int = 3,
) -> dict:
    """Send bulletin PDF to Gemini 2.5 Flash with structured output schema and return raw record."""
    pdf_bytes = pdf_path.read_bytes()
    computed_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    if computed_sha256 != bulletin_meta["sha256"]:
        raise ValueError(
            f"SHA-256 mismatch for {pdf_path.name}: "
            f"expected {bulletin_meta['sha256']}, got {computed_sha256}"
        )


    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Calling Gemini (%s) for %s (attempt %d/%d)...",
                MODEL_NAME,
                bulletin_meta["id"],
                attempt,
                max_retries,
            )
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                    USER_PROMPT,
                ],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=ImdBulletinExtraction,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            raw_parsed = json.loads(response.text)

            # Validate against Pydantic schema
            validated = ImdBulletinExtraction.model_validate(raw_parsed)

            record = {
                "bulletin_id": bulletin_meta["id"],
                "bulletin_number_meta": bulletin_meta["bulletin_number"],
                "target_stage": bulletin_meta["target_stage"],
                "nominal_timestep": bulletin_meta["nominal_timestep"],
                "hours_to_landfall": bulletin_meta["hours_to_landfall"],
                "source_url": bulletin_meta["source_url"],
                "filename": bulletin_meta["filename"],
                "sha256": computed_sha256,
                "model": MODEL_NAME,
                "extracted_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": USER_PROMPT,
                "api_response": response.to_json_dict(),
                "parsed_gemini_output": validated.model_dump(mode="json"),
                "raw_response": validated.model_dump(mode="json"),
            }
            return record
        except Exception as exc:
            logger.warning("Attempt %d failed for %s: %s", attempt, bulletin_meta["id"], exc)
            if attempt == max_retries:
                raise
            time.sleep(35.0 * attempt)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract structured data from IMD Amphan bulletins using Gemini"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-extract even if raw response file exists"
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.is_configured("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY is not configured in api/.env")
        sys.exit(1)

    if not MANIFEST_PATH.is_file():
        logger.error("Manifest not found: %s", MANIFEST_PATH)
        sys.exit(1)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    logger.info("Found %d bulletins in manifest: %s", len(manifest), MANIFEST_PATH)

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # Save prompt reference
    prompt_file = IMD_DIR / "gemini_prompt.txt"
    prompt_file.write_text(
        f"=== SYSTEM PROMPT ===\n{SYSTEM_PROMPT}\n\n=== USER PROMPT ===\n{USER_PROMPT}\n",
        encoding="utf-8",
    )

    successes = 0
    for b in manifest:
        pdf_path = IMD_DIR / b["filename"]
        raw_out_path = IMD_DIR / f"raw_gemini_{b['id']}.json"

        if raw_out_path.is_file() and not args.force:
            logger.info(
                "Raw response already exists for %s at %s, skipping (use --force to overwrite)",
                b["id"],
                raw_out_path.name,
            )
            successes += 1
            continue

        if not pdf_path.is_file():
            logger.error("Source PDF missing: %s", pdf_path)
            continue

        record = extract_bulletin(client, pdf_path, b)
        raw_out_path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        logger.info("Committed raw Gemini extraction to %s", raw_out_path.name)
        successes += 1
        # Polite rate-limiting pace
        time.sleep(5.0)

    logger.info("Completed: %d/%d bulletins extracted successfully.", successes, len(manifest))


if __name__ == "__main__":
    main()
