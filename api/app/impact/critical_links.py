"""Critical links for GET /api/impact/critical-links (v1.4 change, pending Dev A).

The roads and ferry crossings that the most last safe departure routes depend on. The routes are
the committed ones (app/impact/departures.py): from each facility to its nearest safe hospital
at its deadline step, under normal conditions. At a timestep:
- horizon 0: the routes of facilities whose deadline has not passed (deadline >= timestep);
- horizon 24: of those, the ones whose deadline falls within the next 24 h (a route that stays
  open to T-0 has no real deadline, so it is left out).

Each OSM way counts the facilities whose route uses it. OSM splits one road or crossing into many
ways, so ways that follow each other on a route, have the same name (or are both unnamed, of the
same type) and serve exactly the same facilities are listed as one link (way_ids, in the
direction of travel); every way in a link has the link's count. Ranked by that count, then the
earliest deadline among the facilities, then the label.

The departures fixture keeps each route only as simplified geometry, so the way ids come from
re-running its routing on the road graph (scripts/build_critical_links_fixture.py), which must
reproduce the committed departures fixture exactly. The fixture, impact__critical-links, stores
each facility's route as ways (facility to destination, and whether it follows the way's
coordinate order) and, per way, its name, type, CD blocks (in coordinate order) and geometry
(the exposure road feature's). The ranking per timestep and horizon is computed on request from
it and the departures fixture: no graph, no hazard layers.

Labels: the OSM name, else "Unnamed road" / "Unnamed ferry route" (as on the map), then the CD
block(s) it runs through, in the direction of travel of the facility with the earliest deadline:
"Unnamed road (Sagar → Namkhana)".
"""

from functools import lru_cache
from typing import Any

import shapely
from shapely.geometry import MultiLineString, Point, shape

from app.core.config import get_settings
from app.impact import countdown, departures
from app.impact.horizon import FORECAST_HORIZON_H
from app.impact.network import ImpactNetwork
from app.schemas import LIVE, REPLAY_TIMESTEPS, CriticalLinks

FIXTURE_KEY = "impact__critical-links"
NOTE = "Based on normal-condition routes to the nearest safe hospital."
STEP_H = 3  # the replay's resolution
DENSIFY_DEG = 0.0005  # ~50 m between the points that place a way in blocks
MIN_BLOCK_SHARE = 0.05  # a block holding less of the way than this is a boundary sliver


class CriticalLinksMissing(RuntimeError):
    """The impact__critical-links fixture has not been built."""


class DeparturesOutOfDate(RuntimeError):
    """Re-running the departure routing no longer reproduces the committed departures fixture."""


# --- Build (road graph) ---------------------------------------------------------------------------


def blocks_along(line, names: list[str], polygons: list) -> list[str]:
    """The CD blocks `line` runs through, in its coordinate order. Points every ~50 m; a block
    needs MIN_BLOCK_SHARE of them (slivers along a boundary don't count). A way in no block
    (out at sea) gets the nearest one."""
    dense = shapely.segmentize(line, DENSIFY_DEG)
    parts = dense.geoms if isinstance(dense, MultiLineString) else [dense]
    points = shapely.points([c for part in parts for c in part.coords])
    tree = shapely.STRtree(polygons)
    point_idx, block_idx = tree.query(points, predicate="within")
    if len(point_idx) == 0:
        return [names[int(tree.nearest(line.centroid))]]
    first: dict[int, int] = {}
    count: dict[int, int] = {}
    for p, b in sorted(zip(point_idx.tolist(), block_idx.tolist(), strict=True)):
        first.setdefault(b, p)
        count[b] = count.get(b, 0) + 1
    keep = [b for b in first if count[b] >= MIN_BLOCK_SHARE * len(points)] or [
        max(count, key=count.__getitem__)
    ]
    return [names[b] for b in sorted(keep, key=first.__getitem__)]


def compute(
    net: ImpactNetwork,
    hops: dict[str, list[tuple[Any, Any, int]]],
    roads: dict[str, dict],
    block_names: list[str],
    block_polygons: list,
) -> dict:
    """The fixture from the departure routes' hops (departures.compute's hops_out), the exposure
    road features by id and the CD block polygons (EPSG:4326)."""
    xy = dict(zip(net.node_ids, map(tuple, net.node_xy), strict=True))
    ends: dict[str, dict[int, list[tuple]]] = {}  # facility -> way -> [entry, exit] point
    for infra_id in sorted(hops):
        ends[infra_id] = {}
        for a, b, link in hops[infra_id]:
            w = int(net.link_osmid[link])
            ends[infra_id].setdefault(w, [xy[a], xy[b]])[1] = xy[b]

    lines, links = {}, {}
    for w in sorted({w for e in ends.values() for w in e}):
        feature = roads.get(f"road-way-{w}")
        if feature is None:
            raise KeyError(f"way {w} is on a departure route but not in exposure__infra-road")
        lines[w] = shape(feature["geometry"])
        links[str(w)] = {
            "name": feature["properties"]["name"],
            "link_type": "ferry" if feature["properties"]["attributes"].get("ferry") else "road",
            "blocks": blocks_along(lines[w], block_names, block_polygons),
            "geometry": feature["geometry"],
        }
    routes = {
        infra_id: [
            [w, lines[w].project(Point(a)) <= lines[w].project(Point(b))] for w, (a, b) in e.items()
        ]
        for infra_id, e in ends.items()
    }
    return {"note": NOTE, "routes": routes, "links": links}


def build() -> dict:
    """From the road graph, the hazard layers (via departures.inputs) and the committed
    departures, exposure and block files. The build script and the fresh-build test use this."""
    from app.risk.blocks import load_blocks

    committed = countdown._read(departures.FIXTURE_KEY)
    net, steps, facilities, destinations = departures.inputs()
    hops: dict[str, list] = {}
    if departures.compute(net, steps, facilities, destinations, hops_out=hops) != committed:
        raise DeparturesOutOfDate(
            f"{departures.FIXTURE_KEY}.json is out of date: run build_departures_fixture.py first"
        )
    roads = {f["id"]: f for f in countdown._read("exposure__infra-road")["features"]}
    blocks = load_blocks()
    return compute(net, hops, roads, list(blocks.names), list(blocks.geometry))


# --- Service ------------------------------------------------------------------------------------


def eligible(departures_data: dict, timestep: str, horizon_h: int) -> list[dict]:
    """The departures whose route counts at `timestep`, by deadline, then name."""
    now = REPLAY_TIMESTEPS.index(timestep)
    until = now + FORECAST_HORIZON_H // STEP_H
    out = []
    for d in departures_data["departures"]:
        if d["deadline"] is None:
            continue
        deadline = REPLAY_TIMESTEPS.index(d["deadline"])
        if deadline < now:
            continue
        if horizon_h == FORECAST_HORIZON_H and (d["route_stays_open"] or deadline > until):
            continue
        out.append(d)
    return sorted(out, key=lambda d: (d["deadline"], d["name"]))


def label(name: str | None, link_type: str, blocks: list[str]) -> str:
    base = name or ("Unnamed ferry route" if link_type == "ferry" else "Unnamed road")
    return f"{base} ({' → '.join(blocks)})" if blocks else base


def _geometry(geometries: list[dict]) -> dict:
    if len(geometries) == 1:
        return geometries[0]
    lines = [
        line
        for g in geometries
        for line in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]])
    ]
    return {"type": "MultiLineString", "coordinates": lines}


def rank(data: dict, departures_data: dict, timestep: str, horizon_h: int) -> dict:
    """The CriticalLinks body (plain data) for one timestep and horizon."""
    ds = [
        d for d in eligible(departures_data, timestep, horizon_h) if d["infra_id"] in data["routes"]
    ]
    users: dict[int, list[dict]] = {}  # way -> facilities, by deadline then name
    for d in ds:
        for w, _ in data["routes"][d["infra_id"]]:
            users.setdefault(w, []).append(d)

    def key(w: int) -> tuple:
        link = data["links"][str(w)]
        return link["name"], link["link_type"], tuple(d["infra_id"] for d in users[w])

    # Merge consecutive ways on a route with the same key (union-find).
    parent = {w: w for w in users}

    def find(w: int) -> int:
        while parent[w] != w:
            parent[w] = parent[parent[w]]
            w = parent[w]
        return w

    for d in ds:
        route = [w for w, _ in data["routes"][d["infra_id"]]]
        for a, b in zip(route, route[1:], strict=False):
            if key(a) == key(b):
                parent[find(b)] = find(a)
    groups: dict[int, set[int]] = {}
    for w in users:
        groups.setdefault(find(w), set()).add(w)

    links = []
    for ways in groups.values():
        facilities = users[next(iter(ways))]
        # Travel order and direction: the route of the facility with the earliest deadline.
        route = [(w, fwd) for w, fwd in data["routes"][facilities[0]["infra_id"]] if w in ways]
        blocks: dict[str, None] = {}
        for w, forward in route:
            way_blocks = data["links"][str(w)]["blocks"]
            blocks.update(dict.fromkeys(way_blocks if forward else reversed(way_blocks)))
        first = data["links"][str(route[0][0])]
        links.append(
            {
                "way_ids": [w for w, _ in route],
                "infra_ids": [f"road-way-{w}" for w, _ in route],
                "label": label(first["name"], first["link_type"], list(blocks)),
                "name": first["name"],
                "link_type": first["link_type"],
                "blocks": list(blocks),
                "facility_count": len(facilities),
                "facilities": [
                    {"infra_id": d["infra_id"], "name": d["name"], "deadline": d["deadline"]}
                    for d in facilities
                ],
                "earliest_deadline": facilities[0]["deadline"],
                "geometry": _geometry([data["links"][str(w)]["geometry"] for w, _ in route]),
            }
        )
    links.sort(
        key=lambda x: (-x["facility_count"], x["earliest_deadline"], x["label"], x["way_ids"])
    )
    return {"timestep": timestep, "horizon_h": horizon_h, "note": data["note"], "links": links}


@lru_cache(maxsize=2)
def _data(demo: bool) -> dict:
    if not demo:
        return build()
    try:
        return countdown._read(FIXTURE_KEY)
    except FileNotFoundError as e:
        raise CriticalLinksMissing(
            f"{FIXTURE_KEY}.json not found; run api/scripts/build_critical_links_fixture.py"
        ) from e


def clear_cache() -> None:
    _data.cache_clear()


def get_critical_links(timestep: str, horizon_h: int = 0) -> CriticalLinks:
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    demo = get_settings().DEMO_MODE
    return CriticalLinks.model_validate(
        rank(_data(demo), departures._data(demo), timestep, horizon_h)
    )
