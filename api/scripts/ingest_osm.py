"""Download OSM infrastructure for the AOI and build the road graph.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\ingest_osm.py [--refresh]

Raw Overpass responses are cached in api/data/raw/ (ignored) and reused unless --refresh.
Writes api/data/processed/infra.parquet and api/data/processed/roads.graphml; the road graph is
built from the cached road response, so it needs no download of its own.
"""

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
import networkx as nx
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.exposure import ingest  # noqa: E402

# Tried in order. A 429 / 504 (or a timeout) fails over to the next one right away; only when a
# round of endpoints has failed does the script back off and start again from the first.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "Tempest/0.1 exposure-ingest (+https://github.com/Soumya-Vinod/Tempest)"
TIMEOUT_S = 180
ATTEMPTS = 5  # rounds over OVERPASS_URLS
BACKOFF_S = 15.0
PAUSE_S = 5.0  # between Overpass queries (usage policy)
FAILOVER_STATUS = {429, 504}
RETRY_STATUS = {429, 502, 503, 504}


class OverpassError(RuntimeError):
    pass


def _post(url: str, query: str) -> tuple[dict | None, str, bool, float]:
    """(data or None, failure reason, fail over to the next mirror?, Retry-After seconds)."""
    host = httpx.URL(url).host
    try:
        r = httpx.post(
            url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S + 30
        )
    except (httpx.TimeoutException, httpx.TransportError) as e:
        return None, f"{host}: {type(e).__name__}", True, 0.0
    if r.status_code == 200:
        data = r.json()
        # Overpass reports runtime errors (timeout, memory) as 200 + partial data.
        remark = data.get("remark", "")
        if "error" not in remark.lower():
            return data, "", False, 0.0
        return None, f"{host}: remark {remark[:100]}", False, 0.0
    if r.status_code in RETRY_STATUS:
        retry_after = float(r.headers.get("Retry-After") or 0)
        failover = r.status_code in FAILOVER_STATUS
        return None, f"{host}: HTTP {r.status_code}", failover, retry_after
    r.raise_for_status()
    raise AssertionError("unreachable")


def fetch_overpass(query: str) -> dict:
    """POST a query to Overpass: fail over across mirrors, then back off with jitter."""
    for attempt in range(ATTEMPTS):
        retry_after = 0.0
        for url in OVERPASS_URLS:
            data, reason, failover, after = _post(url, query)
            if data is not None:
                return data
            retry_after = max(retry_after, after)
            print(
                f"  overpass: {reason}" + ("; trying next mirror" if failover else ""), flush=True
            )
            if not failover:
                break
        if attempt == ATTEMPTS - 1:
            raise OverpassError(f"Overpass failed after {ATTEMPTS} rounds ({reason})")
        wait = max(BACKOFF_S * 2**attempt, retry_after) + random.uniform(0, 5)
        print(f"  overpass: round {attempt + 2}/{ATTEMPTS} in {wait:.0f}s", flush=True)
        time.sleep(wait)
    raise AssertionError("unreachable")


def cached_overpass(name: str, query: str, refresh: bool) -> dict:
    path = ingest.RAW_DIR / f"overpass-{name}.json"
    if path.is_file() and not refresh:
        print(f"  cache: {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"  download: {path.name}", flush=True)
    data = fetch_overpass(query)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic: an interrupted run never leaves a half file that looks cached
    time.sleep(PAUSE_S)
    return data


def _mb(path: Path) -> str:
    return f"{path.stat().st_size / 1e6:.1f} MB"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Bengali names on a cp1252 console
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="ignore cached downloads")
    args = parser.parse_args()
    bbox = get_settings().aoi_bbox_tuple

    print("Boundary")
    boundary = cached_overpass("boundary", ingest.boundary_query(), args.refresh)
    land = ingest.clip_polygon(boundary)
    neighbours = ingest.clip_polygon(boundary, ingest.NEIGHBOUR_RELATIONS)
    polygon = ingest.fill_water_gaps(land, neighbours)
    bangladesh = ingest.clip_polygon(boundary, ingest.BORDER_CHECK_RELATIONS)

    print("Power line count")
    line_n, minor_n = ingest.power_counts(
        cached_overpass("power-line-count", ingest.power_count_query(bbox), args.refresh)
    )
    include_minor = line_n + minor_n <= ingest.MINOR_LINE_LIMIT

    print("Infrastructure")
    records: list[ingest.InfraRecord] = []
    raw_counts: dict[str, int] = {}
    for infra_type in ingest.INFRA_TYPES:
        minor = include_minor and infra_type == "power_line"
        query = ingest.infra_query(infra_type, bbox, include_minor_line=minor)
        data = cached_overpass(infra_type.replace("_", "-"), query, args.refresh)
        if infra_type == "shelter":
            names = [
                cached_overpass(f"shelter-names-{n}", q, args.refresh)
                for n, q in enumerate(ingest.shelter_name_queries(bbox), start=1)
            ]
            data = ingest.merge_responses([data, *names])
        if infra_type == "road":
            ferries_before = _ferry_count(data)
            data = ingest.drop_long_ferries(data)
            long_ferries = ferries_before - _ferry_count(data)
            road_data = data  # the road graph is built from this same response
        found = ingest.normalise(infra_type, data, include_minor_line=minor)
        raw_counts[infra_type] = len(found)
        deduped = ingest.dedupe_health(found) if infra_type == "hospital" else found
        records += ingest.clip_records(deduped, polygon)

    print("Road graph (from overpass-road.json)", flush=True)
    G = ingest.build_road_graph(road_data, polygon)
    ingest.annotate_components(G)
    ingest.annotate_roads(records, ingest.way_components(G))
    ingest.write_infra(records)
    ingest.save_road_graph(G)

    report(records, raw_counts, land, polygon, bangladesh, line_n, minor_n, long_ferries, G)


def _ferry_count(data: dict) -> int:
    return sum(e.get("tags", {}).get("route") == "ferry" for e in data["elements"])


def report(records, raw_counts, land, polygon, bangladesh, line_n, minor_n, long_ferries, G):
    by_type = Counter(r.infra_type for r in records)
    include_minor = line_n + minor_n <= ingest.MINOR_LINE_LIMIT
    print("\n=== Report ===")
    print(
        f"Clip polygon: {ingest.area_km2(polygon):,.0f} km² "
        f"({', '.join(ingest.CLIP_RELATIONS.values())}: land {ingest.area_km2(land):,.0f} km² "
        f"+ river channels up to {2 * ingest.WATER_GAP_M / 1000:.0f} km wide)"
    )
    overlap = ingest.area_km2(polygon.intersection(bangladesh))
    bd_interior = bangladesh.buffer(-1e-6)  # ~0.1 m: shared border edges don't count
    in_bd = sum(bd_interior.intersects(r.geometry) for r in records)
    max_lon = max(r.geometry.bounds[2] for r in records)
    print(f"  overlap with Khulna Division: {overlap:.2f} km²; features touching it: {in_bd}")
    print(f"  easternmost feature longitude: {max_lon:.4f}")
    print(
        f"power=line ways (bbox): {line_n}; power=minor_line: {minor_n}; "
        f"minor_line {'included' if include_minor else 'EXCLUDED'} "
        f"(limit {ingest.MINOR_LINE_LIMIT:,})"
    )
    print("Features (after dedupe + clip; raw in bbox in brackets):")
    for t in ingest.INFRA_TYPES:
        print(f"  {t:<11} {by_type[t]:>7,}  [{raw_counts[t]:,}]")
    for key in ("shelter_kind", "facility_level"):
        c = Counter(r.attributes[key] for r in records if key in r.attributes)
        print(f"{key}: " + ", ".join(f"{k} {v:,}" for k, v in c.most_common()))
    upgraded = [
        r.name
        for r in records
        if r.infra_type == "hospital" and r.name and ingest.HOSPITAL_NAME_RE.search(r.name)
    ]
    print(f"  names matching hospital upgrade patterns: {len(upgraded)}")
    print(f"route=ferry ways longer than {ingest.MAX_FERRY_KM:.0f} km dropped: {long_ferries}")
    parquet, graphml = _mb(ingest.INFRA_PARQUET), _mb(ingest.ROADS_GRAPHML)
    print(f"Files: infra.parquet {parquet}, roads.graphml {graphml}")

    ferries = sum(1 for *_, d in G.edges(data=True) if d["ferry"])
    connectors = sum(1 for *_, d in G.edges(data=True) if d["connector"]) // 2
    sizes = ingest.component_sizes(G)
    print(
        f"Road graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges "
        f"({ferries} ferry edges, {connectors} ferry-to-road connectors)"
    )
    print(f"  weakly connected components: {len(sizes)}; largest: {sizes[:10]}")
    no_ferry = nx.number_connected_components(ingest.undirected(G, ferries=False))
    print(f"  components with ferry edges removed: {no_ferry}")
    outside = sum(not polygon.covers(Point(d["x"], d["y"])) for _, d in G.nodes(data=True))
    print(f"  nodes outside the clip polygon (ends of boundary-crossing edges): {outside}")
    print(f"  ferry ends not touching a road: {len(ingest.ferry_endpoints_off_network(G))}")
    index = ingest.road_index(ingest.read_infra())
    missing = {
        d["osmid"]
        for *_, d in G.edges(data=True)
        if ingest.road_feature_for_way(index, d["osmid"]) is None
    }
    print(f"  edge way ids without a road feature: {len(missing)} {sorted(missing)}")
    roads = [r for r in records if r.infra_type == "road"]
    no_edge = sum(r.attributes["baseline_component"] is None for r in roads)
    main = sum(r.attributes["baseline_reachable_from_main"] for r in roads)
    print(
        f"  road features: {main:,} of {len(roads):,} reachable from main at baseline; "
        f"{no_edge} with no graph edge"
    )
    comp0 = {d["baseline_component"] for _, d in G.nodes(data=True)}
    print(f"  baseline_component values: 0..{max(comp0)} ({len(comp0)} distinct)")
    for name, info in ingest.island_links(G).items():
        print(
            f"  {name}: snap {info['snap_m']} m, joined to mainland: {info['joined']}, "
            f"via ferry: {info['via_ferry']}"
        )


if __name__ == "__main__":
    main()
