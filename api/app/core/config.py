from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]

# The values shipped in api/.env.example. A key still set to its placeholder counts as not
# configured. tests/test_health.py checks that .env.example matches this dict.
PLACEHOLDERS: dict[str, str] = {
    "GEMINI_API_KEY": "your-gemini-api-key",
    "GROQ_API_KEY": "your-groq-api-key",
    "GEE_SERVICE_ACCOUNT": "your-sa@your-project.iam.gserviceaccount.com",
    "TELEGRAM_BOT_TOKEN": "123456:your-telegram-bot-token",
    "TELEGRAM_CHAT_ID": "-1001234567890",
    "GMAIL_ADDRESS": "you@gmail.com",
    "GMAIL_APP_PASSWORD": "your-16-char-app-password",
    "DISPATCH_EMAIL_TO": "officer@example.org",
    "DISPATCH_PIN": "change-me",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=API_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    GEMINI_API_KEY: str | None = None
    # Fallback advisory model, only when Gemini fails with 429 / 503 (app/advisory/providers.py).
    # GROQ_MODEL is a plain setting, not a secret: its .env.example value is the real default.
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GEE_SERVICE_ACCOUNT: str | None = None
    GEE_KEY_PATH: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    # Dispatch e-mail: Gmail SMTP with an app password; DISPATCH_EMAIL_TO is comma-separated.
    GMAIL_ADDRESS: str | None = None
    GMAIL_APP_PASSWORD: str | None = None
    DISPATCH_EMAIL_TO: str | None = None
    # Required in the request for every live (non-dry-run) dispatch.
    DISPATCH_PIN: str | None = None
    DEMO_MODE: bool = True
    # SQLite state (advisories, audit log, dispatch receipts). Unset: api/data/state/tempest.db.
    # On Render: /tmp/tempest.db (set in render.yaml), the only writable path; it is lost on every
    # deploy, restart and spin-down. One instance keeps a single shared queue.
    STATE_DB_PATH: str | None = None
    # The OASIS CAP 1.2 XSD. Unset: api/data/raw/CAP-v1.2.xsd, downloaded on first use; the API
    # image downloads and checks it at build time (api/Dockerfile).
    CAP_XSD_PATH: str | None = None
    # South 24 Parganas / Sundarbans, EPSG:4326: min_lon,min_lat,max_lon,max_lat
    AOI_BBOX: str = "88.0,21.5,89.1,22.7"

    def is_configured(self, name: str) -> bool:
        """True if setting `name` is set and not left at its .env.example placeholder."""
        value = getattr(self, name)
        return bool(value) and value != PLACEHOLDERS.get(name)

    @property
    def gee_key_file(self) -> Path | None:
        """GEE_KEY_PATH as a Path; relative paths resolve against api/."""
        if not self.GEE_KEY_PATH:
            return None
        path = Path(self.GEE_KEY_PATH)
        return path if path.is_absolute() else API_DIR / path

    @property
    def aoi_bbox_tuple(self) -> tuple[float, float, float, float]:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in self.AOI_BBOX.split(","))
        return min_lon, min_lat, max_lon, max_lat


@lru_cache
def get_settings() -> Settings:
    return Settings()
