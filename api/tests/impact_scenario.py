"""Hand-built road graph, infrastructure and hazards for the impact tests.

A ---1--- B ---2--- C          mainland (anchor at A)
          |         |
          5 ferry   3 "Clinic Road" (dead end)
          |         |
          E ---4--- F          D  <- clinic
                    ^ island shelter
G ---6--- H  <- hospital, disconnected at baseline
far hospital: more than 2 km from any node
"""

import networkx as nx
from pyproj import Geod
from shapely.geometry import LineString, Point

from app.exposure import ingest
from app.schemas import HazardLayerCollection, InfraFeatureCollection

A, B, C, D, E, F, G, H = range(1, 9)
XY = {
    A: (88.10, 22.50),
    B: (88.20, 22.50),
    C: (88.30, 22.50),
    D: (88.30, 22.45),
    E: (88.20, 22.30),
    F: (88.25, 22.30),
    G: (88.50, 22.10),
    H: (88.52, 22.10),
}
ANCHOR = XY[A]
# way id -> (u, v, highway or "ferry", name)
WAYS = {
    1: (A, B, "primary", "Mainland Road"),
    2: (B, C, "secondary", None),
    3: (C, D, "tertiary", "Clinic Road"),
    4: (E, F, "unclassified", "Island Road"),
    5: (B, E, "ferry", "Island Ferry"),
    6: (G, H, "unclassified", None),
}
CLINIC, SHELTER, CUT_OFF, FAR = (
    "hospital-node-10",
    "shelter-node-11",
    "hospital-node-12",
    "hospital-node-13",
)
SUBSTATION, POWER_LINE = "substation-node-14", "power-line-way-15"
_GEOD = Geod(ellps="WGS84")


def build_graph() -> nx.MultiDiGraph:
    G_ = nx.MultiDiGraph(crs="EPSG:4326")
    for n, (x, y) in XY.items():
        G_.add_node(n, x=x, y=y)
    for way, (u, v, kind, name) in WAYS.items():
        (x1, y1), (x2, y2) = XY[u], XY[v]
        length = abs(_GEOD.inv(x1, y1, x2, y2)[2])
        attrs = {"osmid": way, "length": length, "name": name}
        attrs.update({"route": "ferry"} if kind == "ferry" else {"highway": kind})
        G_.add_edge(u, v, **attrs)
        G_.add_edge(v, u, **attrs)
    return ingest.finish_road_graph(G_)


def _record(fid, infra_type, name, osm_id, attributes, geometry) -> ingest.InfraRecord:
    return ingest.InfraRecord(fid, infra_type, name, osm_id, attributes, geometry)


def records(skip_ways: tuple[int, ...] = ()) -> list[ingest.InfraRecord]:
    out = []
    for way, (u, v, kind, name) in WAYS.items():
        if way in skip_ways:
            continue
        attrs = {"ferry": True} if kind == "ferry" else {"highway": kind, "ferry": False}
        out.append(_record(f"road-way-{way}", "road", name, f"way/{way}", attrs,
                           LineString([XY[u], XY[v]])))  # fmt: skip
    hc, hosp = {"facility_level": "health_centre"}, {"facility_level": "hospital"}
    out += [
        _record(CLINIC, "hospital", "Clinic", "node/10", hc, Point(88.3005, 22.4495)),
        _record(
            SHELTER,
            "shelter",
            None,
            "node/11",
            {"shelter_kind": "school_proxy"},
            Point(88.2505, 22.3),
        ),  # fmt: skip
        _record(CUT_OFF, "hospital", "Cut-off Hospital", "node/12", hosp, Point(88.52, 22.1005)),
        _record(FAR, "hospital", "Far Hospital", "node/13", hosp, Point(88.90, 22.60)),
        _record(SUBSTATION, "substation", "Sub", "node/14", {}, Point(88.1005, 22.5)),
        _record(
            POWER_LINE,
            "power_line",
            None,
            "way/15",
            {},
            LineString([(88.10, 22.52), (88.20, 22.52)]),
        ),  # fmt: skip
    ]
    return out


def infra(skip_ways: tuple[int, ...] = ()) -> InfraFeatureCollection:
    return InfraFeatureCollection(features=[ingest.to_feature(r) for r in records(skip_ways)])


def box(minx, miny, maxx, maxy, value):
    return (minx, miny, maxx, maxy, value)


def hazards(timestep: str, *, surge=(), wind=(), flood=()) -> dict[str, HazardLayerCollection]:
    """Hazard layers from (minx, miny, maxx, maxy, value) boxes. Flood value is the severity."""
    units = {"surge": ("m", 3.0), "wind": ("m/s", 60.0), "flood": ("index", 1.0)}
    out = {}
    for hazard, boxes in (("surge", surge), ("wind", wind), ("flood", flood)):
        unit, scale = units[hazard]
        features = []
        for i, (x0, y0, x1, y1, v) in enumerate(boxes):
            fid = f"test-{hazard}-{i}"
            ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
            features.append({
                "type": "Feature", "id": fid,
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {"id": fid, "hazard_type": hazard, "timestep": timestep,
                               "value": v, "unit": unit, "severity": min(1.0, v / scale)},
            })  # fmt: skip
        out[hazard] = HazardLayerCollection.model_validate(
            {"type": "FeatureCollection", "features": features}
        )
    return out


EVERYWHERE = (87.9, 21.4, 89.2, 22.8)
