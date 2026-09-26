"""Multimodal Gemini analysis service for Sentinel-1 SAR flood validation (Phase 13).

Provides demo-ready, AI-generated observations and visual interpretations derived from
curated Sentinel-1 C-band SAR before/after satellite imagery over Sagar Island during
Cyclone Amphan landfall.

This service is strictly observational, deterministic, and offline:
- Never queries Google Gemini, Google AI Studio, or Vertex AI APIs
- Never generates live prompts or makes LLM network requests at runtime
- Never invokes Google Earth Engine or external spatial APIs
- Reads and validates pre-generated cached fixtures (shared/contracts.md §4.9, §7)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import get_settings
from app.core.demo import DEMO_DIR, load_fixture
from app.schemas.contracts import (
    GeminiAnalysisResponse,
    GeminiFinding,
    GeminiGeneratedFrom,
)

logger = logging.getLogger(__name__)

GEMINI_ANALYSIS_FIXTURE_KEY = "hazard__gemini-analysis"

# Static deterministic fallback analysis for Sagar Island in case fixture file is inaccessible
DEFAULT_GEMINI_ANALYSIS: dict[str, Any] = {
    "location": "Sagar Island",
    "confidence": 0.91,
    "summary": (
        "Multimodal AI visual interpretation comparing pre-landfall (2020-05-14) and "
        "post-landfall (2020-05-22) Copernicus Sentinel-1 Synthetic Aperture Radar (SAR) "
        "orthorectified imagery over Sagar Island following Cyclone Amphan landfall. "
        "Visual analysis confirms widespread storm surge inundation and low-lying agricultural "
        "polder flooding across southern and eastern coastlines, highly congruent with "
        "hydrodynamic model predictions."
    ),
    "observations": [
        (
            "Significant surface water expansion detected across southern coastal polders "
            "(Gangasagar, Dhablat) characterized by sharp SAR backscatter attenuation "
            "(specular reflection over standing floodwaters)."
        ),
        (
            "Severe coastal breach and estuarine flooding evident along the eastern embankment "
            "bordering the Muriganga River, corroborating hydrodynamic surge estimates exceeding 1.8m."
        ),
        (
            "Interior agricultural drainage networks in southern Sagar demonstrate prolonged waterlogging, "
            "with drainage impeded by elevated sea levels post-landfall."
        ),
        (
            "Northern elevated mudflats and mangrove fringes near Kachuberia exhibited localized inundation "
            "but rapid tidal drawdown compared to enclosed southern containment zones."
        ),
    ],
    "flooded_regions": [
        {
            "name": "Gangasagar Coastal Embankment & Beachfront",
            "confidence": 0.94,
            "description": (
                "Direct coastal inundation driven by 2.1m storm surge overtopping earthen dikes, "
                "submerging pilgrimage infrastructure and coastal tourist accommodations."
            ),
        },
        {
            "name": "Muriganga Riverbank Polders (Bamour & Sibpur)",
            "confidence": 0.91,
            "description": (
                "Extensive estuarine surge penetration causing salinization of low-elevation betel vine "
                "nurseries and paddy cultivation fields."
            ),
        },
        {
            "name": "Dhablat South Agricultural Tracts",
            "confidence": 0.89,
            "description": (
                "Impounded standing water across low-gradient polders where drainage sluice gates were damaged "
                "or overwhelmed during peak storm tide."
            ),
        },
        {
            "name": "Boatkhali & Chemaguri Estuarine Flank",
            "confidence": 0.88,
            "description": (
                "Compound estuarine surge backwater inundating fish aquaculture ponds (gher) and "
                "intertidal settlements."
            ),
        },
    ],
    "limitations": [
        (
            "SAR C-band backscatter cannot differentiate deep floodwater (>1.5m) from shallow sheet "
            "flow (<0.2m) once specular reflection conditions are met."
        ),
        (
            "Dense mangrove canopy in southwestern patches causes volume scattering that can obscure "
            "underlying ground-surface flood water."
        ),
        (
            "Temporal latency between landfall (2020-05-20) and satellite pass (2020-05-22) means short-duration "
            "pluvial flash ponding on higher ridges had already receded."
        ),
        (
            "Interpretation is descriptive and qualitative; it does not replace physical hydrodynamic "
            "boundary modeling or field ground-truth surveys."
        ),
    ],
    "generated_from": {
        "before_image": "/assets/sentinel/sentinel1_sagar_20200514_pre.jpg",
        "after_image": "/assets/sentinel/sentinel1_sagar_20200522_post.jpg",
        "baseline_event": "Cyclone Amphan (Landfall 2020-05-20T12:00:00Z)",
    },
}


def get_gemini_analysis() -> GeminiAnalysisResponse:
    """Return the cached deterministic Gemini multimodal analysis for Sagar Island.

    Loads the cached analysis fixture from api/data/demo/hazard__gemini-analysis.json.
    Strictly read-only and offline; never queries Google Gemini, Vertex AI, Google AI Studio,
    or any external network endpoints.
    """
    settings = get_settings()

    # 1. Attempt fixture load via core demo loader when in DEMO_MODE
    if settings.DEMO_MODE:
        try:
            data = load_fixture(GEMINI_ANALYSIS_FIXTURE_KEY)
            if data is not None:
                return GeminiAnalysisResponse.model_validate(data)
        except Exception as e:
            logger.debug(
                "Demo fixture %s could not be loaded via load_fixture: %s",
                GEMINI_ANALYSIS_FIXTURE_KEY,
                e,
            )

    # 2. Fallback to direct reading from DEMO_DIR (supports DEMO_MODE=False without network calls)
    fixture_path = DEMO_DIR / f"{GEMINI_ANALYSIS_FIXTURE_KEY}.json"
    if fixture_path.is_file():
        try:
            with fixture_path.open(encoding="utf-8") as f:
                data = json.load(f)
                return GeminiAnalysisResponse.model_validate(data)
        except Exception as e:
            logger.warning("Error reading gemini analysis fixture file %s: %s", fixture_path, e)

    # 3. Fallback to default in-memory analysis
    return GeminiAnalysisResponse.model_validate(DEFAULT_GEMINI_ANALYSIS)
