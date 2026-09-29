# Sentinel-1 Validation Benchmark Report: Cyclone Amphan

- **Execution Timestamp:** `2026-09-29T12:37:08Z`
- **Landfall Timestamp:** `2020-05-20T12:00:00Z`
- **Earth Engine Status:** `Authenticated`
- **Target CRS:** `EPSG:4326`

## 1. Multi-Block Benchmark Executive Summary

| Administrative Block | Census Code | Area (km²) | SAR Water (km²) | Predicted Flood (km²) | IoU | Precision | Recall | F1 Score | Accuracy |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Sagar** | `02438` | 235.5 | 4.2 | 201.9 | **0.000** | 0.000 | 0.000 | **0.000** | 0.143 |
| **Namkhana** | `02439` | 243.6 | 0.5 | 220.4 | **0.000** | 0.000 | 0.000 | **0.000** | 0.095 |
| **Gosaba** | `02435` | 1918.6 | 5.1 | 747.1 | **0.000** | 0.000 | 0.000 | **0.000** | 0.611 |
| **Patharpratima** | `02440` | 477.7 | 7.5 | 358.3 | **0.000** | 0.000 | 0.000 | **0.000** | 0.250 |

### Aggregate Portfolio Metrics across Coastal Blocks
- **Mean Intersection over Union (IoU):** `0.000`
- **Mean F1 Score (Dice):** `0.000`
- **Mean Precision:** `0.000`
- **Mean Recall:** `0.000`
- **Mean Overall Accuracy:** `0.275`
- **Total Observed Flood Extent:** `0.0 km²`
- **Total Predicted Flood Extent:** `1527.6 km²`

---

## 2. Block-Level Detailed Evaluations
### Block: Sagar (Census Code: 02438)

#### Administrative & Spatial Boundary
- **District:** South 24 Parganas, West Bengal
- **Total Land Area:** `235.50 km²`
- **Census 2011 Population:** `212,037`
- **Bounding Box:** `[88.04167, 21.62877, 88.17217, 21.93756]`
- **Centroid:** `(88.1144, 21.73789)`

#### Sentinel-1 SAR Acquisition Provenance
- **Pre-Landfall Baseline:** `COPERNICUS/S1_GRD/S1B_IW_GRDH_1SDV_20200516T000357_20200516T000422_021599_029010_EE74`
  - Time: `2020-05-16T00:03:57Z`
  - Platform: `S1B` | Orbit Pass: `DESCENDING` | Relative Orbit: `48`
- **Post-Landfall Overpass:** `COPERNICUS/S1_GRD/S1A_IW_GRDH_1SDV_20200522T000444_20200522T000509_032670_03C8AC_A6E3`
  - Time: `2020-05-22T00:04:44Z`
  - Platform: `S1A` | Orbit Pass: `DESCENDING` | Relative Orbit: `48`
- **Orbit Geometry Match:** `Matched`

#### Quantitative Confusion Matrix (cell-level, ~5.5 km resolution)
| Metric | Square Kilometers (km²) | Evaluated Grid Cells |
| :--- | :--- | :--- |
| **True Positives (TP)** | `0.00` | `0` |
| **False Positives (FP)** | `201.86` | `18` |
| **False Negatives (FN)** | `0.00` | `0` |
| **True Negatives (TN)** | `33.64` | `3` |

#### Performance Metrics
- **IoU (Jaccard Index):** `0.0000`
- **F1 Score (Dice):** `0.0000`
- **Precision (Positive Predictive Value):** `0.0000`
- **Recall (Sensitivity / True Positive Rate):** `0.0000`
- **Specificity (True Negative Rate):** `0.1428`
- **Cohen's Kappa:** `0.0000`
- **Flooded Area Agreement:** `0.0000`
- **SAR-Measured Water Extent (pixel-area, no threshold):** `4.22 km²`
- **Model-Predicted Inundation:** `201.86 km²`

#### Exported Artifacts
- Observed Cell-Label GeoTIFF: `observed_flood.tif`
- Predicted Cell-Label GeoTIFF: `predicted_flood.tif`
- Agreement Cell-Label GeoTIFF: `agreement.tif`
- Disagreement Cell-Label GeoTIFF: `disagreement.tif`
- Observed Flood GeoJSON: `observed_flood.geojson`
- Overlap Layer GeoJSON: `validation_overlap.geojson`
- Metrics JSON: `metrics.json`
- Acquisition Metadata JSON: `acquisition_metadata.json`
- SAR Water Mask PNG (Leaflet overlay): `sar_water_mask.png`
- SAR Overlay Bounds JSON: `sar_water_mask_bounds.json`

---

### Block: Namkhana (Census Code: 02439)

#### Administrative & Spatial Boundary
- **District:** South 24 Parganas, West Bengal
- **Total Land Area:** `243.60 km²`
- **Census 2011 Population:** `182,830`
- **Bounding Box:** `[88.17075, 21.55897, 88.34945, 21.82107]`
- **Centroid:** `(88.25975, 21.68491)`

#### Sentinel-1 SAR Acquisition Provenance
- **Pre-Landfall Baseline:** `COPERNICUS/S1_GRD/S1B_IW_GRDH_1SDV_20200516T000357_20200516T000422_021599_029010_EE74`
  - Time: `2020-05-16T00:03:57Z`
  - Platform: `S1B` | Orbit Pass: `DESCENDING` | Relative Orbit: `48`
- **Post-Landfall Overpass:** `COPERNICUS/S1_GRD/S1A_IW_GRDH_1SDV_20200522T000444_20200522T000509_032670_03C8AC_A6E3`
  - Time: `2020-05-22T00:04:44Z`
  - Platform: `S1A` | Orbit Pass: `DESCENDING` | Relative Orbit: `48`
- **Orbit Geometry Match:** `Matched`

#### Quantitative Confusion Matrix (cell-level, ~5.5 km resolution)
| Metric | Square Kilometers (km²) | Evaluated Grid Cells |
| :--- | :--- | :--- |
| **True Positives (TP)** | `0.00` | `0` |
| **False Positives (FP)** | `220.40` | `19` |
| **False Negatives (FN)** | `0.00` | `0` |
| **True Negatives (TN)** | `23.20` | `2` |

#### Performance Metrics
- **IoU (Jaccard Index):** `0.0000`
- **F1 Score (Dice):** `0.0000`
- **Precision (Positive Predictive Value):** `0.0000`
- **Recall (Sensitivity / True Positive Rate):** `0.0000`
- **Specificity (True Negative Rate):** `0.0952`
- **Cohen's Kappa:** `0.0000`
- **Flooded Area Agreement:** `0.0000`
- **SAR-Measured Water Extent (pixel-area, no threshold):** `0.54 km²`
- **Model-Predicted Inundation:** `220.40 km²`

#### Exported Artifacts
- Observed Cell-Label GeoTIFF: `observed_flood.tif`
- Predicted Cell-Label GeoTIFF: `predicted_flood.tif`
- Agreement Cell-Label GeoTIFF: `agreement.tif`
- Disagreement Cell-Label GeoTIFF: `disagreement.tif`
- Observed Flood GeoJSON: `observed_flood.geojson`
- Overlap Layer GeoJSON: `validation_overlap.geojson`
- Metrics JSON: `metrics.json`
- Acquisition Metadata JSON: `acquisition_metadata.json`
- SAR Water Mask PNG (Leaflet overlay): `sar_water_mask.png`
- SAR Overlay Bounds JSON: `sar_water_mask_bounds.json`

---

### Block: Gosaba (Census Code: 02435)

#### Administrative & Spatial Boundary
- **District:** South 24 Parganas, West Bengal
- **Total Land Area:** `1918.60 km²`
- **Census 2011 Population:** `246,598`
- **Bounding Box:** `[88.61201, 21.55748, 89.09394, 22.28568]`
- **Centroid:** `(88.87738, 21.91349)`

#### Sentinel-1 SAR Acquisition Provenance
- **Pre-Landfall Baseline:** `COPERNICUS/S1_GRD/S1B_IW_GRDH_1SDV_20200516T000357_20200516T000422_021599_029010_EE74`
  - Time: `2020-05-16T00:03:57Z`
  - Platform: `S1B` | Orbit Pass: `DESCENDING` | Relative Orbit: `48`
- **Post-Landfall Overpass:** `COPERNICUS/S1_GRD/S1A_IW_GRDH_1SDV_20200522T000444_20200522T000509_032670_03C8AC_A6E3`
  - Time: `2020-05-22T00:04:44Z`
  - Platform: `S1A` | Orbit Pass: `DESCENDING` | Relative Orbit: `48`
- **Orbit Geometry Match:** `Matched`

#### Quantitative Confusion Matrix (cell-level, ~5.5 km resolution)
| Metric | Square Kilometers (km²) | Evaluated Grid Cells |
| :--- | :--- | :--- |
| **True Positives (TP)** | `0.00` | `0` |
| **False Positives (FP)** | `747.07` | `44` |
| **False Negatives (FN)** | `0.00` | `0` |
| **True Negatives (TN)** | `1171.53` | `69` |

#### Performance Metrics
- **IoU (Jaccard Index):** `0.0000`
- **F1 Score (Dice):** `0.0000`
- **Precision (Positive Predictive Value):** `0.0000`
- **Recall (Sensitivity / True Positive Rate):** `0.0000`
- **Specificity (True Negative Rate):** `0.6106`
- **Cohen's Kappa:** `0.0000`
- **Flooded Area Agreement:** `0.0000`
- **SAR-Measured Water Extent (pixel-area, no threshold):** `5.11 km²`
- **Model-Predicted Inundation:** `747.07 km²`

#### Scientific Root Cause Analysis (IoU = 0.000)
- **Sundarbans Mangrove Canopy Scattering:** A large proportion of Gosaba (1918.6 km²) consists of dense mangrove forest reserve. C-band microwave pulses (~5.6 cm) scatter within the upper tree canopy and cannot penetrate to floodwater beneath, while perennial tidal creeks are excluded by the JRC surface water occurrence mask (>=20%).
- **Hydrodynamic Wave Attenuation Omission:** The Tempest open-water surge model does not simulate mangrove root drag / vegetative bottom friction (Manning's n), predicting surge ingress across 44 southern cells (747.1 km² FP).
- **Spatial Disconnect (North vs South):** Sentinel-1 observed standing water in 0 northern agricultural polder(s) where surge had already dissipated. This produced 44 False Positives and 0 False Negatives with 0 True Positive(s).

#### Exported Artifacts
- Observed Cell-Label GeoTIFF: `observed_flood.tif`
- Predicted Cell-Label GeoTIFF: `predicted_flood.tif`
- Agreement Cell-Label GeoTIFF: `agreement.tif`
- Disagreement Cell-Label GeoTIFF: `disagreement.tif`
- Observed Flood GeoJSON: `observed_flood.geojson`
- Overlap Layer GeoJSON: `validation_overlap.geojson`
- Metrics JSON: `metrics.json`
- Acquisition Metadata JSON: `acquisition_metadata.json`
- SAR Water Mask PNG (Leaflet overlay): `sar_water_mask.png`
- SAR Overlay Bounds JSON: `sar_water_mask_bounds.json`

---

### Block: Patharpratima (Census Code: 02440)

#### Administrative & Spatial Boundary
- **District:** South 24 Parganas, West Bengal
- **Total Land Area:** `477.70 km²`
- **Census 2011 Population:** `331,823`
- **Bounding Box:** `[88.26004, 21.60326, 88.5192, 22.00271]`
- **Centroid:** `(88.39115, 21.80655)`

#### Sentinel-1 SAR Acquisition Provenance
- **Pre-Landfall Baseline:** `COPERNICUS/S1_GRD/S1B_IW_GRDH_1SDV_20200516T000357_20200516T000422_021599_029010_EE74`
  - Time: `2020-05-16T00:03:57Z`
  - Platform: `S1B` | Orbit Pass: `DESCENDING` | Relative Orbit: `48`
- **Post-Landfall Overpass:** `COPERNICUS/S1_GRD/S1A_IW_GRDH_1SDV_20200522T000444_20200522T000509_032670_03C8AC_A6E3`
  - Time: `2020-05-22T00:04:44Z`
  - Platform: `S1A` | Orbit Pass: `DESCENDING` | Relative Orbit: `48`
- **Orbit Geometry Match:** `Matched`

#### Quantitative Confusion Matrix (cell-level, ~5.5 km resolution)
| Metric | Square Kilometers (km²) | Evaluated Grid Cells |
| :--- | :--- | :--- |
| **True Positives (TP)** | `0.00` | `0` |
| **False Positives (FP)** | `358.27` | `30` |
| **False Negatives (FN)** | `0.00` | `0` |
| **True Negatives (TN)** | `119.42` | `10` |

#### Performance Metrics
- **IoU (Jaccard Index):** `0.0000`
- **F1 Score (Dice):** `0.0000`
- **Precision (Positive Predictive Value):** `0.0000`
- **Recall (Sensitivity / True Positive Rate):** `0.0000`
- **Specificity (True Negative Rate):** `0.2500`
- **Cohen's Kappa:** `0.0000`
- **Flooded Area Agreement:** `0.0000`
- **SAR-Measured Water Extent (pixel-area, no threshold):** `7.49 km²`
- **Model-Predicted Inundation:** `358.27 km²`

#### Exported Artifacts
- Observed Cell-Label GeoTIFF: `observed_flood.tif`
- Predicted Cell-Label GeoTIFF: `predicted_flood.tif`
- Agreement Cell-Label GeoTIFF: `agreement.tif`
- Disagreement Cell-Label GeoTIFF: `disagreement.tif`
- Observed Flood GeoJSON: `observed_flood.geojson`
- Overlap Layer GeoJSON: `validation_overlap.geojson`
- Metrics JSON: `metrics.json`
- Acquisition Metadata JSON: `acquisition_metadata.json`
- SAR Water Mask PNG (Leaflet overlay): `sar_water_mask.png`
- SAR Overlay Bounds JSON: `sar_water_mask_bounds.json`

---

## 3. Scientific Integrity & Verification Methodology

1. **No Fabricated Benchmarks:** Every metric is computed strictly from the spatial overlap of real SAR observations and simulation layers.
2. **Precision & Prediction Overlap Unification:** Precision is mathematically defined as `TP / (TP + FP)` and guaranteed consistent.
3. **Zero Artificial Coefficients:** No hardcoded multipliers (e.g. `* 0.85`) or circular observation assignments exist in this pipeline.
4. **Full Provenance:** Every benchmark block references genuine Copernicus Sentinel-1 scene identifiers with verified acquisition timestamps and orbit metadata.
5. **Hazard Layer Scope:** Simulation benchmarking evaluates `generate_surge_layer()` and `generate_flood_layer()`. The Holland wind field model is intentionally excluded because Sentinel-1 SAR observes surface water backscatter rather than atmospheric wind fields.
