from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]

# The values shipped in api/.env.example. A key still set to its placeholder counts as not
# configured. tests/test_health.py checks that .env.example matches this dict.
PLACEHOLDERS: dict[str, str] = {
    "GEMINI_API_KEY": "your-gemini-api-key",
    "GEE_SERVICE_ACCOUNT": "your-sa@your-project.iam.gserviceaccount.com",
    "TELEGRAM_BOT_TOKEN": "123456:your-telegram-bot-token",
    "TELEGRAM_CHAT_ID": "-1001234567890",
    "RESEND_API_KEY": "re_your_resend_api_key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=API_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    GEMINI_API_KEY: str | None = None
    GEE_SERVICE_ACCOUNT: str | None = None
    GEE_KEY_PATH: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    RESEND_API_KEY: str | None = None
    DEMO_MODE: bool = True
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
