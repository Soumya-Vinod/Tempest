"""Parametric insurance terms. ILLUSTRATIVE: not an actual policy; every number here is a
demonstration choice, kept in this one file so it is easy to see and change.

A zone is a CD block (the risk module's 29 South 24 Parganas blocks; Kolkata is not scored).
Each timestep, each hazard is read as the 90th-percentile value over the block's inhabited land,
so a single extreme cell can't trigger a payout alone. The block pays the higher of the wind and
surge tiers, never the sum. Released money is never taken back: the payout released at a
timestep is the highest tier reached at any timestep up to it.
"""

# Wind: sustained wind speed, m/s (Dev A's hazard layer `value`). The thresholds are the IMD
# category boundaries: Very Severe Cyclonic Storm (64 kt = 33 m/s), Extremely Severe (90 kt =
# 46 m/s), Super Cyclonic (120 kt = 62 m/s).
WIND_TIERS_MS: tuple[tuple[float, float], ...] = (
    (33.0, 0.25),  # >= 33 m/s -> 25 % of the sum insured
    (46.0, 0.50),  # >= 46 m/s -> 50 %
    (62.0, 1.00),  # >= 62 m/s -> 100 %
)

# Storm surge: inundation depth above ground, m.
SURGE_TIERS_M: tuple[tuple[float, float], ...] = (
    (1.0, 0.25),  # >= 1.0 m -> 25 %
    (2.0, 0.50),  # >= 2.0 m -> 50 %
    (3.0, 1.00),  # >= 3.0 m -> 100 %
)

# The reading: nearest-rank ("lower") 90th percentile of the hazard cells that overlap the
# block's inhabited land by at least MIN_OVERLAP_KM2. With two or more such cells, the reading
# is never the single highest cell. Every block has at least 5 such cells on the 0.05° grid.
PERCENTILE = 90
MIN_OVERLAP_KM2 = 1.0

# Sum insured per block: INR per resident, Census 2011 population of the CD block.
SUM_INSURED_PER_RESIDENT_INR = 1_000
