"""Build the exposure DEMO_MODE fixtures from api/data/processed/infra.parquet.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_exposure_fixtures.py

Writes api/data/demo/exposure__infra-<type>.json per infra type, as contracts.md §7 names them
(the unfiltered route is composed from these; it has no fixture of its own). Attributes are
copied as-is, incl. the roads' baseline_* connectivity. Display copies only: coordinates rounded to
DECIMALS places, lines simplified to ~TOLERANCE_M metres. The parquet and graph are unchanged.
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.demo import DEMO_DIR  # noqa: E402
from app.exposure import ingest, service  # noqa: E402
from app.schemas import InfraFeatureCollection  # noqa: E402

DECIMALS = 5  # ~1 m
TOLERANCE_M = 10.0


def _round(geom, decimals: int):
    return shapely.transform(geom, lambda c: np.round(c, decimals))


def _drop_repeats(geom):
    """Remove consecutive duplicate vertices left by rounding, unless a line would collapse."""
    tidy = shapely.remove_repeated_points(geom)
    parts = getattr(tidy, "geoms", [tidy])
    return geom if any(len(p.coords) < 2 for p in parts) else tidy


def display_gdf(
    gdf: gpd.GeoDataFrame, tolerance_m: float = TOLERANCE_M, decimals: int = DECIMALS
) -> gpd.GeoDataFrame:
    """Simplify lines to ~tolerance_m (in metres) and round all coordinates."""
    out = gdf.copy()
    lines = out.geom_type.isin(["LineString", "MultiLineString"])
    if lines.any():
        metric = out.loc[lines].geometry.to_crs(ingest.METRIC_CRS)
        simplified = metric.simplify(tolerance_m, preserve_topology=True).to_crs("EPSG:4326")
        out.loc[lines, "geometry"] = simplified.to_numpy()
    out["geometry"] = [_drop_repeats(_round(g, decimals)) for g in out.geometry]
    return out


def write_fixture(path: Path, gdf: gpd.GeoDataFrame) -> None:
    collection = InfraFeatureCollection(features=service.features_from_gdf(gdf))
    text = json.dumps(collection.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def build_fixtures(
    infra: gpd.GeoDataFrame,
    out_dir: Path,
    tolerance_m: float = TOLERANCE_M,
    decimals: int = DECIMALS,
) -> dict[str, Path]:
    """Write one fixture per infra type (empty collections included)."""
    display = display_gdf(infra, tolerance_m, decimals)
    written: dict[str, Path] = {}
    for infra_type in ingest.INFRA_TYPES:
        key = service.fixture_key(infra_type)
        rows = display[display["infra_type"] == infra_type]
        path = out_dir / f"{key}.json"
        write_fixture(path, rows)
        written[key] = path
    return written


def main() -> None:
    infra = ingest.read_infra()
    for key, path in build_fixtures(infra, DEMO_DIR).items():
        n = len(json.loads(path.read_text(encoding="utf-8"))["features"])
        print(f"{path.name:<34} {n:>6,} features  {path.stat().st_size / 1e6:6.2f} MB  ({key})")


if __name__ == "__main__":
    main()
