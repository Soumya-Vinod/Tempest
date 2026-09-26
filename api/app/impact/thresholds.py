"""Impact thresholds. Every value here is an ASSUMPTION for the Amphan replay, not a standard or a
calibrated model; change them here only. Comparisons are inclusive (value >= threshold).

Hazard metrics (contracts.md §4.1, added in v1.1): surge and wind use the physical
`value` (m, m/s); flood uses `severity` (0-1).
"""

# --- Flood: static susceptibility, not an event (contracts.md §4.1, added in v1.1) ---
# The flood layer is the same at every timestep, so it never cuts a road, a substation or an
# isolation path: it only marks roads, substations, hospitals and shelters at_risk.
# Enable FLOOD_CUTS_ROADS only if the flood layer becomes time-varying (for example,
# rainfall-driven); it then restores the old road rule below (cut / at_risk from half).
FLOOD_CUTS_ROADS = False
# Assumption: severe flood susceptibility (severity >= 0.7) means at risk.
FLOOD_AT_RISK_SEVERITY = 0.7
# Old road rule, used only when FLOOD_CUTS_ROADS is True.
ROAD_CUT_FLOOD_SEVERITY = 0.7
ROAD_AT_RISK_FLOOD_SEVERITY = ROAD_CUT_FLOOD_SEVERITY / 2

# --- Roads (surge acts on road edges; ferries are unaffected by it) ---
# Assumption: ~30 cm of standing water makes a rural road impassable to ordinary vehicles.
ROAD_CUT_SURGE_M = 0.3
# Assumption: at risk from half the cut value.
ROAD_AT_RISK_SURGE_M = ROAD_CUT_SURGE_M / 2

# --- Ferries (wind only) ---
# Assumption: ferries stop at gale force (Beaufort 8, >= 17 m/s).
FERRY_CUT_WIND_MS = 17.0
# Assumption: ferries are at risk from a strong breeze (Beaufort 6, >= 12 m/s).
FERRY_AT_RISK_WIND_MS = 12.0

# --- Substations (at their location) ---
# Assumption: 0.5 m of surge reaches switchgear and trips the substation.
SUBSTATION_CUT_SURGE_M = 0.5
# Assumption: hurricane-force wind (Beaufort 12, >= 33 m/s) puts a substation at risk.
SUBSTATION_AT_RISK_WIND_MS = 33.0

# --- Power lines (along the line; at_risk only, never cut) ---
# Assumption: hurricane-force wind (>= 33 m/s) along the line puts it at risk.
POWER_LINE_AT_RISK_WIND_MS = 33.0

# --- Hospitals and shelters (at their location; isolation comes from the road network) ---
# Assumption: the road at-risk value for surge, FLOOD_AT_RISK_SEVERITY for flood, and
# hurricane-force wind.
FACILITY_AT_RISK_SURGE_M = ROAD_AT_RISK_SURGE_M
FACILITY_AT_RISK_FLOOD_SEVERITY = FLOOD_AT_RISK_SEVERITY
FACILITY_AT_RISK_WIND_MS = 33.0

# --- Network ---
# Assumption: a facility more than 2 km from any road node can't be judged by the road graph; it
# is flagged (snap_too_far) and never marked isolated.
MAX_SNAP_M = 2000.0
# Assumption: Diamond Harbour (a sub-divisional town on the main road network) stands for "the
# mainland". Baseline travel times are measured from its nearest graph node.
ANCHOR_NAME = "Diamond Harbour"
ANCHOR_LONLAT = (88.194, 22.190)
# When one road edge is cut by several hazards, the isolation is attributed in this order.
# Flood only takes part when FLOOD_CUTS_ROADS is True (see isolation_hazards()).
CUT_ATTRIBUTION_ORDER = ("surge", "flood", "wind")


def isolation_hazards() -> tuple[str, ...]:
    """Hazards whose cut edges are removed for the isolation step, in attribution order."""
    return tuple(h for h in CUT_ATTRIBUTION_ORDER if h != "flood" or FLOOD_CUTS_ROADS)
