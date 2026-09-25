"""OSM ingest: tag mapping, normalising, dedupe, clipping, ids and graph helpers. No network."""

import json
import re
from pathlib import Path

import networkx as nx
import pytest
from shapely.geometry import LineString, MultiLineString, Point

from app.exposure import ingest
from app.schemas.contracts import INFRA_ID_PATTERN

DATA = Path(__file__).parent / "data"


def load(name: str) -> dict:
    return json.loads((DATA / f"overpass-{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def clip():
    return ingest.clip_polygon(load("boundary"), [1])


def by_id(records):
    return {r.id: r for r in records}


# --- Tag mapping --------------------------------------------------------------------------------


def test_shelter_kinds():
    recs = by_id(ingest.normalise("shelter", load("shelter")))
    kinds = {rid: r.attributes["shelter_kind"] for rid, r in recs.items()}
    assert kinds == {
        "shelter-node-3": "cyclone_shelter",  # amenity=shelter named as a cyclone shelter
        "shelter-node-4": "assembly_point",
        "shelter-way-5": "cyclone_shelter",  # school doubling as flood shelter: listed once
        "shelter-node-6": "school_proxy",
        "shelter-node-7": "cyclone_shelter",  # Bengali name, precomposed ড় / য়
        "shelter-node-8": "cyclone_shelter",  # indicator beats assembly_point
        "shelter-node-11": "cyclone_shelter",  # public building, name matched locally
    }  # bus shelter (1), plain amenity=shelter (2), restaurant (9), civic office (10) dropped


def test_shelter_queries():
    bbox = (88.0, 21.5, 89.1, 22.7)
    tag_query = ingest.infra_query("shelter", bbox)
    assert 'name"~' not in tag_query  # name regex is applied locally, not in Overpass
    assert 'nwr["building"~"^(public|civic)$"]["name"];' in tag_query

    tiles = ingest.bbox_tiles(bbox)
    assert len(tiles) == 4
    assert tiles[0] == pytest.approx((88.0, 21.5, 88.55, 22.1))  # SW
    assert tiles[3] == pytest.approx((88.55, 22.1, 89.1, 22.7))  # NE
    assert sum((t[2] - t[0]) * (t[3] - t[1]) for t in tiles) == pytest.approx(1.1 * 1.2)

    name_queries = ingest.shelter_name_queries(bbox)
    assert len(name_queries) == 4
    assert all('nwr["name"~' in q and 'nwr["name:en"~' in q for q in name_queries)
    assert "[bbox:21.5,88.0,22.1,88.55]" in name_queries[0]


def test_merge_responses_dedupes_via_normalise():
    data = load("shelter")
    tile = {"elements": data["elements"][2:4]}  # the same elements seen by a name tile
    merged = ingest.merge_responses([data, tile])
    assert len(merged["elements"]) == len(data["elements"]) + 2
    ids = [r.id for r in ingest.normalise("shelter", merged)]
    assert len(ids) == len(set(ids))


def test_facility_levels():
    recs = by_id(ingest.normalise("hospital", load("hospital")))
    assert "hospital-node-8" not in recs  # pharmacy
    levels = {rid: r.attributes["facility_level"] for rid, r in recs.items()}
    assert levels["hospital-way-10"] == "hospital"
    assert levels["hospital-node-3"] == "hospital"  # clinic upgraded by "BPHC"
    assert levels["hospital-node-4"] == "health_centre"
    assert levels["hospital-node-7"] == "health_centre"  # healthcare=centre
    assert levels["hospital-node-9"] == "hospital"  # "Sub-Divisional Hospital" in name:en


@pytest.mark.parametrize(
    ("name", "upgraded"),
    [
        ("Gosaba Rural Hospital", True),
        ("Kultali BLOCK HOSPITAL", True),
        ("Basanti BPHC", True),
        ("Kakdwip Subdivisional Hospital", True),
        ("Baruipur Sub Divisional Hospital", True),
        ("Alipore District Hospital", True),
        ("BPHCX Clinic", False),
        ("Sagar Primary Health Centre", False),
    ],
)
def test_hospital_name_upgrade(name, upgraded):
    level = ingest.facility_level({"amenity": "clinic", "name": name})
    assert (level == "hospital") is upgraded


def test_roads_and_power_tag_mapping():
    roads = by_id(ingest.normalise("road", load("road")))
    assert "road-way-101" not in roads  # residential is not a road class here
    assert roads["road-way-102"].attributes == {"ferry": True}
    assert roads["road-way-104"].attributes == {
        "highway": "secondary_link",
        "bridge": "yes",
        "ferry": False,
    }
    assert roads["road-way-100"].attributes["ref"] == "SH 1"

    power = load("power")
    lines = by_id(ingest.normalise("power_line", power))
    assert set(lines) == {"power-line-way-200"}
    assert lines["power-line-way-200"].attributes == {"voltage": "132000", "operator": "WBSETCL"}
    with_minor = ingest.normalise("power_line", power, include_minor_line=True)
    assert {r.id for r in with_minor} == {"power-line-way-200", "power-line-way-201"}
    assert ingest.power_counts(power) == (4210, 1234)


# --- Normalising --------------------------------------------------------------------------------


def test_points_use_centroids_and_lines_stay_lines():
    subs = by_id(ingest.normalise("substation", load("power")))
    assert subs["substation-node-202"].geometry.equals(Point(88.4, 22.4))
    way = subs["substation-way-203"]
    assert isinstance(way.geometry, Point)
    assert way.geometry.x == pytest.approx(88.51) and way.geometry.y == pytest.approx(22.41)
    assert way.area is not None

    rel = by_id(ingest.normalise("hospital", load("hospital")))["hospital-relation-20"]
    assert (rel.geometry.x, rel.geometry.y) == pytest.approx((88.11, 22.11))

    road = by_id(ingest.normalise("road", load("road")))["road-way-100"]
    assert isinstance(road.geometry, LineString)


def test_names_and_osm_ids():
    recs = by_id(ingest.normalise("hospital", load("hospital")))
    assert recs["hospital-node-7"].name is None  # no name: null in data, UI shows "Unnamed"
    assert recs["hospital-node-9"].name == "Kakdwip Sub-Divisional Hospital"  # from name:en
    assert recs["hospital-way-10"].osm_id == "way/10"
    assert recs["hospital-relation-20"].osm_id == "relation/20"


def test_ids_are_hyphenated_and_valid_features():
    records = []
    for infra_type, sample in [
        ("substation", "power"),
        ("power_line", "power"),
        ("road", "road"),
        ("hospital", "hospital"),
        ("shelter", "shelter"),
    ]:
        records += ingest.normalise(infra_type, load(sample), include_minor_line=True)
    for r in records:
        assert re.fullmatch(INFRA_ID_PATTERN, r.id), r.id
        assert "_" not in r.id
        ingest.to_feature(r)  # validates against the contract
    assert ingest.infra_id("power_line", "way", 5) == "power-line-way-5"


# --- Dedupe -------------------------------------------------------------------------------------


def test_health_dedupe():
    recs = by_id(ingest.dedupe_health(ingest.normalise("hospital", load("hospital"))))
    assert "hospital-node-2" not in recs  # node inside the district hospital's polygon
    assert "hospital-node-5" not in recs  # same name ~65 m from node 4
    assert "hospital-node-6" in recs  # same name but ~155 m away
    # The kept record takes the higher facility_level of the pair it absorbed.
    assert recs["hospital-node-4"].attributes["facility_level"] == "hospital"


def test_dedupe_by_osm_id():
    data = load("hospital")
    data["elements"].append(data["elements"][3])  # node 3 returned twice by a union query
    ids = [r.id for r in ingest.normalise("hospital", data)]
    assert len(ids) == len(set(ids))


# --- Clipping -----------------------------------------------------------------------------------


def test_clip_polygon_assembles_relation(clip):
    assert clip.bounds == pytest.approx((88.0, 22.0, 88.6, 22.6))
    assert ingest.area_km2(clip) == pytest.approx(4300, rel=0.05)


def test_clip_points_and_lines(clip):
    roads = by_id(ingest.clip_records(ingest.normalise("road", load("road")), clip))
    assert "road-way-103" not in roads  # fully outside
    cut = roads["road-way-100"].geometry
    assert isinstance(cut, LineString) and cut.bounds[2] == pytest.approx(88.6)
    split = roads["road-way-105"].geometry  # leaves the polygon and comes back
    assert isinstance(split, MultiLineString) and len(split.geoms) == 2
    for r in roads.values():
        assert clip.covers(r.geometry)

    hospitals = by_id(ingest.clip_records(ingest.normalise("hospital", load("hospital")), clip))
    assert "hospital-node-30" not in hospitals  # across the border


def test_parquet_round_trip(tmp_path, clip):
    records = ingest.clip_records(ingest.normalise("road", load("road")), clip)
    path = tmp_path / "infra.parquet"
    ingest.write_infra(records, path)
    gdf = ingest.read_infra(path, "road")
    assert list(gdf.columns) == ["id", "infra_type", "name", "osm_id", "attributes", "geometry"]
    assert gdf.crs.to_epsg() == 4326
    row = gdf.set_index("id").loc["road-way-102"]
    assert json.loads(row["attributes"]) == {"ferry": True}


# --- Road graph ---------------------------------------------------------------------------------


A, B, C, D, E, F = range(1, 7)


def _graph(ferry_to_island: bool = True) -> nx.MultiDiGraph:
    """Mainland A-B-C, island D-E; a ferry C<->D joins them. Int ids, as osmnx reloads them."""
    G = nx.MultiDiGraph(crs="EPSG:4326")
    for n, (x, y) in {A: (88.35, 22.56), B: (88.36, 22.50), C: (88.40, 22.20),
                      D: (88.45, 22.18), E: (88.80, 22.16)}.items():  # fmt: skip
        G.add_node(n, x=x, y=y)

    def road(u, v, osmid, **attrs):
        for s, t in ((u, v), (v, u)):
            G.add_edge(s, t, osmid=osmid, length=1000.0, **attrs)

    road(A, B, 1, highway="primary")
    road(B, C, 2, highway="unclassified", maxspeed="40")
    road(D, E, 3, highway="tertiary")
    if ferry_to_island:
        road(C, D, 4, route="ferry")
    return G


def test_finish_road_graph_speeds_and_ferries():
    G = ingest.finish_road_graph(_graph())
    edges = {(u, v): d for u, v, d in G.edges(data=True)}
    assert edges[(C, D)]["ferry"] is True and edges[(A, B)]["ferry"] is False
    assert edges[(A, B)]["speed_kph"] == 50  # hwy_speeds default
    assert edges[(B, C)]["speed_kph"] == 40  # tagged maxspeed wins
    ferry = edges[(C, D)]
    assert ferry["speed_kph"] == ingest.FERRY_SPEED_KPH
    expected = 1000 / (ingest.FERRY_SPEED_KPH / 3.6) + ingest.FERRY_BOARDING_S
    assert ferry["travel_time"] == pytest.approx(expected, abs=0.1)
    assert all(isinstance(d["osmid"], int) for *_, d in G.edges(data=True))


def test_edges_must_map_to_one_way():
    G = _graph()
    G.edges[A, B, 0]["osmid"] = [1, 5]
    with pytest.raises(ValueError, match="several OSM ways"):
        ingest.finish_road_graph(G)


def test_island_links_via_ferry():
    places = {"Island": (88.79, 22.16)}
    mainland = ("Mainland", (88.35, 22.56))
    G = ingest.finish_road_graph(_graph())
    assert ingest.component_sizes(G) == [5]
    info = ingest.island_links(G, places, mainland)["Island"]
    assert info["joined"] and info["via_ferry"] and info["snap_m"] < 2000

    cut = ingest.finish_road_graph(_graph(ferry_to_island=False))
    assert ingest.component_sizes(cut) == [3, 2]
    assert not ingest.island_links(cut, places, mainland)["Island"]["joined"]


def test_ferry_endpoints_off_network():
    G = _graph()
    G.add_node(F, x=88.5, y=22.1)
    G.add_edge(D, F, osmid=9, length=10.0, route="ferry", ferry=True)
    G.add_edge(F, D, osmid=9, length=10.0, route="ferry", ferry=True)
    for *_, d in G.edges(data=True):
        d.setdefault("ferry", d.get("route") == "ferry")
    assert ingest.ferry_endpoints_off_network(G) == [F]


def test_build_road_graph_from_cached_response(clip):
    data = ingest.drop_long_ferries(load("road-graph"))
    assert 7 not in {e["id"] for e in data["elements"]}  # the long-distance ship
    G = ingest.build_road_graph(data, clip)

    assert {30, 31, 40, 41}.isdisjoint(G.nodes)  # way 6 fully outside; ship dropped
    assert 4 in G.nodes  # boundary-crossing edge kept whole (truncate_by_edge)
    assert {20, 21} <= set(G.nodes)  # isolated fragment kept (retain_all)
    assert ingest.component_sizes(G) == [8, 2]

    connectors = [d for *_, d in G.edges(data=True) if d["connector"]]
    assert len(connectors) == 4  # both ferry ends, both directions
    assert {d["osmid"] for d in connectors} == {4}  # maps back to the ferry's road feature
    assert all(isinstance(d["osmid"], int) for *_, d in G.edges(data=True))

    info = ingest.island_links(G, {"Island": (88.39, 22.2)}, ("Mainland", (88.1, 22.5)))
    assert info["Island"]["joined"] and info["Island"]["via_ferry"]


def test_mid_river_ferry_vertices_are_not_ends(clip):
    data = load("road-graph")
    for e in data["elements"]:
        if e["id"] == 4:  # add an interior vertex ~110 m from mainland road node 3
            e["nodes"].insert(1, 14)
            e["geometry"].insert(1, {"lat": 22.499, "lon": 88.3})
    G = ingest.build_road_graph(ingest.drop_long_ferries(data), clip)
    attached = {n for u, v, d in G.edges(data=True) if d["connector"] for n in (u, v)}
    assert 14 not in attached  # interior vertex: no connector
    assert {12, 13} <= attached  # the ferry way's real ends
    assert len([d for *_, d in G.edges(data=True) if d["connector"]]) == 4


def test_write_osm_xml_requires_node_ids(tmp_path):
    data = load("road")  # geometry only, no `nodes` lists
    with pytest.raises(ValueError, match="node ids missing"):
        ingest.write_osm_xml(data, tmp_path / "roads.osm")


def test_connectors_respect_max_distance(clip):
    data = load("road-graph")
    for e in data["elements"]:
        if e["id"] == 4:  # move the ferry's mainland end ~1.1 km off the road
            e["geometry"][0]["lat"] = 22.49
    G = ingest.build_road_graph(ingest.drop_long_ferries(data), clip)
    assert len([d for *_, d in G.edges(data=True) if d["connector"]]) == 2  # island end only
    assert ingest.component_sizes(G)[0] < 8


def test_fill_water_gaps_bridges_channels_but_not_neighbours():
    from shapely.geometry import box

    west, east = box(88.0, 22.0, 88.1, 22.1), box(88.11, 22.0, 88.2, 22.1)  # ~1 km channel
    neighbour = box(88.1, 22.05, 88.11, 22.1)  # a foreign bank in the channel's north half
    filled = ingest.fill_water_gaps(west.union(east), neighbour, gap_m=1000)
    assert filled.covers(Point(88.105, 22.02))  # channel filled
    assert filled.intersection(neighbour).area < 1e-9  # but never the neighbour
    far = ingest.fill_water_gaps(
        west.union(box(88.2, 22.0, 88.3, 22.1)), box(88.5, 22.5, 88.6, 22.6), 1000
    )
    assert not far.covers(Point(88.15, 22.05))  # ~10 km gap stays open


def test_graphml_round_trip_keeps_bools(tmp_path):
    G = ingest.finish_road_graph(_graph())
    ingest.annotate_components(G)
    path = tmp_path / "roads.graphml"
    ingest.save_road_graph(G, path)
    H = ingest.load_road_graph(path)
    ferries = {d["osmid"] for *_, d in H.edges(data=True) if d["ferry"] is True}
    assert ferries == {4}
    assert all(isinstance(d["ferry"], bool) for *_, d in H.edges(data=True))
    for _, d in H.nodes(data=True):
        assert type(d["baseline_component"]) is int
        assert type(d["baseline_reachable_from_main"]) is bool


# --- Baseline connectivity ----------------------------------------------------------------------


def _road(way_id: int) -> ingest.InfraRecord:
    return ingest.InfraRecord(
        id=f"road-way-{way_id}",
        infra_type="road",
        name=None,
        osm_id=f"way/{way_id}",
        attributes={"highway": "tertiary", "ferry": False},
        geometry=LineString([(88.1, 22.1), (88.2, 22.2)]),
    )


def test_annotate_components_numbers_largest_first():
    G = ingest.finish_road_graph(_graph(ferry_to_island=False))  # mainland A-B-C, island D-E
    assert ingest.annotate_components(G) == [3, 2]
    for n in (A, B, C):
        assert G.nodes[n]["baseline_component"] == 0
        assert G.nodes[n]["baseline_reachable_from_main"] is True
    for n in (D, E):
        assert G.nodes[n]["baseline_component"] == 1
        assert G.nodes[n]["baseline_reachable_from_main"] is False


def test_road_features_get_baseline_via_way_id():
    G = ingest.finish_road_graph(_graph(ferry_to_island=False))
    G.add_node(F, x=88.34, y=22.55)  # way 3 also has a piece on the mainland
    G.add_edge(A, F, osmid=3, length=10.0, ferry=False)
    ingest.annotate_components(G)
    components = ingest.way_components(G)
    assert components == {1: 0, 2: 0, 3: 0}  # split way 3 takes its best-connected part

    G.remove_node(F)
    ingest.annotate_components(G)
    records = [_road(1), _road(3), _road(99)]
    assert ingest.annotate_roads(records, ingest.way_components(G)) == 1  # way 99: no edge
    got = {r.id: (r.attributes["baseline_component"], r.attributes["baseline_reachable_from_main"])
           for r in records}  # fmt: skip
    assert got == {"road-way-1": (0, True), "road-way-3": (1, False), "road-way-99": (None, False)}
    for r in records:
        ingest.to_feature(r)  # still a valid contract InfraFeature


def test_missing_way_id_lookup_returns_none(tmp_path, clip):
    records = ingest.clip_records(ingest.normalise("road", load("road")), clip)
    path = tmp_path / "infra.parquet"
    ingest.write_infra(records, path)
    index = ingest.road_index(ingest.read_infra(path))
    assert ingest.road_feature_for_way(index, 100) == "road-way-100"
    # The real boundary edge whose clipped road feature came out empty (way 657485282).
    assert ingest.road_feature_for_way(index, 657485282) is None
    assert ingest.road_feature_for_way(index, "657485282") is None  # GraphML-loaded ids too
