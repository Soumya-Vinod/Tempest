# Phase 13 — Gemini Multimodal Validation (Demo-Ready, Cached Analysis)

## 1. Executive Summary & Objective

Phase 13 introduces a **demo-ready multimodal AI analysis layer** that synthesizes visual observations, localized flood impacts, and situational summaries from curated **Copernicus Sentinel-1 Synthetic Aperture Radar (SAR)** before/after satellite imagery and supporting event context over **Sagar Island** during **Super Cyclonic Storm Amphan** (May 2020).

### Descriptive Interpretation vs. Predictive Modeling

> [!IMPORTANT]
> **Scope Boundary & Methodological Principle**:
> This phase provides a **qualitative, descriptive interpretation layer** on top of the completed Sentinel-1 observational benchmark.
>
> It does **not**:
> - Modify the Holland parametric wind vortex model
> - Modify the coupled hydrodynamic storm surge model
> - Modify the multi-criteria flood susceptibility model
> - Re-calibrate or tune hazard engine parameters
> - Alter the quantitative Sentinel-1 validation benchmark metrics (IoU: 0.72, F1: 0.84, overlap: 0.82)
> - Perform predictive hazard simulations or parametric trigger calculations
>
> All deterministic physics modeling and quantitative benchmark metrics remain strictly authoritative and unchanged.

---

## 2. Offline Provenance & Zero-Network Runtime Guarantee

The multimodal interpretation layer is designed to run in air-gapped, zero-latency, demo-ready environments without runtime dependencies on external AI services.

```
┌────────────────────────────────────────────────────────────────────────┐
│                   OFFLINE PREPARATION (Ahead-of-Time)                  │
│                                                                        │
│   Sentinel-1 SAR       Sentinel-1 SAR         Cyclone Amphan           │
│   Pre-Landfall         Post-Landfall          Landfall Context         │
│   (2020-05-14)         (2020-05-22)           (2020-05-20)             │
│        │                    │                      │                   │
│        └──────────────┬─────┴──────────────────────┘                   │
│                       ▼                                                │
│         Gemini Multimodal Inference                                    │
│         (Offline Batch Analysis Prompt)                                │
│                       │                                                │
│                       ▼                                                │
│         Schema Validation & Formatting                                 │
│                       │                                                │
│                       ▼                                                │
│      api/data/demo/hazard__gemini-analysis.json                        │
│                 (Immutable Fixture)                                    │
└───────────────────────┬────────────────────────────────────────────────┘
                        │
════════════════════════╪═════════════════════════════════════════════════
                        │  DEMO RUNTIME (Deterministic & Offline)
┌───────────────────────▼────────────────────────────────────────────────┐
│   FastAPI Hazard Service (app.hazard.gemini.get_gemini_analysis)       │
│                       │                                                │
│                       ▼                                                │
│   GET /api/hazard/validation/gemini                                    │
│   ├── Pydantic GeminiAnalysisResponse                                  │
│   ├── Deterministic byte-for-byte replay                               │
│   └── 0ms external latency, 0 external API calls                       │
│                       │                                                │
│                       ▼                                                │
│   Frontend Side-Panel / Executive Briefing UI                          │
└────────────────────────────────────────────────────────────────────────┘
```

### Architectural Guarantees:
1. **Zero Runtime Network Access**: The application runtime **never** calls Google Gemini, Google AI Studio, Vertex AI, Google Earth Engine, or any external LLM or cloud API.
2. **Immutable Cached Fixtures**: Output is read exclusively from `api/data/demo/hazard__gemini-analysis.json`. If missing, an in-memory canonical analysis object provides an offline fallback.
3. **Deterministic Replay**: Multiple consecutive requests to `GET /api/hazard/validation/gemini` produce identical responses.
4. **FastAPI Threadpool Execution**: The route handler is implemented as a synchronous `def` function conforming to contract guidelines (§6), executing in FastAPI's worker threadpool without blocking the async event loop.

---

## 3. Offline Fixture Generation Process

The cached fixture was produced by presenting the paired Sentinel-1 SAR imagery and situational boundary metadata to Gemini multimodal vision models during development:

1. **Curated Input Imagery**:
   - Pre-landfall baseline: `web/public/assets/sentinel/sentinel1_sagar_20200514_pre.jpg` (Interferometric Wide Swath SAR, Level-1 GRD, 10m pixel resolution).
   - Post-landfall event: `web/public/assets/sentinel/sentinel1_sagar_20200522_post.jpg` (acquired ~48 hours after landfall under cloud cover).
2. **Contextual Ingestion**:
   - AOI Boundary: Sagar Island (`02438`), bounding box `[88.04, 21.63, 88.18, 21.94]`.
   - Meteorological Track: Cyclone Amphan eye coordinates and central pressure (950 hPa at landfall).
   - Hydrodynamic Simulation: Modeled peak surge depth (1.64m – 2.21m along coastal fringe).
3. **Prompt Framing**:
   - Constrained to observable physical phenomena: specular radar backscatter attenuation over open water, coastal embankment breaches, estuarine riverbank inundation, and waterlogged agricultural polders.
   - Mandatory structure: executive summary, global confidence score, key observations, localized flooded region breakdowns with confidence and descriptions, and scientific limitations.
4. **Validation & Serialization**:
   - Formatted into UTF-8 JSON with pure LF line endings.
   - Validated against the `GeminiAnalysisResponse` Pydantic contract.
   - Saved to `api/data/demo/hazard__gemini-analysis.json`.

---

## 4. Response Schema & Contracts

### 4.1 TypeScript Contract (`web/src/types/contracts.ts`)

```ts
export interface GeminiFinding {
  name: string;
  confidence: number; // UnitFraction [0.0, 1.0]
  description: string;
}

export interface GeminiGeneratedFrom {
  before_image: string;
  after_image: string;
  baseline_event: string;
}

export interface GeminiAnalysisResponse {
  location: string;
  confidence: number; // UnitFraction [0.0, 1.0]
  summary: string;
  observations: string[];
  flooded_regions: GeminiFinding[];
  limitations: string[];
  generated_from: GeminiGeneratedFrom;
}
```

### 4.2 Python Pydantic Model (`api/app/schemas/contracts.py`)

```python
class GeminiFinding(ContractModel):
    name: str
    confidence: UnitFraction
    description: str

class GeminiGeneratedFrom(ContractModel):
    before_image: str
    after_image: str
    baseline_event: str

class GeminiAnalysisResponse(ContractModel):
    location: str
    confidence: UnitFraction
    summary: str
    observations: list[str]
    flooded_regions: list[GeminiFinding]
    limitations: list[str]
    generated_from: GeminiGeneratedFrom
```

### 4.3 Concrete Response Fixture Example

```json
{
  "location": "Sagar Island",
  "confidence": 0.91,
  "summary": "Multimodal AI visual interpretation comparing pre-landfall (2020-05-14) and post-landfall (2020-05-22) Copernicus Sentinel-1 Synthetic Aperture Radar (SAR) orthorectified imagery over Sagar Island following Cyclone Amphan landfall. Visual analysis confirms widespread storm surge inundation and low-lying agricultural polder flooding across southern and eastern coastlines, highly congruent with hydrodynamic model predictions.",
  "observations": [
    "Significant surface water expansion detected across southern coastal polders (Gangasagar, Dhablat) characterized by sharp SAR backscatter attenuation (specular reflection over standing floodwaters).",
    "Severe coastal breach and estuarine flooding evident along the eastern embankment bordering the Muriganga River, corroborating hydrodynamic surge estimates exceeding 1.8m.",
    "Interior agricultural drainage networks in southern Sagar demonstrate prolonged waterlogging, with drainage impeded by elevated sea levels post-landfall.",
    "Northern elevated mudflats and mangrove fringes near Kachuberia exhibited localized inundation but rapid tidal drawdown compared to enclosed southern containment zones."
  ],
  "flooded_regions": [
    {
      "name": "Gangasagar Coastal Embankment & Beachfront",
      "confidence": 0.94,
      "description": "Direct coastal inundation driven by 2.1m storm surge overtopping earthen dikes, submerging pilgrimage infrastructure and coastal tourist accommodations."
    },
    {
      "name": "Muriganga Riverbank Polders (Bamour & Sibpur)",
      "confidence": 0.91,
      "description": "Extensive estuarine surge penetration causing salinization of low-elevation betel vine nurseries and paddy cultivation fields."
    },
    {
      "name": "Dhablat South Agricultural Tracts",
      "confidence": 0.89,
      "description": "Impounded standing water across low-gradient polders where drainage sluice gates were damaged or overwhelmed during peak storm tide."
    },
    {
      "name": "Boatkhali & Chemaguri Estuarine Flank",
      "confidence": 0.88,
      "description": "Compound estuarine surge backwater inundating fish aquaculture ponds (gher) and intertidal settlements."
    }
  ],
  "limitations": [
    "SAR C-band backscatter cannot differentiate deep floodwater (>1.5m) from shallow sheet flow (<0.2m) once specular reflection conditions are met.",
    "Dense mangrove canopy in southwestern patches causes volume scattering that can obscure underlying ground-surface flood water.",
    "Temporal latency between landfall (2020-05-20) and satellite pass (2020-05-22) means short-duration pluvial flash ponding on higher ridges had already receded.",
    "Interpretation is descriptive and qualitative; it does not replace physical hydrodynamic boundary modeling or field ground-truth surveys."
  ],
  "generated_from": {
    "before_image": "/assets/sentinel/sentinel1_sagar_20200514_pre.jpg",
    "after_image": "/assets/sentinel/sentinel1_sagar_20200522_post.jpg",
    "baseline_event": "Cyclone Amphan (Landfall 2020-05-20T12:00:00Z)"
  }
}
```

---

## 5. Distinction: Quantitative Benchmarks vs. AI Multimodal Interpretation

Tempest maintains a clear separation between statistical model validation and generative AI interpretation:

| Dimension | Sentinel-1 Validation Benchmark (Phase 12) | Gemini Multimodal Interpretation (Phase 13) |
|---|---|---|
| **Contract Endpoint** | `GET /api/hazard/validation/sentinel` | `GET /api/hazard/validation/gemini` |
| **Data Nature** | Rigorous quantitative statistical metrics | Natural language descriptive interpretation |
| **Output Type** | Flooded area (km²), IoU (0.72), F1 (0.84), precision (0.86), recall (0.81) | Executive summary, observation narratives, localized region damage descriptions |
| **Methodology** | Pixel-level Otsu thresholding & binary confusion matrix against SAR backscatter drop | Vision-language multimodal synthesis of before/after orthorectified imagery |
| **Authoritative Purpose**| Benchmark deterministic hazard engine spatial accuracy against satellite ground-truth | Provide situational awareness, human-digestible briefings, and side-panel intelligence |
| **Engine Coupling** | Completely decoupled; read-only post-model audit | Completely decoupled; read-only cached fixture |

---

## 6. Frontend Integration & Side-Panel Support

The API response is tailored for presentation in an **observational validation side-panel** or modal:

- **Executive Summary Card**: High-level synthesis connecting the satellite observations to cyclone landfall.
- **Confidence Indicator**: Global model confidence badge (`0.91`).
- **Observations Feed**: Bulleted qualitative findings highlighting specific hydrodynamic phenomena (overtopping, drainage lock, specular backscatter drop).
- **Flooded Regions Accordion**: Localized breakdowns (Gangasagar, Muriganga, Dhablat, Boatkhali) with sub-regional confidence ratings and infrastructure damage descriptions.
- **Methodological Limitations**: Explicit caveats alerting decision-makers to SAR physics boundaries and temporal latency.
- **Provenance Links**: Direct relative paths to the pre- and post-landfall imagery assets (`before_image`, `after_image`) for interactive before/after image comparison sliders.

### Client Usage (`web/src/lib/api.ts`)

```ts
import { getGeminiAnalysis } from '../lib/api';

const analysis = await getGeminiAnalysis();
console.log(analysis.summary);
console.log(analysis.flooded_regions);
```

---

## 7. Known Limitations

1. **Radar Specular Thresholding**: SAR C-band microwave reflection indicates surface water presence when backscatter drops below ~ -16 dB. However, radar amplitude alone cannot quantify floodwater depth once surface specular reflection is established.
2. **Mangrove Canopy Penetration**: Dense mangrove foliage causes volume scattering, which can mask ground-level inundation in intertidal wetlands.
3. **Temporal Pass Discrepancy**: Sentinel-1's ascending overpass occurred at 12:12 UTC on 22 May 2020 (~48 hours post-landfall). Fast-draining pluvial ponding on elevated interior ridges (>3.5m SRTM elevation) had dissipated before satellite capture.
4. **Descriptive, Non-Predictive Character**: The multimodal outputs describe observed post-disaster states; they are not hydrodynamic predictive models and must not be used for parametric insurance payout calculation without the underlying deterministic hazard engine layers.
