"""Three blocks over the impact scenario (tests/impact_scenario.py) for the risk tests.

mainland (90001): A, B, C, D, the clinic, the substation and the power line
island   (90002): E, F and the shelter (reached by the ferry B-E)
fragment (90003): G, H and the cut-off hospital (the only facility_level "hospital")
"""

import geopandas as gpd
import shapely
from shapely.geometry import box

from app.exposure import ingest
from app.risk.blocks import Blocks, make_blocks
from tests import impact_scenario as S

BLOCK_BOXES = {
    "90001": ("Mainland", box(88.05, 22.42, 88.35, 22.58)),
    "90002": ("Island", box(88.15, 22.25, 88.35, 22.35)),
    "90003": ("Fragment", box(88.45, 22.05, 88.55, 22.15)),
}
POPULATION = 50_000
# Land beyond the blocks (like Kolkata): an unscored piece.
EXTRA_LAND = box(88.60, 22.40, 88.70, 22.50)


def blocks(population: int = POPULATION, protected=None) -> Blocks:
    """`protected`: a polygon of uninhabited reserve land (none by default)."""
    frame = gpd.GeoDataFrame(
        {
            "census2011_code": list(BLOCK_BOXES),
            "block_name": [name for name, _ in BLOCK_BOXES.values()],
            "population_2011": [population] * len(BLOCK_BOXES),
        },
        geometry=[g for _, g in BLOCK_BOXES.values()],
        crs="EPSG:4326",
    )
    frame["land_area_km2"] = frame.geometry.to_crs(ingest.METRIC_CRS).area / 1e6
    land = shapely.union_all([*frame.geometry, EXTRA_LAND])
    if protected is None:
        frame["inhabited_area_km2"] = frame["land_area_km2"]
        return make_blocks(frame, land)
    inhabited = land.difference(protected)
    frame["inhabited_area_km2"] = (
        frame.geometry.intersection(inhabited).to_crs(ingest.METRIC_CRS).area / 1e6
    )
    return make_blocks(frame, land, inhabited)


def infra(extra_hospital_at_a: bool = False):
    fc = S.infra()
    if extra_hospital_at_a:
        record = ingest.InfraRecord(
            "hospital-node-99", "hospital", "Mainland Hospital", "node/99",
            {"facility_level": "hospital"}, shapely.Point(88.1003, 22.5002),
        )  # fmt: skip
        fc.features.append(ingest.to_feature(record))
    return fc


def records():
    return S.records()
