"""OSM infrastructure ingest and road graph for the exposure module.

Everything here is network-free: it turns cached Overpass JSON into contract InfraFeatures and
post-processes an osmnx road graph. Downloading lives in scripts/ingest_osm.py.
"""

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import shapely
from pyproj import Geod
from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from app.core.config import API_DIR
from app.schemas import InfraFeature, InfraType

RAW_DIR = API_DIR / "data" / "raw"
PROCESSED_DIR = API_DIR / "data" / "processed"
OSMNX_CACHE_DIR = API_DIR / "data" / "cache" / "osmnx"
INFRA_PARQUET = PROCESSED_DIR / "infra.parquet"
ROADS_GRAPHML = PROCESSED_DIR / "roads.graphml"

INFRA_TYPES: tuple[str, ...] = ("substation", "power_line", "road", "hospital", "shelter")
# Metric CRS for distances (UTM 45N covers 84–90° E).
METRIC_CRS = "EPSG:32645"
_GEOD = Geod(ellps="WGS84")

# --- Clip polygon -------------------------------------------------------------------------------

# OSM admin_level=5 district relations whose union is the ingest clip polygon (India only).
CLIP_RELATIONS: dict[int, str] = {9513027: "South 24 Parganas", 10371838: "Kolkata"}
# Khulna Division (Bangladesh), the only foreign unit in the AOI bbox; used to verify the clip.
BORDER_CHECK_RELATIONS: dict[int, str] = {3825003: "Khulna Division (BD)"}

# --- Tag mapping --------------------------------------------------------------------------------

ROAD_HIGHWAY_RE = re.compile(
    r"^(motorway|trunk|primary|secondary|tertiary)(_link)?$|^unclassified$"
)
MINOR_LINE_LIMIT = 10_000  # include power=minor_line only if line + minor_line ways <= this

HEALTH_AMENITY = {"hospital", "clinic"}
HEALTH_HEALTHCARE = {"hospital", "clinic", "centre"}
# Names that upgrade a clinic / health centre to facility_level "hospital".
HOSPITAL_NAME_PATTERNS: tuple[str, ...] = (
    r"rural hospital",
    r"block hospital",
    r"\bbphc\b",
    r"sub[- ]?divisional hospital",
    r"district hospital",
)
HOSPITAL_NAME_RE = re.compile("|".join(HOSPITAL_NAME_PATTERNS), re.IGNORECASE)

# Cyclone / flood shelter indicators. Name patterns are a heuristic; adjust here only.
SHELTER_NAME_PATTERNS: tuple[str, ...] = (
    r"cyclone",
    r"flood shelter",
    r"flood cent(re|er)",
    r"সাইক্লোন",  # cyclone
    r"ঘূর্ণিঝড়",  # cyclone
    r"আশ্রয় ?কেন্দ্র",  # shelter centre
)
SHELTER_INDICATOR_KEYS = ("shelter_type", "emergency", "building", "amenity", "social_facility")
SHELTER_INDICATOR_RE = re.compile(r"cyclone|flood", re.IGNORECASE)
SHELTER_FLAG_KEYS = ("cyclone_shelter", "flood_shelter")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


SHELTER_NAME_RE = re.compile("|".join(_nfc(p) for p in SHELTER_NAME_PATTERNS), re.IGNORECASE)


def _names(tags: dict[str, str]) -> list[str]:
    return [_nfc(tags[k]) for k in ("name", "name:en") if tags.get(k)]


def has_shelter_indicator(tags: dict[str, str]) -> bool:
    """True if the element is tagged or named as a cyclone / flood shelter."""
    if any(SHELTER_INDICATOR_RE.search(tags.get(k, "")) for k in SHELTER_INDICATOR_KEYS):
        return True
    if any(tags.get(k) == "yes" for k in SHELTER_FLAG_KEYS):
        return True
    return any(SHELTER_NAME_RE.search(n) for n in _names(tags))


def facility_level(tags: dict[str, str]) -> str:
    if tags.get("amenity") == "hospital" or tags.get("healthcare") == "hospital":
        return "hospital"
    if any(HOSPITAL_NAME_RE.search(n) for n in _names(tags)):
        return "hospital"
    return "health_centre"


def _pick(tags: dict[str, str], keys: Iterable[str]) -> dict[str, Any]:
    return {k: tags[k] for k in keys if tags.get(k)}


def classify(infra_type: str, tags: dict[str, str], *, include_minor_line: bool = False):
    """Contract attributes for an element of `infra_type`, or None if it doesn't belong."""
    if infra_type == "substation":
        return _pick(tags, ("voltage", "operator")) if tags.get("power") == "substation" else None
    if infra_type == "power_line":
        allowed = {"line", "minor_line"} if include_minor_line else {"line"}
        return _pick(tags, ("voltage", "operator")) if tags.get("power") in allowed else None
    if infra_type == "road":
        is_ferry = tags.get("route") == "ferry"
        if not is_ferry and not ROAD_HIGHWAY_RE.match(tags.get("highway", "")):
            return None
        return {**_pick(tags, ("highway", "ref", "bridge")), "ferry": is_ferry}
    if infra_type == "hospital":
        if tags.get("amenity") in HEALTH_AMENITY or tags.get("healthcare") in HEALTH_HEALTHCARE:
            return {"facility_level": facility_level(tags)}
        return None
    if infra_type == "shelter":
        if has_shelter_indicator(tags):
            return {"shelter_kind": "cyclone_shelter"}
        if tags.get("emergency") == "assembly_point":
            return {"shelter_kind": "assembly_point"}
        if tags.get("amenity") == "school":
            return {"shelter_kind": "school_proxy"}
        return None
    raise ValueError(f"unknown infra_type {infra_type!r}")


# --- Overpass queries ---------------------------------------------------------------------------


def _overpass_bbox(bbox: tuple[float, float, float, float]) -> str:
    min_lon, min_lat, max_lon, max_lat = bbox
    return f"{min_lat},{min_lon},{max_lat},{max_lon}"


def _alternation(patterns: Iterable[str]) -> str:
    """Overpass regex; Bengali ড় ঢ় য় are matched both precomposed and decomposed."""
    out: list[str] = []
    for p in patterns:
        nfc = composed = _nfc(p)  # NFC leaves these three decomposed (composition exclusions)
        for pre, base in {"ড়": "ড", "ঢ়": "ঢ", "য়": "য"}.items():
            composed = composed.replace(base + "়", pre)
        out += [nfc, composed]
    return "|".join(dict.fromkeys(out)).replace('"', '\\"')


def _query(bbox: tuple[float, float, float, float], statements: Iterable[str], out: str) -> str:
    body = "\n  ".join(statements)
    return f"[out:json][timeout:180][bbox:{_overpass_bbox(bbox)}];\n(\n  {body}\n);\n{out};"


def infra_query(infra_type: str, bbox, *, include_minor_line: bool = False) -> str:
    road_re = ROAD_HIGHWAY_RE.pattern
    names = _alternation(SHELTER_NAME_PATTERNS)
    statements = {
        "substation": ['nwr["power"="substation"];'],
        "power_line": ['way["power"="line"];']
        + (['way["power"="minor_line"];'] if include_minor_line else []),
        "road": [f'way["highway"~"{road_re}"];', 'way["route"="ferry"];'],
        "hospital": [
            'nwr["amenity"~"^(hospital|clinic)$"];',
            'nwr["healthcare"~"^(hospital|clinic|centre)$"];',
        ],
        "shelter": [
            'nwr["emergency"="assembly_point"];',
            'nwr["amenity"="shelter"];',
            'nwr["amenity"="school"];',
            *(f'nwr["{k}"~"cyclone|flood",i];' for k in SHELTER_INDICATOR_KEYS),
            *(f'nwr["{k}"="yes"];' for k in SHELTER_FLAG_KEYS),
            f'nwr["name"~"{names}",i];',
            f'nwr["name:en"~"{names}",i];',
        ],
    }[infra_type]
    return _query(bbox, statements, "out geom")


def power_count_query(bbox) -> str:
    b = _overpass_bbox(bbox)
    return (
        f"[out:json][timeout:180][bbox:{b}];\n"
        'way["power"="line"];\nout count;\nway["power"="minor_line"];\nout count;'
    )


def boundary_query() -> str:
    ids = ",".join(str(i) for i in [*CLIP_RELATIONS, *BORDER_CHECK_RELATIONS])
    return f"[out:json][timeout:180];\nrel(id:{ids});\nout geom;"


def power_counts(data: dict) -> tuple[int, int]:
    """(power=line, power=minor_line) way counts from power_count_query's response."""
    line, minor = (int(e["tags"]["ways"]) for e in data["elements"] if e["type"] == "count")
    return line, minor


# --- Geometry -----------------------------------------------------------------------------------


def _coords(geometry: list[dict] | None) -> list[tuple[float, float]]:
    return [(p["lon"], p["lat"]) for p in geometry or [] if p]


def relation_area(members: list[dict]) -> BaseGeometry | None:
    """Assemble a multipolygon relation's way members into a (Multi)Polygon."""
    rings: dict[str, list[LineString]] = {"outer": [], "inner": []}
    for m in members:
        coords = _coords(m.get("geometry"))
        if m.get("type") == "way" and len(coords) >= 2:
            rings["inner" if m.get("role") == "inner" else "outer"].append(LineString(coords))
    outer = unary_union(list(polygonize(rings["outer"])))
    if outer.is_empty:
        return None
    if rings["inner"]:
        outer = outer.difference(unary_union(list(polygonize(rings["inner"]))))
    return outer


def element_geometry(
    element: dict, *, as_line: bool
) -> tuple[BaseGeometry | None, BaseGeometry | None]:
    """(feature geometry, source area). Lines stay lines; areas become their centroid."""
    kind = element["type"]
    if kind == "node":
        return Point(element["lon"], element["lat"]), None
    if kind == "way":
        coords = _coords(element.get("geometry"))
        if len(coords) < 2:
            return None, None
        if as_line:
            return LineString(coords), None
        if len(coords) >= 4 and coords[0] == coords[-1]:
            area = Polygon(coords)
            return area.centroid, area
        return LineString(coords).centroid, None
    if kind == "relation" and not as_line:
        area = relation_area(element.get("members", []))
        return (area.centroid, area) if area is not None else (None, None)
    return None, None


def clip_polygon(boundary: dict, relation_ids: Iterable[int] = CLIP_RELATIONS) -> BaseGeometry:
    """Union of the given admin relations from boundary_query's response."""
    wanted = set(relation_ids)
    parts = [
        relation_area(e.get("members", []))
        for e in boundary["elements"]
        if e["type"] == "relation" and e["id"] in wanted
    ]
    found = [p for p in parts if p is not None]
    if len(found) != len(wanted):
        raise ValueError(f"expected {len(wanted)} boundary relations, assembled {len(found)}")
    return shapely.make_valid(unary_union(found))


def area_km2(geom: BaseGeometry) -> float:
    return abs(_GEOD.geometry_area_perimeter(geom)[0]) / 1e6


# --- Normalising --------------------------------------------------------------------------------


@dataclass
class InfraRecord:
    id: str
    infra_type: str
    name: str | None
    osm_id: str
    attributes: dict[str, Any]
    geometry: BaseGeometry
    area: BaseGeometry | None = field(default=None, repr=False)  # source polygon, for dedupe


def infra_id(infra_type: str, osm_type: str, osm_number: int) -> str:
    return f"{infra_type.replace('_', '-')}-{osm_type}-{osm_number}"


def normalise(
    infra_type: str, data: dict, *, include_minor_line: bool = False
) -> list[InfraRecord]:
    """Overpass `out geom` JSON -> InfraRecords of one type (not yet deduped or clipped)."""
    as_line = infra_type in ("road", "power_line")
    records: dict[str, InfraRecord] = {}
    for element in data["elements"]:
        tags = element.get("tags", {})
        attributes = classify(infra_type, tags, include_minor_line=include_minor_line)
        if attributes is None:
            continue
        geometry, area = element_geometry(element, as_line=as_line)
        if geometry is None or geometry.is_empty:
            continue
        name = (tags.get("name") or tags.get("name:en") or "").strip() or None
        rid = infra_id(infra_type, element["type"], element["id"])
        records[rid] = InfraRecord(
            id=rid,
            infra_type=infra_type,
            name=name,
            osm_id=f"{element['type']}/{element['id']}",
            attributes=attributes,
            geometry=geometry,
            area=area,
        )
    return list(records.values())


# --- Deduplication (health facilities) ----------------------------------------------------------

DEDUPE_NAME_DISTANCE_M = 100.0
_LEVEL_RANK = {"health_centre": 0, "hospital": 1}


def _norm_name(name: str | None) -> str | None:
    if not name:
        return None
    return " ".join(re.sub(r"[^\w\s]", " ", _nfc(name).casefold()).split()) or None


def _merge_into(kept: InfraRecord, dropped: InfraRecord) -> None:
    kept.name = kept.name or dropped.name
    a, b = kept.attributes.get("facility_level"), dropped.attributes.get("facility_level")
    if a and b and _LEVEL_RANK[b] > _LEVEL_RANK[a]:
        kept.attributes["facility_level"] = b


def _priority(r: InfraRecord) -> tuple[int, int]:
    """Lower sorts first = kept: areas beat nodes, then the smaller OSM id."""
    return (0 if r.area is not None else 1, int(r.osm_id.split("/")[1]))


def dedupe_health(records: list[InfraRecord]) -> list[InfraRecord]:
    """Drop duplicate facilities: same OSM id; a node inside a facility polygon; the same name
    within DEDUPE_NAME_DISTANCE_M. The kept record takes the higher facility_level."""
    by_id = {r.id: r for r in records}
    kept = sorted(by_id.values(), key=_priority)

    areas = [r for r in kept if r.area is not None]
    if areas:
        tree = shapely.STRtree([r.area for r in areas])
        survivors = []
        for r in kept:
            if r.area is None:
                hits = tree.query(r.geometry, predicate="within")
                if len(hits):
                    _merge_into(areas[int(hits[0])], r)
                    continue
            survivors.append(r)
        kept = survivors

    groups: dict[str, list[InfraRecord]] = {}
    for r in kept:
        if key := _norm_name(r.name):
            groups.setdefault(key, []).append(r)
    dropped: set[str] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        pts = gpd.GeoSeries([r.geometry for r in group], crs="EPSG:4326").to_crs(METRIC_CRS)
        for i, a in enumerate(group):
            if a.id in dropped:
                continue
            for j in range(i + 1, len(group)):
                b = group[j]
                near = pts.iloc[i].distance(pts.iloc[j]) <= DEDUPE_NAME_DISTANCE_M
                if near and b.id not in dropped:
                    _merge_into(a, b)
                    dropped.add(b.id)
    return [r for r in kept if r.id not in dropped]


# --- Clipping -----------------------------------------------------------------------------------


def _line_parts(geom: BaseGeometry) -> list[LineString]:
    if isinstance(geom, LineString):
        return [] if geom.is_empty else [geom]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _line_parts(g)]
    return []


def clip_records(records: list[InfraRecord], polygon: BaseGeometry) -> list[InfraRecord]:
    """Points must lie inside `polygon`; lines are cut to it (a split way -> MultiLineString)."""
    shapely.prepare(polygon)
    out = []
    for r in records:
        g = r.geometry
        if isinstance(g, Point):
            if polygon.covers(g):
                out.append(r)
            continue
        if polygon.covers(g):
            out.append(r)
            continue
        if not polygon.intersects(g):
            continue
        merged = shapely.line_merge(MultiLineString(_line_parts(polygon.intersection(g))))
        parts = _line_parts(merged)
        if not parts:
            continue
        r.geometry = parts[0] if len(parts) == 1 else MultiLineString(parts)
        out.append(r)
    return out


# --- Output -------------------------------------------------------------------------------------


def to_feature(r: InfraRecord) -> InfraFeature:
    """Validate a record as a contract InfraFeature."""
    return InfraFeature.model_validate(
        {
            "type": "Feature",
            "id": r.id,
            "geometry": mapping(r.geometry),
            "properties": {
                "id": r.id,
                "infra_type": r.infra_type,
                "name": r.name,
                "osm_id": r.osm_id,
                "attributes": r.attributes,
            },
        }
    )


def to_geodataframe(records: list[InfraRecord]) -> gpd.GeoDataFrame:
    """One row per feature; `attributes` is a JSON string (per-type keys don't fit a struct)."""
    for r in records:
        to_feature(r)
    return gpd.GeoDataFrame(
        {
            "id": [r.id for r in records],
            "infra_type": [r.infra_type for r in records],
            "name": [r.name for r in records],
            "osm_id": [r.osm_id for r in records],
            "attributes": [json.dumps(r.attributes, ensure_ascii=False) for r in records],
        },
        geometry=[r.geometry for r in records],
        crs="EPSG:4326",
    )


def write_infra(records: list[InfraRecord], path: Path = INFRA_PARQUET) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    to_geodataframe(records).to_parquet(path, index=False)


def read_infra(path: Path = INFRA_PARQUET, infra_type: InfraType | None = None) -> gpd.GeoDataFrame:
    gdf = gpd.read_parquet(path)
    return gdf if infra_type is None else gdf[gdf["infra_type"] == infra_type]


# --- Road graph ---------------------------------------------------------------------------------

ROAD_GRAPH_FILTERS = [f'["highway"~"{ROAD_HIGHWAY_RE.pattern}"]', '["route"="ferry"]']
GRAPH_WAY_TAGS = ("route", "ferry")  # added to osmnx useful_tags_way

# km/h for edges without a usable maxspeed tag (rarely tagged here).
HWY_SPEEDS_KPH: dict[str, float] = {
    "motorway": 80, "motorway_link": 80,
    "trunk": 60, "trunk_link": 60,
    "primary": 50, "primary_link": 50,
    "secondary": 40, "secondary_link": 40,
    "tertiary": 30, "tertiary_link": 30,
    "unclassified": 20,
}  # fmt: skip
FALLBACK_SPEED_KPH = 20.0
FERRY_SPEED_KPH = 12.0
FERRY_BOARDING_S = 15 * 60  # added once per ferry edge


def _edge_osmid(value: Any) -> int:
    if isinstance(value, list):
        raise ValueError(f"edge spans several OSM ways: {value}")
    return int(value)


def finish_road_graph(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Mark ferries, check one way id per edge, add speed_kph and travel_time (s)."""
    for _, _, d in G.edges(data=True):
        d["osmid"] = _edge_osmid(d["osmid"])
        d["ferry"] = d.get("route") == "ferry"
    ox.add_edge_speeds(G, hwy_speeds=HWY_SPEEDS_KPH, fallback=FALLBACK_SPEED_KPH)
    for _, _, d in G.edges(data=True):
        if d["ferry"]:
            d["speed_kph"] = FERRY_SPEED_KPH
    ox.add_edge_travel_times(G)
    for _, _, d in G.edges(data=True):
        if d["ferry"]:
            d["travel_time"] += FERRY_BOARDING_S
    return G


def _bool(value: str) -> bool:
    return value == "True"


def save_road_graph(G: nx.MultiDiGraph, path: Path = ROADS_GRAPHML) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, path)


def load_road_graph(path: Path = ROADS_GRAPHML) -> nx.MultiDiGraph:
    """Load roads.graphml with `ferry` (and `connector`, if present) restored to bool."""
    return ox.load_graphml(path, edge_dtypes={"ferry": _bool, "connector": _bool})


# --- Graph analysis -----------------------------------------------------------------------------

# Approximate reference points (lon, lat); reports include the snap distance to the graph.
MAINLAND_REF = ("Kolkata (Esplanade)", (88.351, 22.565))
ISLAND_REFS: dict[str, tuple[float, float]] = {
    "Gosaba": (88.807, 22.165),
    "Sagar Island": (88.080, 21.660),
}


def nearest_node(G: nx.MultiDiGraph, lon: float, lat: float) -> tuple[Any, float]:
    """(node id, distance m) of the node closest to (lon, lat). No scikit-learn needed."""
    ids = list(G.nodes)
    xs = np.array([G.nodes[n]["x"] for n in ids])
    ys = np.array([G.nodes[n]["y"] for n in ids])
    _, _, dist = _GEOD.inv(np.full_like(xs, lon), np.full_like(ys, lat), xs, ys)
    i = int(np.argmin(dist))
    return ids[i], float(dist[i])


def _component_index(G: nx.Graph) -> dict[Any, int]:
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    return {n: i for i, c in enumerate(comps) for n in c}


def undirected(G: nx.MultiDiGraph, *, ferries: bool = True) -> nx.Graph:
    H = nx.Graph()
    H.add_nodes_from(G.nodes)
    H.add_edges_from((u, v) for u, v, d in G.edges(data=True) if ferries or not d.get("ferry"))
    return H


def component_sizes(G: nx.MultiDiGraph) -> list[int]:
    return sorted((len(c) for c in nx.connected_components(undirected(G))), reverse=True)


def island_links(
    G: nx.MultiDiGraph,
    places: dict[str, tuple[float, float]] = ISLAND_REFS,
    mainland: tuple[str, tuple[float, float]] = MAINLAND_REF,
) -> dict[str, dict[str, Any]]:
    """For each place: snap distance, joined to the mainland, and whether only via ferries."""
    with_ferry = _component_index(undirected(G))
    without_ferry = _component_index(undirected(G, ferries=False))
    home, _ = nearest_node(G, *mainland[1])
    out = {}
    for name, (lon, lat) in places.items():
        node, dist = nearest_node(G, lon, lat)
        joined = with_ferry[node] == with_ferry[home]
        joined_by_road = without_ferry[node] == without_ferry[home]
        out[name] = {
            "snap_m": round(dist),
            "joined": joined,
            "via_ferry": joined and not joined_by_road,
        }
    return out


def ferry_endpoints_off_network(G: nx.MultiDiGraph) -> list[Any]:
    """Ferry edge endpoints with no road (non-ferry) edge: the ferry doesn't touch a road."""
    ends = {n for u, v, d in G.edges(data=True) if d.get("ferry") for n in (u, v)}
    return [
        n
        for n in ends
        if all(d.get("ferry") for *_, d in G.edges(n, data=True))
        and all(d.get("ferry") for *_, d in G.in_edges(n, data=True))
    ]
