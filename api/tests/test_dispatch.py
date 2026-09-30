"""Dispatch: CAP 1.2 (validated against the OASIS XSD), Telegram, Gmail SMTP and Brevo (all
mocked: no real sends), the approved-only / PIN / resend / rate-limit rules, dry runs and the
audit log."""

import base64
import email
import json
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app.advisory import store
from app.core.config import Settings
from app.dispatch import cap, channels, service
from app.main import app
from app.schemas import Advisory, AdvisoryProperties, AdvisoryTexts, Citation

client = TestClient(app)
NS = {"cap": cap.CAP_NS}
TOKEN = "123456:SECRET-bot-token"
APP_PASSWORD = "abcd efgh ijkl mnop"
BREVO_KEY = "xkeysib-SECRET-brevo-key"
PIN = "4321"
SAGAR, TS = "02438", "2020-05-20T09:00:00Z"
LABEL = {
    "en": "⚠️ [EXERCISE: Cyclone Amphan 2020 replay]",
    "bn": "⚠️ [মহড়া: ঘূর্ণিঝড় আমফান ২০২০ রিপ্লে]",
    "hi": "⚠️ [अभ्यास: चक्रवात अम्फान 2020 रीप्ले]",
}


def settings(**overrides) -> Settings:
    values = {
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "TELEGRAM_CHAT_ID": "-1009876543210",
        "GMAIL_ADDRESS": "tempest.drill@gmail.com",
        "GMAIL_APP_PASSWORD": APP_PASSWORD,
        "BREVO_API_KEY": BREVO_KEY,
        "DISPATCH_EMAIL_TO": "officer.one@example.org, bdo@example.org",
        "DISPATCH_PIN": PIN,
        **overrides,
    }
    return Settings(_env_file=None, **values)


def texts(lang: str) -> dict:
    prefix = {"en": "Sagar", "bn": "সাগর", "hi": "सागर"}[lang]
    return {
        "headline": f"{prefix}: severe surge ({lang})",
        "body": f"[EXERCISE] {prefix} body <&> ({lang})",
        "actions": [f"{lang} action 1", f"{lang} action 2", f"{lang} action 3"],
    }


def make_advisory(status: str = "approved", block_id: str = SAGAR, block_name: str = "Sagar"):
    now = datetime.now(UTC)
    t = AdvisoryTexts(**{lang: texts(lang) for lang in ("en", "bn", "hi")})
    extra = {"approved_by": "A. Officer (BDO)", "approved_at": now} if status != "draft" else {}
    props = AdvisoryProperties(
        id=str(uuid.uuid4()),
        block_id=block_id,
        block_name=block_name,
        timestep=TS,
        texts=t,
        templates=t,
        citations=[
            Citation(key="risk_score", label="Risk", value=0.553, unit=None, source="risk"),
            Citation(key="hours_to_landfall", label="h", value=3, unit="h", source="replay"),
        ],
        status=status,
        created_at=now,
        **extra,
    )
    advisory = Advisory(id=props.id, properties=props)
    with store.transaction() as conn:
        store.save(conn, advisory)
    return advisory


def make_text(lang: str):
    from app.schemas import AdvisoryText

    return AdvisoryText(**texts(lang))


class FakeTelegram:
    """httpx transport for the Bot API: records messages; `fail` makes sendMessage fail."""

    def __init__(self):
        self.messages: list[dict] = []
        self.urls: list[str] = []
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if self.fail:
            return httpx.Response(
                400, json={"ok": False, "description": "Bad Request: chat not found"}
            )
        self.messages.append(json.loads(request.content))
        return httpx.Response(
            200, json={"ok": True, "result": {"message_id": 100 + len(self.messages)}}
        )


class FakeBrevo:
    """httpx handler for Brevo's send endpoint: records requests; `response` overrides the reply."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.response: httpx.Response | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.response is not None:
            return self.response
        return httpx.Response(201, json={"messageId": "<202609291200.1234@smtp-relay.brevo.com>"})


class FakeSMTP:
    sent: list = []
    fail: Exception | None = None
    calls: list = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.calls.append(("connect", host, port))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        FakeSMTP.calls.append(("starttls",))

    def login(self, user, password):
        FakeSMTP.calls.append(("login", user, password))
        if FakeSMTP.fail is not None:
            raise FakeSMTP.fail

    def send_message(self, message):
        FakeSMTP.sent.append(message)
        return {}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "state" / "tempest.db")
    s = settings()
    monkeypatch.setattr(service, "get_settings", lambda: s)
    telegram, brevo = FakeTelegram(), FakeBrevo()

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.brevo.com":
            return brevo.handler(request)
        return telegram.handler(request)

    monkeypatch.setattr(
        channels, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(route))
    )
    FakeSMTP.sent, FakeSMTP.fail, FakeSMTP.calls = [], None, []
    monkeypatch.setattr(channels, "SMTP", FakeSMTP)

    def use(**overrides):
        s2 = settings(**overrides)
        monkeypatch.setattr(service, "get_settings", lambda: s2)

    return type(
        "Env",
        (),
        {"telegram": telegram, "brevo": brevo, "smtp": FakeSMTP, "use": staticmethod(use)},
    )


def post(advisory_id: str, **body):
    body = {"channels": ["telegram", "email"], **body}
    return client.post(f"/api/dispatch/{advisory_id}", json=body)


def actions(advisory_id: str) -> list[str]:
    return [e.action for e in store.events(advisory_id)]


def status_of(advisory_id: str) -> str:
    return store.get(advisory_id).properties.status


# --- CAP ----------------------------------------------------------------------------------------


def cap_doc(env) -> ET.Element:
    a = make_advisory()
    return ET.fromstring(cap.build(a, datetime.now(UTC)).encode("utf-8"))


def test_cap_validates_against_the_oasis_xsd(env):
    a = make_advisory()
    xml = cap.build(a, datetime(2026, 9, 26, 8, 10, tzinfo=UTC))
    assert cap.errors(xml) == []
    root = ET.fromstring(xml.encode("utf-8"))
    assert root.findtext("cap:status", namespaces=NS) == "Exercise"
    assert root.findtext("cap:msgType", namespaces=NS) == "Alert"
    assert root.findtext("cap:scope", namespaces=NS) == "Public"
    assert root.findtext("cap:sender", namespaces=NS) == "tempest-s24p-exercise@invalid"
    assert root.findtext("cap:sent", namespaces=NS) == "2026-09-26T13:40:00+05:30"
    infos = root.findall("cap:info", NS)
    assert [i.findtext("cap:language", namespaces=NS) for i in infos] == ["en-IN", "bn-IN", "hi-IN"]
    for info, lang in zip(infos, ("en", "bn", "hi"), strict=True):
        assert info.findtext("cap:category", namespaces=NS) == "Met"
        assert info.findtext("cap:event", namespaces=NS) == "Cyclone"
        assert info.findtext("cap:urgency", namespaces=NS) == "Immediate"  # 3 h to landfall
        assert info.findtext("cap:severity", namespaces=NS) == "Severe"  # score 0.553
        assert info.findtext("cap:certainty", namespaces=NS) == "Likely"
        assert info.findtext("cap:headline", namespaces=NS) == texts(lang)["headline"]
        assert info.findtext("cap:description", namespaces=NS) == texts(lang)["body"]
        assert info.findtext("cap:instruction", namespaces=NS) == "\n".join(texts(lang)["actions"])
        area = info.find("cap:area", NS)
        assert area.findtext("cap:geocode/cap:valueName", namespaces=NS) == "census2011_cd"
        assert area.findtext("cap:geocode/cap:value", namespaces=NS) == SAGAR
    areas = [i.findtext("cap:area/cap:areaDesc", namespaces=NS) for i in infos]
    assert areas == ["Sagar", "সাগর", "Sagar"]  # no Hindi label on Wikidata: English


def test_cap_polygons_are_lat_lon_and_closed(env):
    root = cap_doc(env)
    polygons = [p.text for p in root.findall("cap:info/cap:area/cap:polygon", NS)]
    assert len(polygons) >= 3  # 3 languages x at least one part (Sagar has several islands)
    vertices = []
    for polygon in polygons:
        points = [tuple(map(float, pair.split(","))) for pair in polygon.split(" ")]
        assert len(points) >= 4 and points[0] == points[-1]
        vertices += points
    assert all(21.5 < lat < 22.1 and 87.9 < lon < 88.4 for lat, lon in vertices)  # lat first
    assert any(abs(lat - 21.6) < 0.1 and abs(lon - 88.1) < 0.1 for lat, lon in vertices)


def test_invalid_cap_is_reported(env):
    xml = cap.build(make_advisory(), datetime.now(UTC)).replace(">Exercise<", ">Drill<")
    assert cap.errors(xml)
    with pytest.raises(cap.CapInvalid):
        cap.validate(xml)


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.6, "Extreme"), (0.59, "Severe"), (0.4, "Severe"), (0.25, "Moderate"), (0.24, "Minor")],
)
def test_severity_bands(score, expected):
    assert cap.severity(score) == expected


@pytest.mark.parametrize(
    ("hours", "expected"), [(0, "Immediate"), (12, "Immediate"), (15, "Future")]
)
def test_urgency_immediate_within_12_hours(hours, expected):
    assert cap.urgency(hours) == expected


def test_certainty_observed_only_at_landfall():
    assert cap.certainty(0) == "Observed" and cap.certainty(3) == "Likely"


# --- Rules --------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["draft", "rejected"])
def test_only_approved_advisories_can_be_dispatched(env, status):
    extra = {}
    if status == "rejected":
        a = make_advisory("draft")
        props = AdvisoryProperties.model_validate(
            {
                **a.properties.model_dump(),
                "status": "rejected",
                "rejection_reason": "no",
                "rejected_at": datetime.now(UTC),
            }
        )
        with store.transaction() as conn:
            store.save(conn, Advisory(id=props.id, properties=props))
        advisory_id = props.id
    else:
        advisory_id = make_advisory("draft").id
    for body in ({"pin": PIN, **extra}, {"dry_run": True}):
        resp = post(advisory_id, **body)
        assert resp.status_code == 409, resp.text
    assert env.telegram.messages == [] and env.smtp.sent == []


def test_unknown_advisory_is_404(env):
    assert post(str(uuid.uuid4()), pin=PIN).status_code == 404


@pytest.mark.parametrize("pin", [None, "1234", "", "4321 "])
def test_live_dispatch_needs_the_right_pin(env, pin):
    a = make_advisory()
    body = {} if pin is None else {"pin": pin}
    resp = post(a.id, **body)
    assert resp.status_code == 403
    assert env.telegram.messages == [] and env.smtp.sent == []
    assert status_of(a.id) == "approved"


def test_live_dispatch_is_disabled_without_a_configured_pin(env):
    for unset in (None, "change-me"):  # missing, or left at the .env.example placeholder
        env.use(DISPATCH_PIN=unset)
        resp = post(make_advisory().id, pin="change-me")
        assert resp.status_code == 403 and "DISPATCH_PIN" in resp.json()["detail"]


def test_request_cannot_carry_recipients(env):
    a = make_advisory()
    for extra in ({"to": ["x@example.org"]}, {"chat_id": "-100"}):
        assert post(a.id, pin=PIN, **extra).status_code == 422
    assert env.telegram.messages == [] and env.smtp.sent == []


# --- Sending ------------------------------------------------------------------------------------


def test_live_dispatch_sends_both_channels_and_marks_sent(env):
    a = make_advisory()
    resp = post(a.id, pin=PIN)
    assert resp.status_code == 200, resp.text
    receipt = resp.json()
    assert receipt["dry_run"] is False and receipt["resend"] is False
    by_channel = {c["channel"]: c for c in receipt["channels"]}
    assert by_channel["telegram"]["status"] == "sent"
    assert by_channel["telegram"]["provider_message_id"] == "101,102"
    assert by_channel["email"]["status"] == "sent"
    assert by_channel["email"]["provider_message_id"].endswith("@tempest.invalid>")
    assert status_of(a.id) == "sent"

    # Telegram: bn first, then en, plain text, to the configured chat.
    tg = env.telegram.messages
    assert [m["chat_id"] for m in tg] == ["-1009876543210"] * 2
    # The exercise label is the first line (the notification preview), then a blank line.
    assert tg[0]["text"].startswith(f"{LABEL['bn']}\n\n{texts('bn')['headline']}\n\n")
    assert tg[1]["text"].startswith(f"{LABEL['en']}\n\n{texts('en')['headline']}\n\n")
    assert texts("bn")["body"] in tg[0]["text"]  # the body keeps its own prefix
    assert "parse_mode" not in tg[0]

    # E-mail: STARTTLS before login, [EXERCISE] subject, en then bn, CAP attached and valid.
    assert env.smtp.calls[:3] == [
        ("connect", "smtp.gmail.com", 587),
        ("starttls",),
        ("login", "tempest.drill@gmail.com", APP_PASSWORD),
    ]
    assert env.brevo.requests == []  # EMAIL_PROVIDER defaults to smtp
    [msg] = env.smtp.sent
    msg = email.message_from_bytes(msg.as_bytes())
    assert msg["Subject"].startswith("[EXERCISE]")
    assert msg["To"] == "officer.one@example.org, bdo@example.org"
    parts = list(msg.walk())
    body = next(p for p in parts if p.get_content_type() == "text/plain").get_payload(decode=True)
    body = body.decode("utf-8")
    assert body.index(texts("en")["headline"]) < body.index(texts("bn")["headline"])
    assert body.startswith(f"{LABEL['en']}\n\n{texts('en')['headline']}\n\n")
    assert f"----------\n\n{LABEL['bn']}\n\n{texts('bn')['headline']}" in body
    attachment = next(p for p in parts if p.get_filename())
    assert attachment.get_filename() == "tempest-cap-02438-20200520T090000Z.xml"
    assert cap.errors(attachment.get_payload(decode=True).decode("utf-8")) == []

    # Stored receipt, CAP served, audit: one "dispatched" per channel, then "sent".
    stored = client.get(f"/api/dispatch/{a.id}/receipts").json()["receipts"]
    assert stored == [receipt]
    served = client.get(f"/api/dispatch/{a.id}/cap.xml")
    assert served.status_code == 200 and served.headers["content-type"].startswith(
        "application/xml"
    )
    assert served.text == attachment.get_payload(decode=True).decode("utf-8")
    assert actions(a.id) == ["dispatched", "dispatched", "sent"]
    details = [json.loads(e.details) for e in store.events(a.id)]
    assert [d["channel"] for d in details[:2]] == ["telegram", "email"]
    assert all(d["status"] == "sent" and d["dry_run"] is False for d in details[:2])


def test_one_channel_failing_does_not_stop_the_other(env):
    env.telegram.fail = True
    a = make_advisory()
    receipt = post(a.id, pin=PIN).json()
    by_channel = {c["channel"]: c for c in receipt["channels"]}
    assert by_channel["telegram"]["status"] == "failed"
    assert "chat not found" in by_channel["telegram"]["error"]
    assert by_channel["email"]["status"] == "sent"
    assert status_of(a.id) == "sent"  # at least one channel succeeded
    assert actions(a.id) == ["dispatched", "dispatched", "sent"]


def test_both_channels_failing_keeps_it_approved_and_stores_the_receipt(env):
    env.telegram.fail = True
    env.smtp.fail = OSError(f"auth failed for {APP_PASSWORD}")
    a = make_advisory()
    receipt = post(a.id, pin=PIN).json()
    assert [c["status"] for c in receipt["channels"]] == ["failed", "failed"]
    assert status_of(a.id) == "approved"
    assert actions(a.id) == ["dispatched", "dispatched"]  # no "sent"
    assert len(client.get(f"/api/dispatch/{a.id}/receipts").json()["receipts"]) == 1
    # No credential in any error text, receipt or audit entry.
    dumped = json.dumps(receipt) + "".join(e.details or "" for e in store.events())
    assert APP_PASSWORD not in dumped and TOKEN not in dumped and "***" in dumped


def test_transport_errors_never_leak_the_bot_token(env, monkeypatch):
    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")  # the URL holds the token

    monkeypatch.setattr(
        channels, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(boom))
    )
    a = make_advisory()
    receipt = post(a.id, pin=PIN, channels=["telegram"]).json()
    [result] = receipt["channels"]
    assert result["status"] == "failed" and "ConnectError" in result["error"]
    assert TOKEN not in result["error"] and "bot***" in result["error"]
    assert TOKEN not in "".join(e.details or "" for e in store.events())


def test_unconfigured_channel_fails_on_its_own(env):
    env.use(GMAIL_APP_PASSWORD=None)
    a = make_advisory()
    receipt = post(a.id, pin=PIN).json()
    by_channel = {c["channel"]: c for c in receipt["channels"]}
    assert by_channel["email"]["status"] == "failed"
    assert "not configured" in by_channel["email"]["error"]
    assert by_channel["telegram"]["status"] == "sent"
    assert env.smtp.calls == []


def test_brevo_sends_the_same_email_over_https(env):
    env.use(EMAIL_PROVIDER="brevo", GMAIL_APP_PASSWORD=None)  # no SMTP credential needed
    a = make_advisory()
    receipt = post(a.id, pin=PIN, channels=["email"]).json()
    [result] = receipt["channels"]
    assert result["status"] == "sent", result
    assert result["provider_message_id"] == "<202609291200.1234@smtp-relay.brevo.com>"
    assert env.smtp.calls == [] and env.telegram.urls == []

    [req] = env.brevo.requests
    assert req.method == "POST" and str(req.url) == "https://api.brevo.com/v3/smtp/email"
    assert req.headers["api-key"] == BREVO_KEY
    payload = json.loads(req.content)
    assert payload["sender"] == {"email": "tempest.drill@gmail.com"}
    assert payload["to"] == [{"email": "officer.one@example.org"}, {"email": "bdo@example.org"}]
    # Same subject and body as the SMTP message.
    smtp_msg = channels.email_message(settings(), a, "<alert/>")
    assert payload["subject"] == smtp_msg["Subject"]
    assert payload["subject"].startswith("[EXERCISE]")
    assert payload["textContent"] == smtp_msg.get_body(("plain",)).get_content()
    assert payload["textContent"].startswith(f"{LABEL['en']}\n\n{texts('en')['headline']}\n\n")
    # The CAP, base64 as cap.xml: valid, and the one served for this advisory.
    [attachment] = payload["attachment"]
    assert attachment["name"] == "cap.xml"
    xml = base64.b64decode(attachment["content"]).decode("utf-8")
    assert cap.errors(xml) == []
    assert client.get(f"/api/dispatch/{a.id}/cap.xml").text == xml
    assert status_of(a.id) == "sent"


def test_brevo_errors_never_leak_the_api_key(env, monkeypatch):
    env.use(EMAIL_PROVIDER="brevo")
    env.brevo.response = httpx.Response(
        401, json={"code": "unauthorized", "message": f"Key not found: {BREVO_KEY}"}
    )
    a = make_advisory()
    [result] = post(a.id, pin=PIN, channels=["email"]).json()["channels"]
    assert result["status"] == "failed"
    assert "HTTP 401" in result["error"] and "Key not found: ***" in result["error"]
    assert BREVO_KEY not in result["error"]

    def boom(request):
        raise httpx.ConnectError(f"cannot reach Brevo with {request.headers['api-key']}")

    monkeypatch.setattr(
        channels, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(boom))
    )
    b = make_advisory()
    [result] = post(b.id, pin=PIN, channels=["email"]).json()["channels"]
    assert result["status"] == "failed" and "ConnectError" in result["error"]
    assert BREVO_KEY not in result["error"] and "***" in result["error"]
    assert BREVO_KEY not in "".join(e.details or "" for e in store.events())
    assert status_of(a.id) == status_of(b.id) == "approved"


def test_brevo_non_json_error_reports_the_status(env):
    env.use(EMAIL_PROVIDER="brevo")
    env.brevo.response = httpx.Response(502, text="Bad Gateway")
    a = make_advisory()
    [result] = post(a.id, pin=PIN, channels=["email"]).json()["channels"]
    assert result["status"] == "failed" and "HTTP 502: Bad Gateway" in result["error"]


def test_brevo_without_its_key_is_not_configured(env):
    env.use(EMAIL_PROVIDER="brevo", BREVO_API_KEY=None)  # the Gmail password doesn't count
    a = make_advisory()
    [result] = post(a.id, pin=PIN, channels=["email"]).json()["channels"]
    assert result["status"] == "failed"
    assert "not configured" in result["error"] and "BREVO_API_KEY" in result["error"]
    assert env.brevo.requests == [] and env.smtp.calls == []
    assert client.get("/api/dispatch/recipients").json()["email"]["configured"] is False


def test_each_provider_needs_its_own_credential():
    assert channels.email_configured(settings()) is True
    assert channels.email_configured(settings(GMAIL_APP_PASSWORD=None)) is False
    assert channels.email_configured(settings(EMAIL_PROVIDER="brevo", GMAIL_APP_PASSWORD=None))
    assert not channels.email_configured(settings(EMAIL_PROVIDER="brevo", BREVO_API_KEY=None))


def test_dry_run_builds_and_validates_without_sending(env):
    a = make_advisory()
    resp = post(a.id, dry_run=True)  # no PIN needed
    assert resp.status_code == 200, resp.text
    receipt = resp.json()
    assert receipt["dry_run"] is True
    assert [c["status"] for c in receipt["channels"]] == ["dry_run", "dry_run"]
    assert env.telegram.messages == [] and env.telegram.urls == [] and env.smtp.calls == []
    assert status_of(a.id) == "approved"
    assert client.get(f"/api/dispatch/{a.id}/receipts").json()["receipts"] == []  # not stored
    assert actions(a.id) == ["dispatched", "dispatched"]  # audited only
    assert all(json.loads(e.details)["status"] == "dry_run" for e in store.events(a.id))


def test_resend_needs_the_flag_and_is_audited(env):
    a = make_advisory()
    assert post(a.id, pin=PIN).status_code == 200
    again = post(a.id, pin=PIN)
    assert again.status_code == 409 and "resend" in again.json()["detail"]
    resent = post(a.id, pin=PIN, resend=True)
    assert resent.status_code == 200 and resent.json()["resend"] is True
    assert status_of(a.id) == "sent"
    assert len(client.get(f"/api/dispatch/{a.id}/receipts").json()["receipts"]) == 2
    sent_events = [json.loads(e.details) for e in store.events(a.id) if e.action == "sent"]
    assert [d["resend"] for d in sent_events] == [False, True]
    assert len(env.telegram.messages) == 4


def test_live_dispatches_are_rate_limited(env, monkeypatch):
    a = make_advisory()
    for _ in range(service.LIVE_PER_HOUR):
        assert post(a.id, pin=PIN, resend=True, channels=["telegram"]).status_code == 200
    limited = post(a.id, pin=PIN, resend=True, channels=["telegram"])
    assert limited.status_code == 429
    assert post(a.id, dry_run=True, resend=True).status_code == 200  # dry runs don't count


# --- Other routes and helpers -------------------------------------------------------------------


def test_recipients_are_masked(env):
    body = client.get("/api/dispatch/recipients").json()
    assert body["telegram"] == {"configured": True, "chat_id": "**********3210"}
    assert body["email"] == {
        "configured": True,
        "to": ["of*********@example.org", "bd***@example.org"],
    }
    assert body["pin_configured"] is True
    assert "officer.one" not in json.dumps(body)


def test_cap_xml_for_never_sent_and_draft_advisories(env):
    fresh = client.get(f"/api/dispatch/{make_advisory().id}/cap.xml")
    assert fresh.status_code == 200 and cap.errors(fresh.text) == []
    assert client.get(f"/api/dispatch/{make_advisory('draft').id}/cap.xml").status_code == 409


def test_long_messages_are_split_under_telegrams_limit():
    text = "\n".join(["x" * 1000] * 9 + ["y" * 5000])
    parts = channels.split_message(text)
    assert all(len(p) <= channels.TELEGRAM_MAX_CHARS for p in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")
    assert channels.split_message("short") == ["short"]


def test_every_telegram_message_starts_with_the_label_even_when_split(env):
    a = make_advisory()
    long_body = "\n".join(f"line {i}: " + "x" * 90 for i in range(80))  # ~8 000 characters
    props = a.properties.model_copy(
        update={
            "texts": a.properties.texts.model_copy(
                update={"bn": make_text("bn").model_copy(update={"body": long_body})}
            )
        }
    )
    messages = channels.telegram_messages(Advisory(id=props.id, properties=props))
    bn = [m for m in messages if m.startswith(LABEL["bn"])]
    assert len(bn) >= 2  # split into several messages
    assert all(m.startswith(f"{LABEL['bn']}\n\n") for m in bn)
    assert all(m.startswith((LABEL["bn"], LABEL["en"])) for m in messages)
    assert all(len(m) <= channels.TELEGRAM_MAX_CHARS for m in messages)
    assert messages[-1].startswith(f"{LABEL['en']}\n\n{texts('en')['headline']}")


def test_plain_text_puts_the_label_first_in_each_language():
    for lang in ("en", "bn", "hi"):
        text = channels.plain_text(make_text(lang), lang)
        assert text.split("\n\n")[:2] == [LABEL[lang], texts(lang)["headline"]]
