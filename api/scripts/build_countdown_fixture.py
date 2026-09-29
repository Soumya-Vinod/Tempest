"""Build the action countdown DEMO_MODE fixture (v1.3 change, pending Dev A).

Run from the repo root:  api\\.venv\\Scripts\\python api\\scripts\\build_countdown_fixture.py

Reads only committed fixtures in api/data/demo/ (impact results at horizons 0 and 24, the
horizon-24 risk scores and the exposure infra) and writes api/data/demo/impact__countdown.json:
per timestep, the facilities expected to be cut off but not yet and those already cut off, plus
the replay's key moments (app/impact/countdown.py). Run it after build_impact_risk_fixtures.py.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.demo import DEMO_DIR  # noqa: E402
from app.impact import countdown  # noqa: E402


def main() -> None:
    data = countdown.from_fixtures()
    path = DEMO_DIR / f"{countdown.FIXTURE_KEY}.json"
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    for m in data["key_moments"]:
        print(f"{m['kind']:26} {m['timestep']}  {m['label']}")
    print(f"wrote {path.name}")


if __name__ == "__main__":
    main()
