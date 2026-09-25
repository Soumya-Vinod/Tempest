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
    }  # bus shelter (1), plain amenity=shelter (2) and the restaurant (9) are dropped


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


def test_graphml_round_trip_keeps_bools(tmp_path):
    G = ingest.finish_road_graph(_graph())
    path = tmp_path / "roads.graphml"
    ingest.save_road_graph(G, path)
    H = ingest.load_road_graph(path)
    ferries = {d["osmid"] for *_, d in H.edges(data=True) if d["ferry"] is True}
    assert ferries == {4}
    assert all(isinstance(d["ferry"], bool) for *_, d in H.edges(data=True))
