"""Risk score weights and fixed normalisation scales. Every value is an ASSUMPTION, not a
calibrated model; change them here only.

    score = max(hazard, exposure) x (W_EXPOSURE * exposure + W_VULNERABILITY * vulnerability)

The first factor is the cyclone's reach. A block is reached either directly (hazard on its
inhabited land) or indirectly (the cyclone cut it off: its facilities isolated, roads and
substations cut, which exposure measures). Either one alone is enough, so the larger counts; a
block with little hazard of its own but cut off by the storm still scores. The breakdown's
`reach` says which was used (direct on a tie).

Every component and part is 0-1 on a FIXED scale (never relative to this timestep's maximum), so
scores are comparable across timesteps.
"""

import re

from app.exposure.ingest import HOSPITAL_NAME_PATTERNS
from app.impact.thresholds import ROAD_CUT_SURGE_M

# --- Score ---
W_EXPOSURE = 0.6
W_VULNERABILITY = 0.4

# --- Hazard (inhabited land only: the block's land outside OSM protected areas, so the
# uninhabited Sundarbans reserve forest doesn't count) ---
# surge part: share of the block's inhabited land with surge depth >= the road-cut threshold.
SURGE_LAND_THRESHOLD_M = ROAD_CUT_SURGE_M
# wind part: inhabited-land-weighted mean of (wind - WIND_FLOOR) / (WIND_CEILING - WIND_FLOOR),
# clipped 0-1.
# Assumption: below gale force (17 m/s, Beaufort 8) wind adds no risk; 60 m/s is the top of scale.
WIND_FLOOR_MS = 17.0
WIND_CEILING_MS = 60.0
# hazard = max(surge, wind) + FLOOD_WEIGHT x inhabited-land-weighted flood severity, capped at 1.
# Flood is static susceptibility (contracts.md §4.1), so it only adds a small constant weight.
FLOOD_WEIGHT = 0.1

# --- Exposure (from the timestep's impact results inside the block) ---
# isolated_facilities: SHARE of the block's eligible facilities that are isolated. Eligible =
#   hospitals, health centres and shelters in the block that are reachable from the main road
#   component at baseline and within 2 km of the graph (exactly those that can be isolated).
#   0 if the block has none. No cap needed: a share is already 0-1.
# cut_roads: SHARE of the block's road length that is cut (cut metres / all road metres), 0-1.
# Both used to be counts / fixed caps (3 facilities, half the road length), which saturated at 1
# in the worst-hit blocks on Dev A's real hazards and stopped separating them.
CUT_SUBSTATIONS_CAP = 2  # cut substations: 2 or more = 1 (few per block, so a count stays)
EXPOSURE_PARTS = {
    "isolated_facilities": 0.5,
    "cut_roads": 0.35,
    "cut_substations": 0.15,
}

# --- Vulnerability (static; computed once) ---
DENSITY_SCALE_PER_KM2 = 2000.0  # population / inhabited km2; 2,000 or more = 1
# Hospital access: travel time from the nearest hospital (facility_level "hospital", Kolkata's
# included), median over the block's road graph nodes; 2 h or more (or unreachable) = 1.
HOSPITAL_ACCESS_SCALE_S = 2 * 3600.0
# Hospital access sources: facility_level "hospital" minus private / specialist facilities that
# are not general hospitals (OSM tags many nursing homes amenity=hospital). Matched on the name,
# case-insensitive. Names matching a KEEP pattern (government hospitals, medical colleges) are
# always sources, even if they also match an EXCLUDE pattern. Unnamed hospitals are kept.
HOSPITAL_ACCESS_EXCLUDE_PATTERNS: tuple[str, ...] = (
    r"nursing\s*home",
    r"poly\s*clinic",
    r"diagnostic",
    r"\bclinic\b",
    r"\beye\b",
    r"\bdental\b",
    r"\bmaternity\b",
)
HOSPITAL_ACCESS_KEEP_PATTERNS: tuple[str, ...] = (
    *HOSPITAL_NAME_PATTERNS,  # rural / block hospital, BPHC, sub-divisional / district hospital
    r"medical college",
)
_EXCLUDE_RE = re.compile("|".join(HOSPITAL_ACCESS_EXCLUDE_PATTERNS), re.IGNORECASE)
_KEEP_RE = re.compile("|".join(HOSPITAL_ACCESS_KEEP_PATTERNS), re.IGNORECASE)


def is_access_hospital(name: str | None) -> bool:
    """Whether a facility_level "hospital" counts as a source for hospital access."""
    if not name or _KEEP_RE.search(name):
        return True
    return not _EXCLUDE_RE.search(name)


def is_access_source(infra_type: str, attributes: dict, name: str | None) -> bool:
    """A hospital access source: a facility_level "hospital" that is_access_hospital keeps.
    Shared by the risk engine and the ingest's hospital_travel_time_s."""
    return (
        infra_type == "hospital"
        and attributes.get("facility_level") == "hospital"
        and is_access_hospital(name)
    )


# Mapped shelters: 1 - min(1, shelters and stand-ins per 10,000 people / 2).
MAPPED_SHELTERS_PER_10K_TARGET = 2.0
# Low literacy is OFF (weight 0) until a primary source is available: the Census PCA file for the
# district (DDW_PCA1917_2011_MDDS with UI.xlsx) was unreachable, census2011.co.in block pages have
# no literacy, and Wikidata has no literacy value for any of the 29 blocks (queried 2026-09-25).
# The approved weights with literacy were: density 0.3, hospital access 0.4, low literacy 0.2,
# mapped shelters 0.1; without it they are respread in proportion (each / 0.8).
VULNERABILITY_PARTS = {
    "population_density": 0.375,
    "hospital_access": 0.5,
    "low_literacy": 0.0,
    "mapped_shelters": 0.125,
}
