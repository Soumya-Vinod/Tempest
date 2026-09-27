"""Advisory suggestion rule (v1.3 change, pending Dev A): expected risk >= 0.25 or a facility
expected to be cut off within 24 h, with reasons; facilities that don't count for advisories
(the hospital-access exclusions) are no reason and are not in the advisory facts."""

import pytest
from fastapi.testclient import TestClient

from app.advisory import facts as facts_module
from app.advisory import service as advisory
from app.advisory import suggest as S
from app.core import demo as demo_module
from app.core.config import Settings
from app.exposure import service as exposure
from app.impact import service as impact
from app.insurance import service as insurance
from app.main import app
from app.risk import service as risk
from app.risk import weights as W
from app.risk.blocks import load_blocks
from app.schemas import REPLAY_TIMESTEPS, InfraFeature

client = TestClient(app)


def t(hours_before_landfall: int) -> str:
    return REPLAY_TIMESTEPS[-1 - hours_before_landfall // 3]


def facility(i: int, name: str | None, lon: float = 88.5, lat: float = 22.0) -> InfraFeature:
    return InfraFeature.model_validate(
        {
            "type": "Feature",
            "id": f"hospital-node-{i}",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": f"hospital-node-{i}",
                "infra_type": "hospital",
                "name": name,
                "osm_id": f"node/{i}",
                "attributes": {},
            },
        }
    )


@pytest.fixture
def demo(monkeypatch):
    s = Settings(_env_file=None, DEMO_MODE=True, GEMINI_API_KEY="", GROQ_API_KEY="")
    for module in (impact, risk, exposure, insurance, demo_module):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    for module in (impact, risk, exposure, insurance):
        module.clear_cache()
    advisory._facility_blocks.cache_clear()
    yield
    for module in (impact, risk, exposure, insurance):
        module.clear_cache()
    advisory._facility_blocks.cache_clear()


# --- The rule -------------------------------------------------------------------------------------


def test_risk_only_cut_off_only_and_both():
    phc, clinic = facility(1, "B PHC"), facility(2, "A Health Centre")
    out = S.suggest(
        [("1", "Low", 0.1), ("2", "High", 0.4), ("3", "Both", 0.3), ("4", "Cut", 0.0)],
        {"3": [phc], "4": [clinic, phc]},
    )
    assert [(s.block_name, [r.label for r in s.reasons]) for s in out] == [
        ("High", ["risk 0.40"]),
        ("Both", ["risk 0.30", "B PHC expected to be cut off"]),
        ("Cut", ["A Health Centre expected to be cut off", "B PHC expected to be cut off"]),
    ]
    assert [r.kind for r in out[1].reasons] == ["risk", "expected_cut_off"]
    assert out[1].reasons[1].infra_id == phc.id


def test_the_threshold_is_inclusive_and_ties_go_by_name():
    out = S.suggest([("1", "B", 0.25), ("2", "A", 0.25), ("3", "C", 0.2499)], {})
    assert [s.block_name for s in out] == ["A", "B"]


def test_facility_outside_every_block_is_left_out():
    blocks = load_blocks()
    inside = facility(1, "Frasergunj PHC", 88.26, 21.59)
    at_sea = facility(2, "Nowhere PHC", 89.9, 20.0)
    blocks_of = S.facility_blocks([inside, at_sea], blocks)
    assert blocks_of == {inside.id: blocks.codes[blocks.names.index("Namkhana")]}
    by_id = {f.id: f for f in (inside, at_sea)}
    assert S.expected_by_block({at_sea.id, "hospital-node-999"}, by_id, blocks_of) == {}


# --- Excluded facilities --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "counts"),
    [
        ("Suraksha Diagnostic Centre", False),
        ("Kakdwip Maternity and Nursing Home", False),
        ("Sagar Polyclinic", False),
        ("Lions Eye Hospital", False),
        ("Smile Dental Care", False),
        ("Raidighi BPHC", True),
        ("Gosaba Rural Hospital", True),
        ("Kakdwip Sub Divisional Hospital", True),
        ("Rural Hospital Eye Clinic", True),  # a KEEP pattern wins, as for hospital access
        (None, True),
    ],
)
def test_counts_for_advisory_uses_the_hospital_access_patterns(name, counts):
    assert W.counts_for_advisory(name) is counts
    assert W.counts_for_advisory(name) is W.is_access_hospital(name)  # one list, not a copy


def test_excluded_facilities_are_no_reason():
    diag, bphc = facility(1, "Suraksha Diagnostic Centre"), facility(2, "Raidighi BPHC")
    by_id = {f.id: f for f in (diag, bphc)}
    expected = S.expected_by_block({diag.id, bphc.id}, by_id, {diag.id: "b", bphc.id: "b"})
    assert expected == {"b": [bphc]}
    assert S.expected_by_block({diag.id}, by_id, {diag.id: "b"}) == {}


# --- On the committed fixtures --------------------------------------------------------------------

# Each block's first suggestion and why (DEMO_MODE, the committed fixtures).
FIRST_SUGGESTION = {
    "Namkhana": (42, ["Frasergunj PHC expected to be cut off"]),
    "Gosaba": (
        27,
        [
            "risk 0.27",
            "Chotomollakhali PHC expected to be cut off",
            "Gosaba Rural Hospital expected to be cut off",
        ],
    ),
    "Sagar": (
        27,
        [
            "risk 0.60",
            "Gangasagar PHC expected to be cut off",
            "Mahendraganj PHC expected to be cut off",
        ],
    ),
    "Patharpratima": (27, ["Madhabnagar Rural Hospital expected to be cut off"]),
    "Kakdwip": (
        24,
        [
            "risk 0.28",
            "Kakdwip Sub Divisional Hospital expected to be cut off",
            "Nonamath Sub Center expected to be cut off",
            "Sundarban Adarsha Vidyamandir expected to be cut off",
            "Sundarban Maha Vidyalaya expected to be cut off",
        ],
    ),
    # Suraksha Diagnostic Centre is excluded; Raidighi BPHC still suggests the block at T-24.
    "Mathurapur-II": (24, ["Raidighi BPHC expected to be cut off"]),
    "Kultali": (24, ["Bhubaneswari PHC expected to be cut off"]),
}


def test_first_suggestion_per_block(demo):
    first: dict[str, tuple[int, list[str]]] = {}
    for n, ts in enumerate(REPLAY_TIMESTEPS):
        body = client.get("/api/advisory/suggestions", params={"timestep": ts}).json()
        for b in body["blocks"]:
            first.setdefault(b["block_name"], ((24 - n) * 3, [r["label"] for r in b["reasons"]]))
    assert first == FIRST_SUGGESTION


def test_excluded_facility_not_in_the_advisory_facts(demo):
    """Suraksha Diagnostic Centre (Mathurapur-II) is expected to be cut off at T-24 and cut off
    at landfall; Kakdwip Maternity and Nursing Home is cut off at landfall. Neither is listed,
    though both stay isolated in the impact results."""
    for block, ts, excluded, kept in (
        ("Mathurapur-II", t(24), "Suraksha Diagnostic Centre", "Raidighi BPHC"),
        ("Mathurapur-II", t(0), "Suraksha Diagnostic Centre", "Raidighi BPHC"),
        ("Kakdwip", t(0), "Kakdwip Maternity and Nursing Home", "Kakdwip Sub Divisional Hospital"),
    ):
        infra = {f.properties.name: f.id for f in exposure.get_infra().features}
        horizon = 0 if ts == t(0) else 24
        assert infra[excluded] in impact.isolated_ids(ts, horizon)
        blocks = load_blocks()
        facts = facts_module.build_facts(blocks.codes[blocks.names.index(block)], ts)
        values = {c.value for c in facts.citations}
        assert excluded not in values, (block, ts)
        assert kept in values, (block, ts)
