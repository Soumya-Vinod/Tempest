"""Advisory generation, the number check and the approval queue. Gemini is mocked throughout."""

import json

import httpx
import pytest
import shapely
from fastapi.testclient import TestClient

from app.advisory import facts as facts_module
from app.advisory import gemini, providers, render, service, store
from app.advisory.facts import Facts
from app.advisory.prompt import SYSTEM_PROMPT, user_message
from app.core import demo as demo_module
from app.core.config import Settings
from app.main import app
from app.schemas import (
    LANDFALL_TIMESTEP,
    REPLAY_TIMESTEPS,
    AdvisoryTexts,
    Citation,
    GeneratedBy,
    InfraFeature,
)
from tests import impact_scenario as S
from tests import risk_scenario as R

TS = LANDFALL_TIMESTEP
BLOCK = "02435"
URL = "/api/advisory/"
client = TestClient(app)

CITATIONS = [
    Citation(key="block_name", label="CD block", value="Gosaba", unit=None, source="reference"),
    Citation(key="risk_score", label="Risk", value=0.2741, unit=None, source="risk"),
    Citation(key="peak_surge_m", label="Peak surge", value=1.5, unit="m", source="hazard"),
    Citation(key="hours_to_landfall", label="Hours", value=3, unit="h", source="replay"),
    Citation(key="cut_road_km", label="Cut roads", value=24.7, unit="km", source="impact"),
    Citation(key="reach", label="Reach", value="cut off by the storm", unit=None, source="risk"),
    Citation(
        key="isolated_1_name", label="Isolated", value="Ward 12 PHC", unit=None, source="impact"
    ),
    Citation(
        key="isolated_1_next_hospital_min",
        label="Next hospital",
        value=37,
        unit="min",
        source="exposure",
    ),
]
FACTS = Facts(BLOCK, "Gosaba", TS, CITATIONS)


def lang(
    headline="{{block_name}}: cut roads {{cut_road_km}}",
    body="Surge up to {{peak_surge_m}} in {{hours_to_landfall}}; {{reach}}.",
    actions=(
        "Move patients from {{isolated_1_name}}.",
        "Open shelters.",
        "Clear roads ({{cut_road_km}}).",
    ),
):
    return {"headline": headline, "body": body, "actions": list(actions)}


CLEAN = {"en": lang(), "bn": lang(), "hi": lang()}


def with_en(**changes) -> dict:
    return {**CLEAN, "en": lang(**changes)}


class FakeGemini:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, system_prompt, message, api_key):
        assert "{{" in system_prompt and api_key == "test-key"
        self.calls.append(message)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return json.loads(json.dumps(response))


def settings(demo: bool, key: str | None, groq_key: str | None = None) -> Settings:
    return Settings(_env_file=None, DEMO_MODE=demo, GEMINI_API_KEY=key, GROQ_API_KEY=groq_key)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Empty DB and demo dir; facts stubbed; live mode with a key unless a test changes it."""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "state" / "tempest.db")
    monkeypatch.setattr(demo_module, "DEMO_DIR", tmp_path)
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: FACTS)

    def mode(demo: bool, key: str | None = "test-key", groq_key: str | None = None):
        s = settings(demo, key, groq_key)
        for module in (service, demo_module):
            monkeypatch.setattr(module, "get_settings", lambda: s)

    mode(False)
    env = type("Env", (), {"mode": staticmethod(mode), "dir": tmp_path})()

    def fake(*responses):
        f = FakeGemini(*responses)
        monkeypatch.setattr(gemini, "generate", f)
        return f

    env.gemini = staticmethod(fake)
    return env


def create(env, *responses):
    fake = env.gemini(*responses)
    resp = client.post(URL, json={"block_id": BLOCK, "timestep": TS})
    return resp, fake


def actions(advisory_id=None):
    return [e.action for e in store.events(advisory_id)]


# --- Filling and the number check ---------------------------------------------------------------


def test_placeholders_filled_in_all_three_languages():
    texts = render.render(AdvisoryTexts.model_validate(CLEAN), CITATIONS)
    assert texts.en.headline == "Gosaba: cut roads 24.7 km"
    assert texts.en.body.endswith("Surge up to 1.5 m in 3 hours; cut off by the storm.")
    assert texts.en.actions[0] == "Move patients from Ward 12 PHC."
    # Bengali numerals and units, the block's Bengali name; other names keep their own digits.
    assert texts.bn.headline == "গোসাবা: cut roads ২৪.৭ কিমি"
    assert "১.৫ মিটার" in texts.bn.body and "৩ ঘণ্টা" in texts.bn.body
    assert "ঝড়ে বিচ্ছিন্ন" in texts.bn.body
    assert texts.bn.actions[0] == "Move patients from Ward 12 PHC."
    assert texts.bn.actions[2] == "Clear roads (২৪.৭ কিমি)."
    # Hindi: Latin digits, Hindi units.
    assert "1.5 मीटर" in texts.hi.body and "3 घंटे" in texts.hi.body
    assert texts.hi.headline == "Gosaba: cut roads 24.7 किमी"  # no Hindi label: English name


def test_one_hour_is_singular():
    c = Citation(key="hours_to_landfall", label="h", value=1, unit="h", source="replay")
    assert render.format_value(c, "en") == "1 hour"


def cite(key: str, value, unit: str | None = None) -> Citation:
    return Citation(key=key, label=key, value=value, unit=unit, source="test")


@pytest.mark.parametrize(
    ("ms", "en", "bn", "hi"),
    [
        (37, "135 km/h", "১৩৫ কিমি/ঘণ্টা", "135 किमी/घंटा"),  # 133.2 km/h
        (41, "150 km/h", "১৫০ কিমি/ঘণ্টা", "150 किमी/घंटा"),  # 147.6 km/h
        (6.25, "25 km/h", "২৫ কিমি/ঘণ্টা", "25 किमी/घंटा"),  # 22.5 km/h: half a step rounds up
        (0, "0 km/h", "০ কিমি/ঘণ্টা", "0 किमी/घंटा"),
    ],
)
def test_wind_is_written_in_kmh_to_the_nearest_5(ms, en, bn, hi):
    c = cite("peak_wind_ms", ms, "m/s")
    assert [render.format_value(c, lang) for lang in render.LANGUAGES] == [en, bn, hi]
    assert c.value == ms and c.unit == "m/s"  # the citation keeps m/s


@pytest.mark.parametrize(
    ("metres", "en", "bn"),
    [(2.56, "2.6 m", "২.৬ মিটার"), (4.09, "4.1 m", "৪.১ মিটার"), (3, "3.0 m", "৩.০ মিটার")],
)
def test_surge_is_written_to_a_tenth_of_a_metre(metres, en, bn):
    c = cite("peak_surge_m", metres, "m")
    assert render.format_value(c, "en") == en and render.format_value(c, "bn") == bn


def test_block_name_in_the_text_language():
    gosaba = cite("block_name", "Gosaba")
    assert render.format_value(gosaba, "en") == "Gosaba"
    assert render.format_value(gosaba, "bn") == "গোসাবা"
    assert render.format_value(gosaba, "hi") == "Gosaba"  # no Hindi label on Wikidata
    thakurpukur = cite("block_name", "Thakurpukur Mahestola")
    assert render.format_value(thakurpukur, "hi") == "ठाकुरपुकुर महेशतला"
    assert render.format_value(cite("block_name", "Not A Block"), "bn") == "Not A Block"


def test_local_names_skip_empty_labels(tmp_path):
    from app.risk.blocks import local_names

    path = tmp_path / "lookup.csv"
    rows = ["# note", "block_name,census2011_code,name_bn,name_hi", "A,00001,আ,", "B,00002,,बी"]
    path.write_text("\n".join(rows) + "\n", "utf-8")
    assert local_names(path) == {"A": {"bn": "আ"}, "B": {"hi": "बी"}}


@pytest.mark.parametrize("kind", list(render.UNNAMED))
def test_unnamed_facility_in_each_language(kind):
    cited, en, bn, hi = render.UNNAMED[kind]
    c = cite("isolated_1_name", cited)
    assert [render.format_value(c, lang) for lang in render.LANGUAGES] == [en, bn, hi]


def test_unnamed_phrases():
    assert render.UNNAMED["hospital"][1:] == (
        "an unnamed hospital",
        "নামহীন একটি হাসপাতাল",
        "एक अनाम अस्पताल",
    )
    assert render.UNNAMED["public_building_proxy"][1:] == (
        "an unnamed public building (stand-in shelter)",
        "নামহীন একটি সরকারি ভবন (বিকল্প আশ্রয়)",
        "एक अनाम सरकारी भवन (वैकल्पिक आश्रय)",
    )


@pytest.mark.parametrize(
    ("attributes", "infra_type", "expected"),
    [
        ({"facility_level": "hospital"}, "hospital", "Unnamed hospital"),
        ({"facility_level": "health_centre"}, "hospital", "Unnamed health centre"),
        ({"shelter_kind": "school_proxy"}, "shelter", "Unnamed school (stand-in shelter)"),
        (
            {"shelter_kind": "community_proxy"},
            "shelter",
            "Unnamed community centre (stand-in shelter)",
        ),
        ({"shelter_kind": "cyclone_shelter"}, "shelter", "Unnamed cyclone shelter"),
    ],
)
def test_facts_label_unnamed_facilities_by_kind(attributes, infra_type, expected):
    from types import SimpleNamespace

    f = SimpleNamespace(
        properties=SimpleNamespace(name=None, attributes=attributes, infra_type=infra_type)
    )
    assert facts_module._name(f) == expected


def test_english_values_starting_a_sentence_are_capitalised():
    by_key = {
        "isolated_1_name": cite("isolated_1_name", render.UNNAMED["hospital"][0]),
        "reach": cite("reach", "cut off by the storm"),
    }
    text = (
        "{{isolated_1_name}} is cut off. {{reach}} now! Is it {{reach}}? {{reach}}, then "
        "{{isolated_1_name}}.{{reach}}"
    )
    assert render.fill(text, by_key, "en") == (
        "An unnamed hospital is cut off. Cut off by the storm now! Is it cut off by the storm? "
        "Cut off by the storm, then an unnamed hospital.cut off by the storm"
    )
    assert render.fill("{{isolated_1_name}}.", by_key, "bn") == "নামহীন একটি হাসপাতাল."


def test_rendered_body_capitalised_after_the_exercise_label():
    templates = AdvisoryTexts.model_validate(with_en(body="{{reach}}: act now."))
    texts = render.render(templates, CITATIONS)
    assert texts.en.body == f"{render.EXERCISE_PREFIX['en']} Cut off by the storm: act now."


@pytest.mark.parametrize(
    ("language", "text", "found"),
    [
        ("en", "Surge 3 m", ["3"]),
        ("en", "Move two boats and a dozen crews", ["two", "dozen"]),
        ("en", "Twice as many, half the time, thousands", ["Twice", "half", "thousands"]),
        ("en", "Someone often mentions the tone", []),
        ("bn", "৩ মিটার জলোচ্ছ্বাস", ["৩"]),
        ("bn", "তিনটি নৌকা ও দুই দল", ["তিনটি", "দুই"]),
        ("bn", "তিনি এখানে; এটি নিরাপদ নয়; একটি নৌকা", []),  # he/she, "is not", "a"
        ("bn", "হাজার মানুষ", ["হাজার"]),
        ("hi", "दोनों अस्पताल, चार नावें", ["दोनों", "चार"]),
        ("hi", "एक नाव भेजें, नौका तैयार रखें, चारपाई", []),  # "a", boat, bed
        ("hi", "५ किमी", ["५"]),
        ("hi", "सौ लोग", ["सौ"]),
    ],
)
def test_number_check(language, text, found):
    assert [m for _, m in render.number_problems(text, language)] == found


def test_placeholders_are_not_numbers():
    assert render.number_problems("{{peak_surge_m}} and {{isolated_1_name}}", "en") == []


def test_unknown_placeholder_is_a_problem():
    t = AdvisoryTexts.model_validate(with_en(headline="{{made_up}}"))
    problems = render.check(t, {c.key for c in CITATIONS})
    assert [(p.language, p.kind, p.text) for p in problems] == [
        ("en", "unknown_placeholder", "made_up")
    ]


# --- Generation ---------------------------------------------------------------------------------


def test_create_fills_and_prefixes(env):
    resp, fake = create(env, CLEAN)
    assert resp.status_code == 200, resp.text
    p = resp.json()["properties"]
    assert len(fake.calls) == 1 and p["status"] == "draft" and p["block_name"] == "Gosaba"
    for language, prefix in render.EXERCISE_PREFIX.items():
        assert p["texts"][language]["body"].startswith(prefix + " ")
        assert not p["templates"][language]["body"].startswith("[")
    assert p["citations"] == [c.model_dump() for c in CITATIONS]
    assert actions(p["id"]) == ["generated"]


def test_stray_digit_retries_once_then_succeeds(env):
    bad = with_en(body="Surge of 3 m expected in {{hours_to_landfall}}.")
    resp, fake = create(env, bad, CLEAN)
    assert resp.status_code == 200
    assert len(fake.calls) == 2 and "previous draft was rejected" in fake.calls[1]
    failed = [e for e in store.events() if e.action == "number_check_failed"]
    assert len(failed) == 1 and failed[0].advisory_id is None
    details = json.loads(failed[0].details)
    assert details["attempt"] == 1 and "en.body: digit '3'" in details["problems"]
    assert details["text"]["en.body"] == "Surge of 3 m expected in {{hours_to_landfall}}."


def test_number_words_fail_twice_then_502(env):
    bad = with_en(actions=["Send two boats.", "Open shelters.", "Clear roads."])
    resp, fake = create(env, bad, bad)
    assert resp.status_code == 502
    assert "number_word 'two'" in " ".join(resp.json()["detail"]["problems"])
    assert len(fake.calls) == 2
    assert actions() == ["number_check_failed", "number_check_failed"]
    assert store.list_advisories() == []


def test_invalid_structure_is_retried(env):
    too_few = {**CLEAN, "hi": lang(actions=("Only one.",))}
    resp, fake = create(env, too_few, CLEAN)
    assert resp.status_code == 200 and len(fake.calls) == 2
    assert actions()[0] == "invalid_response"


def test_gemini_error_is_502(env, monkeypatch):
    def boom(*_):
        raise gemini.GeminiError("Gemini call failed: timeout")

    monkeypatch.setattr(gemini, "generate", boom)
    resp = client.post(URL, json={"block_id": BLOCK, "timestep": TS})
    assert resp.status_code == 502 and "timeout" in resp.json()["detail"]


def test_demo_mode_uses_cached_response_without_calling_gemini(env):
    env.mode(True, key=None)
    write_cached(env, service.fixture_payload(CLEAN, FACTS))
    resp, fake = create(env)
    assert resp.status_code == 200 and fake.calls == []
    assert json.loads(store.events()[0].details)["source"] == "fixture"


STALE = {**CLEAN, "bn": lang(body="{{peak_surge_m}}, {{cut_substations}}.")}  # key facts lack


def write_cached(env, response: dict) -> None:
    (env.dir / f"{service.fixture_key(BLOCK, TS)}.json").write_text(
        json.dumps(response), encoding="utf-8"
    )


def with_citations(*changes: Citation) -> Facts:
    """FACTS with citations replaced or added by key."""
    by_key = {c.key: c for c in CITATIONS} | {c.key: c for c in changes}
    return Facts(BLOCK, "Gosaba", TS, list(by_key.values()))


# Mahendraganj PHC at Sagar T-3: first cut off by a ferry stopped by wind, then (Dev A's new
# surge model) by storm surge. Same keys, different meaning.
CAUSE_WIND = Citation(
    key="isolated_1_cause",
    label="Cause",
    value="ferry suspended by wind",
    unit=None,
    source="impact",
)
CAUSE_SURGE = CAUSE_WIND.model_copy(update={"value": "road flooded by storm surge"})
MAHENDRAGANJ = Citation(
    key="isolated_1_name", label="Isolated", value="Mahendraganj PHC", unit=None, source="impact"
)
WITH_CAUSE = {
    **CLEAN,
    "en": lang(
        actions=("Move patients from {{isolated_1_name}} ({{isolated_1_cause}}).", "b", "c")
    ),
}


def test_fixture_payload_stores_the_text_values_its_templates_use():
    facts = with_citations(MAHENDRAGANJ, CAUSE_WIND)
    stored = service.fixture_payload(WITH_CAUSE, facts)[service.CITED_TEXT_KEY]
    # Text only (numbers are filled at render time), and only keys the templates use.
    assert stored == {
        "block_name": "Gosaba",
        "isolated_1_cause": "ferry suspended by wind",
        "isolated_1_name": "Mahendraganj PHC",
        "reach": "cut off by the storm",
    }


def test_staleness():
    wind = with_citations(MAHENDRAGANJ, CAUSE_WIND)
    cached = service.fixture_payload(WITH_CAUSE, wind)
    assert service.staleness(cached, wind) is None
    # Numbers may change freely.
    surge_up = CITATIONS[2].model_copy(update={"value": 3.32})
    assert service.staleness(cached, with_citations(MAHENDRAGANJ, CAUSE_WIND, surge_up)) is None
    # A referenced cause that changed makes it stale.
    assert service.staleness(cached, with_citations(MAHENDRAGANJ, CAUSE_SURGE)) == {
        "changed_text": {
            "isolated_1_cause": {
                "cached": "ferry suspended by wind",
                "current": "road flooded by storm surge",
            }
        }
    }
    # Missing keys, and fixtures written before values were stored (the Sagar T-3 one).
    assert service.staleness(STALE, FACTS) == {"missing_keys": ["cut_substations"]}
    assert service.staleness(CLEAN, FACTS) == {"cited_text": "not stored"}
    assert service.staleness({"en": "not a draft"}, FACTS) is None  # evaluate() reports it


def test_changed_cause_is_stale_audited_and_falls_back_to_503(env, monkeypatch):
    env.mode(True, key=None)
    write_cached(env, service.fixture_payload(WITH_CAUSE, with_citations(MAHENDRAGANJ, CAUSE_WIND)))
    now = with_citations(MAHENDRAGANJ, CAUSE_SURGE)
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: now)
    resp, fake = create(env, CLEAN)
    assert resp.status_code == 503 and fake.calls == []
    stale = store.events()[0]
    assert stale.action == "invalid_response" and stale.advisory_id is None
    details = json.loads(stale.details)
    assert details["reason"] == "stale_fixture" and details["attempt"] == "fixture"
    assert details["changed_text"]["isolated_1_cause"]["current"] == "road flooded by storm surge"


def test_fixture_without_stored_values_is_stale(env):
    env.mode(True, key=None)
    write_cached(env, CLEAN)  # as written before this check existed
    resp, fake = create(env, CLEAN)
    assert resp.status_code == 503 and fake.calls == []
    details = json.loads(store.events()[0].details)
    assert details["reason"] == "stale_fixture" and details["cited_text"] == "not stored"


def test_stale_cached_response_is_audited_and_falls_back_to_503(env):
    env.mode(True, key=None)
    write_cached(env, STALE)
    resp, fake = create(env, CLEAN)
    assert resp.status_code == 503 and fake.calls == []
    stale = store.events()[0]
    assert stale.action == "invalid_response" and stale.advisory_id is None
    details = json.loads(stale.details)
    assert details["reason"] == "stale_fixture" and details["missing_keys"] == ["cut_substations"]


def test_stale_cached_response_falls_back_to_the_live_key(env):
    env.mode(True, key="test-key")
    write_cached(env, STALE)
    resp, fake = create(env, CLEAN)
    assert resp.status_code == 200 and len(fake.calls) == 1
    assert [e.action for e in store.events()][:2] == ["invalid_response", "generated"]
    assert json.loads(store.events()[1].details)["source"] == "gemini"


def test_demo_mode_without_fixture_or_key_is_503(env):
    env.mode(True, key=None)
    resp, fake = create(env, CLEAN)
    assert resp.status_code == 503 and fake.calls == []
    assert "No cached Gemini response for Gosaba" in resp.json()["detail"]
    assert "GEMINI_API_KEY is not set" in resp.json()["detail"]


def test_demo_mode_without_fixture_uses_the_key(env):
    env.mode(True, key="test-key")
    resp, fake = create(env, CLEAN)
    assert resp.status_code == 200 and len(fake.calls) == 1


def test_live_mode_without_key_is_503(env):
    env.mode(False, key=None)
    resp, _ = create(env, CLEAN)
    assert resp.status_code == 503


def test_live_timestep_is_501(env):
    resp = client.post(URL, json={"block_id": BLOCK, "timestep": "live"})
    assert resp.status_code == 501


# --- Approval rules -----------------------------------------------------------------------------


@pytest.fixture
def draft(env):
    resp, _ = create(env, CLEAN)
    return resp.json()["properties"]


def test_edit_rerenders_and_keeps_the_prefix(draft):
    new = with_en(body="Updated: {{reach}}, surge {{peak_surge_m}}, {{hours_to_landfall}}.")
    resp = client.patch(f"{URL}{draft['id']}", json={"templates": new, "edited_by": "Asha"})
    assert resp.status_code == 200, resp.text
    body = resp.json()["properties"]["texts"]["en"]["body"]
    expected = "Updated: cut off by the storm, surge 1.5 m, 3 hours."
    assert body == f"{render.EXERCISE_PREFIX['en']} {expected}"
    assert actions(draft["id"]) == ["generated", "edited"]


KEPT = "{{peak_surge_m}} {{hours_to_landfall}} {{reach}}"


@pytest.mark.parametrize(
    ("templates", "problem"),
    [
        (with_en(body="Surge {{hours_to_landfall}} and {{reach}}."), "removed_placeholder"),
        (with_en(body=f"Surge 2 m {KEPT}"), "digit"),
        (with_en(body=f"Five boats {KEPT}"), "number_word"),
        (with_en(body=f"{{{{nope}}}} {KEPT}"), "unknown_placeholder"),
    ],
)
def test_edit_is_checked(draft, templates, problem):
    resp = client.patch(f"{URL}{draft['id']}", json={"templates": templates})
    assert resp.status_code == 422
    assert any(problem in p for p in resp.json()["detail"]["problems"])
    assert client.get(f"{URL}{draft['id']}").json()["properties"]["templates"] == draft["templates"]
    audit = actions(draft["id"])
    expected = "number_check_failed" if problem in ("digit", "number_word") else "invalid_response"
    assert audit == ["generated", expected]


@pytest.mark.parametrize(
    "approver",
    [
        "Asha Roy (BDO)",
        "Asha Roy (SDO)",
        "Asha Roy (ADM (Disaster Management))",
        "Asha Roy (District Magistrate)",
        "Asha Roy (Other: Block Health Officer)",
    ],
)
def test_approve_accepts_designations(draft, approver):
    resp = client.post(f"{URL}{draft['id']}/approve", json={"approved_by": approver})
    assert resp.status_code == 200, resp.text
    p = resp.json()["properties"]
    assert p["status"] == "approved" and p["approved_by"] == approver and p["approved_at"]


@pytest.mark.parametrize(
    "approver",
    ["Asha Roy", "Asha Roy (Mayor)", "Asha Roy (Other)", "Asha Roy (Other: )", "(BDO)", "  "],
)
def test_approve_rejects_bad_approver(draft, approver):
    resp = client.post(f"{URL}{draft['id']}/approve", json={"approved_by": approver})
    assert resp.status_code == 422
    assert client.get(f"{URL}{draft['id']}").json()["properties"]["status"] == "draft"


def test_approved_is_locked(draft):
    aid = draft["id"]
    client.post(f"{URL}{aid}/approve", json={"approved_by": "Asha Roy (BDO)"})
    assert client.patch(f"{URL}{aid}", json={"templates": CLEAN}).status_code == 409
    assert client.post(f"{URL}{aid}/approve", json={"approved_by": "B (SDO)"}).status_code == 409
    assert client.post(f"{URL}{aid}/reject", json={"reason": "late"}).status_code == 409
    assert actions(aid) == ["generated", "approved"]
    assert store.events(aid)[1].actor == "Asha Roy (BDO)"


def test_reject_needs_a_reason(draft):
    aid = draft["id"]
    assert client.post(f"{URL}{aid}/reject", json={}).status_code == 422
    assert client.post(f"{URL}{aid}/reject", json={"reason": "   "}).status_code == 422
    resp = client.post(f"{URL}{aid}/reject", json={"reason": "Wrong block", "rejected_by": "Asha"})
    assert resp.status_code == 200
    p = resp.json()["properties"]
    assert p["status"] == "rejected" and p["rejection_reason"] == "Wrong block" and p["rejected_at"]
    assert client.post(f"{URL}{aid}/approve", json={"approved_by": "A (BDO)"}).status_code == 409
    event = store.events(aid)[-1]
    assert (event.action, event.actor, json.loads(event.details)) == (
        "rejected",
        "Asha",
        {"reason": "Wrong block"},
    )


def test_new_draft_from_approved(draft):
    aid = draft["id"]
    assert client.post(f"{URL}{aid}/new-draft").status_code == 409  # a draft: edit it instead
    client.post(f"{URL}{aid}/approve", json={"approved_by": "Asha Roy (BDO)"})
    resp = client.post(f"{URL}{aid}/new-draft", json={"created_by": "Asha"})
    assert resp.status_code == 200
    new = resp.json()["properties"]
    assert new["id"] != aid and new["status"] == "draft" and new["created_from"] == aid
    assert new["texts"] == draft["texts"] and new["approved_by"] is None
    assert actions(new["id"]) == ["new_draft"]
    assert actions(aid) == ["generated", "approved", "copied"]
    # The copy is editable; the original stays locked.
    assert client.patch(f"{URL}{new['id']}", json={"templates": CLEAN}).status_code == 200
    assert client.get(f"{URL}{aid}").json()["properties"]["status"] == "approved"


def test_list_audit_and_404(draft):
    client.post(f"{URL}{draft['id']}/reject", json={"reason": "duplicate"})
    assert [f["id"] for f in client.get(URL).json()["features"]] == [draft["id"]]
    assert client.get(URL, params={"status": "draft"}).json()["features"] == []
    log = client.get(f"{URL}{draft['id']}/audit").json()["events"]
    assert [e["action"] for e in log] == ["generated", "rejected"]
    assert [e["action"] for e in client.get(f"{URL}audit").json()["events"]] == [
        "generated",
        "rejected",
    ]
    assert client.get(f"{URL}nope").status_code == 404
    assert client.get(f"{URL}nope/audit").status_code == 404


def test_suggestions(env, monkeypatch):
    from app.schemas import RiskScoreCollection

    def score(block_id, name, value):
        return {
            "type": "Feature",
            "id": f"{block_id}__{TS}",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "properties": {
                "id": f"{block_id}__{TS}",
                "block_id": block_id,
                "block_source": "census2011_cd",
                "block_name": name,
                "timestep": TS,
                "score": value,
                "components": {"hazard": 0.5, "exposure": 0.5, "vulnerability": 0.5},
            },
        }

    fc = RiskScoreCollection.model_validate(
        {
            "type": "FeatureCollection",
            "features": [score("1", "A", 0.2499), score("2", "B", 0.25), score("3", "C", 0.6)],
        }
    )
    horizons = []
    monkeypatch.setattr(service.risk, "get_scores", lambda ts, h=0: horizons.append(h) or fc)
    monkeypatch.setattr(service, "expected_cut_off_by_block", lambda ts: {})
    resp = client.get(f"{URL}suggestions", params={"timestep": TS})
    assert resp.status_code == 200
    body = resp.json()
    assert body["threshold"] == service.SUGGEST_MIN_SCORE == 0.25
    assert [b["block_name"] for b in body["blocks"]] == ["C", "B"]
    assert body["blocks"][0]["reasons"] == [
        {"kind": "risk", "label": "risk 0.60", "infra_id": None}
    ]
    assert horizons == [24]  # suggestions use the risk expected within 24 h (v1.3)

    # v1.3: a facility expected to be cut off suggests its block whatever the score.
    phc = InfraFeature.model_validate(
        {
            "type": "Feature",
            "id": "hospital-node-1",
            "geometry": {"type": "Point", "coordinates": [88.5, 22.0]},
            "properties": {
                "id": "hospital-node-1",
                "infra_type": "hospital",
                "name": "A PHC",
                "osm_id": "node/1",
                "attributes": {},
            },
        }
    )
    monkeypatch.setattr(service, "expected_cut_off_by_block", lambda ts: {"1": [phc]})
    body = client.get(f"{URL}suggestions", params={"timestep": TS}).json()
    assert [b["block_name"] for b in body["blocks"]] == ["C", "B", "A"]
    assert body["blocks"][2]["reasons"] == [
        {"kind": "expected_cut_off", "label": "A PHC expected to be cut off", "infra_id": phc.id}
    ]


# --- Facts --------------------------------------------------------------------------------------


def test_peak_counts_only_inhabited_land():
    # Island block, its west half protected (uninhabited): a deep surge cell there doesn't count,
    # nor does one that only touches the block's edge from outside.
    reserve = shapely.box(88.15, 22.25, 88.25, 22.35)
    blocks = R.blocks(protected=reserve)
    land = blocks.inhabited_metric.iloc[1]
    layer = S.hazards(
        TS,
        surge=[
            S.box(88.16, 22.26, 88.24, 22.34, 3.0),  # inside the reserve
            S.box(88.27, 22.27, 88.33, 22.33, 1.2),  # inhabited land
            S.box(88.35, 22.25, 88.40, 22.35, 5.0),  # touches the block's east edge only
        ],
    )["surge"]
    assert facts_module.peak_on_land(layer, land) == pytest.approx(1.2)


def test_hours_to_landfall():
    assert facts_module.hours_to_landfall(TS) == 0
    assert facts_module.hours_to_landfall("2020-05-20T09:00:00Z") == 3


def test_gosaba_facts_from_the_demo_fixtures(monkeypatch):
    from app.exposure import service as exposure
    from app.impact import service as impact
    from app.risk import service as risk

    s = settings(True, None)
    for module in (impact, risk, exposure, demo_module):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    for module in (impact, risk, exposure):
        module.clear_cache()
    try:
        f = facts_module.build_facts(BLOCK, "2020-05-20T09:00:00Z")
    finally:
        for module in (impact, risk, exposure):
            module.clear_cache()
    by_key = {c.key: c for c in f.citations}
    assert f.block_name == "Gosaba" and by_key["hours_to_landfall"].value == 3
    assert by_key["reach"].value == "cut off by the storm"
    assert by_key["isolated_count"].value == 2
    assert by_key["isolated_1_name"].label == "Isolated facility (already cut off now)"
    # A count for every list: per facility type, cut substations, stand-ins (all and named).
    hospitals = by_key["isolated_hospital_count"].value
    assert hospitals + by_key["isolated_shelter_count"].value == 2
    assert "cut_substation_count" in by_key and "cut_substations" not in by_key
    named = [k for k in by_key if k.startswith("standin_") and k.endswith("_name")]
    assert by_key["standin_named_count"].value == len(named)
    assert by_key["standin_count"].value >= len(named)
    names = {by_key[k].value for k in ("isolated_1_name", "isolated_2_name")}
    assert "Gosaba Rural Hospital" in names
    assert by_key["isolated_1_cause"].value == "ferry suspended by wind"
    assert by_key["peak_surge_m"].unit == "m" and by_key["peak_wind_ms"].unit == "m/s"
    assert all(c.key == c.key.lower() for c in f.citations)


# --- Fixture script: pacing, 503 back-off, call budget ------------------------------------------


@pytest.fixture
def fixture_script(env, monkeypatch):
    """The fixture script's run(), with a fake clock: sleeps advance it instead of waiting."""
    import importlib
    import os

    if "DEMO_MODE" in os.environ:  # the script sets DEMO_MODE on import; restore it afterwards
        monkeypatch.setenv("DEMO_MODE", os.environ["DEMO_MODE"])
    else:
        monkeypatch.delenv("DEMO_MODE", raising=False)
    script = importlib.import_module("scripts.build_advisory_fixtures")
    monkeypatch.setattr(script, "build_facts", lambda block_id, ts: FACTS)
    clock = {"now": 0.0, "sleeps": [], "calls": []}

    def sleep(seconds):
        clock["sleeps"].append(round(seconds, 3))
        clock["now"] += seconds

    def generate(responses):
        def fake(system_prompt, message, api_key):
            clock["calls"].append(clock["now"])
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return json.loads(json.dumps(r))

        monkeypatch.setattr(gemini, "generate", fake)

    written = []

    def run(todo, max_calls, *responses, allow_groq=False):
        generate(list(responses))
        return script.run(
            todo,
            max_calls,
            lambda block_id, ts, payload: written.append((block_id, ts, payload)),
            sleep=sleep,
            clock=lambda: clock["now"],
            allow_groq=allow_groq,
        )

    return type("Script", (), {"run": staticmethod(run), "clock": clock, "written": written})


OVERLOADED = gemini.GeminiError("Gemini call failed: ServerError: 503 UNAVAILABLE", status=503)
PAIR = (BLOCK, "Gosaba", TS)


def test_script_backs_off_60s_after_503_and_retries_the_pair(fixture_script):
    result = fixture_script.run([PAIR, PAIR], 20, OVERLOADED, CLEAN, CLEAN)
    assert result.calls == 3 and len(result.written) == 2 and not result.failed
    # 503 on the first call, 60 s back-off, retry; then the next pair paced at 20 s.
    assert fixture_script.clock["calls"] == [0.0, 60.0, 80.0]
    assert fixture_script.clock["sleeps"] == [60.0, 20.0]


def test_script_counts_every_attempt_against_the_budget(fixture_script):
    result = fixture_script.run([PAIR, PAIR], 3, OVERLOADED, OVERLOADED, OVERLOADED)
    assert result.calls == 3 and not result.written
    assert result.skipped == [("Gosaba", TS), ("Gosaba", TS)]
    assert len(fixture_script.clock["calls"]) == 3


def test_script_stops_at_once_on_429_and_lists_the_pairs_left(fixture_script):
    quota = gemini.GeminiError("Gemini call failed: ClientError: 429 RESOURCE_EXHAUSTED", 429)
    first, second, third = (BLOCK, "Gosaba", TS), (BLOCK, "Sagar", TS), (BLOCK, "Namkhana", TS)
    result = fixture_script.run([first, second, third], 20, CLEAN, quota)
    assert result.calls == 2 and result.written == [("Gosaba", TS, 1)]
    assert result.remaining == [("Sagar", TS), ("Namkhana", TS)]
    assert not result.failed and not result.skipped
    assert len(fixture_script.clock["calls"]) == 2  # nothing called after the 429
    assert fixture_script.clock["sleeps"] == [20.0]  # pacing only, no back-off


def test_script_other_gemini_errors_fail_the_pair_without_back_off(fixture_script):
    error = gemini.GeminiError("Gemini call failed: ClientError: 400", status=400)
    result = fixture_script.run([PAIR], 20, error)
    assert result.calls == 1 and [f[0] for f in result.failed] == ["Gosaba"]
    assert fixture_script.clock["sleeps"] == []


def test_script_number_check_retry_uses_the_budget(fixture_script):
    bad = with_en(headline="Surge of 3 m")
    result = fixture_script.run([PAIR], 20, bad, CLEAN)
    assert result.calls == 2 and result.written == [("Gosaba", TS, 2)]
    assert fixture_script.clock["sleeps"] == [20.0]


def test_script_writes_the_cited_text_with_the_response(fixture_script):
    fixture_script.run([PAIR], 20, CLEAN)
    [(block_id, ts, payload)] = fixture_script.written
    assert (block_id, ts) == (BLOCK, TS)
    assert payload == service.fixture_payload(CLEAN, FACTS, providers.GEMINI)
    assert payload[service.CITED_TEXT_KEY]["isolated_1_name"] == "Ward 12 PHC"
    assert service.staleness(payload, FACTS) is None


# --- Groq fallback (both providers mocked) ------------------------------------------------------

GROQ_KEY = "gsk_test-SECRET-groq-key"
QUOTA = gemini.GeminiError("Gemini call failed: ClientError: 429 RESOURCE_EXHAUSTED", status=429)
BUSY = gemini.GeminiError("Gemini call failed: ServerError: 503 UNAVAILABLE", status=503)


class FakeGroq:
    """Groq's chat completions endpoint: returns `responses` (drafts, or (status, error body))."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {GROQ_KEY}"
        self.requests.append(json.loads(request.content))
        r = self.responses.pop(0)
        if isinstance(r, tuple):
            return httpx.Response(r[0], json=r[1])
        content = json.dumps(r, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def groq(env, monkeypatch):
    """Groq configured and mocked; service.sleep recorded instead of waiting."""
    env.mode(False, groq_key=GROQ_KEY)
    fake = FakeGroq()
    monkeypatch.setattr(
        providers, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler))
    )
    monkeypatch.setattr(service, "sleep", fake.sleeps.append)
    return fake


def generated_event(advisory_id: str) -> dict:
    [event] = [e for e in store.events(advisory_id) if e.action == "generated"]
    return json.loads(event.details)


def test_gemini_429_falls_back_to_groq_and_is_labelled(env, groq):
    groq.responses = [CLEAN]
    resp, fake = create(env, QUOTA)
    assert resp.status_code == 200, resp.text
    p = resp.json()["properties"]
    assert p["generated_by"] == {"provider": "groq", "model": "openai/gpt-oss-120b"}
    assert len(fake.calls) == 1 and groq.sleeps == []  # 429: straight to Groq, no retry
    details = generated_event(p["id"])
    assert details["fallback_reason"] == "gemini 429" and details["source"] == "groq"
    assert details["generated_by"] == p["generated_by"]
    # Same prompt, same schema, strict JSON-schema output.
    [request] = groq.requests
    assert request["model"] == "openai/gpt-oss-120b"
    assert request["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message(FACTS)},
    ]
    fmt = request["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema["required"] == ["en", "bn", "hi"] and schema["additionalProperties"] is False
    # Rendered exactly like a Gemini draft: placeholders filled, exercise prefix added.
    assert p["texts"]["en"]["body"].startswith(render.EXERCISE_PREFIX["en"])
    assert "1.5 m" in p["texts"]["en"]["body"]


def test_gemini_503_is_retried_once_after_2s_then_groq(env, groq):
    groq.responses = [CLEAN]
    resp, fake = create(env, BUSY, BUSY)
    assert resp.status_code == 200, resp.text
    assert len(fake.calls) == 2 and groq.sleeps == [2.0]
    assert resp.json()["properties"]["generated_by"]["provider"] == "groq"
    assert generated_event(resp.json()["id"])["fallback_reason"] == "gemini 503 x2"


def test_gemini_503_then_ok_needs_no_groq(env, groq):
    resp, fake = create(env, BUSY, CLEAN)
    assert resp.status_code == 200
    assert resp.json()["properties"]["generated_by"] == {
        "provider": "gemini",
        "model": "gemini-3.7-flash",
    }
    assert len(fake.calls) == 2 and groq.sleeps == [2.0] and groq.requests == []
    assert "fallback_reason" not in generated_event(resp.json()["id"])


def test_gemini_ok_never_calls_groq(env, groq):
    resp, fake = create(env, CLEAN)
    assert resp.status_code == 200 and len(fake.calls) == 1
    assert groq.requests == [] and groq.sleeps == []
    assert resp.json()["properties"]["generated_by"]["provider"] == "gemini"


@pytest.mark.parametrize(("responses", "status"), [((QUOTA,), "429"), ((BUSY, BUSY), "503")])
def test_without_a_groq_key_the_gemini_error_stands(env, groq, responses, status):
    env.mode(False, groq_key=None)
    resp, _ = create(env, *responses)
    assert resp.status_code == 502 and status in resp.json()["detail"]
    assert groq.requests == []


def test_other_gemini_errors_do_not_fall_back(env, groq):
    bad_request = gemini.GeminiError("Gemini call failed: ClientError: 400", status=400)
    resp, _ = create(env, bad_request)
    assert resp.status_code == 502 and groq.requests == []


def test_number_check_rejects_bad_groq_output(env, groq):
    bad = with_en(headline="Surge of 3 m")
    groq.responses = [bad, bad]
    resp, _ = create(env, QUOTA)
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "Groq" in detail["message"] and "gemini 429" in detail["message"]
    assert any("digit" in p for p in detail["problems"])
    assert len(groq.requests) == 2  # one retry with the correction note, like Gemini
    assert "rejected" in groq.requests[1]["messages"][1]["content"]
    failed = [json.loads(e.details) for e in store.events() if e.action == "number_check_failed"]
    assert [f["generated_by"]["provider"] for f in failed] == ["groq", "groq"]


def test_bad_then_good_groq_output_passes_on_the_retry(env, groq):
    groq.responses = [with_en(headline="Two boats"), CLEAN]
    resp, _ = create(env, QUOTA)
    assert resp.status_code == 200 and len(groq.requests) == 2


def test_groq_errors_never_contain_the_key(env, groq):
    groq.responses = [(401, {"error": {"message": f"Invalid API Key {GROQ_KEY}"}})]
    resp, _ = create(env, QUOTA)
    assert resp.status_code == 502
    assert GROQ_KEY not in resp.text and "***" in resp.text
    assert GROQ_KEY not in "".join(e.details or "" for e in store.events())


def test_fixture_drafts_are_labelled_gemini_and_copies_keep_the_label(env, groq):
    env.mode(True, key=None, groq_key=GROQ_KEY)
    write_cached(env, service.fixture_payload(CLEAN, FACTS))
    resp, fake = create(env)
    p = resp.json()["properties"]
    assert p["generated_by"]["provider"] == "gemini" and fake.calls == [] and groq.requests == []
    approved = client.post(f"{URL}{p['id']}/approve", json={"approved_by": "A. Officer (BDO)"})
    copy = client.post(f"{URL}{approved.json()['id']}/new-draft", json={})
    assert copy.json()["properties"]["generated_by"] == p["generated_by"]


def test_fixture_script_never_falls_back_to_groq(env, groq, fixture_script):
    env.mode(False, groq_key=GROQ_KEY)
    result = fixture_script.run([PAIR], 20, QUOTA)
    assert result.remaining == [("Gosaba", TS)] and not result.written
    assert groq.requests == [] and groq.sleeps == []


# --- Counts: placeholders, never words ----------------------------------------------------------


def cite_count(key: str, label: str, value: int) -> Citation:
    return Citation(key=key, label=label, value=value, unit=None, source="impact")


ISOLATED_COUNT = cite_count("isolated_count", "Isolated facilities", 2)
COUNTED = with_citations(
    ISOLATED_COUNT,
    cite_count("isolated_hospital_count", "Isolated hospitals and health centres", 2),
    cite_count("isolated_shelter_count", "Isolated shelters", 0),
)
# Three: no count of this block is 3, so the auto-repair leaves it for the check to reject.
COUNT_IN_WORDS = {
    "en": lang(body="The storm has cut off three health facilities in {{block_name}}."),
    "bn": lang(body="{{block_name}}-এ তিনটি স্বাস্থ্যকেন্দ্র বিচ্ছিন্ন।"),
    "hi": lang(body="{{block_name}} में तीन स्वास्थ्य केंद्र कट गए हैं।"),
}


def test_counting_in_words_is_rejected_and_the_retry_names_the_count_placeholder(env, monkeypatch):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: COUNTED)
    resp, fake = create(env, COUNT_IN_WORDS, CLEAN)
    assert resp.status_code == 200 and len(fake.calls) == 2
    # The first draft was refused on each count word, and audited with what was found.
    [failed] = [e for e in store.events() if e.action == "number_check_failed"]
    found = json.loads(failed.details)["found"]
    assert [(f["language"], f["field"], f["text"]) for f in found] == [
        ("en", "body", "three"),
        ("bn", "body", "তিনটি"),
        ("hi", "body", "तीन"),
    ]
    # The correction quotes each word and points at the block's count placeholders.
    retry = fake.calls[1]
    assert '"three" in en.body is a number word' in retry
    assert '"তিনটি" in bn.body is a number word' in retry
    assert '"तीन" in hi.body is a number word' in retry
    assert "{{isolated_count}} (Isolated facilities: 2)" in retry
    assert "{{isolated_hospital_count}} (Isolated hospitals and health centres: 2)" in retry


def test_counting_in_words_twice_is_refused(env, monkeypatch):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: COUNTED)
    resp, fake = create(env, COUNT_IN_WORDS, COUNT_IN_WORDS)
    assert resp.status_code == 502 and len(fake.calls) == 2
    assert any("'three'" in p for p in resp.json()["detail"]["problems"])


def test_retry_note_for_other_problems_has_no_count_hint():
    details = {
        "found": [
            {"language": "en", "field": "headline", "kind": "unknown_placeholder", "text": "x"}
        ]
    }
    note = service._retry_note(details, COUNTED)
    assert "{{x}} in en.headline is not in the list" in note
    assert "count placeholder" not in note


def test_isolated_count_renders_as_numerals_in_each_language():
    templates = AdvisoryTexts.model_validate(
        {
            lang_: lang(body="{{isolated_count}} facilities are cut off.")
            for lang_ in ("en", "bn", "hi")
        }
    )
    texts = render.render(templates, [*CITATIONS, ISOLATED_COUNT])
    bodies = [getattr(texts, lang_).body for lang_ in ("en", "bn", "hi")]
    assert [b.split("] ", 1)[1] for b in bodies] == [
        "2 facilities are cut off.",
        "২ facilities are cut off.",
        "2 facilities are cut off.",
    ]


def test_prompt_states_the_count_rule_and_lists_the_block_counts():
    assert "never write a count in words" in SYSTEM_PROMPT
    assert "{{..._count}}" in SYSTEM_PROMPT
    message = user_message(COUNTED)
    assert (
        "Count placeholders (use these to say how many): {{isolated_count}} (Isolated facilities), "
        "{{isolated_hospital_count}} (Isolated hospitals and health centres), "
        "{{isolated_shelter_count}} (Isolated shelters)."
    ) in message


# --- Prompt / data rules: tense, no model scores, one count per statement, shelters -------------

from app.advisory.facts import MODEL_SCORE_KEYS, offered_keys  # noqa: E402


def test_model_scores_are_cited_but_not_offered_to_the_model():
    assert {c.key for c in CITATIONS} >= {"risk_score"}
    assert "risk_score" not in offered_keys(CITATIONS)
    message = user_message(FACTS)
    assert all(f'"{k}"' not in message for k in MODEL_SCORE_KEYS)
    assert '"peak_surge_m"' in message and '"isolated_1_name"' in message
    assert "Cite physical facts only" in SYSTEM_PROMPT


def test_a_draft_citing_the_risk_score_is_rejected(env):
    scored = {**CLEAN, "en": lang(headline="{{block_name}}: risk {{risk_score}}")}
    resp, fake = create(env, scored, CLEAN)
    assert resp.status_code == 200 and len(fake.calls) == 2
    assert "{{risk_score}} in en.headline is not in the list" in fake.calls[1]
    # Still in the citations table.
    assert "risk_score" in {c["key"] for c in resp.json()["properties"]["citations"]}


def test_a_fixture_citing_the_risk_score_is_stale():
    scored = {**CLEAN, "en": lang(headline="{{block_name}}: risk {{risk_score}}")}
    cached = service.fixture_payload(scored, FACTS)
    assert service.staleness(cached, FACTS) == {"missing_keys": ["risk_score"]}


def test_old_drafts_using_the_risk_score_can_still_be_edited(env):
    env.mode(False)
    resp, _ = create(env, CLEAN)
    advisory_id = resp.json()["id"]
    # A draft stored before the rule (templates written directly, as an old row would be).
    old = with_en(headline="{{block_name}}: risk {{risk_score}}")
    with store.transaction() as conn:
        a = store.load(conn, advisory_id)
        props = a.properties.model_copy(update={"templates": AdvisoryTexts.model_validate(old)})
        store.save(conn, a.model_copy(update={"properties": props}))
    edited = with_en(headline="{{block_name}}: still risk {{risk_score}}")
    assert client.patch(f"{URL}{advisory_id}", json={"templates": edited}).status_code == 200


def test_isolated_facilities_are_labelled_already_cut_off():
    prompt_text = " ".join(SYSTEM_PROMPT.split())  # wrapping doesn't matter
    assert "Tense: an isolated facility is already cut off now" in prompt_text
    assert (
        '"before it is disrupted", "while routes are open" or "before road routes become '
        'impassable"'
    ) in prompt_text
    assert "Only things at risk may be described as threatened" in prompt_text


EQUAL = with_citations(
    cite_count("isolated_count", "Isolated facilities", 3),
    cite_count("isolated_hospital_count", "Isolated hospitals and health centres", 3),
)
TOTAL_AND_SUBTOTAL = (
    "{{isolated_count}} facilities are cut off, including {{isolated_hospital_count}} hospitals."
)


def test_equal_total_and_subtotal_in_one_sentence_is_rejected(env, monkeypatch):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: EQUAL)
    bad = {**CLEAN, "en": lang(body=TOTAL_AND_SUBTOTAL)}
    resp, fake = create(env, bad, CLEAN)
    assert resp.status_code == 200 and len(fake.calls) == 2
    assert (
        "en.body states {{isolated_count}} and {{isolated_hospital_count}} in one sentence, "
        "but they are equal: state one count only"
    ) in fake.calls[1]
    assert "One count per statement" in SYSTEM_PROMPT


@pytest.mark.parametrize(
    ("hospitals", "body", "ok"),
    [
        (2, TOTAL_AND_SUBTOTAL, True),  # a real subtotal
        (
            3,
            "{{isolated_count}} facilities are cut off. {{isolated_hospital_count}} are hospitals.",
            True,
        ),
        (3, TOTAL_AND_SUBTOTAL, False),
    ],
)
def test_duplicate_count_check(hospitals, body, ok):
    facts = with_citations(
        cite_count("isolated_count", "Isolated facilities", 3),
        cite_count("isolated_hospital_count", "Isolated hospitals and health centres", hospitals),
    )
    templates = AdvisoryTexts.model_validate({**CLEAN, "en": lang(body=body)})
    kinds = [p.kind for p in render.fact_problems(templates, facts.citations)]
    assert ("duplicate_count" not in kinds) is ok


NO_SHELTERS = with_citations(cite_count("standin_count", "Stand-in shelters (not designated)", 0))


def test_no_shelters_the_server_adds_one_fixed_action_to_every_language(env, monkeypatch):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: NO_SHELTERS)
    resp, fake = create(env, CLEAN)  # three actions, none about shelters
    assert resp.status_code == 200 and len(fake.calls) == 1  # no citation required any more
    assert "do not write any shelter action" in fake.calls[0]
    p = resp.json()["properties"]
    for lang_ in ("en", "bn", "hi"):
        assert p["templates"][lang_]["actions"][-1] == render.NO_SHELTERS_ACTION[lang_]
        assert p["texts"][lang_]["actions"][-1] == render.NO_SHELTERS_ACTION[lang_]
        assert p["texts"][lang_]["actions"].count(render.NO_SHELTERS_ACTION[lang_]) == 1
    assert render.NO_SHELTERS_ACTION["en"] == (
        "No shelters are mapped in this block: identify safe concrete buildings (schools, "
        "panchayat offices) locally before the storm."
    )


def test_the_fixed_shelter_action_passes_the_number_check():
    texts = {
        lang_: lang(actions=("a", "b", render.NO_SHELTERS_ACTION[lang_]))
        for lang_ in ("en", "bn", "hi")
    }
    assert render.check(AdvisoryTexts.model_validate(texts), {c.key for c in CITATIONS}) == []


def test_five_actions_leave_no_room_for_the_shelter_action_so_the_draft_is_retried(
    env, monkeypatch
):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: NO_SHELTERS)
    five = {**CLEAN, "en": lang(actions=("a", "b", "c", "d", "e"))}
    resp, fake = create(env, five, CLEAN)
    assert resp.status_code == 200 and len(fake.calls) == 2
    assert "en has 5 actions" in fake.calls[1] and "at most four" in fake.calls[1]
    assert len(resp.json()["properties"]["texts"]["en"]["actions"]) == 4


def test_an_edit_keeps_the_shelter_action_once(env, monkeypatch):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: NO_SHELTERS)
    resp, _ = create(env, CLEAN)
    templates = resp.json()["properties"]["templates"]
    templates["en"]["headline"] = "Updated {{block_name}}"
    r = client.patch(f"{URL}{resp.json()['id']}", json={"templates": templates})
    assert r.status_code == 200, r.text
    en = r.json()["properties"]["texts"]["en"]["actions"]
    assert en.count(render.NO_SHELTERS_ACTION["en"]) == 1


def test_shelter_action_not_required_when_shelters_exist():
    some = with_citations(cite_count("standin_count", "Stand-in shelters (not designated)", 4))
    templates = AdvisoryTexts.model_validate(CLEAN)
    assert render.fact_problems(templates, some.citations) == []
    assert render.add_shelter_action(templates, some.citations) == (templates, [])
    assert "NO mapped stand-in shelters" not in user_message(some)


# --- Fixture script: --pairs and --allow-groq-fallback (both providers mocked) -----------------

CODES = ["02413", "02435", "02438", "02439"]
NAMES = ["Budge Budge-I", "Gosaba", "Sagar", "Namkhana"]


def script_module():
    import importlib

    return importlib.import_module("scripts.build_advisory_fixtures")


@pytest.mark.usefixtures("fixture_script")
def test_parse_pairs_accepts_names_codes_t_labels_and_iso():
    parse = script_module().parse_pairs
    got = parse(
        "Namkhana:T-33, gosaba:t-27 ,02438:T-24,budge budge-i:T-0,Sagar:2020-05-20T09:00:00Z,"
        "Namkhana:T-33",  # duplicate: dropped
        CODES,
        NAMES,
    )
    assert got == [
        ("02439", "Namkhana", "2020-05-19T03:00:00Z"),
        ("02435", "Gosaba", "2020-05-19T09:00:00Z"),
        ("02438", "Sagar", "2020-05-19T12:00:00Z"),
        ("02413", "Budge Budge-I", "2020-05-20T12:00:00Z"),
        ("02438", "Sagar", "2020-05-20T09:00:00Z"),
    ]


@pytest.mark.usefixtures("fixture_script")
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Kolkata:T-3", "unknown block"),
        ("Gosaba:T-4", "not a replay step"),
        ("Gosaba:T-75", "not a replay step"),
        ("Gosaba", "expected <block>:<time>"),
        ("Gosaba:", "expected <block>:<time>"),
        ("Gosaba:tomorrow", "not a T-label or a replay timestep"),
        ("Gosaba:2020-05-20T10:00:00Z", "not a T-label or a replay timestep"),
        (" , ", "empty"),
    ],
)
def test_parse_pairs_rejects_bad_input(text, message):
    with pytest.raises(ValueError, match=message):
        script_module().parse_pairs(text, CODES, NAMES)


def test_script_gemini_success_is_labelled_gemini(env, groq, fixture_script):
    result = fixture_script.run([PAIR], 20, CLEAN, allow_groq=True)
    [(_, _, payload)] = fixture_script.written
    assert payload[service.GENERATED_BY_KEY] == {"provider": "gemini", "model": "gemini-3.7-flash"}
    assert payload[service.CITED_TEXT_KEY]  # the staleness guard's values are still stored
    assert [(r.provider, r.ok) for r in result.summary] == [("gemini", True)]
    assert groq.requests == []


def test_script_503_after_the_back_off_goes_to_groq_with_the_flag(env, groq, fixture_script):
    groq.responses = [CLEAN]
    result = fixture_script.run([PAIR], 20, OVERLOADED, OVERLOADED, allow_groq=True)
    assert 60.0 in fixture_script.clock["sleeps"]  # one back-off before giving up on Gemini
    assert len(fixture_script.clock["calls"]) == 2 and len(groq.requests) == 1
    [(_, _, payload)] = fixture_script.written
    assert payload[service.GENERATED_BY_KEY]["provider"] == "groq"
    assert [(r.provider, r.ok) for r in result.summary] == [("groq", True)]
    assert result.calls == 3  # every call counts towards --max-calls


def test_script_429_switches_every_remaining_pair_to_groq(env, groq, fixture_script):
    groq.responses = [CLEAN, CLEAN]
    other = (BLOCK, "Gosaba", REPLAY_TIMESTEPS[-3])
    result = fixture_script.run([PAIR, other], 20, QUOTA, allow_groq=True)
    assert len(fixture_script.clock["calls"]) == 1  # Gemini asked once, never again
    assert len(groq.requests) == 2
    assert [(r.provider, r.ok) for r in result.summary] == [("groq", True), ("groq", True)]
    assert not result.remaining
    assert all(
        p[service.GENERATED_BY_KEY]["provider"] == "groq" for *_, p in fixture_script.written
    )


def test_script_without_the_flag_never_uses_groq(env, groq, fixture_script):
    # 503: the back-off repeats on Gemini; 429: the run stops. Groq is never called.
    result = fixture_script.run([PAIR, PAIR], 20, OVERLOADED, OVERLOADED, CLEAN, QUOTA)
    assert groq.requests == []
    assert [(r.provider, r.ok) for r in result.summary] == [
        ("gemini", True),
        (None, False),
    ]
    assert result.summary[1].reason == "not attempted: Gemini quota (429)"


def test_script_groq_failure_is_reported_with_its_reason(env, groq, fixture_script):
    bad = with_en(headline="Surge of 3 m")
    groq.responses = [bad, bad]
    result = fixture_script.run([PAIR], 20, QUOTA, allow_groq=True)
    [r] = result.summary
    assert (r.provider, r.ok) == ("groq", False) and "Groq" in r.reason and "digit" in r.reason
    assert fixture_script.written == []


def test_a_groq_fixture_is_served_labelled_groq(env, groq):
    env.mode(True, key=None, groq_key=GROQ_KEY)
    groq_by = GeneratedBy(provider="groq", model="openai/gpt-oss-120b")
    write_cached(env, service.fixture_payload(CLEAN, FACTS, groq_by))
    resp, fake = create(env)
    assert resp.status_code == 200 and fake.calls == [] and groq.requests == []
    assert resp.json()["properties"]["generated_by"] == groq_by.model_dump()


# --- Auto-repair: counts written in words -> count placeholders -----------------------------------

REPAIR_FACTS = with_citations(
    cite_count("isolated_count", "Isolated facilities", 2),
    cite_count("isolated_hospital_count", "Isolated hospitals and health centres", 2),
    cite_count("standin_count", "Stand-in shelters (not designated)", 0),
)
SHELTER_OK = "No shelters are mapped ({{standin_count}}): identify safe buildings locally."


def repaired(language: str, text: str, facts: Facts = REPAIR_FACTS):
    """The repaired body of one language, and the repairs."""
    texts = {lang_: lang() for lang_ in ("en", "bn", "hi")}
    texts[language] = lang(body=text)
    out, found = render.repair_counts(AdvisoryTexts.model_validate(texts), facts.citations)
    return getattr(out, language).body, found


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [
        ("en", "Two health centres are cut off.", "{{isolated_count}} health centres are cut off."),
        ("en", "Both clinics are cut off.", "{{isolated_count}} clinics are cut off."),
        ("en", "There are zero mapped shelters.", "There are {{standin_count}} mapped shelters."),
        ("bn", "দুটো হাসপাতাল বিচ্ছিন্ন।", "{{isolated_count}}টি হাসপাতাল বিচ্ছিন্ন।"),
        ("bn", "দুটি কেন্দ্র, দুই দল।", "{{isolated_count}}টি কেন্দ্র, {{isolated_count}} দল।"),
        ("bn", "শূন্য আশ্রয়কেন্দ্র।", "{{standin_count}} আশ্রয়কেন্দ্র।"),
        ("hi", "दोनों अस्पताल कट गए हैं।", "{{isolated_count}} अस्पताल कट गए हैं।"),
        ("hi", "दो केंद्र, शून्य आश्रय।", "{{isolated_count}} केंद्र, {{standin_count}} आश्रय।"),
    ],
)
def test_counts_in_words_are_repaired_to_a_matching_count_placeholder(language, text, expected):
    body, found = repaired(language, text)
    assert body == expected
    assert found and all(r.language == language and r.field == "body" for r in found)


def test_repair_leaves_what_it_cannot_match():
    body, found = repaired("en", "Three boats and 2 crews; both wind and surge rise.")
    assert body == "Three boats and 2 crews; both wind and surge rise." and found == []
    # ...so the number check still rejects the word without a matching count, and the digit.
    templates = AdvisoryTexts.model_validate({**CLEAN, "en": lang(body=body)})
    kinds = {(p.kind, p.text) for p in render.check(templates, {c.key for c in CITATIONS})}
    assert {("number_word", "Three"), ("digit", "2")} <= kinds


def test_repair_needs_a_count_citation():
    no_counts = Facts(BLOCK, "Gosaba", TS, [c for c in CITATIONS if not c.key.endswith("_count")])
    body, found = repaired("en", "Two clinics.", no_counts)
    assert body == "Two clinics." and found == []


def test_repaired_draft_passes_and_the_audit_records_each_repair(env, monkeypatch):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: REPAIR_FACTS)
    draft = {
        "en": lang(body="Both health centres are cut off.", actions=("a", SHELTER_OK, "c")),
        "bn": lang(body="দুটো হাসপাতাল বিচ্ছিন্ন।", actions=("a", SHELTER_OK, "c")),
        "hi": lang(body="दोनों अस्पताल कट गए हैं।", actions=("a", SHELTER_OK, "c")),
    }
    resp, fake = create(env, draft)
    assert resp.status_code == 200 and len(fake.calls) == 1  # no retry needed
    texts = resp.json()["properties"]["texts"]
    assert "2 health centres are cut off." in texts["en"]["body"]
    assert "২টি হাসপাতাল" in texts["bn"]["body"]
    details = json.loads(next(e for e in store.events() if e.action == "generated").details)
    assert details["auto_repaired"] == [
        {
            "language": "en",
            "field": "body",
            "original": "Both",
            "placeholder": "{{isolated_count}}",
        },
        {"language": "bn", "field": "body", "original": "দুটো", "placeholder": "{{isolated_count}}"},
        {
            "language": "hi",
            "field": "body",
            "original": "दोनों",
            "placeholder": "{{isolated_count}}",
        },
    ]


def test_a_digit_is_never_repaired(env, monkeypatch):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: REPAIR_FACTS)
    digit = {lang_: lang(body="2 health centres.", actions=("a", SHELTER_OK, "c"))
             for lang_ in ("en", "bn", "hi")}  # fmt: skip
    resp, _ = create(env, digit, digit)
    assert resp.status_code == 502
    assert any("digit '2'" in p for p in resp.json()["detail"]["problems"])


def test_groq_drafts_are_repaired_too(env, groq, monkeypatch):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: REPAIR_FACTS)
    groq.responses = [
        {
            **{lang_: lang(actions=("a", SHELTER_OK, "c")) for lang_ in ("en", "bn", "hi")},
            "en": lang(body="Two clinics are cut off.", actions=("a", SHELTER_OK, "c")),
        }
    ]
    resp, _ = create(env, QUOTA)
    assert resp.status_code == 200
    assert resp.json()["properties"]["generated_by"]["provider"] == "groq"
    details = json.loads(next(e for e in store.events() if e.action == "generated").details)
    assert [r["original"] for r in details["auto_repaired"]] == ["Two"]


# An edit can't remove a placeholder.
KEPT_EDIT = "Surge up to {{peak_surge_m}} in {{hours_to_landfall}}; {{reach}}."


def test_edits_are_repaired_and_audited(env, monkeypatch):
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: REPAIR_FACTS)
    base = {lang_: lang(actions=("a", SHELTER_OK, "c")) for lang_ in ("en", "bn", "hi")}
    resp, _ = create(env, base)
    advisory_id = resp.json()["id"]
    edited = {
        **base,
        "en": lang(
            body="Two clinics are cut off. " + KEPT_EDIT,
            actions=("a", SHELTER_OK, "c"),
        ),
    }
    r = client.patch(f"{URL}{advisory_id}", json={"templates": edited})
    assert r.status_code == 200, r.text
    assert (
        r.json()["properties"]["templates"]["en"]["body"]
        == "{{isolated_count}} clinics are cut off. " + KEPT_EDIT
    )
    event = next(e for e in store.events(advisory_id) if e.action == "edited")
    assert json.loads(event.details)["auto_repaired"][0]["original"] == "Two"


# --- Duplicated units, road times, trivial facts, time to landfall --------------------------------

UNITS = {
    c.key: c
    for c in [
        Citation(key="t", label="t", value=20, unit="min", source="x"),
        Citation(key="h", label="h", value=3, unit="h", source="x"),
        Citation(key="k", label="k", value=12.5, unit="km", source="x"),
        Citation(key="s", label="s", value=2.71, unit="m", source="x"),
        Citation(key="w", label="w", value=37, unit="m/s", source="x"),
    ]
}


@pytest.mark.parametrize(
    ("language", "template", "expected"),
    [
        ("en", "within {{t}} minutes", "within 20 min"),
        ("en", "within {{t}} min", "within 20 min"),
        ("en", "in {{h}} hours", "in 3 hours"),
        ("en", "in {{h}} h", "in 3 hours"),
        ("en", "{{k}} km of road", "12.5 km of road"),
        ("en", "{{k}} kilometres of road", "12.5 km of road"),
        ("en", "{{s}} metres of surge", "2.7 m of surge"),
        ("en", "{{s}} m surge", "2.7 m surge"),
        ("en", "winds of {{w}} km/h", "winds of 135 km/h"),
        ("en", "{{s}} more than before", "2.7 m more than before"),  # "more" isn't "m"
        ("bn", "{{t}} মিনিট", "২০ মিনিট"),
        ("bn", "{{h}} ঘন্টা পরে", "৩ ঘণ্টা পরে"),
        ("bn", "{{k}} কিলোমিটার", "১২.৫ কিমি"),
        ("bn", "{{w}} কিমি/ঘণ্টা", "১৩৫ কিমি/ঘণ্টা"),
        ("hi", "{{t}} मिनट", "20 मिनट"),
        ("hi", "{{h}} घंटे बाद", "3 घंटे बाद"),
        ("hi", "{{s}} मीटर", "2.7 मीटर"),
        ("hi", "{{w}} किमी/घंटा", "135 किमी/घंटा"),
    ],
)
def test_a_unit_repeated_after_the_placeholder_is_dropped(language, template, expected):
    assert render.fill(template, UNITS, language) == expected


def test_road_times_are_labelled_normal_conditions(monkeypatch):
    from app.exposure import service as exposure
    from app.impact import service as impact
    from app.risk import service as risk

    s = settings(True, None)
    for module in (impact, risk, exposure, demo_module):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    for module in (impact, risk, exposure):
        module.clear_cache()
    try:
        f = facts_module.build_facts(BLOCK, "2020-05-20T09:00:00Z")
    finally:
        for module in (impact, risk, exposure):
            module.clear_cache()
    labels = {c.label for c in f.citations if c.key.endswith("_next_hospital_min")}
    assert labels == {"Normal road time to next hospital (before the storm)"}
    prompt_text = " ".join(SYSTEM_PROMPT.split())
    assert "road travel times in normal conditions, before the storm" in prompt_text
    assert "never as boat times" in prompt_text


def test_hours_to_landfall_rule():
    prompt_text = " ".join(SYSTEM_PROMPT.split())
    assert "{{hours_to_landfall}} is only the time until the cyclone makes landfall" in prompt_text
    assert "Never use it as the time until something is cut off" in prompt_text


@pytest.mark.parametrize(
    ("surge", "road_km", "offered"),
    [(0.05, 0.0, set()), (0.1, 0.0, {"peak_surge_m"}), (0.0, 3.2, {"cut_road_km"})],
)
def test_trivial_facts_are_cited_but_not_offered(surge, road_km, offered):
    facts = with_citations(
        Citation(key="peak_surge_m", label="Surge", value=surge, unit="m", source="hazard"),
        Citation(key="cut_road_km", label="Cut roads", value=road_km, unit="km", source="impact"),
    )
    keys = facts_module.offered_keys(facts.citations)
    assert {"peak_surge_m", "cut_road_km"} & keys == offered
    assert {"peak_surge_m", "cut_road_km"} <= {c.key for c in facts.citations}  # still cited
    message = user_message(facts)
    assert ('"peak_surge_m"' in message) == ("peak_surge_m" in offered)


def test_a_template_citing_a_trivial_surge_is_rejected(env, monkeypatch):
    calm = with_citations(
        Citation(key="peak_surge_m", label="Surge", value=0.03, unit="m", source="hazard")
    )
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: calm)
    cites_surge = {**CLEAN, "en": lang(body="Surge up to {{peak_surge_m}}.")}
    calm_draft = {lang_: lang(body="{{reach}}.") for lang_ in ("en", "bn", "hi")}
    resp, fake = create(env, cites_surge, calm_draft)
    assert resp.status_code == 200 and len(fake.calls) == 2
    assert "{{peak_surge_m}} in en.body is not in the list" in fake.calls[1]
