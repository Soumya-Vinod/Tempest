"""Fresh-clone / container smoke test: DEMO_MODE on, no API keys, no data/processed/ or data/raw/
(as in the API image, api/Dockerfile). Every route answers for all 25 replay timesteps, and
nothing opens a file under data/raw or data/processed. No network: with every key blank, no
Gemini, Groq, Telegram, SMTP or Brevo call can happen."""

import os
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.advisory import store
from app.core import config
from app.dispatch import cap
from app.exposure import ingest
from app.exposure import service as exposure
from app.impact import countdown, departures
from app.impact import service as impact
from app.insurance import service as insurance
from app.main import app
from app.risk import service as risk
from app.schemas import (
    REPLAY_TIMESTEPS,
    Advisory,
    AdvisoryProperties,
    AdvisoryTexts,
    Citation,
)

KEYS = (
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GMAIL_ADDRESS",
    "GMAIL_APP_PASSWORD",
    "BREVO_API_KEY",
    "DISPATCH_EMAIL_TO",
    "DISPATCH_PIN",
    "GEE_SERVICE_ACCOUNT",
    "GEE_KEY_PATH",
)
FORBIDDEN = ("/data/raw/", "/data/processed/")
CACHED_XSD = cap.DEFAULT_XSD_PATH  # the local cache stands in for the image's build-time copy

# Reads under FORBIDDEN while watching: Python opens via an audit hook (it can't be removed once
# added, so it checks a flag), and the native readers (pyarrow, GDAL) via wrappers, since their
# file access never reaches Python's `open` event.
_watch = {"on": False, "hits": []}


def _record(path) -> None:
    if _watch["on"] and isinstance(path, str | bytes | os.PathLike):
        resolved = os.path.abspath(os.fsdecode(path)).replace("\\", "/")
        if any(part in resolved for part in FORBIDDEN):
            _watch["hits"].append(resolved)


def _hook(event: str, args: tuple) -> None:
    if event == "open" and args:
        _record(args[0])


sys.addaudithook(_hook)


def _watched(reader):
    def wrapper(path, *args, **kwargs):
        _record(path)
        return reader(path, *args, **kwargs)

    return wrapper


def _clear_caches() -> None:
    config.get_settings.cache_clear()
    cap._schema.cache_clear()
    for module in (exposure, impact, risk, insurance, countdown, departures):
        module.clear_cache()


@pytest.fixture
def container(tmp_path, monkeypatch):
    """The API as in the image: DEMO_MODE, no keys, state in a temp dir, no raw/processed."""
    if not CACHED_XSD.is_file():
        pytest.skip("CAP XSD not cached locally (the image downloads it at build time)")
    xsd = tmp_path / "xsd" / "CAP-v1.2.xsd"
    xsd.parent.mkdir()
    shutil.copy(CACHED_XSD, xsd)  # before watching: this reads data/raw on purpose

    monkeypatch.setenv("DEMO_MODE", "true")
    for key in KEYS:
        monkeypatch.setenv(key, "")  # env beats api/.env: every key is "not configured"
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "state" / "tempest.db"))
    monkeypatch.setenv("CAP_XSD_PATH", str(xsd))
    monkeypatch.setattr(store, "DB_PATH", None)  # use STATE_DB_PATH, as the image does
    # data/raw and data/processed don't exist in the image.
    missing = tmp_path / "missing"
    monkeypatch.setattr(ingest, "RAW_DIR", missing / "raw")
    monkeypatch.setattr(ingest, "PROCESSED_DIR", missing / "processed")
    monkeypatch.setattr(exposure, "INFRA_PATH", missing / "processed" / "infra.parquet")
    monkeypatch.setattr(impact, "GRAPH_PATH", missing / "processed" / "roads.graphml")
    for module, name in ((gpd, "read_file"), (gpd, "read_parquet"), (pd, "read_parquet")):
        monkeypatch.setattr(module, name, _watched(getattr(module, name)))
    _clear_caches()
    _watch.update(on=True, hits=[])
    yield TestClient(app)
    _watch["on"] = False
    _clear_caches()


def approved_advisory() -> str:
    now = datetime.now(UTC)
    text = {"headline": "Sagar", "body": "[EXERCISE] body", "actions": ["a", "b", "c"]}
    t = AdvisoryTexts(en=text, bn=text, hi=text)
    props = AdvisoryProperties(
        id=str(uuid.uuid4()),
        block_id="02438",
        block_name="Sagar",
        timestep="2020-05-20T09:00:00Z",
        texts=t,
        templates=t,
        citations=[
            Citation(key="risk_score", label="Risk", value=0.55, unit=None, source="risk"),
            Citation(key="hours_to_landfall", label="h", value=3, unit="h", source="replay"),
        ],
        status="approved",
        approved_by="A. Officer (BDO)",
        approved_at=now,
        created_at=now,
    )
    with store.transaction() as conn:
        store.save(conn, Advisory(id=props.id, properties=props))
    return props.id


def test_every_route_in_demo_mode_without_raw_or_processed_data(container, tmp_path):
    client = container
    failures: list[str] = []

    def get(path: str, **params) -> None:
        r = client.get(path, params=params)
        if r.status_code != 200:
            failures.append(f"GET {path} {params}: {r.status_code} {r.text[:150]}")

    # Static routes.
    get("/health")
    get("/api/hazard/timesteps")
    get("/api/exposure/infra")
    for infra_type in ("substation", "power_line", "road", "hospital", "shelter"):
        get("/api/exposure/infra", infra_type=infra_type)
    get("/api/risk/unscored-areas")
    get("/api/impact/departures")
    get("/api/insurance/summary")
    get("/api/advisory/")
    get("/api/advisory/audit")
    get("/api/dispatch/recipients")

    # Every replay timestep.
    for ts in REPLAY_TIMESTEPS:
        for hazard_type in ("wind", "surge", "flood"):
            get("/api/hazard/layers", hazard_type=hazard_type, timestep=ts)
        for path in (
            "/api/impact/results",
            "/api/impact/countdown",
            "/api/risk/scores",
            "/api/risk/breakdown",
            "/api/insurance/triggers",
            "/api/advisory/suggestions",
        ):
            get(path, timestep=ts)
        # Both forecast horizons (v1.3): now and expected within 24 h.
        for path in ("/api/impact/results", "/api/risk/scores", "/api/risk/breakdown"):
            for horizon in ("0", "24"):
                get(path, timestep=ts, horizon=horizon)

    # Advisory generation with no key and no valid cached response: 503, never a live call.
    r = client.post("/api/advisory/", json={"block_id": "02435", "timestep": REPLAY_TIMESTEPS[-1]})
    if r.status_code != 503:
        failures.append(f"POST /api/advisory/: expected 503, got {r.status_code} {r.text[:150]}")

    # Dispatch dry run: builds the messages and validates the CAP against the image's XSD.
    advisory_id = approved_advisory()
    r = client.post(
        f"/api/dispatch/{advisory_id}", json={"channels": ["telegram", "email"], "dry_run": True}
    )
    if r.status_code != 200 or {c["status"] for c in r.json()["channels"]} != {"dry_run"}:
        failures.append(f"dispatch dry run: {r.status_code} {r.text[:150]}")
    if client.get(f"/api/dispatch/{advisory_id}/cap.xml").status_code != 200:
        failures.append("GET cap.xml failed")
    # A live dispatch without DISPATCH_PIN is refused.
    r = client.post(f"/api/dispatch/{advisory_id}", json={"channels": ["telegram"], "pin": "x"})
    if r.status_code != 403:
        failures.append(f"live dispatch without a PIN: expected 403, got {r.status_code}")

    assert not failures, "\n".join(failures)
    assert _watch["hits"] == [], f"read raw / processed data: {sorted(set(_watch['hits']))}"
    # State went to STATE_DB_PATH (in the image: /tmp), not api/data/state.
    assert (tmp_path / "state" / "tempest.db").is_file()


def test_the_image_setting_points_state_and_xsd_outside_the_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DB_PATH", "/tmp/tempest.db")
    monkeypatch.setenv("CAP_XSD_PATH", "/app/data/xsd/CAP-v1.2.xsd")
    monkeypatch.setattr(store, "DB_PATH", None)
    config.get_settings.cache_clear()
    try:
        assert store.db_path() == Path("/tmp/tempest.db")
    finally:
        config.get_settings.cache_clear()


def test_the_watch_catches_python_and_native_reads(monkeypatch):
    """The detector itself: a relative Python open and a native parquet read are both caught."""
    raw = cap.DEFAULT_XSD_PATH
    parquet = ingest.INFRA_PARQUET
    if not (raw.is_file() and parquet.is_file()):
        pytest.skip("needs the local data/raw and data/processed files")
    monkeypatch.setattr(gpd, "read_parquet", _watched(gpd.read_parquet))
    monkeypatch.chdir(raw.parents[2])  # api/, so the open below is relative
    _watch.update(on=True, hits=[])
    try:
        open("data/raw/CAP-v1.2.xsd", "rb").close()
        gpd.read_parquet(parquet)
    finally:
        _watch["on"] = False
    assert any(h.endswith("/data/raw/CAP-v1.2.xsd") for h in _watch["hits"])
    assert any(h.endswith("/data/processed/infra.parquet") for h in _watch["hits"])
