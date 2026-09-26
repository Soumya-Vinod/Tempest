"""OSM infrastructure ingest and road graph for the exposure module.

Everything here is network-free: it turns cached Overpass JSON into contract InfraFeatures and
builds the road graph from the cached road response. Downloading lives in scripts/ingest_osm.py.
"""

import json
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
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
# Every admin unit touching the clip districts. Water gaps are filled only where no neighbour is.
NEIGHBOUR_RELATIONS: dict[int, str] = {
    9381362: "Howrah",
    9513028: "North 24 Parganas",
    3390340: "Purba Medinipur",
    1970297: "Hooghly",
    **BORDER_CHECK_RELATIONS,
}
# The district polygons leave out wide river channels (e.g. the Muriganga between Sagar Island
# and the mainland), which would cut ferries and bridges. Channels up to 2 x this are filled.
WATER_GAP_M = 2000.0

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
# Government buildings that are not places to shelter people: forest department offices, camps
# and posts (the Sundarbans reserve has many, tagged office=government). Never a
# public_building_proxy, wherever they are. Matched on name / name:en, case-insensitive.
PUBLIC_BUILDING_EXCLUDE_PATTERNS: tuple[str, ...] = (
    r"\b(forest|range|beat)\s+office",
    r"\bforest\s+camp",
    r"\bpermissions?\s+counter",
    r"\bcheck\s*-?\s*post",
    r"\bwatch\s*-?\s*tower",
)

# shelter_kind values, highest priority first. An element matching several keeps the first.
# The *_proxy kinds are stand-ins: buildings that could shelter people, not designated shelters.
SHELTER_KINDS: tuple[str, ...] = (
    "cyclone_shelter",
    "assembly_point",
    "school_proxy",
    "community_proxy",
    "public_building_proxy",
)
STAND_IN_KINDS = frozenset(k for k in SHELTER_KINDS if k.endswith("_proxy"))
STAND_IN_RULES: tuple[tuple[str, Any], ...] = (
    (
        "school_proxy",
        lambda t: (
            t.get("amenity") in {"school", "college", "university"} or t.get("building") == "school"
        ),
    ),
    ("community_proxy", lambda t: t.get("amenity") in {"community_centre", "townhall"}),
    (
        "public_building_proxy",
        lambda t: (
            (t.get("office") == "government" or t.get("building") in {"public", "civic"})
            and not _excluded_public_building(t)
        ),
    ),
)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


SHELTER_NAME_RE = re.compile("|".join(_nfc(p) for p in SHELTER_NAME_PATTERNS), re.IGNORECASE)
PUBLIC_BUILDING_EXCLUDE_RE = re.compile("|".join(PUBLIC_BUILDING_EXCLUDE_PATTERNS), re.IGNORECASE)


def _excluded_public_building(tags: dict[str, str]) -> bool:
    return any(PUBLIC_BUILDING_EXCLUDE_RE.search(n) for n in _names(tags))


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
        for kind, is_kind in STAND_IN_RULES:
            if is_kind(tags):
                return {"shelter_kind": kind}
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
    """One `out geom` query per infra type. For shelters this is the cheap tag query only; the
    name regex runs locally in classify() and, for untagged elements, in shelter_name_queries()."""
    road_re = ROAD_HIGHWAY_RE.pattern
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
            'nwr["shelter_type"~"cyclone|flood",i];',
            'nwr["building"~"^(public|civic)$"]["name"];',
        ],
    }[infra_type]
    return _query(bbox, statements, "out geom")


def standin_candidate_query(bbox) -> str:
    """Stand-in candidates beyond the tag query: `out center` (centres only; these are points)."""
    return _query(
        bbox,
        [
            'nwr["amenity"~"^(community_centre|townhall|college|university)$"];',
            'nwr["office"="government"];',
            'nwr["building"~"^(school|public|civic)$"];',
        ],
        "out center",
    )


def bbox_tiles(bbox: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    """2 x 2 tiles, numbered 1..4 row by row from the south-west: SW, SE, NW, NE."""
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lon, mid_lat = (min_lon + max_lon) / 2, (min_lat + max_lat) / 2
    return [
        (min_lon, min_lat, mid_lon, mid_lat),
        (mid_lon, min_lat, max_lon, mid_lat),
        (min_lon, mid_lat, mid_lon, max_lat),
        (mid_lon, mid_lat, max_lon, max_lat),
    ]


def shelter_name_queries(bbox) -> list[str]:
    """Cyclone / flood shelter name search on `name` and `name:en`, one query per tile."""
    names = _alternation(SHELTER_NAME_PATTERNS)
    statements = [f'nwr["name"~"{names}",i];', f'nwr["name:en"~"{names}",i];']
    return [_query(tile, statements, "out geom") for tile in bbox_tiles(bbox)]


def merge_responses(responses: Iterable[dict]) -> dict:
    """Concatenate Overpass `elements`; normalise() dedupes elements seen in several responses."""
    return {"elements": [e for r in responses for e in r["elements"]]}


def power_count_query(bbox) -> str:
    b = _overpass_bbox(bbox)
    return (
        f"[out:json][timeout:180][bbox:{b}];\n"
        'way["power"="line"];\nout count;\nway["power"="minor_line"];\nout count;'
    )


def boundary_query() -> str:
    ids = ",".join(str(i) for i in [*CLIP_RELATIONS, *NEIGHBOUR_RELATIONS])
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
    """(feature geometry, source area). Lines stay lines; areas become their centroid.

    `out center` responses give ways and relations only a centre point; that is used as is.
    """
    kind = element["type"]
    if kind == "node":
        return Point(element["lon"], element["lat"]), None
    if "center" in element and not element.get("geometry") and not element.get("members"):
        if as_line:
            return None, None
        return Point(element["center"]["lon"], element["center"]["lat"]), None
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
    valid = shapely.make_valid(unary_union(found))
    # make_valid may return a GeometryCollection; keep only its polygonal parts.
    return unary_union([g for g in getattr(valid, "geoms", [valid]) if g.area > 0])


def fill_water_gaps(
    land: BaseGeometry, neighbours: BaseGeometry, gap_m: float = WATER_GAP_M
) -> BaseGeometry:
    """Close channels narrower than 2 * gap_m between the land parts, minus every neighbour.

    A morphological closing (buffer out, then in) in metres. Subtracting the neighbouring admin
    units means the added area can only be water, never another district or Bangladesh.
    """
    series = gpd.GeoSeries([land, neighbours], crs="EPSG:4326").to_crs(METRIC_CRS)
    land_m, neighbours_m = series.iloc[0], series.iloc[1]
    closed = land_m.buffer(gap_m).buffer(-gap_m).union(land_m).difference(neighbours_m)
    return shapely.make_valid(gpd.GeoSeries([closed], crs=METRIC_CRS).to_crs("EPSG:4326").iloc[0])


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


def _kind_rank(attributes: dict[str, Any]) -> int:
    """Priority of a shelter_kind (0 = highest); 0 for every other type."""
    kind = attributes.get("shelter_kind")
    return SHELTER_KINDS.index(kind) if kind else 0


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
        if rid in records and _kind_rank(records[rid].attributes) <= _kind_rank(attributes):
            continue  # same element seen in another response: keep the better / first copy
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


# An unnamed hospital / health centre this close (outline to outline) to a named one is the same
# facility mapped twice. 120 m: Sagar's unnamed hospital outline is 108 m from Gangasagar PHC, a
# same-compound duplicate; in the current data 120 m merges nothing else inside the AOI.
UNNAMED_MERGE_M = 120.0


@dataclass(frozen=True)
class Merge:
    dropped: str  # the unnamed facility's id
    kept: str  # the named facility's id
    kept_name: str
    distance_m: float


def merge_unnamed_health(
    records: list[InfraRecord], max_m: float = UNNAMED_MERGE_M
) -> tuple[list[InfraRecord], list[Merge]]:
    """Merge each unnamed hospital / health centre into the nearest named one within `max_m`
    (outline to outline: the source polygon where there is one). The named record is kept as it
    is (name and facility_level); two named facilities are never merged."""
    named = [r for r in records if r.name]
    unnamed = [r for r in records if not r.name]
    if not named or not unnamed:
        return records, []

    def metric(rs: list[InfraRecord]) -> list[BaseGeometry]:
        shapes = [r.area if r.area is not None else r.geometry for r in rs]
        return list(gpd.GeoSeries(shapes, crs="EPSG:4326").to_crs(METRIC_CRS))

    named_m = metric(named)
    tree = shapely.STRtree(named_m)
    merges: list[Merge] = []
    for r, geom in zip(unnamed, metric(unnamed), strict=True):
        i = tree.nearest(geom)
        if i is None:
            continue
        d = float(named_m[int(i)].distance(geom))
        if d <= max_m:
            kept = named[int(i)]
            merges.append(Merge(r.id, kept.id, kept.name or "", round(d, 1)))
    dropped = {m.dropped for m in merges}
    return [r for r in records if r.id not in dropped], merges


STAND_IN_DEDUPE_M = 50.0


def dedupe_shelters(records: list[InfraRecord]) -> list[InfraRecord]:
    """Drop a stand-in within STAND_IN_DEDUPE_M of another stand-in with the same normalised name,
    or, if both are unnamed, the same shelter_kind. The higher-priority kind is kept, then an area
    over a node, then the smaller OSM id. Real shelters are never dropped."""
    stand_ins = sorted(
        (r for r in records if r.attributes["shelter_kind"] in STAND_IN_KINDS),
        key=lambda r: (_kind_rank(r.attributes), *_priority(r)),
    )
    groups: dict[tuple[str, str], list[InfraRecord]] = {}
    for r in stand_ins:
        key = ("name", n) if (n := _norm_name(r.name)) else ("kind", r.attributes["shelter_kind"])
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
                if b.id not in dropped and pts.iloc[i].distance(pts.iloc[j]) <= STAND_IN_DEDUPE_M:
                    a.name = a.name or b.name
                    dropped.add(b.id)
    return [r for r in records if r.id not in dropped]


# --- Protected areas ---


def protected_areas_query(bbox: tuple[float, float, float, float]) -> str:
    """OSM protected areas (reserve forest, sanctuaries, national park) in the AOI bbox."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        f"[out:json][timeout:180][bbox:{min_lat},{min_lon},{max_lat},{max_lon}];\n(\n"
        '  nwr["boundary"="protected_area"];\n'
        '  nwr["leisure"="nature_reserve"];\n'
        '  nwr["boundary"="national_park"];\n'
        ");\nout geom;"
    )


def protected_polygons(data: dict) -> list[tuple[str, BaseGeometry]]:
    """(label, polygon) for every protected area with an area geometry (closed way / relation)."""
    out = []
    for e in data["elements"]:
        if e["type"] == "relation":
            geom = relation_area(e.get("members", []))
        elif e["type"] == "way":
            coords = _coords(e.get("geometry"))
            geom = Polygon(coords) if len(coords) >= 4 and coords[0] == coords[-1] else None
        else:
            geom = None  # nodes have no area
        if geom is not None and not geom.is_empty:
            tags = e.get("tags", {})
            label = (
                f"{tags.get('name:en') or tags.get('name') or 'unnamed'} ({e['type']}/{e['id']})"
            )
            out.append((label, shapely.make_valid(geom)))
    return out


def drop_protected_stand_ins(
    records: list[InfraRecord], protected: BaseGeometry
) -> tuple[list[InfraRecord], list[InfraRecord]]:
    """(kept, dropped): no stand-in shelter (*_proxy) inside a protected area. The reserve is
    uninhabited; buildings there are forest department posts, not places to shelter people.
    Designated shelters, hospitals and health centres are kept."""
    shapely.prepare(protected)
    kept, dropped = [], []
    for r in records:
        stand_in = r.attributes.get("shelter_kind") in STAND_IN_KINDS
        (dropped if stand_in and protected.covers(r.geometry) else kept).append(r)
    return kept, dropped


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

GRAPH_WAY_TAGS = ("route", "ferry")  # kept as edge attributes, beyond osmnx useful_tags_way

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
MAX_FERRY_KM = 50.0  # longer route=ferry ways are ships (e.g. Kolkata - Port Blair), not ferries
# A ferry end with no road edge is joined to the nearest road node within this distance.
CONNECTOR_MAX_M = 500.0
CONNECTOR_SPEED_KPH = 5.0  # walking the ghat / jetty


def drop_long_ferries(road_data: dict, max_km: float = MAX_FERRY_KM) -> dict:
    """Road response without route=ferry ways longer than max_km (long-distance ships)."""

    def keep(e: dict) -> bool:
        if e.get("tags", {}).get("route") != "ferry":
            return True
        coords = _coords(e.get("geometry"))
        return len(coords) < 2 or _GEOD.geometry_length(LineString(coords)) / 1000 <= max_km

    return {**road_data, "elements": [e for e in road_data["elements"] if keep(e)]}


def write_osm_xml(data: dict, path: Path) -> None:
    """Overpass `out geom` ways -> minimal OSM XML for ox.graph_from_xml.

    Topology comes from the ways' `nodes` id lists (shared ids join ways); coordinates come from
    the aligned `geometry` list. A way without an aligned id list is an error, not skipped.
    """
    root = ET.Element("osm", version="0.6", generator="tempest-ingest")
    ways = [e for e in data["elements"] if e["type"] == "way"]
    coords: dict[int, tuple[float, float]] = {}
    for w in ways:
        nodes, geometry = w.get("nodes") or [], w.get("geometry") or []
        if len(nodes) < 2 or len(nodes) != len(geometry):
            raise ValueError(f"way {w['id']}: node ids missing or not aligned with geometry")
        for n, p in zip(nodes, geometry, strict=True):
            coords.setdefault(n, (p["lat"], p["lon"]))
    for n, (lat, lon) in coords.items():
        ET.SubElement(root, "node", id=str(n), lat=f"{lat:.7f}", lon=f"{lon:.7f}")
    for w in ways:
        way = ET.SubElement(root, "way", id=str(w["id"]))
        for n in w["nodes"]:
            ET.SubElement(way, "nd", ref=str(n))
        for k, v in w.get("tags", {}).items():
            ET.SubElement(way, "tag", k=k, v=v)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def build_road_graph(road_data: dict, polygon: BaseGeometry) -> nx.MultiDiGraph:
    """Road graph from the cached Overpass road response (road classes + ferries).

    Every connected component is kept (retain_all), edges crossing the polygon boundary are
    kept whole (truncate_by_edge), and simplification never merges across OSM ways, so each
    edge carries exactly one way id.
    """
    default_tags = ox.settings.useful_tags_way
    ox.settings.useful_tags_way = list(dict.fromkeys([*default_tags, *GRAPH_WAY_TAGS]))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            xml = Path(tmp) / "roads.osm"
            write_osm_xml(road_data, xml)
            G = ox.graph_from_xml(xml, simplify=False, retain_all=True)
    finally:
        ox.settings.useful_tags_way = default_tags
    G = ox.truncate.truncate_graph_polygon(G, polygon, truncate_by_edge=True)
    for _, _, d in G.edges(data=True):
        d["ferry"] = d.get("route") == "ferry"
        d["connector"] = False
    # Before simplifying, so ferry ends can snap to any road vertex, not only intersections.
    connect_ferry_ends(G)
    # A connector shares its ferry's osmid; "connector" keeps the two from being merged.
    G = ox.simplify_graph(G, edge_attrs_differ=["osmid", "connector"])
    return finish_road_graph(G)


def _road_nodes(G: nx.MultiDiGraph) -> list[Any]:
    return sorted({n for u, v, d in G.edges(data=True) if not d.get("ferry") for n in (u, v)})


def connect_ferry_ends(G: nx.MultiDiGraph, max_m: float = CONNECTOR_MAX_M) -> int:
    """Join each ferry end that touches no road to the nearest road node within max_m.

    The ghat approach is often a path or service road outside the road classes, so the ferry
    stops short. Connector edges (both directions) carry the ferry's OSM way id, so they map back
    to the ferry's road feature, and are marked connector=True. Returns the number joined.
    """
    road = _road_nodes(G)
    if not road:
        return 0
    xs = np.array([G.nodes[n]["x"] for n in road])
    ys = np.array([G.nodes[n]["y"] for n in road])
    joined = 0
    for end in ferry_endpoints_off_network(G):
        x, y = G.nodes[end]["x"], G.nodes[end]["y"]
        _, _, dist = _GEOD.inv(np.full_like(xs, x), np.full_like(ys, y), xs, ys)
        i = int(np.argmin(np.abs(dist)))
        if abs(dist[i]) > max_m:
            continue
        osmid = next(
            d["osmid"] for *_, d in [*G.edges(end, data=True), *G.in_edges(end, data=True)]
        )
        for u, v in ((end, road[i]), (road[i], end)):
            G.add_edge(u, v, osmid=osmid, length=float(abs(dist[i])), ferry=False, connector=True)
        joined += 1
    return joined


def _edge_osmid(value: Any) -> int:
    if isinstance(value, list):
        raise ValueError(f"edge spans several OSM ways: {value}")
    return int(value)


def finish_road_graph(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Mark ferries and connectors, check one way id per edge, add speed_kph and travel_time."""
    for _, _, d in G.edges(data=True):
        d["osmid"] = _edge_osmid(d["osmid"])
        d["ferry"] = d.get("route") == "ferry"
        d.setdefault("connector", False)
    ox.add_edge_speeds(G, hwy_speeds=HWY_SPEEDS_KPH, fallback=FALLBACK_SPEED_KPH)
    for _, _, d in G.edges(data=True):
        if d["ferry"]:
            d["speed_kph"] = FERRY_SPEED_KPH
        elif d["connector"]:
            d["speed_kph"] = CONNECTOR_SPEED_KPH
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
    """Load roads.graphml with bool / int attributes restored (GraphML stores strings)."""
    return ox.load_graphml(
        path,
        node_dtypes={"baseline_component": int, "baseline_reachable_from_main": _bool},
        edge_dtypes={"ferry": _bool, "connector": _bool},
    )


# --- Baseline connectivity ----------------------------------------------------------------------
# Impact status "isolated" means reachable at baseline and unreachable under hazard, so features
# already cut off from the main component at baseline carry a flag instead (contracts.md §4.3).


def annotate_components(G: nx.MultiDiGraph) -> list[int]:
    """Set baseline_component (0 = largest) and baseline_reachable_from_main on every node.

    Components are weakly connected, ordered by size, then by lowest node id so the numbering
    is stable across runs. Returns the component sizes in that order.
    """
    comps = sorted(nx.connected_components(undirected(G)), key=lambda c: (-len(c), min(c)))
    for i, comp in enumerate(comps):
        for n in comp:
            G.nodes[n]["baseline_component"] = i
            G.nodes[n]["baseline_reachable_from_main"] = i == 0
    return [len(c) for c in comps]


def way_components(G: nx.MultiDiGraph) -> dict[int, int]:
    """OSM way id -> baseline_component of its edges; a way split across components (e.g. by
    the polygon boundary) takes the lowest index, i.e. its best-connected part."""
    out: dict[int, int] = {}
    for u, _, d in G.edges(data=True):
        comp = G.nodes[u]["baseline_component"]
        out[d["osmid"]] = min(comp, out.get(d["osmid"], comp))
    return out


def annotate_roads(records: list[InfraRecord], components: dict[int, int]) -> int:
    """Copy baseline connectivity onto road features via their way id. A road with no edge in
    the graph gets baseline_component None and is not reachable. Returns how many had none."""
    missing = 0
    for r in records:
        if r.infra_type != "road":
            continue
        comp = components.get(int(r.osm_id.split("/")[1]))
        missing += comp is None
        r.attributes["baseline_component"] = comp
        r.attributes["baseline_reachable_from_main"] = comp == 0
    return missing


def road_index(infra: gpd.GeoDataFrame) -> dict[int, str]:
    """OSM way id -> road feature id, from infra.parquet (read_infra)."""
    roads = infra[infra["infra_type"] == "road"]
    return {int(o.split("/")[1]): fid for o, fid in zip(roads["osm_id"], roads["id"], strict=True)}


def road_feature_for_way(index: dict[int, str], way_id: int) -> str | None:
    """Road feature id for a graph edge's way id, or None if the way has no road feature (an
    edge kept across the clip boundary whose clipped feature came out empty)."""
    return index.get(int(way_id))


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


def ferry_way_ends(G: nx.MultiDiGraph) -> set[Any]:
    """First and last node of every ferry way (not its interior vertices), in any graph state.

    Within one OSM way, an end has a single neighbour; an interior vertex has two.
    """
    neighbours: dict[tuple[int, Any], set[Any]] = {}
    for u, v, d in G.edges(data=True):
        if d.get("ferry"):
            neighbours.setdefault((d["osmid"], u), set()).add(v)
            neighbours.setdefault((d["osmid"], v), set()).add(u)
    return {n for (_, n), nbrs in neighbours.items() if len(nbrs) == 1}


def ferry_endpoints_off_network(G: nx.MultiDiGraph) -> list[Any]:
    """Ferry way ends with no road (non-ferry) edge: the ferry doesn't touch a road."""
    return sorted(
        n
        for n in ferry_way_ends(G)
        if all(d.get("ferry") for *_, d in G.edges(n, data=True))
        and all(d.get("ferry") for *_, d in G.in_edges(n, data=True))
    )
