"""Action countdown for GET /api/impact/countdown (v1.3 change, pending Dev A).

For each replay timestep:
- expected: facilities isolated on the expected hazard (horizon 24: cut off within the next 24 h)
  but not on the observed one yet, soonest first by the hours until the observed hazard first
  cuts them off;
- cut_off: facilities isolated now, longest cut off first, `since` the start of that isolation.
Plus the replay's key moments: the first alert (the first advisory suggestion, by the same rule
as /api/advisory/suggestions: app/advisory/suggest.py), the first expected and first actual
isolation, and landfall.

Everything derives from the impact results at both horizons and the horizon-24 risk scores, so
it is precomputed: DEMO_MODE serves one fixture, impact__countdown, built by
scripts/build_countdown_fixture.py from the committed fixtures (from_fixtures below). Live mode
computes the same from the services, once.

The replay's expected hazard is the observed storm's next 24 h (a perfect forecast), so the
"expected" list is exactly the facilities the storm cuts off within 24 h; real warning time
depends on forecast accuracy.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from app.core.config import get_settings
from app.core.demo import DEMO_DIR
from app.impact import horizon as fh
from app.impact.engine import feature_label
from app.impact.fixtures import fixture_key
from app.impact.horizon import FORECAST_HORIZON_H
from app.schemas import (
    LANDFALL_TIMESTEP,
    LIVE,
    REPLAY_TIMESTEPS,
    ActionCountdown,
    AdvisorySuggestion,
    InfraFeature,
)

FIXTURE_KEY = "impact__countdown"
IMPACT_H24_PREFIX = "impact__results-h24"  # = service.H24_PREFIX (not imported: no graph deps)
SCORES_H24_PREFIX = "risk__scores-h24"  # = risk.service.SCORES_H24_PREFIX
EXPOSURE_TYPES = ("road", "hospital", "shelter")  # names, facility types and ferry flags
MORE_NAMES = 2  # key-moment labels name this many, then "and N more"


class CountdownMissing(RuntimeError):
    """The impact__countdown fixture has not been built (scripts/build_countdown_fixture.py)."""


@dataclass(frozen=True)
class Isolation:
    hazard_type: str
    cut_infra_id: str | None  # the first cut link on the facility's usual route


def isolations(rows) -> dict[str, Isolation]:
    """infra_id -> how it is isolated, from ImpactResult properties (dicts); isolated rows only.
    The pathway of an isolated row is [hazard, first cut link, facility]."""
    out = {}
    for p in rows:
        if p["status"] != "isolated":
            continue
        path = p["pathway"]
        cut = path[1]["id"] if len(path) >= 3 else None
        out[p["infra_id"]] = Isolation(p["hazard_type"], cut)
    return out


def _hours(a: str, b: str) -> int:
    parse = lambda t: datetime.fromisoformat(t.replace("Z", "+00:00"))  # noqa: E731
    return round((parse(b) - parse(a)).total_seconds() / 3600)


def _cause(iso: Isolation, infra: dict[str, InfraFeature]) -> str:
    cut = infra.get(iso.cut_infra_id or "")
    ferry = cut is not None and cut.properties.attributes.get("ferry") is True
    return f"{'ferry suspended' if ferry else 'road cut'} by {iso.hazard_type}"


def _names(names: list[str]) -> str:
    if len(names) <= MORE_NAMES:
        return ", ".join(names)
    return f"{', '.join(names[:MORE_NAMES])} and {len(names) - MORE_NAMES} more"


def _alert_label(suggested: list[AdvisorySuggestion]) -> str:
    """ "First alert: Namkhana (Frasergunj PHC expected to be cut off)": the reason is given when
    one block is suggested."""
    names = _names([s.block_name for s in suggested])
    if len(suggested) != 1:
        return f"First alert: {names}"
    return f"First alert: {names} ({'; '.join(r.label for r in suggested[0].reasons)})"


def compute(
    h0: dict[str, dict[str, Isolation]],
    h24: dict[str, dict[str, Isolation]],
    suggestions: dict[str, list[AdvisorySuggestion]],
    infra: dict[str, InfraFeature],
    timesteps: tuple[str, ...] = REPLAY_TIMESTEPS,
) -> dict:
    """The fixture: {"key_moments": [...], "timesteps": {ts: {"expected", "cut_off"}}}.
    h0 / h24: isolations per timestep; suggestions: the advisory suggestions per timestep."""

    def name(i: str) -> str:
        f = infra.get(i)
        return feature_label(f) if f else i

    def entry(i: str, iso: Isolation, **extra) -> dict:
        cut = infra.get(iso.cut_infra_id or "")
        return {
            "infra_id": i,
            "name": name(i),
            "infra_type": infra[i].properties.infra_type if i in infra else "hospital",
            "cause": _cause(iso, infra),
            "cut_infra_id": iso.cut_infra_id,
            "cut_name": feature_label(cut) if cut else None,
            **extra,
        }

    by_ts = {}
    for n, ts in enumerate(timesteps):
        expected = []
        for i, iso in h24[ts].items():
            if i in h0[ts]:
                continue
            nxt = next((t for t in timesteps[n + 1 :] if i in h0[t]), None)
            expected.append(entry(i, iso, hours_remaining=_hours(ts, nxt) if nxt else None))
        expected.sort(
            key=lambda e: (e["hours_remaining"] is None, e["hours_remaining"] or 0, e["name"])
        )
        cut_off = []
        for i, iso in h0[ts].items():
            k = n
            while k > 0 and i in h0[timesteps[k - 1]]:
                k -= 1
            cut_off.append(entry(i, iso, since=timesteps[k]))
        cut_off.sort(key=lambda e: (e["since"], e["name"]))
        by_ts[ts] = {"expected": expected, "cut_off": cut_off}

    def first(found) -> tuple[str | None, list[str]]:
        for ts in timesteps:
            if names := found(ts):
                return ts, names
        return None, []

    alert_ts, alert = first(lambda ts: suggestions[ts])
    exp_ts, exp = first(lambda ts: sorted(name(i) for i in h24[ts]))
    act_ts, act = first(lambda ts: sorted(name(i) for i in h0[ts]))
    moments = [
        ("first_alert", alert_ts, _alert_label(alert), "No alert in the replay"),
        (
            "first_expected_isolation",
            exp_ts,
            f"First expected cut-off: {_names(exp)}",
            "No facility expected to be cut off",
        ),
        (
            "first_actual_isolation",
            act_ts,
            f"First cut-off: {_names(act)}",
            "No facility cut off in the replay",
        ),
        ("landfall", LANDFALL_TIMESTEP, "Landfall", "Landfall"),
    ]
    return {
        "key_moments": [
            {"kind": k, "timestep": ts, "label": label if ts else none}
            for k, ts, label, none in moments
        ],
        "timesteps": by_ts,
    }


# --- Inputs ---------------------------------------------------------------------------------------


def _read(key: str) -> dict:
    return json.loads((DEMO_DIR / f"{key}.json").read_text("utf-8"))


def _infra_from_fixtures() -> dict[str, InfraFeature]:
    return {
        f["id"]: InfraFeature.model_validate(f)
        for t in EXPOSURE_TYPES
        for f in _read(f"exposure__infra-{t}")["features"]
    }


def from_fixtures() -> dict:
    """The countdown from the committed impact, risk and exposure fixtures (the build script and
    the tests use this; it reads the files directly, whatever DEMO_MODE is)."""
    from app.advisory.suggest import expected_by_block, facility_blocks, suggest
    from app.risk.blocks import load_blocks

    impact_h24 = _read(fh.index_key(IMPACT_H24_PREFIX))["files"]
    scores_h24 = _read(fh.index_key(SCORES_H24_PREFIX))["files"]
    infra = _infra_from_fixtures()
    blocks_of = facility_blocks(infra.values(), load_blocks())

    def rows(fixture: dict):
        return (r["properties"] for r in fixture["features"])

    h24 = {ts: isolations(rows(_read(impact_h24[ts]))) for ts in REPLAY_TIMESTEPS}
    return compute(
        h0={ts: isolations(rows(_read(fixture_key(ts)))) for ts in REPLAY_TIMESTEPS},
        h24=h24,
        suggestions={
            ts: suggest(
                [(p["block_id"], p["block_name"], p["score"]) for p in rows(_read(scores_h24[ts]))],
                expected_by_block(h24[ts], infra, blocks_of),
            )
            for ts in REPLAY_TIMESTEPS
        },
        infra=infra,
    )


def _from_services() -> dict:
    from app.advisory import service as advisory
    from app.exposure import service as exposure
    from app.impact import service as impact

    def iso(ts: str, h: int) -> dict[str, Isolation]:
        fc = impact.results(ts, h)
        return isolations(f.properties.model_dump() for f in fc.features)

    return compute(
        h0={ts: iso(ts, 0) for ts in REPLAY_TIMESTEPS},
        h24={ts: iso(ts, FORECAST_HORIZON_H) for ts in REPLAY_TIMESTEPS},
        suggestions={ts: advisory.suggestions(ts).blocks for ts in REPLAY_TIMESTEPS},
        infra={f.id: f for f in exposure.get_infra().features},
    )


# --- Service ------------------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _data(demo: bool) -> dict:
    if not demo:
        return _from_services()
    try:
        return _read(FIXTURE_KEY)
    except FileNotFoundError as e:
        raise CountdownMissing(
            f"{FIXTURE_KEY}.json not found; run api/scripts/build_countdown_fixture.py"
        ) from e


def clear_cache() -> None:
    _data.cache_clear()


def get_countdown(timestep: str) -> ActionCountdown:
    if timestep == LIVE:
        raise NotImplementedError("timestep=live is not implemented yet")
    data = _data(get_settings().DEMO_MODE)
    return ActionCountdown.model_validate(
        {
            "timestep": timestep,
            "horizon_h": FORECAST_HORIZON_H,
            **data["timesteps"][timestep],
            "key_moments": data["key_moments"],
        }
    )
