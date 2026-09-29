"""Pre-rendered GET responses for DEMO_MODE (api/scripts/build_static_responses.py).

The build script requests every route and parameter combination the web app uses, through the
app itself, and stores each final body gzip-compressed in data/static/, with manifest.json
mapping the request key to its file and Content-Type. In DEMO_MODE this middleware answers a GET
whose key is in the manifest with that file as it is (Content-Encoding: gzip), so the route code,
validation, serialisation and compression never run. Any other request falls through to the app.

A request key is the path plus the query parameters sorted by name, so parameter order doesn't
matter; any other difference (an extra parameter, "horizon=00") is a miss and goes to the app.
"""

import gzip
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import API_DIR, get_settings

# None turns the middleware off (the build script, and tests that check the live code).
STATIC_DIR: Path | None = API_DIR / "data" / "static"
MANIFEST = "manifest.json"


def request_key(path: str, query: str) -> str:
    """Path plus the query parameters sorted by name (values as decoded by the router)."""
    params = sorted(parse_qsl(query, keep_blank_values=True))
    return f"{path}?{urlencode(params)}" if params else path


@lru_cache(maxsize=4)
def load_manifest(directory: Path) -> dict[str, dict[str, str]]:
    """{request key: {"file": name, "content_type": ...}}; empty if nothing was built."""
    path = directory / MANIFEST
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _accepts_gzip(scope: Scope) -> bool:
    for name, value in scope["headers"]:
        if name == b"accept-encoding":
            return b"gzip" in value.lower()
    return False


class StaticResponseMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        entry = None
        if (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and STATIC_DIR is not None
            and get_settings().DEMO_MODE
        ):
            key = request_key(scope["path"], scope["query_string"].decode("latin-1"))
            entry = load_manifest(STATIC_DIR).get(key)
        body = None
        if entry is not None:
            try:
                body = (STATIC_DIR / entry["file"]).read_bytes()
            except OSError:
                body = None  # manifest without its file: let the route answer
        if body is None:
            await self.app(scope, receive, send)
            return

        headers = [
            (b"content-type", entry["content_type"].encode("latin-1")),
            (b"vary", b"Accept-Encoding"),
        ]
        if _accepts_gzip(scope):
            headers.append((b"content-encoding", b"gzip"))
        else:
            body = gzip.decompress(body)
        headers.append((b"content-length", str(len(body)).encode("latin-1")))
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body})
