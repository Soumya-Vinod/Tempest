import json
import re
from typing import Any

from app.core.config import API_DIR, get_settings

DEMO_DIR = API_DIR / "data" / "demo"
_KEY_RE = re.compile(r"^[a-z0-9_\-]+$")


def load_fixture(key: str) -> Any | None:
    """Return the parsed fixture data/demo/<key>.json when DEMO_MODE is on, else None.

    Callers fall through to the live call on None. Raises FileNotFoundError if
    DEMO_MODE is on but the fixture is missing.
    """
    if not get_settings().DEMO_MODE:
        return None
    if not _KEY_RE.match(key):
        raise ValueError(f"Invalid fixture key: {key!r}")
    path = DEMO_DIR / f"{key}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Demo fixture not found: {path.name}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)
