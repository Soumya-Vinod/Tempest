"""Build the insurance DEMO_MODE fixtures from the committed hazard layers and block population.

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_insurance_fixtures.py

Writes to api/data/demo/ (contracts.md §7; the summary and the extra fields: added in v1.2):
- insurance__triggers__<ts>.json  compact: TriggerEvents without block polygons (added on load)
- insurance__summary.json         released district totals per timestep, first trigger per block
It runs the live compute path (app/insurance/service.py) on the same hazard layers DEMO_MODE
serves, so the fixtures round-trip exactly. ILLUSTRATIVE terms (app/insurance/constants.py).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.demo import DEMO_DIR  # noqa: E402
from app.insurance import engine  # noqa: E402
from app.insurance import service as insurance  # noqa: E402
from app.schemas import REPLAY_TIMESTEPS  # noqa: E402


def write_json(path: Path, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def crore(inr: float) -> str:
    return f"₹{inr / 1e7:,.2f} crore"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    written = []
    for ts in REPLAY_TIMESTEPS:
        path = DEMO_DIR / f"{insurance.fixture_key(ts)}.json"
        write_json(path, insurance.compact_triggers(ts))
        written.append(path)
    summary = engine.summary(*insurance.series())
    path = DEMO_DIR / f"{insurance.SUMMARY_FIXTURE_KEY}.json"
    write_json(path, summary.model_dump(mode="json"))
    written.append(path)

    size = sum(p.stat().st_size for p in written)
    print(f"{len(written)} fixtures, {size / 1e3:.0f} KB")
    print("\nReleased district total per timestep (never decreases):")
    for d in summary.district:
        print(
            f"  {d.timestep}  {crore(d.released_payout_inr):>16}  "
            f"triggered now {d.triggered_zones:2d}, released {d.released_zones:2d}"
        )
    print("\nFirst trigger per block:")
    hits = sorted(
        (z for z in summary.zones if z.first_trigger_timestep),
        key=lambda z: (z.first_trigger_timestep, z.zone_name),
    )
    for z in hits:
        print(
            f"  {z.zone_name:<16} {z.first_trigger_timestep} ({z.hours_before_landfall} h before "
            f"landfall)  {z.first_trigger_metric} tier {z.first_trigger_tier}  "
            f"{crore(z.first_trigger_payout_inr)}; released by T-0: tier "
            f"{z.final_released_tier}, {crore(z.final_released_payout_inr)}"
        )
    print(f"\nTotal released at T-0: {crore(summary.district[-1].released_payout_inr)}")


if __name__ == "__main__":
    main()
