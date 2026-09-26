import pytest
from fastapi.testclient import TestClient

from app.core.config import API_DIR, PLACEHOLDERS, Settings
from app.main import app

ENV_VARS = (
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "GEE_SERVICE_ACCOUNT",
    "GEE_KEY_PATH",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GMAIL_ADDRESS",
    "GMAIL_APP_PASSWORD",
    "DISPATCH_EMAIL_TO",
    "DISPATCH_PIN",
    "DEMO_MODE",
)
FLAGS = {v.lower() for v in ENV_VARS if v != "DEMO_MODE"}
OTHER_VARS = ("GROQ_MODEL",)  # settings, not keys: reported by value, not as a flag


@pytest.fixture
def client(monkeypatch):
    for var in (*ENV_VARS, *OTHER_VARS):
        monkeypatch.delenv(var, raising=False)
    # Fresh settings per request from env vars only; never touches a real api/.env.
    monkeypatch.setattr("app.main.get_settings", lambda: Settings(_env_file=None))
    return TestClient(app)


def test_health_defaults(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True
    assert body["groq_model"] == "openai/gpt-oss-120b"
    assert set(body["configured"]) == FLAGS
    assert not any(body["configured"].values())


def test_health_reports_flags_not_values(client, monkeypatch, tmp_path):
    key_file = tmp_path / "key.json"
    key_file.write_text("{}")
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    monkeypatch.setenv("GEE_KEY_PATH", str(key_file))
    resp = client.get("/health")
    assert "super-secret-value" not in resp.text
    assert str(key_file) not in resp.text
    assert resp.json()["configured"]["gemini_api_key"] is True
    assert resp.json()["configured"]["gee_key_path"] is True


def test_gee_key_path_false_when_file_missing(client, monkeypatch, tmp_path):
    monkeypatch.setenv("GEE_KEY_PATH", str(tmp_path / "missing.json"))
    assert client.get("/health").json()["configured"]["gee_key_path"] is False


def test_placeholders_are_not_configured(client, monkeypatch):
    for var, placeholder in PLACEHOLDERS.items():
        monkeypatch.setenv(var, placeholder)
    configured = client.get("/health").json()["configured"]
    assert not any(configured[var.lower()] for var in PLACEHOLDERS)


def test_env_example_matches_placeholders():
    lines = (API_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    example = dict(
        line.split("=", 1) for line in lines if line.strip() and not line.startswith("#")
    )
    assert {var: example.get(var) for var in PLACEHOLDERS} == PLACEHOLDERS
