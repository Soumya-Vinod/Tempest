"""Last safe departure for GET /api/impact/departures (v1.3 change, pending Dev A).

For every hospital and health centre (infra_type "hospital"; not the shelter stand-ins) that is
cut off (isolated at horizon 0) at some replay step, except those that don't count for advisories
(weights.counts_for_advisory): the last step at which patients can still be moved out by road,
and where to.

- Safe destinations: hospital access sources (weights.is_access_source) within 2 km of the road
  graph, in its main component, and never isolated at horizon 0 from T-72 to T-0.
- Per step: the horizon-0 graph with that step's cut links removed (engine.link_masks), and a
  multi-source Dijkstra from every safe destination (normal-condition travel times).
- Deadline: the last step before the first step at which no safe destination is reachable
  (a route that reopens later doesn't count). If one stays reachable to T-0: T-0,
  route_stays_open. None if none is reachable at T-72.
- Destination: the nearest safe destination reachable at the deadline step; its route's normal
  travel time, whether it uses a ferry, whether any link on it is at risk at that step, and the
  route as simplified legs. usual_destination: the nearest on the intact network, for comparison.

Times are normal-condition estimates at the replay's 3-hour resolution. Precomputed: DEMO_MODE
serves impact__departures, built by scripts/build_departures_fixture.py.
"""

import heapq
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from shapely.geometry import LineString

from app.core.config import get_settings
from app.impact import countdown
from app.impact.engine import feature_label, link_masks, network_for
from app.impact.fixtures import fixture_key
from app.impact.network import ImpactNetwork
from app.risk import weights as W
from app.schemas import REPLAY_TIMESTEPS, Departures, InfraFeature

FIXTURE_KEY = "impact__departures"
DEPARTURE_TYPE = "hospital"  # hospitals and health centres; shelters only show when cut off
SIMPLIFY_DEG = 0.0005  # ~50 m
COORD_DECIMALS = 5


class DeparturesMissing(RuntimeError):
    """The impact__departures fixture has not been built (scripts/build_departures_fixture.py)."""


@dataclass(frozen=True)
class Step:
    timestep: str
    cut: np.ndarray  # per link
    at_risk: np.ndarray  # per link, not cut


@dataclass
class Reach:
    """A multi-source Dijkstra: per reached node, seconds, nearest source, and the link and node
    one hop towards that source."""

    dist: dict[Any, float]
    source: dict[Any, str]
    via: dict[Any, tuple[int, Any] | None]

    def path(self, node: Any) -> list[tuple[Any, Any, int]]:
        """(from node, to node, link) hops from `node` to its source."""
        hops = []
        while (hop := self.via[node]) is not None:
            link, nxt = hop
            hops.append((node, nxt, link))
            node = nxt
        return hops


def reach(net: ImpactNetwork, sources: dict[str, Any], cut: np.ndarray | None) -> Reach:
    dist: dict[Any, float] = {}
    source: dict[Any, str] = {}
    via: dict[Any, tuple[int, Any] | None] = {}
    heap = [(0.0, i, node, key, None) for i, (key, node) in enumerate(sources.items())]
    heapq.heapify(heap)
    tie = len(heap)
    while heap:
        d, _, n, key, hop = heapq.heappop(heap)
        if n in dist:
            continue
        dist[n], source[n], via[n] = d, key, hop
        for m, link in net.adjacency[n]:
            if m in dist or (cut is not None and cut[link]):
                continue
            tie += 1
            heapq.heappush(heap, (d + float(net.link_tt[link]), tie, m, key, (link, n)))
    return Reach(dist, source, via)


def _legs(net: ImpactNetwork, hops: list[tuple[Any, Any, int]], xy: dict[Any, tuple]) -> list:
    """Consecutive road / ferry stretches as simplified LineStrings, facility to destination."""
    legs: list[dict] = []
    for a, _b, link in hops:
        coords = list(net.link_geom[link].coords)
        ax, ay = xy[a]
        if (coords[-1][0] - ax) ** 2 + (coords[-1][1] - ay) ** 2 < (coords[0][0] - ax) ** 2 + (
            coords[0][1] - ay
        ) ** 2:
            coords.reverse()
        ferry = bool(net.link_ferry[link])
        if legs and legs[-1]["ferry"] == ferry:
            legs[-1]["coords"].extend(coords[1:])
        else:
            legs.append({"ferry": ferry, "coords": coords})
    out = []
    for leg in legs:
        line = LineString(leg["coords"]).simplify(SIMPLIFY_DEG)
        coords = [[round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)] for x, y in line.coords]
        out.append(
            {"ferry": leg["ferry"], "geometry": {"type": "LineString", "coordinates": coords}}
        )
    return out


def compute(
    net: ImpactNetwork,
    steps: list[Step],
    facilities: list[tuple[InfraFeature, str]],
    destinations: list[InfraFeature],
) -> dict:
    """The fixture: {"resolution_h": 3, "departures": [...]}. `facilities`: (facility, first
    cut-off timestep); `destinations`: the safe destinations."""
    xy = dict(zip(net.node_ids, map(tuple, net.node_xy), strict=True))
    names = {d.id: feature_label(d) for d in destinations}
    sources = {}
    for d in destinations:
        lon, lat = d.geometry.coordinates
        s = net.snap(d.id, lon, lat)
        if not s.too_far and s.node in net.main:
            sources[d.id] = s.node
    intact = reach(net, sources, None)
    per_step = [reach(net, sources, st.cut) for st in steps]

    out = []
    for f, first_cut in facilities:
        lon, lat = f.geometry.coordinates
        snap = net.snap(f.id, lon, lat)
        entry = {
            "infra_id": f.id,
            "name": feature_label(f),
            "infra_type": f.properties.infra_type,
            "first_cut_off": first_cut,
            "deadline": None,
            "route_stays_open": False,
            "destination_id": None,
            "destination_name": None,
            "travel_time_s": None,
            "uses_ferry": None,
            "at_risk": None,
            "legs": [],
            "usual_destination_id": None,
            "usual_destination_name": None,
            "note": None,
        }
        out.append(entry)
        if snap.too_far:
            entry["note"] = "More than 2 km from the road network"
            continue
        node = snap.node
        if node in intact.source:
            entry["usual_destination_id"] = intact.source[node]
            entry["usual_destination_name"] = names[intact.source[node]]
        closed = next((k for k, r in enumerate(per_step) if node not in r.dist), None)
        if closed == 0:
            entry["note"] = "No safe destination reachable by road at any step"
            continue
        k = len(steps) - 1 if closed is None else closed - 1
        r, st = per_step[k], steps[k]
        hops = r.path(node)
        links = [link for _, _, link in hops]
        entry.update(
            deadline=st.timestep,
            route_stays_open=closed is None,
            destination_id=r.source[node],
            destination_name=names[r.source[node]],
            travel_time_s=round(r.dist[node]),
            uses_ferry=bool(net.link_ferry[links].any()) if links else False,
            at_risk=bool(st.at_risk[links].any()) if links else False,
            legs=_legs(net, hops, xy),
        )
    out.sort(key=lambda e: (e["deadline"] is None, e["deadline"] or "", e["name"]))
    return {"resolution_h": 3, "departures": out}


# --- Inputs -------------------------------------------------------------------------------------


def _isolated_h0() -> dict[str, set[str]]:
    """Isolated infra ids per step at horizon 0, from the committed impact fixtures."""
    return {
        ts: set(
            countdown.isolations(
                r["properties"] for r in countdown._read(fixture_key(ts))["features"]
            )
        )
        for ts in REPLAY_TIMESTEPS
    }


def build() -> dict:
    """From the road graph (data/processed), the hazard layers and the committed impact and
    exposure fixtures. The build script and the fresh-computation test use this."""
    from app.impact import service as impact

    infra = countdown._infra_from_fixtures()
    isolated = _isolated_h0()
    ever: dict[str, str] = {}
    for ts in REPLAY_TIMESTEPS:
        for i in isolated[ts]:
            ever.setdefault(i, ts)
    facilities = [
        (infra[i], ts)
        for i, ts in ever.items()
        if i in infra
        and infra[i].properties.infra_type == DEPARTURE_TYPE
        and W.counts_for_advisory(infra[i].properties.name)
    ]
    destinations = [
        f
        for f in infra.values()
        if W.is_access_source(f.properties.infra_type, f.properties.attributes, f.properties.name)
        and f.id not in ever
    ]
    net = network_for(impact._graph(impact.GRAPH_PATH), impact.ANCHOR)
    steps = [Step(ts, *link_masks(impact.hazard_layers(ts), net)) for ts in REPLAY_TIMESTEPS]
    return compute(net, steps, facilities, destinations)


# --- Service ------------------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _data(demo: bool) -> dict:
    if not demo:
        return build()
    try:
        return countdown._read(FIXTURE_KEY)
    except FileNotFoundError as e:
        raise DeparturesMissing(
            f"{FIXTURE_KEY}.json not found; run api/scripts/build_departures_fixture.py"
        ) from e


def clear_cache() -> None:
    _data.cache_clear()


def get_departures() -> Departures:
    return Departures.model_validate(_data(get_settings().DEMO_MODE))


def by_facility() -> dict[str, dict]:
    """infra_id -> its departure entry (plain dicts, for the advisory facts). Empty when they
    can't be computed or loaded: the advisory then goes without departure facts."""
    from app.exposure.service import InfraDataMissing
    from app.impact.service import GraphMissing

    try:
        data = _data(get_settings().DEMO_MODE)
    except (DeparturesMissing, GraphMissing, InfraDataMissing, FileNotFoundError):
        return {}
    return {d["infra_id"]: d for d in data["departures"]}
