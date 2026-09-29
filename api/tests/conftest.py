import pytest

from app.core import static_responses


@pytest.fixture(autouse=True)
def _live_routes(monkeypatch):
    """Tests exercise the route code, not a local data/static/ build (it may be stale).
    tests/test_static_responses.py points the middleware at its own build."""
    monkeypatch.setattr(static_responses, "STATIC_DIR", None)
