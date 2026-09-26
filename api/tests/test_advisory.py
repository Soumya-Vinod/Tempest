"""Advisory generation, the number check and the approval queue. Gemini is mocked throughout."""

import json

import pytest
import shapely
from fastapi.testclient import TestClient

from app.advisory import facts as facts_module
from app.advisory import gemini, render, service, store
from app.advisory.facts import Facts
from app.core import demo as demo_module
from app.core.config import Settings
from app.main import app
from app.schemas import LANDFALL_TIMESTEP, AdvisoryTexts, Citation
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
    headline="{{block_name}}: risk {{risk_score}}",
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
        return json.loads(json.dumps(self.responses.pop(0)))


def settings(demo: bool, key: str | None) -> Settings:
    return Settings(_env_file=None, DEMO_MODE=demo, GEMINI_API_KEY=key)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Empty DB and demo dir; facts stubbed; live mode with a key unless a test changes it."""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "state" / "tempest.db")
    monkeypatch.setattr(demo_module, "DEMO_DIR", tmp_path)
    monkeypatch.setattr(service, "build_facts", lambda block_id, ts: FACTS)

    def mode(demo: bool, key: str | None = "test-key"):
        s = settings(demo, key)
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
    assert texts.en.headline == "Gosaba: risk 0.27"
    assert texts.en.body.endswith("Surge up to 1.5 m in 3 hours; cut off by the storm.")
    assert texts.en.actions[0] == "Move patients from Ward 12 PHC."
    # Bengali numerals and units, the block's Bengali name; other names keep their own digits.
    assert texts.bn.headline == "গোসাবা: risk ০.২৭"
    assert "১.৫ মিটার" in texts.bn.body and "৩ ঘণ্টা" in texts.bn.body
    assert "ঝড়ে বিচ্ছিন্ন" in texts.bn.body
    assert texts.bn.actions[0] == "Move patients from Ward 12 PHC."
    assert texts.bn.actions[2] == "Clear roads (২৪.৭ কিমি)."
    # Hindi: Latin digits, Hindi units.
    assert "1.5 मीटर" in texts.hi.body and "3 घंटे" in texts.hi.body
    assert texts.hi.headline == "Gosaba: risk 0.27"  # no Hindi label: English name


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
    monkeypatch.setattr(service.risk, "get_scores", lambda ts: fc)
    resp = client.get(f"{URL}suggestions", params={"timestep": TS})
    assert resp.status_code == 200
    body = resp.json()
    assert body["threshold"] == service.SUGGEST_MIN_SCORE == 0.25
    assert [b["block_name"] for b in body["blocks"]] == ["C", "B"]


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

    def run(todo, max_calls, *responses):
        generate(list(responses))
        return script.run(
            todo,
            max_calls,
            lambda block_id, ts, payload: written.append((block_id, ts, payload)),
            sleep=sleep,
            clock=lambda: clock["now"],
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
    assert payload == service.fixture_payload(CLEAN, FACTS)
    assert payload[service.CITED_TEXT_KEY]["isolated_1_name"] == "Ward 12 PHC"
    assert service.staleness(payload, FACTS) is None
