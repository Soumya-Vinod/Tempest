"""Forecast horizon (v1.3 change, pending Dev A): act on what's coming, not only what's happening.

The expected hazard at timestep t is, per hazard type and grid cell, the maximum over the replay
timesteps from t to t + FORECAST_HORIZON_H (capped at landfall): the worst the cell sees in the
next 24 h. Impact and risk run on it unchanged, so at horizon 24 their results mean "expected
within 24 h" (an `isolated` feature is expected to be cut off).

This is a PERFECT-FORECAST REPLAY: the "forecast" is the replay's own future hazard. Operationally
the same model would run on IMD's forecast track instead. Taking each cell's maximum over the
window is deliberately conservative: wind and surge can peak at different times, and both
peaks are kept.

DEMO_MODE fixtures at horizon 24 are deduplicated: the expected hazard is the same at many
timesteps (every window from T-24 to T-6 contains the T-3 peak), so each distinct result is
stored once, under a content hash of the result with its timestep replaced by a token, and an
index maps each timestep to its file. Loading substitutes the timestep back, so responses are
exactly what the computation returns.
"""

import hashlib
import json

from app.schemas import REPLAY_TIMESTEPS, HazardLayerCollection

FORECAST_HORIZON_H = 24
REPLAY_STEP_H = 3
HORIZONS = (0, FORECAST_HORIZON_H)
HAZARD_TYPES = ("wind", "surge", "flood")


def window(timestep: str, horizon_h: int = FORECAST_HORIZON_H) -> list[str]:
    """The replay timesteps from `timestep` to `timestep` + horizon_h, capped at landfall."""
    i = REPLAY_TIMESTEPS.index(timestep)
    return list(REPLAY_TIMESTEPS[i : i + horizon_h // REPLAY_STEP_H + 1])


def _cell(feature_id: str) -> str:
    """ "c0042" from "surge__c0042__20200520T0900Z": the same grid cell at any timestep."""
    parts = feature_id.split("__")
    return parts[1] if len(parts) > 1 else feature_id


def expected_hazard(
    layers: list[dict[str, HazardLayerCollection]],
) -> dict[str, HazardLayerCollection]:
    """Cell-wise max of value and severity over the window's layers (first = the timestep itself,
    whose cells, ids and timestep label the result)."""
    out = {}
    for h in HAZARD_TYPES:
        best: dict[str, tuple[float, float]] = {}
        for step in layers:
            for f in step[h].features:
                key = _cell(f.properties.id)
                v, s = f.properties.value, f.properties.severity
                if key in best:
                    bv, bs = best[key]
                    v, s = max(v, bv), max(s, bs)
                best[key] = (v, s)
        base = layers[0][h].model_copy(deep=True)
        for f in base.features:
            f.properties.value, f.properties.severity = best[_cell(f.properties.id)]
        out[h] = base
    return out


# --- Deduplicated DEMO_MODE fixtures at horizon 24 ---------------------------------------------

TIMESTEP_TOKEN = "{{timestep}}"
HASH_CHARS = 12


def _replace(data, old: str, new: str):
    if isinstance(data, str):
        return data.replace(old, new)
    if isinstance(data, list):
        return [_replace(v, old, new) for v in data]
    if isinstance(data, dict):
        return {k: _replace(v, old, new) for k, v in data.items()}
    return data


def dedup_key(resource_prefix: str, data: dict, timestep: str) -> tuple[str, dict]:
    """(fixture key, timestep-free content) for one timestep's result. `resource_prefix` is e.g.
    "impact__results-h24"; the key is "<prefix>-<hash>"."""
    neutral = _replace(data, timestep, TIMESTEP_TOKEN)
    text = json.dumps(neutral, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:HASH_CHARS]
    return f"{resource_prefix}-{digest}", neutral


def index_key(resource_prefix: str) -> str:
    return f"{resource_prefix}-index"


def restore(neutral: dict, timestep: str) -> dict:
    """A stored timestep-free result for `timestep`."""
    return _replace(neutral, TIMESTEP_TOKEN, timestep)
