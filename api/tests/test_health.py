import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app

ENV_VARS = (
    "GEMINI_API_KEY",
    "GEE_SERVICE_ACCOUNT",
    "GEE_KEY_PATH",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "RESEND_API_KEY",
    "DEMO_MODE",
)
FLAGS = {v.lower() for v in ENV_VARS if v != "DEMO_MODE"}


@pytest.fixture
def client(monkeypatch):
    for var in ENV_VARS:
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
