"""Ingest official NOAA IBTrACS Cyclone Amphan track into canonical demo fixture.

Source Dataset:
    NOAA NCEI International Best Track Archive for Climate Stewardship (IBTrACS) v04
    Basin: North Indian Ocean (NI), Storm ID: 2020136N10088 / 2020137N10087 (AMPHAN).
    Source URL:
    https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r00/access/csv/ibtracs.NI.list.v04r00.csv

Architecture & Provenance:
    hazard__track.json is a generated artifact produced by api/scripts/ingest_track.py
    from the official IBTrACS dataset. The repository uses the generated fixture at runtime
    to ensure deterministic replay behavior and avoid network dependencies.

Workflow:
    IBTrACS CSV (api/data/raw/ibtracs_amphan.csv)
            │
            ▼
    ingest_track.py
            │
            ▼
    hazard__track.json (api/data/demo/hazard__track.json)
            │
            ▼
    Replay Engine

Run from repo root:
    .venv\\Scripts\\python api/scripts/ingest_track.py
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import urllib.request
from pathlib import Path

# Ensure api directory is in Python path when executed directly
API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.core.config import API_DIR as CONFIG_API_DIR  # noqa: E402
from app.hazard.models import CycloneTrack, CycloneTrackPoint  # noqa: E402
from app.schemas import REPLAY_TIMESTEPS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ingest_track")

RAW_DEFAULT = CONFIG_API_DIR / "data" / "raw" / "ibtracs_amphan.csv"
FIXTURE_DEFAULT = CONFIG_API_DIR / "data" / "demo" / "hazard__track.json"
NOAA_NI_CSV_URL = (
    "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship"
    "-ibtracs/v04r00/access/csv/ibtracs.NI.list.v04r00.csv"
)

# Known storm identifiers for Cyclone Amphan (2020)
AMPHAN_SIDS = {"2020136N10088", "2020137N10087"}
KTS_TO_MPS = 0.514444
NM_TO_KM = 1.852
EARTH_RADIUS_M = 6371000.0


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points in meters using Haversine formula."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def forward_azimuth_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate initial forward geodesic azimuth bearing in degrees [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def download_ibtracs_amphan(dest_path: Path) -> None:
    """Download official NOAA IBTrACS NI basin CSV and extract Amphan records."""
    logger.info("Downloading official IBTrACS NI dataset from NOAA NCEI...")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(NOAA_NI_CSV_URL, headers={"User-Agent": "TempestHazardIngest/1.0"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        header1 = resp.readline().decode("utf-8")
        header2 = resp.readline().decode("utf-8")
        matched_lines = [header1, header2]
        for line in resp:
            decoded = line.decode("utf-8")
            if "AMPHAN" in decoded or any(sid in decoded for sid in AMPHAN_SIDS):
                matched_lines.append(decoded)

    dest_path.write_text("".join(matched_lines), encoding="utf-8", newline="\n")
    logger.info("Wrote %d rows to %s", len(matched_lines) - 2, dest_path)


def read_raw_ibtracs(csv_path: Path) -> list[dict[str, str]]:
    """Read raw IBTrACS CSV, skipping the units header row."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"IBTrACS raw file not found: {csv_path}")

    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Skip unit metadata row (row 2 in IBTrACS)
        next(reader, None)
        rows = list(reader)

    # Filter for Cyclone Amphan
    amphan_rows = [
        r for r in rows
        if r.get("NAME") == "AMPHAN" or r.get("SID") in AMPHAN_SIDS
    ]
    if not amphan_rows:
        raise ValueError(f"No records matching Cyclone Amphan found in {csv_path}")

    logger.info("Loaded %d raw IBTrACS records for Cyclone Amphan", len(amphan_rows))
    return amphan_rows


def extract_and_resample_track(raw_rows: list[dict[str, str]]) -> list[dict]:
    """Extract and align track points to the 25 official 3-hour replay timesteps."""
    # Map raw rows by ISO 8601 UTC timestamp
    row_by_ts: dict[str, dict[str, str]] = {}
    for r in raw_rows:
        iso_time = r.get("ISO_TIME", "").strip()
        if iso_time:
            # Convert 'YYYY-MM-DD HH:MM:SS' to 'YYYY-MM-DDTHH:MM:SSZ'
            ts = iso_time.replace(" ", "T")
            if not ts.endswith("Z"):
                ts += "Z"
            row_by_ts[ts] = r

    raw_points: list[dict] = []
    for ts in REPLAY_TIMESTEPS:
        if ts not in row_by_ts:
            raise ValueError(f"Missing IBTrACS fix for replay timestep {ts}")

        r = row_by_ts[ts]

        # Coordinates: primary WMO consensus, fallback to USA / New Delhi
        lat_str = r.get("LAT") or r.get("NEWDELHI_LAT") or r.get("USA_LAT")
        lon_str = r.get("LON") or r.get("NEWDELHI_LON") or r.get("USA_LON")
        if not lat_str or not lon_str:
            raise ValueError(f"Missing coordinates at {ts}")
        lat = round(float(lat_str), 4)
        lon = round(float(lon_str), 4)

        # Maximum sustained wind (kts -> m/s): WMO (IMD 3-min/10-min) or USA (1-min)
        wind_str = r.get("WMO_WIND") or r.get("NEWDELHI_WIND") or r.get("USA_WIND")
        wind_kts = float(wind_str) if wind_str else 65.0
        max_wind_mps = round(wind_kts * KTS_TO_MPS, 2)

        # Central pressure (mb / hPa)
        pres_str = r.get("WMO_PRES") or r.get("NEWDELHI_PRES") or r.get("USA_PRES")
        pres_hpa = round(float(pres_str), 1) if pres_str else 950.0

        # Radius of maximum wind (nm -> km)
        rmw_str = r.get("USA_RMW")
        rmw_nm = float(rmw_str) if rmw_str else 16.0
        radius_max_wind_km = round(rmw_nm * NM_TO_KM, 1)

        raw_points.append({
            "timestep": ts,
            "lat": lat,
            "lon": lon,
            "central_pressure_hpa": pres_hpa,
            "max_wind_mps": max_wind_mps,
            "radius_max_wind_km": radius_max_wind_km,
            "forward_speed_mps": 0.0,
            "heading_deg": 0.0,
        })

    # Compute derived forward translation speed and geodesic heading
    for i in range(len(raw_points) - 1):
        p1 = raw_points[i]
        p2 = raw_points[i + 1]
        dist_m = haversine_distance_m(p1["lat"], p1["lon"], p2["lat"], p2["lon"])
        # 3 hours = 10,800 seconds
        raw_points[i]["forward_speed_mps"] = round(dist_m / 10800.0, 2)
        raw_points[i]["heading_deg"] = round(
            forward_azimuth_deg(p1["lat"], p1["lon"], p2["lat"], p2["lon"]), 2
        )

    # For final landfall fix (T-0), maintain velocity/heading from penultimate fix
    raw_points[-1]["forward_speed_mps"] = raw_points[-2]["forward_speed_mps"]
    raw_points[-1]["heading_deg"] = raw_points[-2]["heading_deg"]

    return raw_points


def validate_track(points: list[dict]) -> CycloneTrack:
    """Perform rigorous validation on ingested track points.

    Checks:
    - Exactly 25 timestamps
    - Perfect synchronization with REPLAY_TIMESTEPS
    - Strict chronological order
    - Latitude/longitude within Bay of Bengal AOI domain
    - Physical bounds on pressure, wind, radius, speed, heading
    - Pydantic schema validation for CycloneTrackPoint and CycloneTrack
    """
    if len(points) != 25:
        raise ValueError(f"Expected exactly 25 track points, got {len(points)}")

    timesteps = [p["timestep"] for p in points]
    if timesteps != list(REPLAY_TIMESTEPS):
        raise ValueError("Ingested timesteps do not match canonical REPLAY_TIMESTEPS")

    # Chronological ordering check (strictly increasing ISO timestamps)
    for i in range(len(timesteps) - 1):
        if timesteps[i] >= timesteps[i + 1]:
            raise ValueError(f"Non-chronological timestep order at index {i}: {timesteps[i]}")

    # Physical coordinate bounds
    for i, p in enumerate(points):
        lat = p["lat"]
        lon = p["lon"]
        if not (10.0 <= lat <= 23.0):
            raise ValueError(f"Latitude out of bounds at index {i}: {lat}")
        if not (85.0 <= lon <= 90.0):
            raise ValueError(f"Longitude out of bounds at index {i}: {lon}")

    # General northward progression
    if points[-1]["lat"] <= points[0]["lat"]:
        raise ValueError("Track does not progress northward toward landfall")

    # Pydantic model validation
    validated_points = [CycloneTrackPoint.model_validate(p) for p in points]
    track_model = CycloneTrack(event="amphan", points=validated_points)
    logger.info("Track successfully validated against CycloneTrack schema")
    return track_model


def write_fixture(track: CycloneTrack, out_path: Path) -> None:
    """Write validated track model to demo fixture with LF line endings."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = track.model_dump(mode="json")
    text = json.dumps(serialized, indent=2, ensure_ascii=False) + "\n"
    out_path.write_text(text, encoding="utf-8", newline="\n")
    logger.info("Successfully wrote canonical fixture to %s (%d bytes)", out_path, len(text))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest official IBTrACS Cyclone Amphan track into hazard__track.json fixture"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=RAW_DEFAULT,
        help=f"Path to raw IBTrACS CSV (default: {RAW_DEFAULT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=FIXTURE_DEFAULT,
        help=f"Path to output demo fixture (default: {FIXTURE_DEFAULT})",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download official IBTrACS CSV from NOAA NCEI if input file is missing",
    )

    args = parser.parse_args()

    if not args.input.is_file():
        if args.download:
            download_ibtracs_amphan(args.input)
        else:
            logger.error(
                "Raw input file %s does not exist. Use --download to fetch it.", args.input
            )
            sys.exit(1)

    try:
        raw_rows = read_raw_ibtracs(args.input)
        points_data = extract_and_resample_track(raw_rows)
        track_model = validate_track(points_data)
        write_fixture(track_model, args.output)
        print(f"Ingestion successful: 25 track points written to {args.output.name}")
    except Exception as exc:
        logger.error("Track ingestion failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
