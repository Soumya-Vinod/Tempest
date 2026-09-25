"""Risk score weights and fixed normalisation scales. Every value is an ASSUMPTION, not a
calibrated model; change them here only.

    score = hazard x (W_EXPOSURE * exposure + W_VULNERABILITY * vulnerability)

Every component and part is 0-1 on a FIXED scale (never relative to this timestep's maximum), so
scores are comparable across timesteps.
"""

from app.impact.thresholds import ROAD_CUT_SURGE_M

# --- Score ---
W_EXPOSURE = 0.6
W_VULNERABILITY = 0.4

# --- Hazard (land only: the blocks' share of the unfilled OSM district land polygon) ---
# surge part: share of the block's land with surge depth >= the road-cut threshold.
SURGE_LAND_THRESHOLD_M = ROAD_CUT_SURGE_M
# wind part: land-weighted mean of (wind - WIND_FLOOR) / (WIND_CEILING - WIND_FLOOR), clipped 0-1.
# Assumption: below gale force (17 m/s, Beaufort 8) wind adds no risk; 60 m/s is the top of scale.
WIND_FLOOR_MS = 17.0
WIND_CEILING_MS = 60.0
# hazard = max(surge, wind) + FLOOD_WEIGHT x land-weighted flood severity, capped at 1.
# Flood is static susceptibility (contracts.md §4.1), so it only adds a small constant weight.
FLOOD_WEIGHT = 0.1

# --- Exposure (from the timestep's impact results inside the block) ---
ISOLATED_FACILITIES_CAP = 3  # isolated hospitals + shelters; 3 or more = 1
CUT_ROAD_SHARE_CAP = 0.5  # cut road length / all road length; half the network cut = 1
CUT_SUBSTATIONS_CAP = 2  # 2 or more cut substations = 1
EXPOSURE_PARTS = {
    "isolated_facilities": 0.5,
    "cut_roads": 0.35,
    "cut_substations": 0.15,
}

# --- Vulnerability (static; computed once) ---
DENSITY_SCALE_PER_KM2 = 2000.0  # population / land km2; 2,000 or more = 1
# Hospital access: travel time from the nearest hospital (facility_level "hospital", Kolkata's
# included), median over the block's road graph nodes; 2 h or more (or unreachable) = 1.
HOSPITAL_ACCESS_SCALE_S = 2 * 3600.0
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
