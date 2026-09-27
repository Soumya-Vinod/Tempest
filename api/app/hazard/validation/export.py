"""Automated artifact export pipeline for Sentinel-1 validation benchmarking.

Generates and writes reproducible, publication-ready raster and vector products:
- observed_flood.tif (GeoTIFF)
- predicted_flood.tif (GeoTIFF)
- agreement.tif (GeoTIFF)
- disagreement.tif (GeoTIFF)
- observed_flood.geojson (GeoJSON)
- predicted_flood.geojson (GeoJSON)
- validation_overlap.geojson (GeoJSON with TP, FP, FN, TN status)
- metrics.json (JSON metrics and confusion matrix)
- acquisition_metadata.json (JSON Sentinel-1 scene metadata)
"""

from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.hazard.validation.acquisition import SentinelPairResult
from app.hazard.validation.comparison import CellEvaluation, HazardComparisonResult
from app.hazard.validation.datasets import AdminBlock
from app.hazard.validation.metrics import BenchmarkMetrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportedArtifacts:
    """Paths to all exported validation products for an administrative block."""

    block_identifier: str
    block_name: str
    output_dir: Path
    observed_flood_tif: Path
    predicted_flood_tif: Path
    agreement_tif: Path
    disagreement_tif: Path
    observed_flood_geojson: Path
    predicted_flood_geojson: Path
    validation_overlap_geojson: Path
    metrics_json: Path
    acquisition_metadata_json: Path

    def to_dict(self) -> dict[str, str]:
        """Map artifact keys to portable filenames (not absolute paths)."""
        return {
            "observed_flood_tif": self.observed_flood_tif.name,
            "predicted_flood_tif": self.predicted_flood_tif.name,
            "agreement_tif": self.agreement_tif.name,
            "disagreement_tif": self.disagreement_tif.name,
            "observed_flood_geojson": self.observed_flood_geojson.name,
            "predicted_flood_geojson": self.predicted_flood_geojson.name,
            "validation_overlap_geojson": self.validation_overlap_geojson.name,
            "metrics_json": self.metrics_json.name,
            "acquisition_metadata_json": self.acquisition_metadata_json.name,
        }


def write_geotiff(
    output_path: Path,
    width: int,
    height: int,
    data_bytes: bytes,
    bbox: tuple[float, float, float, float],
) -> None:
    """Write an uncompressed 8-bit GeoTIFF file with genuine EPSG:4326 georeferencing.

    Pure-Python implementation with zero binary dependencies.
    Encodes TIFF specification tags plus GeoTIFF tags (33550, 33922, 34735).
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    pixel_scale_x = (max_lon - min_lon) / max(1, width)
    pixel_scale_y = (max_lat - min_lat) / max(1, height)

    header = struct.pack("<2sHI", b"II", 42, 8)

    # GeoKeyDirectory: GeographicTypeGeoKey = 4326 (WGS84)
    geokeys = struct.pack(
        "<8H",
        1, 1, 0, 1,       # Header: ver 1, rev 1.0, 1 key
        2048, 0, 1, 4326, # GeographicTypeGeoKey = 4326 (EPSG:4326)
    )
    pixel_scale = struct.pack("<3d", pixel_scale_x, pixel_scale_y, 0.0)
    tiepoints = struct.pack("<6d", 0.0, 0.0, 0.0, min_lon, max_lat, 0.0)

    num_entries = 14
    ifd_size = 2 + (num_entries * 12) + 4
    ifd_offset = 8

    data_offset = ifd_offset + ifd_size
    geokeys_offset = data_offset + len(data_bytes)
    pixel_scale_offset = geokeys_offset + len(geokeys)
    tiepoints_offset = pixel_scale_offset + len(pixel_scale)

    def ifd_entry(tag: int, typ: int, count: int, val_or_offset: int) -> bytes:
        return struct.pack("<HHI I", tag, typ, count, val_or_offset)

    entries = [
        ifd_entry(256, 4, 1, width),                       # ImageWidth
        ifd_entry(257, 4, 1, height),                      # ImageLength
        ifd_entry(258, 3, 1, 8),                           # BitsPerSample (8-bit)
        ifd_entry(259, 3, 1, 1),                           # Compression (1 = uncompressed)
        ifd_entry(262, 3, 1, 1),                           # Photometric (1 = BlackIsZero)
        ifd_entry(273, 4, 1, data_offset),                 # StripOffsets
        ifd_entry(277, 3, 1, 1),                           # SamplesPerPixel (1)
        ifd_entry(278, 4, 1, height),                      # RowsPerStrip
        ifd_entry(279, 4, 1, len(data_bytes)),             # StripByteCounts
        ifd_entry(284, 3, 1, 1),                           # PlanarConfiguration (1)
        ifd_entry(33550, 12, 3, pixel_scale_offset),       # ModelPixelScaleTag
        ifd_entry(33922, 12, 6, tiepoints_offset),         # ModelTiepointTag
        ifd_entry(34735, 3, 8, geokeys_offset),            # GeoKeyDirectoryTag
        ifd_entry(34736, 12, 0, 0),                        # GeoDoubleParamsTag (empty)
    ]
    entries.sort(key=lambda b: struct.unpack("<H", b[:2])[0])
    ifd_bytes = struct.pack("<H", len(entries)) + b"".join(entries) + struct.pack("<I", 0)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        f.write(header)
        f.write(ifd_bytes)
        f.write(data_bytes)
        f.write(geokeys)
        f.write(pixel_scale)
        f.write(tiepoints)


def rasterize_cell_evaluations(
    evaluations: list[CellEvaluation],
    bbox: tuple[float, float, float, float],
    dims: tuple[int, int] = (128, 128),
) -> dict[str, bytes]:
    """Rasterize cell-level evaluation states onto a 2D regular pixel grid.

    Produces true binary raster arrays for:
    - observed_flood (1 = flooded, 0 = dry)
    - predicted_flood (1 = flooded, 0 = dry)
    - agreement (1 = TP or TN, 0 = disagreement)
    - disagreement (1 = FP or FN, 0 = agreement)
    """
    w, h = dims
    min_lon, min_lat, max_lon, max_lat = bbox
    dx = (max_lon - min_lon) / w
    dy = (max_lat - min_lat) / h

    obs_arr = np.zeros((h, w), dtype=np.uint8)
    pred_arr = np.zeros((h, w), dtype=np.uint8)
    agree_arr = np.zeros((h, w), dtype=np.uint8)
    disagree_arr = np.zeros((h, w), dtype=np.uint8)

    # For each cell polygon, rasterize its evaluated value onto intersecting pixels
    for ev in evaluations:
        poly_coords = ev.polygon.get("coordinates", [[]])[0]
        if not poly_coords:
            continue

        lons = [pt[0] for pt in poly_coords]
        lats = [pt[1] for pt in poly_coords]
        c_min_lon, c_max_lon = min(lons), max(lons)
        c_min_lat, c_max_lat = min(lats), max(lats)

        # Convert geographic bounds to pixel index bounding box
        x_start = max(0, min(w - 1, int((c_min_lon - min_lon) / dx)))
        x_end = max(0, min(w, int((c_max_lon - min_lon) / dx) + 1))
        # Latitude decreases from top (index 0) to bottom (index h-1)
        y_start = max(0, min(h - 1, int((max_lat - c_max_lat) / dy)))
        y_end = max(0, min(h, int((max_lat - c_min_lat) / dy) + 1))

        if ev.observed_flooded:
            obs_arr[y_start:y_end, x_start:x_end] = 1
        if ev.predicted_flooded:
            pred_arr[y_start:y_end, x_start:x_end] = 1

        if ev.status in ("tp", "tn"):
            agree_arr[y_start:y_end, x_start:x_end] = 1
        else:
            disagree_arr[y_start:y_end, x_start:x_end] = 1

    return {
        "observed_flood": obs_arr.tobytes(),
        "predicted_flood": pred_arr.tobytes(),
        "agreement": agree_arr.tobytes(),
        "disagreement": disagree_arr.tobytes(),
    }


def export_block_validation_artifacts(
    block: AdminBlock,
    comparison: HazardComparisonResult,
    metrics: BenchmarkMetrics,
    acquisition_pair: SentinelPairResult,
    output_base_dir: Path,
    raster_dims: tuple[int, int] = (128, 128),
) -> ExportedArtifacts:
    """Export all publication-ready GeoTIFF, GeoJSON, and JSON benchmark artifacts for a block."""
    block_dir = output_base_dir / block.name.lower().replace(" ", "_")
    block_dir.mkdir(parents=True, exist_ok=True)

    # 1. Export GeoJSON layers
    layers = comparison.layers
    obs_geojson_path = block_dir / "observed_flood.geojson"
    obs_geojson_path.write_text(
        json.dumps(layers.get("observed_flood", {}), indent=2), encoding="utf-8"
    )

    pred_geojson_path = block_dir / "predicted_flood.geojson"
    pred_geojson_path.write_text(
        json.dumps(layers.get("predicted_flood", {}), indent=2), encoding="utf-8"
    )

    overlap_geojson_path = block_dir / "validation_overlap.geojson"
    overlap_geojson_path.write_text(
        json.dumps(layers.get("overlap_layer", {}), indent=2), encoding="utf-8"
    )

    # 2. Export Metrics JSON
    metrics_path = block_dir / "metrics.json"
    metrics_payload = {
        "block": {
            "identifier": block.identifier,
            "name": block.name,
            "census_code": block.census_code,
            "area_km2": block.area_km2,
            "population": block.population,
            "bbox": list(block.bbox),
            "centroid": list(block.centroid),
        },
        "metrics": metrics.to_dict(),
    }
    metrics_path.write_text(json.dumps(metrics_payload, indent=2), encoding="utf-8")

    # 3. Export Acquisition Metadata JSON
    acquisition_path = block_dir / "acquisition_metadata.json"
    acquisition_path.write_text(json.dumps(acquisition_pair.to_dict(), indent=2), encoding="utf-8")

    # 4. Rasterize and export GeoTIFFs
    w, h = raster_dims
    raster_bytes = rasterize_cell_evaluations(
        evaluations=comparison.cell_evaluations,
        bbox=block.bbox,
        dims=(w, h),
    )

    obs_tif_path = block_dir / "observed_flood.tif"
    write_geotiff(obs_tif_path, w, h, raster_bytes["observed_flood"], block.bbox)

    pred_tif_path = block_dir / "predicted_flood.tif"
    write_geotiff(pred_tif_path, w, h, raster_bytes["predicted_flood"], block.bbox)

    agree_tif_path = block_dir / "agreement.tif"
    write_geotiff(agree_tif_path, w, h, raster_bytes["agreement"], block.bbox)

    disagree_tif_path = block_dir / "disagreement.tif"
    write_geotiff(disagree_tif_path, w, h, raster_bytes["disagreement"], block.bbox)

    return ExportedArtifacts(
        block_identifier=block.identifier,
        block_name=block.name,
        output_dir=block_dir,
        observed_flood_tif=obs_tif_path,
        predicted_flood_tif=pred_tif_path,
        agreement_tif=agree_tif_path,
        disagreement_tif=disagree_tif_path,
        observed_flood_geojson=obs_geojson_path,
        predicted_flood_geojson=pred_geojson_path,
        validation_overlap_geojson=overlap_geojson_path,
        metrics_json=metrics_path,
        acquisition_metadata_json=acquisition_path,
    )
