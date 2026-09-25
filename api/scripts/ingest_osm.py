"""Download OSM infrastructure for the AOI and build the road graph.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\ingest_osm.py [--refresh]

Raw Overpass responses are cached in api/data/raw/ (ignored) and reused unless --refresh.
Writes api/data/processed/infra.parquet and api/data/processed/roads.graphml.
"""

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import osmnx as ox  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.exposure import ingest  # noqa: E402

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "Tempest/0.1 exposure-ingest (+https://github.com/Soumya-Vinod/Tempest)"
TIMEOUT_S = 180
ATTEMPTS = 5
BACKOFF_S = 15.0
PAUSE_S = 5.0  # between Overpass queries (usage policy)
RETRY_STATUS = {429, 502, 503, 504}


class OverpassError(RuntimeError):
    pass


def fetch_overpass(query: str) -> dict:
    """POST a query to Overpass, retrying with exponential backoff and jitter."""
    for attempt in range(ATTEMPTS):
        delay = BACKOFF_S * 2**attempt
        try:
            r = httpx.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_S + 30,
            )
            if r.status_code == 200:
                data = r.json()
                # Overpass reports runtime errors (timeout, memory) as 200 + partial data.
                remark = data.get("remark", "")
                if "error" not in remark.lower():
                    return data
                reason = f"remark: {remark[:120]}"
            elif r.status_code in RETRY_STATUS:
                reason = f"HTTP {r.status_code}"
                delay = max(delay, float(r.headers.get("Retry-After") or 0))
            else:
                r.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as e:
            reason = type(e).__name__
        if attempt == ATTEMPTS - 1:
            raise OverpassError(f"Overpass failed after {ATTEMPTS} attempts ({reason})")
        wait = delay + random.uniform(0, 5)
        print(f"  overpass: {reason}; retry {attempt + 2}/{ATTEMPTS} in {wait:.0f}s", flush=True)
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


def configure_osmnx(refresh: bool) -> None:
    ox.settings.cache_folder = str(ingest.OSMNX_CACHE_DIR)
    ox.settings.use_cache = not refresh
    ox.settings.http_user_agent = USER_AGENT
    ox.settings.requests_timeout = TIMEOUT_S
    ox.settings.log_console = False
    ox.settings.useful_tags_way = list(
        dict.fromkeys([*ox.settings.useful_tags_way, *ingest.GRAPH_WAY_TAGS])
    )


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
    polygon = ingest.clip_polygon(boundary)
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
        found = ingest.normalise(infra_type, data, include_minor_line=minor)
        raw_counts[infra_type] = len(found)
        deduped = ingest.dedupe_health(found) if infra_type == "hospital" else found
        records += ingest.clip_records(deduped, polygon)
    ingest.write_infra(records)

    print("Road graph (osmnx)", flush=True)
    configure_osmnx(args.refresh)
    G = ox.graph_from_polygon(
        polygon,
        custom_filter=ingest.ROAD_GRAPH_FILTERS,
        simplify=False,
        retain_all=True,
        truncate_by_edge=True,
    )
    G = ingest.finish_road_graph(ox.simplify_graph(G, edge_attrs_differ=["osmid"]))
    ingest.save_road_graph(G)

    report(records, raw_counts, polygon, bangladesh, line_n, minor_n, include_minor, G)


def report(records, raw_counts, polygon, bangladesh, line_n, minor_n, include_minor, G) -> None:
    by_type = Counter(r.infra_type for r in records)
    print("\n=== Report ===")
    print(
        f"Clip polygon: {ingest.area_km2(polygon):,.0f} km² "
        f"({', '.join(ingest.CLIP_RELATIONS.values())})"
    )
    overlap = ingest.area_km2(polygon.intersection(bangladesh))
    in_bd = sum(bangladesh.intersects(r.geometry) for r in records)
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
    parquet, graphml = _mb(ingest.INFRA_PARQUET), _mb(ingest.ROADS_GRAPHML)
    print(f"Files: infra.parquet {parquet}, roads.graphml {graphml}")

    ferries = sum(1 for *_, d in G.edges(data=True) if d["ferry"])
    sizes = ingest.component_sizes(G)
    print(
        f"Road graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges "
        f"({ferries} ferry edges)"
    )
    print(f"  weakly connected components: {len(sizes)}; largest: {sizes[:10]}")
    print(f"  ferry ends not touching a road: {len(ingest.ferry_endpoints_off_network(G))}")
    road_ids = {int(r.osm_id.split("/")[1]) for r in records if r.infra_type == "road"}
    missing = {d["osmid"] for *_, d in G.edges(data=True)} - road_ids
    print(f"  edge way ids without a road feature: {len(missing)}")
    for name, info in ingest.island_links(G).items():
        print(
            f"  {name}: snap {info['snap_m']} m, joined to mainland: {info['joined']}, "
            f"via ferry: {info['via_ferry']}"
        )


if __name__ == "__main__":
    main()
