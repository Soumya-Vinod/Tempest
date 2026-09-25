"""Hazard-independent road network for the impact engine: built once per graph, then reused.

Connectivity is undirected (weak), matching the ingest's baseline components: one-way tags
matter for driving, not for whether a place is cut off. Travel times use the fastest link
between two nodes.
"""

from dataclasses import dataclass, field
from typing import Any

import networkx as nx
import numpy as np
from pyproj import Geod
from shapely.geometry import LineString

from app.impact.thresholds import ANCHOR_LONLAT, MAX_SNAP_M

_GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class Snap:
    node: Any
    distance_m: float
    too_far: bool


def _pair(u: Any, v: Any) -> tuple[Any, Any]:
    return (u, v) if u <= v else (v, u)


@dataclass
class ImpactNetwork:
    """Links are undirected road/ferry segments (the two directions of a way collapse into one)."""

    anchor: Any
    anchor_snap_m: float
    main: frozenset  # baseline main component: the anchor's
    dist_s: dict[Any, float]  # baseline travel time from the anchor
    parent: dict[Any, Any]  # next node towards the anchor on the baseline shortest path
    link_u: list[Any]
    link_v: list[Any]
    link_osmid: np.ndarray
    link_ferry: np.ndarray
    link_connector: np.ndarray
    link_tt: np.ndarray
    link_geom: list[LineString]
    pair_links: dict[tuple[Any, Any], list[int]]
    adjacency: dict[Any, list[tuple[Any, int]]]
    way_links: dict[int, np.ndarray]
    node_ids: list[Any]
    node_xy: np.ndarray
    _snaps: dict[tuple[str, float, float], Snap] = field(default_factory=dict)

    def snap(self, key: str, lon: float, lat: float) -> Snap:
        """Nearest graph node (any component) for a facility, cached per (key, lon, lat)."""
        cache_key = (key, lon, lat)
        if cache_key not in self._snaps:
            self._snaps[cache_key] = self.snap_many([(lon, lat)])[0]
        return self._snaps[cache_key]

    def snap_many(self, points: list[tuple[float, float]]) -> list[Snap]:
        """Vectorised nearest-node search (equirectangular), exact geodesic distance after."""
        if not points:
            return []
        pts = np.asarray(points, dtype=float)
        lat0 = np.radians(self.node_xy[:, 1].mean())
        kx, ky = 111_320.0 * np.cos(lat0), 110_540.0
        out = []
        for chunk in np.array_split(pts, max(1, len(pts) // 256)):
            dx = (chunk[:, None, 0] - self.node_xy[None, :, 0]) * kx
            dy = (chunk[:, None, 1] - self.node_xy[None, :, 1]) * ky
            nearest = np.argmin(dx * dx + dy * dy, axis=1)
            for (lon, lat), i in zip(chunk, nearest, strict=True):
                nx_, ny_ = self.node_xy[i]
                dist = abs(_GEOD.inv(lon, lat, nx_, ny_)[2]) if (lon, lat) != (nx_, ny_) else 0.0
                out.append(Snap(self.node_ids[i], dist, dist > MAX_SNAP_M))
        return out

    def path_to_anchor(self, node: Any):
        """Hops (node, next node) along the baseline shortest path, starting at `node`."""
        while node != self.anchor and node in self.parent:
            nxt = self.parent[node]
            yield node, nxt
            node = nxt


def build_network(
    graph: nx.MultiDiGraph, anchor_lonlat: tuple[float, float] = ANCHOR_LONLAT
) -> ImpactNetwork:
    link_index: dict[tuple, int] = {}
    link_u: list[Any] = []
    link_v: list[Any] = []
    osmid: list[int] = []
    ferry: list[bool] = []
    connector: list[bool] = []
    tt: list[float] = []
    geom: list[LineString] = []
    for u, v, d in graph.edges(data=True):
        a, b = _pair(u, v)
        key = (a, b, int(d["osmid"]), round(float(d["length"]), 1))
        if key in link_index:
            continue  # the reverse direction of a link already seen
        link_index[key] = len(link_u)
        link_u.append(a)
        link_v.append(b)
        osmid.append(int(d["osmid"]))
        ferry.append(bool(d.get("ferry", False)))
        connector.append(bool(d.get("connector", False)))
        tt.append(float(d["travel_time"]))
        g = d.get("geometry")
        if g is None:
            nu, nv = graph.nodes[u], graph.nodes[v]
            g = LineString([(nu["x"], nu["y"]), (nv["x"], nv["y"])])
        geom.append(g)

    pair_links: dict[tuple[Any, Any], list[int]] = {}
    adjacency: dict[Any, list[tuple[Any, int]]] = {n: [] for n in graph.nodes}
    ug = nx.Graph()
    ug.add_nodes_from(graph.nodes)
    for i, (a, b) in enumerate(zip(link_u, link_v, strict=True)):
        pair_links.setdefault((a, b), []).append(i)
        adjacency[a].append((b, i))
        adjacency[b].append((a, i))
        if not ug.has_edge(a, b) or tt[i] < ug[a][b]["tt"]:
            ug.add_edge(a, b, tt=tt[i])

    node_ids = list(graph.nodes)
    node_xy = np.array([(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in node_ids])
    osmid_arr = np.array(osmid, dtype=np.int64)
    grouped: dict[int, list[int]] = {}
    for i, w in enumerate(osmid):
        grouped.setdefault(w, []).append(i)
    way_links = {w: np.array(idx) for w, idx in grouped.items()}

    net = ImpactNetwork(
        anchor=None,
        anchor_snap_m=0.0,
        main=frozenset(),
        dist_s={},
        parent={},
        link_u=link_u,
        link_v=link_v,
        link_osmid=osmid_arr,
        link_ferry=np.array(ferry, dtype=bool),
        link_connector=np.array(connector, dtype=bool),
        link_tt=np.array(tt),
        link_geom=geom,
        pair_links=pair_links,
        adjacency=adjacency,
        way_links=way_links,
        node_ids=node_ids,
        node_xy=node_xy,
    )
    anchor = net.snap_many([anchor_lonlat])[0]
    pred, dist = nx.dijkstra_predecessor_and_distance(ug, anchor.node, weight="tt")
    net.anchor = anchor.node
    net.anchor_snap_m = anchor.distance_m
    net.dist_s = dict(dist)
    net.parent = {n: p[0] for n, p in pred.items() if p}
    net.main = frozenset(dist)
    return net


def baseline_access(
    graph: nx.MultiDiGraph,
    points: dict[str, tuple[float, float]],
    anchor_lonlat: tuple[float, float] = ANCHOR_LONLAT,
) -> dict[str, dict[str, Any]]:
    """Facility attributes for the ingest: snap distance, too-far flag and baseline travel time
    (seconds, network only, from the anchor's node to the facility's node; null when the
    facility is too far from the graph or not in the anchor's component)."""
    net = build_network(graph, anchor_lonlat)
    keys = list(points)
    out = {}
    for key, s in zip(keys, net.snap_many([points[k] for k in keys]), strict=True):
        reachable = not s.too_far and s.node in net.main
        out[key] = {
            "snap_distance_m": round(s.distance_m, 1),
            "snap_too_far": s.too_far,
            "baseline_travel_time_s": round(net.dist_s[s.node]) if reachable else None,
        }
    return out
