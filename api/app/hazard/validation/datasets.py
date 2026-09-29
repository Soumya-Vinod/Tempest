"""Dataset definitions, schemas, and loaders for the Sentinel-1 validation pipeline.

Provides structured interfaces for:
- Administrative boundary geometries (South 24 Parganas CD blocks)
- Copernicus Sentinel-1 Synthetic Aperture Radar (SAR) GRD imagery
- Digital Elevation Models (Copernicus DEM GLO-30 / USGS SRTM 30m)
- JRC Global Surface Water occurrence data
- Tempest deterministic hazard engine simulation outputs
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry

from app.hazard.gee import is_ee_available, load_surface_water
from app.hazard.models import GridCell, HazardLayerCollection
from app.hazard.replay import (
    generate_flood_layer,
    generate_surge_layer,
    get_aoi_grid,
)
from app.hazard.validation.config import (
    BENCHMARK_BLOCK_CODES,
    BLOCK_CODE_TO_NAME,
    BLOCKS_CSV,
    BLOCKS_GEOJSON,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Administrative Boundary Dataset & AOI
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AdminBlock:
    """Administrative block Area of Interest (AOI) with spatial geometry and census metadata."""

    identifier: str  # Census 2011 code (e.g. "02438")
    name: str  # Canonical block name (e.g. "Sagar")
    census_code: str
    geometry: BaseGeometry  # Shapely geometry in EPSG:4326
    bbox: tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)
    centroid: tuple[float, float]  # (lon, lat)
    area_km2: float  # Land area in square kilometers
    population: int
    admin_metadata: dict[str, Any] = field(default_factory=dict)

    def to_geojson_feature(self) -> dict[str, Any]:
        """Convert block to standard GeoJSON Feature."""
        return {
            "type": "Feature",
            "id": self.identifier,
            "geometry": shapely.geometry.mapping(self.geometry),
            "properties": {
                "identifier": self.identifier,
                "name": self.name,
                "census_code": self.census_code,
                "area_km2": round(self.area_km2, 2),
                "population": self.population,
                "bbox": list(self.bbox),
                "centroid": list(self.centroid),
                **self.admin_metadata,
            },
        }


class AdminBoundariesDataset:
    """Loader for administrative boundary polygons and demographic data."""

    def __init__(
        self,
        geojson_path: Path = BLOCKS_GEOJSON,
        lookup_csv_path: Path = BLOCKS_CSV,
    ) -> None:
        self.geojson_path = geojson_path
        self.lookup_csv_path = lookup_csv_path
        self._blocks_cache: dict[str, AdminBlock] | None = None

    def load_all_blocks(self) -> dict[str, AdminBlock]:
        """Load and cache all CD blocks from committed reference files."""
        if self._blocks_cache is not None:
            return self._blocks_cache

        if not self.geojson_path.is_file():
            raise FileNotFoundError(f"Blocks GeoJSON not found at {self.geojson_path}")

        gdf = gpd.read_file(self.geojson_path)
        pop_lookup: dict[str, int] = {}
        meta_lookup: dict[str, dict[str, Any]] = {}

        if self.lookup_csv_path.is_file():
            df = pd.read_csv(self.lookup_csv_path, comment="#", dtype={"census2011_code": str})
            for _, row in df.iterrows():
                code = str(row["census2011_code"]).zfill(5)
                try:
                    pop_lookup[code] = int(row.get("population_2011", 0))
                except (ValueError, TypeError):
                    pop_lookup[code] = 0
                meta_lookup[code] = {
                    "shape_id": str(row.get("geoboundaries_shape_id", "")),
                    "name_bn": str(row.get("name_bn", "")),
                    "name_hi": str(row.get("name_hi", "")),
                }

        blocks: dict[str, AdminBlock] = {}
        for _, row in gdf.iterrows():
            code = str(row.get("census2011_code") or row.get("block_id") or "").zfill(5)
            raw_name = row.get("block_name") or row.get("name")
            name = str(raw_name or BLOCK_CODE_TO_NAME.get(code, code))
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue

            min_lon, min_lat, max_lon, max_lat = geom.bounds
            centroid_pt = geom.centroid
            land_area = float(row.get("land_area_km2") or (geom.area * 111.0 * 111.0))
            pop = pop_lookup.get(code, int(row.get("population_2011") or 0))

            block = AdminBlock(
                identifier=code,
                name=name,
                census_code=code,
                geometry=geom,
                bbox=(round(min_lon, 5), round(min_lat, 5), round(max_lon, 5), round(max_lat, 5)),
                centroid=(round(centroid_pt.x, 5), round(centroid_pt.y, 5)),
                area_km2=round(land_area, 2),
                population=pop,
                admin_metadata=meta_lookup.get(code, {}),
            )
            # Register by code and lowercase name
            blocks[code] = block
            blocks[name.lower().replace(" ", "_")] = block
            blocks[name.lower()] = block

        self._blocks_cache = blocks
        return blocks

    def get_block(self, name_or_code: str) -> AdminBlock:
        """Retrieve block by Census code, canonical name, or slug."""
        all_blocks = self.load_all_blocks()
        key = name_or_code.strip().lower().replace(" ", "_")
        if key in all_blocks:
            return all_blocks[key]
        raw_key = name_or_code.strip()
        if raw_key in all_blocks:
            return all_blocks[raw_key]
        padded = raw_key.zfill(5)
        if padded in all_blocks:
            return all_blocks[padded]
        raise KeyError(f"Administrative block '{name_or_code}' not found in reference boundaries.")

    def get_benchmark_blocks(self) -> list[AdminBlock]:
        """Return the 4 canonical Cyclone Amphan benchmark blocks."""
        benchmark_blocks: list[AdminBlock] = []
        for name, code in BENCHMARK_BLOCK_CODES.items():
            try:
                block = self.get_block(code)
                benchmark_blocks.append(block)
            except KeyError:
                logger.warning("Benchmark block %s (%s) could not be loaded", name, code)
        return benchmark_blocks


# ---------------------------------------------------------------------------
# 2. Sentinel-1 Scene Metadata & Dataset Loader
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SentinelSceneMetadata:
    """Standardized metadata for a single Copernicus Sentinel-1 SAR acquisition."""

    image_id: str
    acquisition_time: str  # ISO 8601 UTC timestamp
    platform: str  # 'S1A' or 'S1B'
    orbit_pass: str  # 'ASCENDING' or 'DESCENDING'
    relative_orbit: int | None
    absolute_orbit: int | None
    polarization: str  # e.g. 'VV' or 'VH'
    instrument_mode: str  # e.g. 'IW'
    slice_number: int | None = None
    footprint_bbox: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize scene metadata to clean dictionary."""
        return {
            "image_id": self.image_id,
            "acquisition_time": self.acquisition_time,
            "platform": self.platform,
            "orbit_pass": self.orbit_pass,
            "relative_orbit": self.relative_orbit,
            "absolute_orbit": self.absolute_orbit,
            "polarization": self.polarization,
            "instrument_mode": self.instrument_mode,
            "slice_number": self.slice_number,
            "footprint_bbox": list(self.footprint_bbox) if self.footprint_bbox else None,
        }


class Sentinel1Dataset:
    """Earth Engine Copernicus Sentinel-1 GRD collection interface."""

    COLLECTION_ID = "COPERNICUS/S1_GRD"

    @staticmethod
    def query_collection(
        aoi_bbox: tuple[float, float, float, float],
        start_date: str | datetime,
        end_date: str | datetime,
        polarization: str = "VV",
        orbit_pass: str | None = None,
        relative_orbit: int | None = None,
        instrument_mode: str = "IW",
    ) -> Any | None:
        """Query and filter Sentinel-1 ImageCollection in Earth Engine.

        Returns:
            ee.ImageCollection or None if Earth Engine is unavailable.
        """
        if not is_ee_available():
            return None

        try:
            import ee

            min_lon, min_lat, max_lon, max_lat = aoi_bbox
            geometry = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])

            start_str = (
                start_date.strftime("%Y-%m-%d")
                if isinstance(start_date, datetime)
                else str(start_date)[:10]
            )
            # Ensure end_date includes full day
            if isinstance(end_date, datetime):
                end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                dt_end = datetime.strptime(str(end_date)[:10], "%Y-%m-%d") + timedelta(days=1)
                end_str = dt_end.strftime("%Y-%m-%d")

            col = (
                ee.ImageCollection(Sentinel1Dataset.COLLECTION_ID)
                .filterBounds(geometry)
                .filterDate(start_str, end_str)
                .filter(ee.Filter.eq("instrumentMode", instrument_mode))
                .filter(ee.Filter.listContains("transmitterReceiverPolarisation", polarization))
            )

            if orbit_pass:
                col = col.filter(ee.Filter.eq("orbitProperties_pass", orbit_pass))
            if relative_orbit:
                col = col.filter(ee.Filter.eq("relativeOrbitNumber_start", relative_orbit))

            return col
        except Exception as e:
            logger.warning("Error querying Sentinel-1 ImageCollection: %s", e)
            return None

    @staticmethod
    def extract_metadata(ee_image: Any) -> SentinelSceneMetadata | None:
        """Extract complete, genuine metadata from an Earth Engine Sentinel-1 Image."""
        if not is_ee_available() or ee_image is None:
            return None

        try:
            props = ee_image.toDictionary().getInfo()
            system_id = str(ee_image.get("system:id").getInfo() or "")
            system_time = ee_image.get("system:time_start").getInfo()

            dt_utc = (
                datetime.fromtimestamp(system_time / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                if system_time
                else ""
            )

            platform = "S1A" if "S1A" in system_id else ("S1B" if "S1B" in system_id else "S1")
            orbit_pass = str(props.get("orbitProperties_pass", "UNKNOWN"))
            rel_orbit = props.get("relativeOrbitNumber_start")
            abs_orbit = props.get("orbitNumber_start")
            mode = str(props.get("instrumentMode", "IW"))
            slice_num = props.get("sliceNumber")

            pols = props.get("transmitterReceiverPolarisation", ["VV"])
            pol_str = pols[0] if isinstance(pols, list) and pols else str(pols)

            return SentinelSceneMetadata(
                image_id=system_id,
                acquisition_time=dt_utc,
                platform=platform,
                orbit_pass=orbit_pass,
                relative_orbit=int(rel_orbit) if rel_orbit is not None else None,
                absolute_orbit=int(abs_orbit) if abs_orbit is not None else None,
                polarization=pol_str,
                instrument_mode=mode,
                slice_number=int(slice_num) if slice_num is not None else None,
            )
        except Exception as e:
            logger.warning("Error extracting Sentinel-1 metadata: %s", e)
            return None


# ---------------------------------------------------------------------------
# 3. DEM & Surface Water Datasets
# ---------------------------------------------------------------------------
class DemDataset:
    """Topographic elevation and slope dataset loader."""

    @staticmethod
    def load(
        aoi_bbox: tuple[float, float, float, float] | None = None,
        source: str = "copernicus",
    ) -> Any | None:
        """Load DEM ee.Image. If aoi_bbox is None, returns unclipped global asset."""
        if not is_ee_available():
            return None
        try:
            import ee

            if source == "copernicus":
                try:
                    img = ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1").select("DEM").mosaic()
                    return img.clip(ee.Geometry.Rectangle(aoi_bbox)) if aoi_bbox else img
                except Exception:
                    try:
                        img = ee.ImageCollection("COPERNICUS/DEM/GLO30").select("DEM").mosaic()
                        return img.clip(ee.Geometry.Rectangle(aoi_bbox)) if aoi_bbox else img
                    except Exception:
                        pass
            img = ee.Image("USGS/SRTMGL1_003").select("elevation")
            return img.clip(ee.Geometry.Rectangle(aoi_bbox)) if aoi_bbox else img
        except Exception as e:
            logger.warning("Error loading DEM: %s", e)
            return None

    @staticmethod
    def compute_slope(dem_image: Any = None) -> Any | None:
        """Compute terrain slope in degrees using Earth Engine Terrain algorithm."""
        if not is_ee_available():
            return None
        try:
            import ee

            if dem_image is None:
                dem_image = ee.Image("USGS/SRTMGL1_003").select("elevation")
            elev = dem_image.select([0]).rename("elevation")
            return ee.Terrain.slope(elev)
        except Exception as e:
            logger.warning("Error computing DEM slope: %s", e)
            return None


class SurfaceWaterDataset:
    """Historical global surface water occurrence dataset loader."""

    @staticmethod
    def load_occurrence(aoi_bbox: tuple[float, float, float, float]) -> Any | None:
        """Load JRC Global Surface Water occurrence band [0-100%]."""
        return load_surface_water(aoi_bbox=aoi_bbox)

    @staticmethod
    def get_permanent_water_mask(
        aoi_bbox: tuple[float, float, float, float],
        threshold_pct: float = 20.0,
    ) -> Any | None:
        """Return binary mask where 1 indicates perennial surface water."""
        gsw = load_surface_water(aoi_bbox=aoi_bbox)
        if gsw is None:
            return None
        try:
            return gsw.gte(threshold_pct).rename("permanent_water")
        except Exception as e:
            logger.warning("Error generating permanent water mask: %s", e)
            return None


# ---------------------------------------------------------------------------
# 4. Hazard Output Dataset Loader
# ---------------------------------------------------------------------------
class HazardOutputDataset:
    """Loader for deterministic Tempest hazard model simulation layers."""

    @staticmethod
    def load_simulated_layers(timestep: str) -> dict[str, HazardLayerCollection]:
        """Load simulated storm surge and flood susceptibility collections at given timestep."""
        surge_col = generate_surge_layer(timestep)
        flood_col = generate_flood_layer(timestep)
        return {
            "surge": surge_col,
            "flood": flood_col,
        }

    @staticmethod
    def filter_cells_for_block(
        block: AdminBlock,
        grid_cells: list[GridCell] | None = None,
    ) -> list[GridCell]:
        """Find grid cells whose polygon or centroid intersects the administrative block polygon."""
        cells = grid_cells or get_aoi_grid()
        matched: list[GridCell] = []
        block_geom = block.geometry
        block_bbox = box(*block.bbox)

        for cell in cells:
            cell_box = box(cell.min_lon, cell.min_lat, cell.max_lon, cell.max_lat)
            if not block_bbox.intersects(cell_box):
                continue
            # Check shapely intersection with block boundary
            cell_poly = shape(cell.polygon.model_dump())
            if block_geom.intersects(cell_poly):
                matched.append(cell)

        return matched
