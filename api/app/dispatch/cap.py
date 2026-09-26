"""CAP 1.2 (OASIS Common Alerting Protocol) XML for an advisory, validated against the official XSD.

One <alert> per dispatch: status Exercise (CAP's own field for drills), msgType Alert, scope
Public, and one <info> per language (en-IN, bn-IN, hi-IN) with the advisory's filled texts:
headline, description = body, instruction = the actions, one per line. <area> holds the block
name in that language, the block polygon (simplified) and a geocode with the Census 2011 code.

Risk -> CAP mapping (contracts.md §4.7), from the figures the advisory cites:
- severity, from the block risk score (0-1): >= 0.6 Extreme, >= 0.4 Severe, >= 0.25 Moderate
  (the advisory suggestion threshold), else Minor.
- urgency, from hours to landfall: <= 12 h Immediate, else Future. CAP's "Expected" means
  "responsive action should be taken soon (within next hour)", which doesn't fit cyclone lead
  times: at 12 h or less, preparation has to start now; before that it is Future.
- certainty: Observed at landfall (0 h), else Likely (a forecast track).

CAP polygons are "lat,lon" pairs, space-separated, closed (first = last), at least 4 points.
A block with several parts (islands) gets one <polygon> per part; CAP has no holes, so interior
rings are dropped. The identifier is unique per dispatch (advisory id + dispatch time), as CAP
requires for a new message; `sent` carries the IST offset (CAP forbids "Z").

The XSD is downloaded once from OASIS to api/data/raw/ (git-ignored), checked against a pinned
SHA-256, and reused; the API image downloads it at build time (CAP_XSD_PATH).
"""

import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import httpx
import shapely
from shapely.geometry.base import BaseGeometry

from app.core.config import API_DIR, get_settings
from app.exposure.ingest import METRIC_CRS
from app.risk import blocks as block_data
from app.schemas import Advisory

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
XSD_URL = "https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.xsd"
DEFAULT_XSD_PATH = API_DIR / "data" / "raw" / "CAP-v1.2.xsd"
# SHA-256 of the official file; a download that doesn't match is refused (also in api/Dockerfile).
XSD_SHA256 = "b7798ef25868b068c97b268bda02d067c7d4ba9373adc5638bf37105804ee723"
SENDER = "tempest-s24p-exercise@invalid"
SENDER_NAME = "Tempest exercise, South 24 Parganas"
IST = timezone(timedelta(hours=5, minutes=30), "IST")
CAP_LANGUAGES = {"en": "en-IN", "bn": "bn-IN", "hi": "hi-IN"}
GEOCODE_NAME = "census2011_cd"
SIMPLIFY_M = 100.0
COORD_DECIMALS = 5  # ~1 m
EXERCISE_NOTE = "EXERCISE: Cyclone Amphan (May 2020) replay. Not a real warning."

SEVERITY_BANDS = ((0.6, "Extreme"), (0.4, "Severe"), (0.25, "Moderate"))
IMMEDIATE_WITHIN_H = 12


class CapInvalid(ValueError):
    """The generated CAP does not validate against the XSD."""


def severity(score: float) -> str:
    return next((name for threshold, name in SEVERITY_BANDS if score >= threshold), "Minor")


def urgency(hours_to_landfall: float) -> str:
    return "Immediate" if hours_to_landfall <= IMMEDIATE_WITHIN_H else "Future"


def certainty(hours_to_landfall: float) -> str:
    return "Observed" if hours_to_landfall <= 0 else "Likely"


def cap_time(t: datetime) -> str:
    """CAP dateTime: seconds and a numeric offset, e.g. 2026-09-26T13:40:00+05:30."""
    return t.astimezone(IST).replace(microsecond=0).isoformat()


def block_polygons(geom: BaseGeometry) -> list[str]:
    """CAP <polygon> strings ("lat,lon ..."), one per part, simplified and closed."""
    metric = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(METRIC_CRS).iloc[0]
    simple = shapely.make_valid(metric.simplify(SIMPLIFY_M, preserve_topology=True))
    wgs = gpd.GeoSeries([simple], crs=METRIC_CRS).to_crs("EPSG:4326").iloc[0]
    out = []
    for part in getattr(wgs, "geoms", [wgs]):
        if part.geom_type != "Polygon" or part.is_empty:
            continue
        coords = [
            (round(y, COORD_DECIMALS), round(x, COORD_DECIMALS)) for x, y in part.exterior.coords
        ]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        if len(coords) >= 4:
            out.append(" ".join(f"{lat},{lon}" for lat, lon in coords))
    return out


def _citation(advisory: Advisory, key: str) -> float | None:
    c = next((c for c in advisory.properties.citations if c.key == key), None)
    return float(c.value) if c is not None and not isinstance(c.value, str) else None


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, f"{{{CAP_NS}}}{tag}")
    if text is not None:
        el.text = text
    return el


def build(advisory: Advisory, sent: datetime) -> str:
    """The CAP 1.2 alert for `advisory`, dispatched at `sent`, as UTF-8 XML text."""
    p = advisory.properties
    blocks = block_data.load_blocks()
    if p.block_id not in blocks.codes:
        raise ValueError(f"unknown block {p.block_id!r}")
    polygons = block_polygons(blocks.geometry.iloc[blocks.codes.index(p.block_id)])
    names = block_data.local_names().get(p.block_name, {})
    score = _citation(advisory, "risk_score") or 0.0
    hours = _citation(advisory, "hours_to_landfall")
    if hours is None:
        from app.advisory.facts import hours_to_landfall

        hours = hours_to_landfall(p.timestep)

    ET.register_namespace("", CAP_NS)
    alert = ET.Element(f"{{{CAP_NS}}}alert")
    _sub(alert, "identifier", f"{p.id}.{sent.astimezone(IST).strftime('%Y%m%dT%H%M%S')}")
    _sub(alert, "sender", SENDER)
    _sub(alert, "sent", cap_time(sent))
    _sub(alert, "status", "Exercise")
    _sub(alert, "msgType", "Alert")
    _sub(alert, "scope", "Public")
    _sub(alert, "note", EXERCISE_NOTE)
    for lang, cap_lang in CAP_LANGUAGES.items():
        text = getattr(p.texts, lang)
        info = _sub(alert, "info")
        _sub(info, "language", cap_lang)
        _sub(info, "category", "Met")
        _sub(info, "event", "Cyclone")
        _sub(info, "urgency", urgency(hours))
        _sub(info, "severity", severity(score))
        _sub(info, "certainty", certainty(hours))
        _sub(info, "senderName", SENDER_NAME)
        _sub(info, "headline", text.headline)
        _sub(info, "description", text.body)
        _sub(info, "instruction", "\n".join(text.actions))
        area = _sub(info, "area")
        _sub(area, "areaDesc", names.get(lang, p.block_name) if lang != "en" else p.block_name)
        for polygon in polygons:
            _sub(area, "polygon", polygon)
        geocode = _sub(area, "geocode")
        _sub(geocode, "valueName", GEOCODE_NAME)
        _sub(geocode, "value", p.block_id)
    ET.indent(alert)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(alert, encoding="unicode") + "\n"
    )


def xsd_path(path: Path | None = None) -> Path:
    """The OASIS CAP 1.2 XSD: `path`, else the CAP_XSD_PATH setting, else the git-ignored cache
    in api/data/raw/, downloaded on first use and checked against XSD_SHA256."""
    if path is None:
        configured = get_settings().CAP_XSD_PATH
        path = Path(configured) if configured else DEFAULT_XSD_PATH
    if not path.is_file():
        r = httpx.get(XSD_URL, follow_redirects=True, timeout=60)
        r.raise_for_status()
        digest = hashlib.sha256(r.content).hexdigest()
        if digest != XSD_SHA256:
            raise CapInvalid(f"downloaded CAP XSD has SHA-256 {digest}, expected {XSD_SHA256}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    return path


@lru_cache(maxsize=1)
def _schema():
    import xmlschema

    return xmlschema.XMLSchema(str(xsd_path()))


def errors(xml: str) -> list[str]:
    """XSD validation errors for a CAP document ([] if valid)."""
    return [str(e.reason or e) for e in _schema().iter_errors(xml)]


def validate(xml: str) -> None:
    if problems := errors(xml):
        raise CapInvalid("CAP 1.2 validation failed: " + "; ".join(problems[:5]))
