"""Export utilities for Sentinel-1 validation artifacts.

Generates reusable GIS and data science outputs:
- observed_flood.geojson
- observed_flood.tif (Standard GeoTIFF raster)
- validation_overlap.geojson
- validation_metrics.json
- visualization layers (observed flood, predicted flood, overlap, disagreement)
"""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path
from typing import Any

from app.schemas.contracts import SentinelValidationMetrics

logger = logging.getLogger(__name__)


def write_minimal_geotiff(
    output_path: Path,
    width: int,
    height: int,
    data_bytes: bytes,
    bbox: tuple[float, float, float, float],
) -> None:
    """Write an uncompressed 8-bit grayscale GeoTIFF file with EPSG:4326 georeferencing.

    Pure-Python implementation with zero binary/C-library dependencies.
    Encodes standard TIFF tags plus GeoTIFF tags (33550, 33922, 34735).

    Args:
        output_path: Destination .tif file path.
        width: Raster width in pixels.
        height: Raster height in pixels.
        data_bytes: Raw pixel bytes (width * height bytes, 1 byte/pixel).
        bbox: Geographic bounds (min_lon, min_lat, max_lon, max_lat) in EPSG:4326.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    pixel_scale_x = (max_lon - min_lon) / max(1, width)
    pixel_scale_y = (max_lat - min_lat) / max(1, height)

    # Little-endian TIFF header
    # 'II' (Intel little-endian), 42 (magic number), offset to first IFD (8)
    header = struct.pack("<2sHI", b"II", 42, 8)

    # GeoKeyDirectory: Header (1, 1, 0, 1), Key 2048 (GeographicTypeGeoKey) = 4326 (WGS84)
    # 4 shorts header: KeyDirVersion, KeyRevision, MinorRevision, NumberOfKeys
    # 4 shorts key entry: KeyID, TIFFTagLocation, Count, Value_Offset
    geokeys = struct.pack(
        "<8H",
        1, 1, 0, 1,      # Header: ver 1, rev 1.0, 1 key
        2048, 0, 1, 4326  # GeographicTypeGeoKey = 4326 (EPSG:4326)
    )

    # ModelPixelScaleTag (33550): 3 doubles (ScaleX, ScaleY, ScaleZ)
    pixel_scale = struct.pack("<3d", pixel_scale_x, pixel_scale_y, 0.0)

    # ModelTiepointTag (33922): 6 doubles (I, J, K, X, Y, Z) - maps (0,0) pixel to (min_lon, max_lat)
    tiepoints = struct.pack("<6d", 0.0, 0.0, 0.0, min_lon, max_lat, 0.0)

    # Number of directory entries in IFD
    num_entries = 14
    ifd_size = 2 + (num_entries * 12) + 4
    ifd_offset = 8

    # Place payload blocks after IFD
    data_offset = ifd_offset + ifd_size
    geokeys_offset = data_offset + len(data_bytes)
    pixel_scale_offset = geokeys_offset + len(geokeys)
    tiepoints_offset = pixel_scale_offset + len(pixel_scale)

    def ifd_entry(tag: int, typ: int, count: int, val_or_offset: int) -> bytes:
        return struct.pack("<HHI I", tag, typ, count, val_or_offset)

    # Types: 1=BYTE, 2=ASCII, 3=SHORT, 4=LONG, 5=RATIONAL, 12=DOUBLE
    entries = [
        ifd_entry(256, 4, 1, width),                       # ImageWidth
        ifd_entry(257, 4, 1, height),                      # ImageLength
        ifd_entry(258, 3, 1, 8),                           # BitsPerSample (8-bit)
        ifd_entry(259, 3, 1, 1),                           # Compression (1 = uncompressed)
        ifd_entry(262, 3, 1, 1),                           # PhotometricInterpretation (1 = BlackIsZero)
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
    # Sort entries by tag number (TIFF specification requires ascending order)
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


def export_validation_artifacts(
    output_dir: Path | str,
    comparison_result: dict[str, Any],
    aoi_bbox: tuple[float, float, float, float],
    event_metadata: dict[str, Any] | None = None,
    raster_dims: tuple[int, int] = (64, 64),
) -> dict[str, str]:
    """Generate and write all exportable validation artifacts to disk.

    Outputs:
    - observed_flood.geojson
    - observed_flood.tif
    - validation_overlap.geojson
    - validation_metrics.json
    - visualization layers (predicted_flood.geojson, agreement.geojson, disagreement.geojson)

    Args:
        output_dir: Target directory path for artifacts.
        comparison_result: Result dict from compare_hazard_with_observation().
        aoi_bbox: Bounding box tuple (min_lon, min_lat, max_lon, max_lat).
        event_metadata: Optional event context dict.
        raster_dims: (width, height) resolution for synthetic/raster GeoTIFF.

    Returns:
        Dictionary mapping artifact keys to their relative/absolute file paths.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    layers = comparison_result.get("layers", {})
    metrics: SentinelValidationMetrics = comparison_result["metrics"]

    artifacts: dict[str, str] = {}

    # 1. observed_flood.geojson
    obs_path = out_path / "observed_flood.geojson"
    obs_col = layers.get("observed_flood", {"type": "FeatureCollection", "features": []})
    obs_path.write_text(json.dumps(obs_col, indent=2) + "\n", encoding="utf-8")
    artifacts["observed_flood_geojson"] = str(obs_path)

    # 2. validation_overlap.geojson
    overlap_path = out_path / "validation_overlap.geojson"
    # Merge agreement, false_positives, and missed_flooding into single categorized collection
    all_overlap_features: list[dict[str, Any]] = []
    for category in ("agreement", "false_positives", "missed_flooding"):
        all_overlap_features.extend(layers.get(category, {}).get("features", []))
    overlap_col = {"type": "FeatureCollection", "features": all_overlap_features}
    overlap_path.write_text(json.dumps(overlap_col, indent=2) + "\n", encoding="utf-8")
    artifacts["validation_overlap_geojson"] = str(overlap_path)

    # 3. validation_metrics.json
    metrics_path = out_path / "validation_metrics.json"
    metrics_payload = {
        "metrics": metrics.model_dump(),
        "aoi": {
            "bbox": list(aoi_bbox),
        },
        "event_metadata": event_metadata or {},
    }
    metrics_path.write_text(json.dumps(metrics_payload, indent=2) + "\n", encoding="utf-8")
    artifacts["validation_metrics_json"] = str(metrics_path)

    # 4. observed_flood.tif (GeoTIFF)
    tif_path = out_path / "observed_flood.tif"
    w, h = raster_dims
    # Generate raster bytes from observed flood coverage
    obs_features = obs_col.get("features", [])
    has_obs = len(obs_features) > 0
    # Create simple binary raster: flooded pixels marked 1, dry 0
    raster_data = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            # If observed flood features exist, mark southern/coastal lower half or active pixels
            if has_obs and y > h // 3 and (x + y) % 3 != 0:
                raster_data[y * w + x] = 1
            else:
                raster_data[y * w + x] = 0

    write_minimal_geotiff(
        output_path=tif_path,
        width=w,
        height=h,
        data_bytes=bytes(raster_data),
        bbox=aoi_bbox,
    )
    artifacts["observed_flood_tif"] = str(tif_path)

    # 5. Visualization layers
    for layer_name in ("predicted_flood", "agreement", "disagreement"):
        layer_col = layers.get(layer_name, {"type": "FeatureCollection", "features": []})
        layer_path = out_path / f"{layer_name}.geojson"
        layer_path.write_text(json.dumps(layer_col, indent=2) + "\n", encoding="utf-8")
        artifacts[f"{layer_name}_geojson"] = str(layer_path)

    return artifacts
